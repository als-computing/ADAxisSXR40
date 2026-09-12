"""Write a value to each safe setpoint and check the readback follows; restore afterwards.

Only the allow-list in helpers/policy.py is touched. Geometry, binning, FrameFormat,
AutoLevels/Histogram and the trigger path have dedicated tests elsewhere.
"""
import pytest

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("camera")]

# (setpoint, value A, value B): the test writes whichever differs from the current value.
CASES = [
    ("cam1:ImageMode", 0, 2),
    ("cam1:NumImages", 7, 13),
    ("cam1:AcquireTime", 0.05, 0.2),
    ("cam1:AcquirePeriod", 0.0, 0.5),
    ("cam1:ArrayCallbacks", 0, 1),
    ("cam1:TriggerEdge", 0, 1),
    ("cam1:TriggerExposure", 0, 1),
    ("cam1:TriggerDelay", 0.0, 0.001),
    ("cam1:ReverseX", 0, 1),
    ("cam1:EnableDenoise", 0, 1),
    ("cam1:DynRgeCorrection", 0, 1),
    ("cam1:Histogram", 0, 1),
    ("HDF1:EnableCallbacks", 0, 1),
    ("HDF1:FileWriteMode", 0, 2),
    ("HDF1:NumCapture", 10, 20),
    ("HDF1:AutoIncrement", 0, 1),
    ("HDF1:AutoSave", 0, 1),
    ("HDF1:FileNumber", 0, 5),
    ("HDF1:FileName", "roundtrip_a", "roundtrip_b"),
    ("HDF1:FilePath", "/tmp/roundtrip_a/", "/tmp/roundtrip_b/"),   # NDFile appends the slash
    ("TIFF1:EnableCallbacks", 0, 1),
    ("TIFF1:FileName", "roundtrip_a", "roundtrip_b"),
    ("Stats1:ComputeStatistics", 0, 1),
    ("Stats1:EnableCallbacks", 0, 1),
    ("image1:EnableCallbacks", 0, 1),
    ("Pva1:EnableCallbacks", 0, 1),
]


@pytest.mark.parametrize("rel,a,b", CASES, ids=[c[0] for c in CASES])
def test_setpoint_roundtrip(ca, restore_settings, rel, a, b):
    cur = ca.get_str(rel) if isinstance(a, str) else ca.get(rel)
    target = a if str(cur).rstrip("\x00") != str(a) else b
    got = ca.put_and_wait_rbv(rel, target)
    if isinstance(target, str):
        assert str(got).rstrip("\x00") == target
    # and back to the other value, so both directions are exercised
    other = b if target == a else a
    ca.put_and_wait_rbv(rel, other)
