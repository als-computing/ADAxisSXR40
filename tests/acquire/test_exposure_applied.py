"""Exposure must take effect end to end, not just in the readback."""
import time

import pytest

from helpers import acquire

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("camera", "restore_settings")]


def test_half_second_exposure_gives_two_fps(ca):
    acquire.full_frame(ca)
    ca.put_and_wait_rbv("cam1:ArrayCallbacks", 0)
    ca.put_and_wait_rbv("cam1:AcquireTime", 0.5)
    frames = acquire.run_continuous(ca, 6.0)
    fps = frames / 6.0
    assert 1.4 <= fps <= 2.6, f"{frames} frames in 6 s = {fps:.2f} fps with a 0.5 s exposure"


def test_time_remaining_counts_down_during_a_long_exposure(ca):
    acquire.full_frame(ca)
    ca.put_and_wait_rbv("cam1:AcquireTime", 3.0)
    ca.put_and_wait_rbv("cam1:ImageMode", 0)
    c0 = ca.get_int("cam1:ArrayCounter_RBV")
    t0 = time.monotonic()
    ca.put("cam1:Acquire", 1, wait=False)
    ca.wait_for("cam1:ArrayCounter_RBV", lambda v: int(v) == c0 + 1, timeout=15.0)
    dt = time.monotonic() - t0
    acquire.wait_idle(ca)
    assert 2.5 <= dt <= 8.0, f"3 s single exposure took {dt:.1f} s to deliver a frame"
