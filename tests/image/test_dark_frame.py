"""Pixel sanity through Stats1. Marked hardware_state: these describe the camera, not the driver.

History: from 2026-08-26 the camera emitted a synthetic 256-level ramp (min 0, max 65280,
mean exactly 32640.0, known-gaps TODO §8). On 2026-09-11, during the first full-tier run
of this suite (which cycles BinMode 1 -> 2 -> 0), it started delivering real sensor data
again: min ~250, max ~39000, mean ~1650 ADU, sigma ~180, frames differing. The ramp test
is therefore a hard assertion now; a failure means the ramp is back. The dark-frame mean
is still far above the ~68 ADU recorded in the characterisation notes, so that check
remains an expected failure until someone confirms the sensor is dark and the offset.
"""
import pytest

from helpers import acquire
from helpers import expected as ours

pytestmark = [pytest.mark.smoke, pytest.mark.hardware_state,
              pytest.mark.usefixtures("camera", "restore_settings")]


@pytest.fixture
def stats(ca):
    acquire.full_frame(ca)
    ca.put_and_wait_rbv("cam1:AcquireTime", 0.05)
    ca.put_and_wait_rbv("cam1:ArrayCallbacks", 1)
    ca.put_and_wait_rbv("Stats1:EnableCallbacks", 1)
    ca.put_and_wait_rbv("Stats1:ComputeStatistics", 1)

    def take():
        c0 = ca.get_int("Stats1:ArrayCounter_RBV")
        acquire.acquire_single(ca)
        ca.wait_for("Stats1:ArrayCounter_RBV", lambda v: int(v) > c0, timeout=5.0)
        return dict(min=float(ca.get("Stats1:MinValue_RBV")), max=float(ca.get("Stats1:MaxValue_RBV")),
                    mean=float(ca.get("Stats1:MeanValue_RBV")), sigma=float(ca.get("Stats1:Sigma_RBV")))
    return take


def is_ramp(s) -> bool:
    mn, mx, mean = ours.RAMP_SIGNATURE
    return s["min"] == mn and s["max"] == mx and abs(s["mean"] - mean) < 1.0


def test_stats_update_for_a_new_frame(stats):
    s = stats()
    assert s["max"] >= s["min"]


def test_frame_is_not_the_synthetic_ramp(stats, record_property):
    s = stats()
    record_property("stats", s)
    print(f"\n{'RAMP PRESENT' if is_ramp(s) else 'real sensor data'}: {s}")
    assert not is_ramp(s), f"the camera is emitting its test ramp again (TODO §8): {s}"


def test_consecutive_frames_differ(stats):
    a, b = stats(), stats()
    assert a != b, "two frames with identical statistics: a pattern, not a sensor"


@pytest.mark.xfail(strict=False, reason="dark-frame mean was ~68 ADU at 50 ms (2026-07-29); reads ~1650 ADU "
                                        "on 2026-09-11 -- illumination or offset to be confirmed at the detector")
def test_dark_frame_mean_is_tens_of_adu(stats, exp):
    s = stats()
    assert s["mean"] < exp.DARK_FRAME_MEAN_MAX_ADU, f"mean {s['mean']:.0f} ADU: not a dark frame"
