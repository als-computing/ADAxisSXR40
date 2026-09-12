"""Every expected constant for the ADAxisSXR40 IOC, in one place.

When a test fails on a number, this is the file to edit -- after establishing that the
new number is right. `expected_adtucsen.py` overrides the entries that differ when
Damon English's ADTucsen IOC (ioc-xv4040) is the one serving XV4040:.
"""
from pathlib import Path

# ---- where things are ----------------------------------------------------------
TESTS_DIR = Path(__file__).resolve().parents[1]
MODULE_ROOT = TESTS_DIR.parent
IOC_BOOT = MODULE_ROOT / "iocs/axisSXR40IOC/iocBoot/iocAxisSXR40"
TEMPLATE = MODULE_ROOT / "axisSXR40App/Db/axisSXR40.template"
SETTINGS_REQ = MODULE_ROOT / "axisSXR40App/Db/axisSXR40_settings.req"
AUTO_SETTINGS_REQ = IOC_BOOT / "auto_settings.req"
AUTOSAVE_SAV = IOC_BOOT / "autosave/auto_settings.sav"
DRIVER_SRC = MODULE_ROOT / "axisSXR40App/src/axisSXR40.cpp"
ST_CMD = IOC_BOOT / "st.cmd"
ADL_DIR = MODULE_ROOT / "axisSXR40App/op/adl"
SYSTEMD_DIR = MODULE_ROOT / "info/systemd"
ADCORE_DEFAULT = Path("/usr/local/epics/support/areaDetector/ADCore")
ADTUCSEN_TEMPLATE = Path("/usr/local/epics/support/areaDetector/ADTucsen/tucsenApp/Db/tucsen.template")
EPICS_BIN = Path("/usr/local/epics/base-7.0.10/bin/linux-x86_64")
ADSUPPORT = Path("/usr/local/epics/support/areaDetector/ADSupport")
H5CHECK_SRC = MODULE_ROOT / "tools/h5check/h5check.c"

# ---- which IOC ---------------------------------------------------------------------
DRIVER = "adaxissxr40"
UNIT = "ioc-axissxr40"
OTHER_UNIT = "ioc-xv4040"
LOG = Path("/var/log/areadetector/axisSXR40.log")
PROCSERV_CHILD = "axissxr40"                       # @@@ The PID of new child "axissxr40" is: N
ST_CMD_PATTERN = r"axisSXR40App .*iocAxisSXR40/st\.cmd"
PVA_PORT = 5075

# ---- PV naming -------------------------------------------------------------------
PREFIX_DEFAULT = "XV4040:"
CAM = "cam1:"

# ---- boot log ------------------------------------------------------------------------
HAS_CAPABILITY_AUDIT = True
CAPABILITY_AUDIT = (11, 15, 8, 12)                 # capabilities ok/total, properties ok/total
AUTOSAVE_PV_COUNT = 2373                           # "auto_settings.sav: N of N PV's connected"
# The 8 controls this camera does not implement: their autosave-restore writes fail at
# every boot with TUCAMRET_NOT_SUPPORT. Nothing else may appear as a write error.
UNSUPPORTED_CONTROLS = frozenset({
    "Brightness", "BlackLevel", "Sharpness", "HDRK",
    "GainMode", "AutoExposure", "Enhance", "DefectCorrection",
})
WRITE_ERROR_RECORDS = UNSUPPORTED_CONTROLS
# ADTucsen additionally logs these four (no readback tolerance for NO_RESOURCE; ReverseY).
ADTUCSEN_EXTRA_WRITE_ERRORS = frozenset({"AutoLevels", "Histogram", "FlatCorrection", "ReverseY"})
CRASH_SIGNATURES = r"Segmentation|double free|corruption|data size mismatch|SDK buffer is PADDED"

# ---- identity ----------------------------------------------------------------------
IDENTITY = {
    "Manufacturer_RBV": "Tucsen",
    "Model_RBV": "Dhyana XF/XV4040BSI",
    "SerialNumber_RBV": "KBSG09024003",
    "SDKVersion_RBV": "2.0.7.0",
    "FirmwareVersion_RBV": "2c022311292c01220509",
    "PortName_RBV": "TUCSEN",
}
DRIVER_VERSION = "0.2.0"
ADCORE_VERSION_PREFIX = "3.14"

# ---- geometry / camera ---------------------------------------------------------------
MAX_SIZE = 4096
NELM_IMAGE1 = 16777216
BUFF_TOTAL = 2                                     # SDK ring depth
POOL_MAX_MB = 1907.0                               # 2000000000 bytes in MiB
POOL_MAX_TOL_MB = 10.0
TEMP_RANGE_C = (-40.0, 40.0)
TEMP_ACTUAL_PREC = 2
EXPOSURE_STEP_S = 10.32e-6                         # one sensor row time
EXPOSURE_TOL_S = 1e-4
EXPOSURE_MIN_S = 10.32e-6
FULL_FRAME_FPS = (7.0, 10.0)                       # measured 8.6-8.7
ROI_ALIGN = {"MinX": 4, "MinY": 4, "SizeX": 8, "SizeY": 4}

# Enums the driver fills at runtime from the SDK (not in the .template).
DYNAMIC_ENUMS = {
    "FrameSpeed": ("High",),
    "BitDepth": ("16",),
    "BinMode": ("4096x4096", "2048x2048(2x2Bin)", "1024x1024(4x4Bin)"),
    "FanGear": None,                               # non-empty; exact strings not asserted
    "GainMode": (),                                # unsupported: CA exposes it as long, no strings
}
FRAME_FORMAT_ENUM = ("Raw", "Usual")               # RGB888 deliberately removed in our template
# Records that exist only in our template (and therefore only on our IOC).
EXTRA_RECORDS = frozenset({
    "cam1:TECEnable", "cam1:TECEnable_RBV", "cam1:BuffFrames_RBV", "cam1:BuffTotal_RBV",
})
# Telemetry the long continuous run expects to keep updating (stress/test_long_continuous.py).
LONG_RUN_TELEMETRY = ("cam1:BuffFrames_RBV", "cam1:TransferRate_RBV", "cam1:TemperatureActual")
# TemperatureActual exists in both (ADBase); ours overrides PREC. Listed for the static diff.
TEMPLATE_ONLY_OURS = frozenset({"TECEnable", "TECEnable_RBV", "TemperatureActual",
                                "BuffFrames_RBV", "BuffTotal_RBV"})

# ---- plugins (commonPlugins.cmd) -----------------------------------------------------
PLUGINS_FORCED_ON = ("image1:", "Pva1:", "Stats1:")   # st.cmd dbpf after iocInit
PLUGINS_LOADED = (
    "image1:", "Pva1:", "HDF1:", "TIFF1:", "JPEG1:", "netCDF1:", "Nexus1:",
    "Stats1:", "Stats2:", "Stats3:", "Stats4:", "Stats5:",
    "ROI1:", "ROI2:", "ROI3:", "ROI4:", "Proc1:", "Trans1:", "Over1:", "CB1:",
    "Codec1:", "Codec2:", "BadPix1:", "Attr1:", "FFT1:", "Gather1:", "Scatter1:",
    "ROIStat1:", "CC1:", "CC2:",
)
NDARRAY_PORT = "TUCSEN"
FILE_TEMPLATES = {"TIFF1:": "%s%s_%3.3d.tif", "HDF1:": "%s%s_%3.3d.h5",
                  "JPEG1:": "%s%s_%3.3d.jpg", "netCDF1:": "%s%s_%3.3d.nc"}
AUTOSAVE_REQUIRED_PREFIXES = {"Codec1:": 20, "Codec2:": 20, "BadPix1:": 15, "Proc1:TIFF:": 20, "image1:": 15}

# ---- image content ------------------------------------------------------------------
RAMP_SIGNATURE = (0, 65280, 32640.0)               # min, max, mean -- known-gaps TODO §8
DARK_FRAME_MEAN_MAX_ADU = 1000.0
RAMP_REASON = ("camera emits a synthetic 256-level ramp instead of sensor data since "
               "2026-08-26 (info/known-gaps/TODO.md §8); power-cycle the camera")

# ---- performance reference (this host, Renesas controller, 2026-08-26/09-10) ----------
RATE_REFERENCE_FPS = {4096: 8.7, 2048: 17.3, 1024: 34.4, 512: 68.8, 256: 137.1,
                      128: 272.0, 64: 534.0, 32: 1035.0, 8: 3580.0}
RATE_TOLERANCE = 0.05

# ---- stress tier (tests/stress) -------------------------------------------------------
# Writer throughput reference: Stream mode, uncompressed, one frame per chunk, HDF1 the only
# file plugin (info/performance/2026-08-26-roi-frame-rate-vm-renesas-bl1101ad01.md).
WRITER_REFERENCE_FPS = {4096: 8.4, 2048: 15.8, 1024: 31.5, 512: 62.9, 256: 125.9,
                        128: 250.7, 64: 501.8, 32: 945.1, 8: 3254.6}
WRITER_TOLERANCE = 0.15
SWEEP_HEIGHTS = (4096, 2048, 1024, 512, 256, 128, 64, 32, 8)
# NDArrayTimeStamp is the SDK arrival time and the SDK delivers in bulk transfers below
# ~1024 rows (max/nominal interval 6.8 at 512 rows, 12 at 256, 21 at 8 on the 2026-08-26
# files), so the strict "no interval above 2x nominal" rule applies only at large heights;
# below it the check is a stall detector.
JITTER_STRICT_MIN_HEIGHT = 1024
JITTER_STALL_MS = 150.0
POOL_PEAK_FRACTION = 0.9
RSS_GROWTH_MAX_MB = 50.0
LONG_RUN_MIN_RATE_FRACTION = 0.9
PVA_MONITOR_MIN_FRACTION = 0.8
# HDF5 file contract (tests/workflow/test_hdf5_contract.py): the NDAttributes datasets
# NDFileHDF5 writes. The driver's ColorMode attribute is consumed by the plugin to lay out
# the data (mono vs RGB) and is NOT stored as an NDAttributes dataset (verified 2026-09-11).
EXPECTED_NDATTRIBUTES = frozenset({"NDArrayUniqueId", "NDArrayTimeStamp", "NDArrayEpicsTSSec",
                                   "NDArrayEpicsTSnSec"})
EXPECTED_DATASETS = ("/entry/data/data", "/entry/instrument/detector/data",
                     "/entry/instrument/performance/timestamp")
