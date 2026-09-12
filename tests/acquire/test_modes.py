"""Image modes and the stop path, with the port-thread liveness probe after every stop."""
import pytest

from helpers import acquire

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("camera", "restore_settings")]


@pytest.fixture(autouse=True)
def _full_frame_short_exposure(ca):
    acquire.full_frame(ca)
    ca.put_and_wait_rbv("cam1:AcquireTime", 0.05)
    ca.put_and_wait_rbv("cam1:ArrayCallbacks", 1)


def test_single_frame(ca):
    c0 = ca.get_int("cam1:ArrayCounter_RBV")
    u0 = ca.get_int("image1:UniqueId_RBV")
    c1 = acquire.acquire_single(ca)
    assert c1 == c0 + 1
    assert ca.get_str("cam1:DetectorState_RBV") == "Idle"
    assert (ca.get_int("cam1:ArraySizeX_RBV"), ca.get_int("cam1:ArraySizeY_RBV")) == (4096, 4096)
    ca.wait_for("image1:UniqueId_RBV", lambda v: int(v) != u0, timeout=5.0)


def test_multiple_five(ca):
    c0 = ca.get_int("cam1:ArrayCounter_RBV")
    assert acquire.acquire_multiple(ca, 5) == c0 + 5
    assert ca.get_int("cam1:NumImagesCounter_RBV") == 5


def test_continuous_start_stop_port_thread_alive(ca, exp):
    frames = acquire.run_continuous(ca, 3.0)
    lo, _ = exp.FULL_FRAME_FPS
    assert frames >= int(lo * 3.0 * 0.6), f"only {frames} frames in 3 s of continuous"
    acquire.wait_idle(ca)      # raises DeadlockSuspected if the port thread is stuck


def test_array_counter_reset_roundtrip(ca):
    ca.put("cam1:ArrayCounter", 7)
    ca.wait_for("cam1:ArrayCounter_RBV", lambda v: int(v) == 7, timeout=5)
    ca.put("cam1:ArrayCounter", 0)
    ca.wait_for("cam1:ArrayCounter_RBV", lambda v: int(v) == 0, timeout=5)


def test_stop_while_idle_is_harmless(ca):
    acquire.stop(ca)
    assert ca.get_str("cam1:DetectorState_RBV") == "Idle"


def test_status_message_after_stop(ca):
    acquire.stop(ca)
    assert "acquire" in ca.get_str("cam1:StatusMessage_RBV").lower()
