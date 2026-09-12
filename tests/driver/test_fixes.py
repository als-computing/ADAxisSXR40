"""The other fixes the fork made, one test each. fork_fix => xfail when ADTucsen serves."""
import time

import pytest

from helpers import acquire
from helpers.ca import ReadbackTimeout

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("camera", "restore_settings")]


@pytest.mark.fork_fix(reason="upstream calls setIntegerParam(function) twice and never publishes Histogram")
def test_autolevels_publishes_histogram_readback(ca):
    ca.put_and_wait_rbv("cam1:AutoLevels", 0)
    ca.put_and_wait_rbv("cam1:Histogram", 0)
    ca.put("cam1:AutoLevels", 1)                       # the SDK may answer NO_RESOURCE; value applies
    ca.wait_for("cam1:Histogram_RBV", lambda v: int(v) == 1, timeout=3.0)
    ca.put("cam1:AutoLevels", 0)
    ca.wait_for("cam1:Histogram_RBV", lambda v: int(v) == 0, timeout=3.0)


@pytest.mark.fork_fix(reason="upstream accepts RGB888 (index 2) and the mono sensor then stalls acquisition")
def test_frameformat_out_of_range_is_rejected(ca, exp):
    before = ca.get_int("cam1:FrameFormat_RBV")
    try:
        ca.put("cam1:FrameFormat", 2, wait=True, timeout=3.0)
    except Exception:  # noqa: BLE001  -- a CA put error is an acceptable way to refuse
        pass
    time.sleep(1.0)
    assert ca.get_int("cam1:FrameFormat_RBV") == before
    assert tuple(ca.enum_strs("cam1:FrameFormat")) == exp.FRAME_FORMAT_ENUM


def test_frameformat_valid_values_roundtrip(ca):
    ca.put_and_wait_rbv("cam1:FrameFormat", 1)
    ca.put_and_wait_rbv("cam1:FrameFormat", 0)


@pytest.mark.parametrize("t", [0.1, 0.02, 0.5])
def test_exposure_readback_is_quantised_to_row_time(ca, exp, t):
    rbv = float(ca.put_and_wait_rbv("cam1:AcquireTime", t, tol=exp.EXPOSURE_TOL_S))
    steps = rbv / exp.EXPOSURE_STEP_S
    assert abs(steps - round(steps)) < 0.05, f"{rbv} s is not a multiple of {exp.EXPOSURE_STEP_S} s"


@pytest.mark.full
def test_exposure_minimum_is_one_row_time(ca, exp):
    ca.put("cam1:AcquireTime", 1e-6)
    rbv = ca.wait_for("cam1:AcquireTime_RBV", lambda v: float(v) < 1e-3, timeout=5.0)
    assert float(rbv) >= exp.EXPOSURE_MIN_S * 0.99


@pytest.mark.fork_fix(reason="upstream treats TUCAMRET_NO_RESOURCE as failure and forces ReverseY back to 0, "
                             "although the camera applied the write (readback stays 0 on ADTucsen)")
def test_reversey_roundtrip(ca):
    """TUIDC_VERTICAL. The SDK answers the write with NO_RESOURCE but applies it. Our
    setCapability() verifies by readback and accepts; ADTucsen discards the value. The
    earlier note that ReverseY 'does not take' (known-gaps TODO §3) described ADTucsen's
    behaviour, not the camera's. Verified on both drivers 2026-09-11."""
    ca.put_and_wait_rbv("cam1:ReverseY", 1)
    ca.put_and_wait_rbv("cam1:ReverseY", 0)


def test_reversex_roundtrip(ca):
    ca.put_and_wait_rbv("cam1:ReverseX", 1)
    ca.put_and_wait_rbv("cam1:ReverseX", 0)


@pytest.mark.ours_only
def test_write_error_set_equals_the_unsupported_controls(boot_log, exp, opts):
    from helpers import ioclog
    assert ioclog.write_error_records(boot_log, opts.prefix) == set(exp.UNSUPPORTED_CONTROLS)


def test_flat_correction_step_write_does_not_error(ca):
    """FlatCorrection is a 4-step sequence; writing step 0 (off) is accepted by both drivers
    when already off. The NO_RESOURCE difference shows in the boot log (autosave replay), see
    boot/test_boot_log.py, not here."""
    try:
        ca.put("cam1:FlatCorrection", 0, wait=True, timeout=5.0)
    except ReadbackTimeout:
        pytest.fail("write reported an error")
    assert ca.get_int("cam1:FlatCorrection_RBV") == 0
