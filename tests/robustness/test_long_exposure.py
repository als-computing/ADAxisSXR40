"""A 5 s exposure completes: the frame-wait timeout follows the exposure (fork change 1)."""
import time

import pytest

from helpers import acquire

pytestmark = [pytest.mark.full, pytest.mark.usefixtures("camera", "restore_settings")]


def test_five_second_exposure_delivers_a_frame(ca):
    acquire.full_frame(ca)
    ca.put_and_wait_rbv("cam1:ArrayCallbacks", 0)
    ca.put_and_wait_rbv("cam1:AcquireTime", 5.0)
    ca.put_and_wait_rbv("cam1:ImageMode", 0)
    c0 = ca.get_int("cam1:ArrayCounter_RBV")
    t0 = time.monotonic()
    ca.put("cam1:Acquire", 1, wait=False)
    ca.wait_for("cam1:ArrayCounter_RBV", lambda v: int(v) == c0 + 1, timeout=20.0)
    dt = time.monotonic() - t0
    acquire.wait_idle(ca)
    assert 4.5 <= dt <= 12.0, f"frame after {dt:.1f} s for a 5 s exposure"
    assert ca.get_str("cam1:DetectorState_RBV") == "Idle"
