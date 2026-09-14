"""ophyd device for the XV4040 detector (ADAxisSXR40 or ADTucsen serving ``XV4040:``).

Modelled on bluesky-web's ``queue-server/startup_bl531/02_area_detectors.py`` (the Basler and
Pilatus devices there), so this file can later be dropped into a queue-server startup
directory as-is. Differences from that file, on purpose:

- the file writer is **HDF5** (``HDF1:``), one file per scan in Stream mode, because that is
  what this IOC writes at the beamline and what ``tests/`` verifies;
- every PV used exists in both drivers, so the device works whichever IOC is serving;
- ``warmup()`` is our own: the HDF5 plugin needs one frame at the current geometry before a
  Stream capture, and ophyd's version writes ``TriggerMode="Internal"``, which is not an
  enum string of this camera (``Free Run``, ``Standard``, ``Synchronous``, ``Global``,
  ``Software``).

Instantiating the device does not talk to the IOC; ``make_detector()`` does
``wait_for_connection`` so a missing IOC fails here, loudly, as in the reference file.
"""
import os
import time
from collections import OrderedDict

from ophyd import ADComponent as ADCpt
from ophyd import CamBase, Component as Cpt, DetectorBase, EpicsSignalRO, SingleTrigger
from ophyd.areadetector.base import EpicsSignalWithRBV as SignalWithRBV
from ophyd.areadetector.filestore_mixins import FileStoreHDF5IterativeWrite
from ophyd.areadetector.plugins import HDF5Plugin_V34, ImagePlugin_V34, StatsPlugin_V34

# Where the IOC writes and where this client reads. The two are the same directory on
# bl1101ad01. The directory must be writable by the IOC's user (gabrielgazolla for
# ioc-axissxr40, daenglis for ioc-xv4040): main.py creates it with mode 0777.
XV4040_FILES_ROOT = os.environ.get("XV4040_DATA_ROOT", "/home/gabrielgazolla/axis-perf-tmp")
XV4040_IMAGE_DIR = "bluesky/%Y/%m/%d"
XV4040_PREFIX = os.environ.get("XV4040_PREFIX", "XV4040:")


class TucsenCam(CamBase):
    """Camera record. CamBase already carries acquire, acquire_time, acquire_period,
    num_images, image_mode, trigger_mode, array_callbacks, detector_state, array_size...
    Only records present in BOTH the ADAxisSXR40 and the ADTucsen templates are added."""
    temperature_actual = Cpt(EpicsSignalRO, "TemperatureActual")
    bin_mode = ADCpt(SignalWithRBV, "BinMode")
    frame_format = ADCpt(SignalWithRBV, "FrameFormat")
    fan_gear = ADCpt(SignalWithRBV, "FanGear")


# Camera DataType enum string -> numpy dtype string, as in the reference file's
# PilatusTIFFPlugin.describe(); kept for consumers that read the older "dtype_str" key.
DTYPE_STR = {"Int8": "|i1", "UInt8": "|u1", "Int16": "<i2", "UInt16": "<u2",
             "Int32": "<i4", "UInt32": "<u4", "Int64": "<i8", "UInt64": "<u8",
             "Float32": "<f4", "Float64": "<f8"}


class XV4040HDF5Plugin(FileStoreHDF5IterativeWrite, HDF5Plugin_V34):
    """HDF5 writer as a bluesky file store: one file per scan, a datum per point.

    Written for bluesky's TiledWriter: ophyd's default resource spec "AD_HDF5" is not in
    the writer's spec→mimetype table, so the run would be stored with an unreadable
    "application/octet-stream" asset. "AD_HDF5_SWMR_STREAM" is in the table (it is the
    same layout: frames stacked in /entry/data/data), and the resource carries the
    parameters tiled's HDF5 consolidator needs: the dataset path, swmr off (NDFileHDF5
    does not write in SWMR mode) and the chunk shape (one frame per chunk).
    """

    DATASET = "/entry/data/data"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.filestore_spec = "AD_HDF5_SWMR_STREAM"

    def _generate_resource(self, resource_kwargs):
        kwargs = dict(resource_kwargs)                       # ophyd gives frame_per_point
        cam = self.parent.cam
        kwargs.update(dataset=self.DATASET, swmr=False,
                      chunk_shape=(1, int(cam.array_size.array_size_y.get()), int(cam.array_size.array_size_x.get())))
        return super()._generate_resource(kwargs)

    def describe(self):
        """The image key must carry shape and dtype so tiled can allocate the array without
        opening the file. ophyd (>= 1.9) already gives shape (num_images, height, width) and
        "dtype_numpy"; the reference file adds "dtype_str" and a shape from the plugin's own
        array size, which is what is done here, Mono only (this sensor has one color mode)."""
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

    def warmup(self, timeout: float = 30.0) -> None:
        """Acquire one frame with callbacks on so the plugin learns the array geometry.

        NDFileHDF5 in Stream mode fixes the dataset shape from the last array it saw when
        Capture starts; without this a capture after an ROI change rejects every frame with
        "Invalid frame" and silently writes an empty file (info/performance/README.md, §1).
        Restores what it changes.
        """
        cam = self.parent.cam
        self.enable.set(1).wait()
        saved = OrderedDict((s, s.get()) for s in (cam.array_callbacks, cam.image_mode, cam.num_images,
                                                   self.auto_save))
        try:
            self.auto_save.set(0).wait()        # else a Single-mode writer saves the warm-up frame as a stray file
            cam.array_callbacks.set(1).wait()
            cam.image_mode.set("Single").wait()
            cam.num_images.set(1).wait()
            # The camera's counter, not the plugin's: NDPluginFile counts only arrays it saves,
            # but it keeps the last array it received, which is what Stream mode sizes from.
            counter0 = cam.array_counter.get()
            cam.acquire.put(1, wait=False)      # poll rather than wait on completion, so a hung IOC
            deadline = time.monotonic() + timeout   # gives a clear error instead of a silent block
            while time.monotonic() < deadline:
                if cam.acquire.get() == 0 and cam.array_counter.get() > counter0:
                    break
                time.sleep(0.1)
            else:
                raise TimeoutError(f"{self.name}: warm-up frame did not arrive within {timeout} s")
        finally:
            for sig, val in reversed(list(saved.items())):
                sig.set(val).wait()


class XV4040Detector(SingleTrigger, DetectorBase):
    """The detector as bluesky sees it: trigger = one acquisition, read = a datum in the
    scan's HDF5 file. ``read_attrs`` is just the file writer, as in the reference file, so
    the 32 MiB image never travels over Channel Access."""
    cam = ADCpt(TucsenCam, "cam1:")
    image = ADCpt(ImagePlugin_V34, "image1:")
    stats1 = ADCpt(StatsPlugin_V34, "Stats1:")
    hdf5 = ADCpt(
        XV4040HDF5Plugin,
        "HDF1:",
        write_path_template=os.path.join(XV4040_FILES_ROOT, XV4040_IMAGE_DIR),
        read_path_template=os.path.join(XV4040_FILES_ROOT, XV4040_IMAGE_DIR),
        root=XV4040_FILES_ROOT,
    )


def make_detector(prefix: str = XV4040_PREFIX, name: str = "xv4040", *,
                  acquire_time: float = 0.05, connect_timeout: float = 10.0) -> XV4040Detector:
    det = XV4040Detector(prefix, name=name)
    det.wait_for_connection(timeout=connect_timeout)

    # One frame per trigger point. SingleTrigger already stages image_mode=Multiple, acquire=0.
    det.cam.stage_sigs["num_images"] = 1
    det.cam.stage_sigs["acquire_time"] = acquire_time
    det.cam.stage_sigs["array_callbacks"] = 1

    # Stream until unstaged (num_capture 0 = no limit) into one file per scan. num_capture
    # must be written BEFORE capture=1, so it goes in front of the mixin's stage_sigs.
    sigs = OrderedDict([("num_capture", 0), ("auto_increment", 1), ("compression", "None")])
    sigs.update(det.hdf5.stage_sigs)                   # file_template, file_write_mode=Stream, capture=1
    det.hdf5.stage_sigs = sigs

    # What a scan reads from the detector: the file-store datum (picked up by tiled later) and
    # two scalars from Stats1 so a LiveTable has something per point. Never the image itself.
    det.read_attrs = ["hdf5", "stats1"]
    det.hdf5.read_attrs = []
    det.stats1.read_attrs = ["mean_value", "max_value"]
    det.stats1.stage_sigs["enable"] = 1
    det.stats1.stage_sigs["compute_statistics"] = 1
    det.image.kind = "omitted"
    return det


try:
    xv4040 = make_detector()
except Exception as e:  # noqa: BLE001  -- same behaviour as the reference startup file
    print(f"error instantiating connection to the XV4040 detector ({XV4040_PREFIX}): {e}. Is the EPICS IOC on?")
    xv4040 = None
