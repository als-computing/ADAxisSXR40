"""Expectations when Damon English's ADTucsen IOC (ioc-xv4040) is serving XV4040:.

Everything not overridden here is shared with `expected.py`. Only the entries that
differ between the two drivers appear below, so the list itself documents the
difference.
"""
from pathlib import Path

from .expected import *  # noqa: F401,F403  (shared constants)
from . import expected as _ours

DRIVER = "adtucsen"
UNIT = "ioc-xv4040"
OTHER_UNIT = "ioc-axissxr40"
LOG = Path("/var/log/epics/xv4040.log")
PROCSERV_CHILD = "xv4040"
ST_CMD_PATTERN = r"tucsenApp .*xv4040/st\.cmd"

TEMPLATE = _ours.ADTUCSEN_TEMPLATE
AUTOSAVE_SAV = Path("/usr/local/epics/iocs/xv4040/autosave/auto_settings.sav")
IOC_BOOT = Path("/usr/local/epics/iocs/xv4040")

HAS_CAPABILITY_AUDIT = False
CAPABILITY_AUDIT = None
# His auto_settings.req includes ADBase_settings.req twice (37 duplicates); 2354 unique.
AUTOSAVE_PV_COUNT = 2391
WRITE_ERROR_RECORDS = _ours.UNSUPPORTED_CONTROLS | _ours.ADTUCSEN_EXTRA_WRITE_ERRORS

TEMP_ACTUAL_PREC = 1                               # ADBase default; ours overrides to 2
FRAME_FORMAT_ENUM = ("Raw", "Usual", "RGB888")
EXTRA_RECORDS = frozenset()                        # nothing exists only on his IOC
LONG_RUN_TELEMETRY = ("cam1:TransferRate_RBV", "cam1:TemperatureActual")   # no ring counters in his template
DYNAMIC_ENUMS = dict(_ours.DYNAMIC_ENUMS)

# His st.cmd does not force plugin callbacks on at boot? It does (same dbpf lines).
PLUGINS_FORCED_ON = _ours.PLUGINS_FORCED_ON
# His st.cmd sets no FileTemplate defaults; they come from his autosave.
FILE_TEMPLATES = {}
AUTOSAVE_REQUIRED_PREFIXES = {"Codec1:": 20, "Codec2:": 20, "BadPix1:": 15, "Proc1:TIFF:": 20}
