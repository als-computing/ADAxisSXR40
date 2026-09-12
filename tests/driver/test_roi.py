"""ROI handling: the camera's real alignment rules and the height-clamp fix.

Measured 2026-07-29: width must be a multiple of 8, height and both offsets of 4. The
vendor guide says 4 for all; the camera disagrees. ADTucsen's setROI also wrote the
clamped HEIGHT into the WIDTH parameter -- these tests are marked fork_fix and become
expected failures when ADTucsen is serving.
"""
import pytest

from helpers import acquire

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("camera", "restore_settings")]

FULL = (0, 0, 4096, 4096)


def test_full_frame_roundtrip(ca):
    assert acquire.set_geometry(ca, *FULL) == FULL


@pytest.mark.parametrize("req,want", [(1004, 1000), (1012, 1008), (996, 992), (1000, 1000), (1008, 1008)])
def test_sizex_aligns_down_to_8(ca, req, want):
    """Width to a multiple of 8. The CAMERA does this rounding itself, so the readback is the
    same under ADTucsen (verified 2026-09-11); our driver only makes it explicit before SetROI."""
    acquire.set_geometry(ca, *FULL)
    ca.put("cam1:SizeX", req)
    ca.wait_for("cam1:SizeX_RBV", lambda v: int(v) != 4096, timeout=5)
    assert ca.get_int("cam1:SizeX_RBV") == want
    assert ca.get_int("cam1:SizeY_RBV") == 4096, "height must not change when width is written"


def _sizey(ca, req, want):
    acquire.set_geometry(ca, *FULL)
    ca.put("cam1:SizeY", req)
    ca.wait_for("cam1:SizeY_RBV", lambda v: int(v) != 4096, timeout=5)
    assert ca.get_int("cam1:SizeY_RBV") == want
    assert ca.get_int("cam1:SizeX_RBV") == 4096


@pytest.mark.parametrize("req", [1004, 1012, 996])
def test_sizey_multiple_of_4_is_kept(ca, req):
    _sizey(ca, req, req)


@pytest.mark.fork_fix(reason="ADTucsen passes an unaligned height through; the camera does NOT round it (verified 2026-09-11)")
@pytest.mark.parametrize("req,want", [(1006, 1004), (1001, 1000)])
def test_sizey_aligns_down_to_4(ca, req, want):
    _sizey(ca, req, want)


@pytest.mark.parametrize("req,want", [(12, 12), (14, 12), (4, 4), (6, 4)])
def test_minx_aligns_down_to_4(ca, req, want):
    """MinX to a multiple of 4: the camera rounds this itself too (same readback under ADTucsen)."""
    got = acquire.set_geometry(ca, req, 0, 1000, 1000)
    assert got[0] == want, f"MinX {req} -> {got[0]}, wanted {want}"


def test_miny_multiple_of_4_is_kept(ca):
    assert acquire.set_geometry(ca, 0, 12, 1000, 1000)[1] == 12


@pytest.mark.fork_fix(reason="ADTucsen passes an unaligned MinY through; the camera does NOT round it (verified 2026-09-11)")
def test_miny_aligns_down_to_4(ca):
    assert acquire.set_geometry(ca, 0, 14, 1000, 1000)[1] == 12


def test_height_clamp_does_not_touch_width(ca):
    """ADTucsen's setROI writes the clamped HEIGHT into the ADSizeX parameter (copy-paste bug),
    but it then calls Cap_SetROI with the still-correct local width and overwrites ADSizeX from
    Cap_GetROI, so the corruption never reaches EPICS. Verified 2026-09-11: passes on both
    drivers. Kept as a regression test; the fork's fix is correctness, not a visible change."""
    minx, miny, sx, sy = acquire.set_geometry(ca, 0, 100, 4096, 4096)
    assert (miny, sy) == (100, 3996), f"MinY/SizeY = {miny}/{sy}"
    assert sx == 4096, f"width corrupted to {sx} by the height clamp"


def test_width_clamp(ca):
    minx, miny, sx, sy = acquire.set_geometry(ca, 96, 0, 4096, 4096)
    assert (minx, sx, sy) == (96, 4000, 4096)


def test_size_written_before_offset_is_clamped_and_does_not_reexpand(ca):
    """Documents roi-rate-test.sh NOTE 2: set offsets first, then sizes."""
    acquire.set_geometry(ca, *FULL)
    ca.put("cam1:SizeX", 1000)
    ca.wait_for("cam1:SizeX_RBV", lambda v: int(v) == 1000, timeout=5)
    ca.put("cam1:MinX", 3200)
    ca.wait_for("cam1:MinX_RBV", lambda v: int(v) == 3200, timeout=5)
    assert ca.get_int("cam1:SizeX_RBV") == 896, "3200 + 1000 > 4096: width is clamped to 896"
    assert acquire.set_geometry(ca, *FULL) == FULL, "offsets-first recipe restores the full frame"


def test_roi_frame_has_the_requested_dimensions(ca):
    acquire.set_geometry(ca, 0, 0, 4096, 1024)
    acquire.acquire_single(ca)
    assert (ca.get_int("cam1:ArraySizeX_RBV"), ca.get_int("cam1:ArraySizeY_RBV")) == (4096, 1024)
    assert (ca.get_int("image1:ArraySize0_RBV"), ca.get_int("image1:ArraySize1_RBV")) == (4096, 1024)
