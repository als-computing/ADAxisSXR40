"""ophyd device for the XV4040 detector (ADAxisSXR40 or ADTucsen serving ``XV4040:``).

WHAT THIS FILE IS
    The bluesky/ophyd description of the detector: which PVs make up the camera, which plugin
    writes the files, what happens at stage / trigger / read / unstage, and one ready-made
    instance, ``xv4040``. It is modelled on bluesky-web's
    ``queue-server/startup_bl531/02_area_detectors.py`` (the Basler and Pilatus devices) so
    it can be dropped into a queue-server startup directory unchanged.

HOW TO USE IT
    In a queue-server:   copy this file into the startup directory (files load in name
                         order, e.g. as ``02_area_detectors.py``). The device ``xv4040`` and
                         the plan ``warmup_xv4040`` appear in the namespace; a queue item
                         ``scan([xv4040], motor, -1, 1, 11)`` takes 11 frames into one HDF5
                         file and the TiledWriter serves them.
    In a script / IPython: ``from area_detectors import xv4040`` (see main.py next to this file).
    First thing after start-up and after every ROI or binning change: run the
    ``warmup_xv4040`` plan once (or call ``xv4040.hdf5.warmup()``); see section 3 for why.

WHAT DIFFERS FROM THE REFERENCE FILE, ON PURPOSE
    - the file writer is HDF5 (HDF1:), one file per scan in Stream mode, because that is what
      this IOC writes at the beamline and what tests/ verifies;
    - the resource documents are written so that bluesky's TiledWriter can serve the images
      (spec AD_HDF5_SWMR_STREAM plus dataset / swmr / chunk_shape parameters);
    - every PV used exists in both drivers, so the device works whichever IOC is serving;
    - warmup() is our own: ophyd's writes TriggerMode="Internal", which is not an enum string
      of this camera (Free Run, Standard, Synchronous, Global, Software).

LAYOUT
    1. CONFIGURATION   everything an operator may need to change, in one place
    2. CAMERA          TucsenCam            (cam1:)
    3. FILE WRITER     XV4040HDF5Plugin     (HDF1:)  file store, tiled resource, warm-up
    4. DETECTOR        XV4040Detector       (cam + image + stats1 + hdf5)
    5. FACTORY         make_detector()      applies section 1 to a connected device
    6. INSTANCE        xv4040 and the warmup_xv4040 plan, created at import
"""
import os
import time
from collections import OrderedDict

from ophyd import ADComponent as ADCpt
from ophyd import CamBase, Component as Cpt, DetectorBase, EpicsSignalRO, SingleTrigger
from ophyd.areadetector.base import EpicsSignalWithRBV as SignalWithRBV
from ophyd.areadetector.filestore_mixins import FileStoreHDF5IterativeWrite
from ophyd.areadetector.plugins import HDF5Plugin_V34, ImagePlugin_V34, StatsPlugin_V34

# =====================================================================================
# 1. CONFIGURATION -- set these in advance; nothing below this block needs editing
# =====================================================================================

# ---- where the IOC writes and where clients (this file, tiled) read ---------------------
# On bl1101ad01 both are the same directory. Whoever runs the IOC must be able to create
# files there: gabrielgazolla for ioc-axissxr40, daenglis for ioc-xv4040 (main.py creates
# the dated directory with mode 0777). In production this becomes the beamline data mount,
# e.g. XV4040_DATA_ROOT=/data/xv4040 in the queue-server's environment.
XV4040_FILES_ROOT = os.environ.get("XV4040_DATA_ROOT", "/home/gabrielgazolla/axis-perf-tmp")
XV4040_IMAGE_DIR = "bluesky/%Y/%m/%d"        # strftime pattern: one directory per day
XV4040_READ_ROOT = XV4040_FILES_ROOT         # differs from FILES_ROOT only when clients see
                                             # the same storage under another mount point

# ---- which IOC --------------------------------------------------------------------------
XV4040_PREFIX = os.environ.get("XV4040_PREFIX", "XV4040:")   # both drivers serve this prefix
XV4040_NAME = "xv4040"                       # ophyd name: data keys become xv4040_image, ...
CONNECT_TIMEOUT_S = 10.0                     # wait_for_connection at instantiation

# ---- camera settings written at stage(), restored at unstage() -------------------------
# One frame per trigger point. SingleTrigger itself stages image_mode=Multiple, acquire=0.
CAM_STAGE_SIGS = OrderedDict([
    ("num_images", 1),                       # frames per trigger
    ("acquire_time", 0.05),                  # s; full frame runs at ~8.6 fps, so >= 0.02 s
    ("array_callbacks", 1),                  # plugins (writer, stats) must see the frames
])

# ---- file-writer settings written at stage(), in this order ------------------------------
# num_capture MUST be written before capture=1: a NumCapture left over from autosave (100 on
# ioc-xv4040) would end the file after that many frames. The FileStoreHDF5 mixin appends its
# own file_template, file_write_mode=Stream, capture=1 after these (see make_detector).
HDF5_STAGE_SIGS = OrderedDict([
    ("num_capture", 0),                      # 0 = stream until unstaged: one file per scan
    ("auto_increment", 1),                   # file number advances per scan
    ("compression", "None"),                 # None | zlib | Blosc | BSLZ4 | LZ4 (+ N-bit, szip, JPEG).
                                             # Blosc / BSLZ4 give 1.5x at full rate on this
                                             # sensor if disk space ever matters
])
HDF5_DATASET = "/entry/data/data"            # where NDFileHDF5 stacks the frames
HDF5_RESOURCE_SPEC = "AD_HDF5_SWMR_STREAM"   # a spec bluesky's TiledWriter maps to
                                             # application/x-hdf5; ophyd's default "AD_HDF5"
                                             # is NOT in its table and would be unreadable
WARMUP_TIMEOUT_S = 30.0                      # one frame before the first capture; see warmup()

# ---- what a scan reads from the detector at every point ---------------------------------
# The image itself never travels over Channel Access: bluesky gets a datum pointing into the
# HDF5 file (this is what the tiled writer consumes). Two Stats1 scalars give a LiveTable and
# a quick sanity number per point.
DETECTOR_READ_ATTRS = ["hdf5", "stats1"]
HDF5_READ_ATTRS = []                         # the datum only
STATS1_READ_ATTRS = ["mean_value", "max_value"]
STATS1_STAGE_SIGS = OrderedDict([("enable", 1), ("compute_statistics", 1)])   # Yes/No enums, 1 = Yes

# ---- camera DataType enum string -> numpy dtype string -----------------------------------
# For the descriptor's "dtype_str" (older tiled/databroker readers), as in the reference
# file's PilatusTIFFPlugin.describe(). ophyd >= 1.9 also emits "dtype_numpy" by itself.
# This camera delivers UInt16.
DTYPE_STR = {"Int8": "|i1", "UInt8": "|u1", "Int16": "<i2", "UInt16": "<u2",
             "Int32": "<i4", "UInt32": "<u4", "Int64": "<i8", "UInt64": "<u8",
             "Float32": "<f4", "Float64": "<f8"}


# =====================================================================================
# 2. CAMERA  (cam1:)
# =====================================================================================
class TucsenCam(CamBase):
    """The camera record, cam1:.

    CamBase already provides the areaDetector standard set: acquire, acquire_time,
    acquire_period, num_images, image_mode, trigger_mode, array_callbacks, array_counter,
    array_size, detector_state, data_type, color_mode, temperature, model, manufacturer,
    min_x/min_y/size_x/size_y (the ROI), bin_x/bin_y, reverse_x/reverse_y ...

    Added below: the Tucsen-specific records that exist in BOTH the ADAxisSXR40 and the
    ADTucsen templates, so the device works whichever IOC is serving. Records that only
    ADAxisSXR40 has (TECEnable, BuffFrames_RBV, BuffTotal_RBV) are deliberately left out.
    None of them is written by a scan; they are here so a plan or an operator can read or
    set them by name (``xv4040.cam.fan_gear.set("Low")``).
    """
    # Sensor temperature in degC (0.5 s poll). Same PV in both drivers, different numbers:
    # ADAxisSXR40 applies the per-unit calibration (1.7 x raw + 15), ADTucsen publishes raw.
    temperature_actual = Cpt(EpicsSignalRO, "TemperatureActual")
    # Sensor binning: "4096x4096" | "2048x2048(2x2Bin)" | "1024x1024(4x4Bin)". Changing it
    # changes the frame geometry: run the warm-up again before the next scan.
    bin_mode = ADCpt(SignalWithRBV, "BinMode")
    # Pixel format: "Raw" | "Usual" (ADTucsen also lists "RGB888", which stalls this mono
    # sensor; ADAxisSXR40 removed it). Leave at Raw/Usual.
    frame_format = ADCpt(SignalWithRBV, "FrameFormat")
    # Cooling fan: "High" | "Medium" | "Low" | "Off(Water Cooling)". Off is only for a
    # water-cooled installation; the TEC keeps running regardless (info/known-gaps).
    fan_gear = ADCpt(SignalWithRBV, "FanGear")


# =====================================================================================
# 3. FILE WRITER  (HDF1:)  -- bluesky file store + tiled-readable resource + warm-up
# =====================================================================================
class XV4040HDF5Plugin(FileStoreHDF5IterativeWrite, HDF5Plugin_V34):
    """The HDF5 writer, HDF1:, as a bluesky "file store".

    What the two base classes give:
        HDF5Plugin_V34              every HDF1: PV as an attribute (ADCore R3-4+ layout)
        FileStoreHDF5IterativeWrite at stage(): choose a file name (a uuid), write file_path /
                                    file_name / file_number, set Stream mode and Capture=1,
                                    emit a Resource document; at every trigger: emit a Datum
                                    with point_number; at unstage(): Capture=0 closes the file.

    What this subclass adds:
        - the resource spec and parameters that bluesky's TiledWriter needs (see section 1,
          HDF5_RESOURCE_SPEC): without them the run is stored but the images cannot be read
          back through tiled. Verified 2026-09-14 by reading the stack back from a tiled server.
        - describe(): shape and dtype of the image key from the live camera geometry.
        - warmup(): the one frame the plugin must see before its first Stream capture.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.filestore_spec = HDF5_RESOURCE_SPEC

    # -- resource document: what tiled needs to open the file ----------------------------
    def _generate_resource(self, resource_kwargs):
        kwargs = dict(resource_kwargs)           # ophyd supplies frame_per_point
        cam = self.parent.cam
        kwargs.update(
            dataset=HDF5_DATASET,                # path of the frame stack inside the file
            swmr=False,                          # NDFileHDF5 does not write in SWMR mode
            chunk_shape=(1, int(cam.array_size.array_size_y.get()), int(cam.array_size.array_size_x.get())),
        )                                        # one frame per chunk, as the plugin writes it
        return super()._generate_resource(kwargs)

    # -- descriptor: shape and dtype of the image key ------------------------------------
    def describe(self):
        """tiled allocates the array from the descriptor, without opening the file, so the
        image key must carry shape and dtype. ophyd gives shape (num_images, height, width)
        and "dtype_numpy"; the reference file adds "dtype_str" and the shape from the live
        geometry, done here too, Mono only (this sensor has a single color mode)."""
        ret = super().describe()
        key = self.parent._image_name
        if key in ret:
            cam = self.parent.cam
            if cam.color_mode.get(as_string=True) == "Mono":
                ret[key]["shape"] = [cam.num_images.get(),
                                     cam.array_size.array_size_y.get(), cam.array_size.array_size_x.get()]
            dtype_str = DTYPE_STR.get(cam.data_type.get(as_string=True))
            if dtype_str:
                ret[key].setdefault("dtype_str", dtype_str)
                ret[key].setdefault("dtype_numpy", dtype_str)
        return ret

    # -- warm-up: one frame before the first Stream capture ------------------------------
    def warmup(self, timeout: float = WARMUP_TIMEOUT_S) -> None:
        """Acquire one frame with callbacks on so the plugin learns the array geometry.

        Why: NDFileHDF5 in Stream mode fixes the dataset shape from the LAST array it saw
        when Capture starts. Without a recent frame, a capture after an ROI or binning change
        rejects every frame with "Invalid frame" and silently writes an empty file
        (info/performance/README.md, item 1). Run once after start-up and after every
        geometry change. Steps:

            1. writer AutoSave off      (a Single-mode writer would save the frame as a stray file)
            2. ArrayCallbacks on, ImageMode Single, NumImages 1
            3. Acquire 1, then poll until Acquire is back to 0 AND the CAMERA's ArrayCounter
               advanced (the file plugin counts only arrays it saves, but it keeps the last
               array it received, which is what Stream mode sizes from)
            4. restore 1-2 in reverse order, also on failure
        """
        cam = self.parent.cam
        self.enable.set(1).wait()
        saved = OrderedDict((s, s.get()) for s in (cam.array_callbacks, cam.image_mode, cam.num_images,
                                                   self.auto_save))
        try:
            self.auto_save.set(0).wait()
            cam.array_callbacks.set(1).wait()
            cam.image_mode.set("Single").wait()
            cam.num_images.set(1).wait()
            counter0 = cam.array_counter.get()
            cam.acquire.put(1, wait=False)       # poll rather than wait on completion, so a hung
            deadline = time.monotonic() + timeout    # IOC gives a clear error, not a silent block
            while time.monotonic() < deadline:
                if cam.acquire.get() == 0 and cam.array_counter.get() > counter0:
                    break
                time.sleep(0.1)
            else:
                raise TimeoutError(f"{self.name}: warm-up frame did not arrive within {timeout} s")
        finally:
            for sig, val in reversed(list(saved.items())):
                sig.set(val).wait()


# =====================================================================================
# 4. DETECTOR  -- cam + image + stats1 + hdf5, SingleTrigger semantics
# =====================================================================================
class XV4040Detector(SingleTrigger, DetectorBase):
    """The detector as bluesky sees it. What each bluesky step does to the IOC:

        stage()    CAM_STAGE_SIGS, STATS1_STAGE_SIGS, HDF5_STAGE_SIGS are written (old values
                   remembered); the file store opens the scan's HDF5 file (Stream, Capture 1)
        trigger()  Acquire 1; done when Acquire returns to 0; a Datum for the frame is emitted
        read()     the datum (the image lives in the file) + Stats1 mean and max
        unstage()  Capture 0 closes the file; every setting written at stage() is restored

    ``image`` (image1:) is declared so viewers and plans can find it, but is never read here:
    a 32 MiB frame over Channel Access at every point is exactly what the file store avoids.
    """
    cam = ADCpt(TucsenCam, "cam1:")
    image = ADCpt(ImagePlugin_V34, "image1:")
    stats1 = ADCpt(StatsPlugin_V34, "Stats1:")
    hdf5 = ADCpt(
        XV4040HDF5Plugin,
        "HDF1:",
        write_path_template=os.path.join(XV4040_FILES_ROOT, XV4040_IMAGE_DIR),   # the IOC's view
        read_path_template=os.path.join(XV4040_READ_ROOT, XV4040_IMAGE_DIR),     # the client's view
        root=XV4040_READ_ROOT,                                                    # Resource 'root'
    )


# =====================================================================================
# 5. FACTORY  -- connect, then apply the CONFIGURATION block
# =====================================================================================
def make_detector(prefix: str = XV4040_PREFIX, name: str = XV4040_NAME, *,
                  connect_timeout: float = CONNECT_TIMEOUT_S) -> XV4040Detector:
    """Connect to the IOC (raises if it is not there) and apply section 1."""
    det = XV4040Detector(prefix, name=name)
    det.wait_for_connection(timeout=connect_timeout)

    # camera and statistics: written at stage() in the order given
    det.cam.stage_sigs.update(CAM_STAGE_SIGS)
    det.stats1.stage_sigs.update(STATS1_STAGE_SIGS)

    # file writer: OUR settings first (num_capture before capture=1), then the mixin's
    # file_template, file_write_mode=Stream, capture=1
    sigs = OrderedDict(HDF5_STAGE_SIGS)
    sigs.update(det.hdf5.stage_sigs)
    det.hdf5.stage_sigs = sigs

    # what read() returns
    det.read_attrs = list(DETECTOR_READ_ATTRS)
    det.hdf5.read_attrs = list(HDF5_READ_ATTRS)
    det.stats1.read_attrs = list(STATS1_READ_ATTRS)
    det.image.kind = "omitted"
    return det


# =====================================================================================
# 6. INSTANCE  -- created at import so a startup file can `from area_detectors import xv4040`
# =====================================================================================
try:
    xv4040 = make_detector()
except Exception as e:  # noqa: BLE001  -- same behaviour as the reference startup file
    print(f"error instantiating connection to the XV4040 detector ({XV4040_PREFIX}): {e}. Is the EPICS IOC on?")
    xv4040 = None


def warmup_xv4040():
    """Bluesky plan: the warm-up frame the HDF5 writer needs before its first capture.

    Queue it once after the IOC starts and after every ROI or binning change:
        RE(warmup_xv4040())            # or a queue-server item {"name": "warmup_xv4040"}
    It is a generator so the queue-server accepts it as a plan; the work itself is the
    blocking warmup() call above (about one second), which is fine for a one-off.
    """
    if xv4040 is None:
        raise RuntimeError("xv4040 is not connected; was the IOC up when this file loaded?")
    xv4040.hdf5.warmup()
    yield from ()                                 # a plan with no messages
