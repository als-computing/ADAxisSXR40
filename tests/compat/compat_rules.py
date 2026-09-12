"""The intended differences between our IOC and Damon's ADTucsen IOC. Data only.

Names are relative to the prefix. Anything not listed here that differs is a FAIL in the
compat report. When adding an entry, say why in a comment: this file IS the contract.
"""
from helpers import expected as ours

# Records only our template defines (TEC enable, SDK ring telemetry).
ONLY_IN_OURS_OK = {"cam1:TECEnable", "cam1:TECEnable_RBV", "cam1:BuffFrames_RBV", "cam1:BuffTotal_RBV"}

# Records that may exist only on his IOC (regexes on the relative name). Empty on purpose:
# both IOCs load the same commonPlugins.cmd. Add here only with a reason.
ONLY_IN_THEIRS_OK_PATTERNS: list[str] = []

# Enum strings that differ by design: ours must equal the tuple given.
ENUM_DIFF_OK = {
    "cam1:FrameFormat": ours.FRAME_FORMAT_ENUM,        # RGB888 removed: stalls the mono sensor
    "cam1:FrameFormat_RBV": ours.FRAME_FORMAT_ENUM,
}

# PREC/EGU that differ by design.
PREC_EGU_DIFF_OK = {"cam1:TemperatureActual"}         # ours PREC 2 (calibrated °C), ADBase default 1

TYPE_DIFF_OK: set[str] = set()
COUNT_DIFF_OK: set[str] = set()

# Values that must be identical on both IOCs (identity, geometry, wiring). Everything
# else is never value-compared: counters, temperatures, timestamps, file settings...
VALUE_MUST_MATCH = {
    "cam1:Manufacturer_RBV", "cam1:Model_RBV", "cam1:SerialNumber_RBV", "cam1:SDKVersion_RBV",
    "cam1:FirmwareVersion_RBV", "cam1:PortName_RBV", "cam1:MaxSizeX_RBV", "cam1:MaxSizeY_RBV",
    "cam1:ADCoreVersion_RBV", "cam1:DriverVersion_RBV",
    "image1:NDArrayPort_RBV", "Pva1:NDArrayPort_RBV", "HDF1:NDArrayPort_RBV", "Stats1:NDArrayPort_RBV",
    "Pva1:PvName_RBV", "image1:ArrayData.NELM",
}
# ...but these may legitimately differ even though they are in VALUE_MUST_MATCH's spirit.
VALUE_DIFF_OK = {"cam1:DriverVersion_RBV"}             # both read 0.2.0 today; allowed to diverge

# Boot-log differences (see helpers/expected*.py).
WRITE_ERRORS_OURS = set(ours.UNSUPPORTED_CONTROLS)
WRITE_ERRORS_THEIRS = set(ours.UNSUPPORTED_CONTROLS) | set(ours.ADTUCSEN_EXTRA_WRITE_ERRORS)
AUTOSAVE_COUNT_OURS = ours.AUTOSAVE_PV_COUNT          # 2373
AUTOSAVE_COUNT_THEIRS = 2391                          # counts ADBase twice; 2354 unique
