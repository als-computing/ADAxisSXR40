"""The image-processing properties the camera implements: write inside the SDK range, read back.

Ranges from info/camera/dhyana-xfxv4040bsi.md (measured TUCAM_Prop_GetAttr):
Gain 0..5, NoiseLevel 0..3, Gamma 1..255, Contrast 0..255, LeftLevels 0..65534,
RightLevels 1..65535. The driver clips out-of-range writes to the SDK limits.
"""
import pytest

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("camera", "restore_settings")]

KNOBS = [
    ("cam1:Gain", 0, 2, (0, 5)),
    ("cam1:NoiseLevel", 1, 3, (0, 3)),
    ("cam1:Gamma", 100, 120, (1, 255)),
    ("cam1:Contrast", 128, 100, (0, 255)),
    ("cam1:LeftLevels", 0, 10, (0, 65534)),
    ("cam1:RightLevels", 65535, 60000, (1, 65535)),
]


@pytest.mark.parametrize("rel,a,b,rng", KNOBS, ids=[k[0] for k in KNOBS])
def test_knob_roundtrip(ca, rel, a, b, rng):
    cur = float(ca.get(rel))
    target = a if abs(cur - a) > 0.5 else b
    got = float(ca.put_and_wait_rbv(rel, target, tol=0.5))
    assert rng[0] <= got <= rng[1]
    other = b if target == a else a
    ca.put_and_wait_rbv(rel, other, tol=0.5)


@pytest.mark.parametrize("rel,lo,hi", [("cam1:Gain", 0, 5), ("cam1:Contrast", 0, 255)])
def test_out_of_range_write_is_clipped_to_sdk_limit(ca, rel, lo, hi):
    got = float(ca.put_and_wait_rbv(rel, hi + 100, expect=hi, tol=0.5))
    assert got == hi
    ca.put_and_wait_rbv(rel, lo, tol=0.5)
