"""The only trigger mode testable without external hardware: Software."""
import time

import pytest

from helpers import acquire

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("camera", "restore_settings")]

SOFTWARE = 4      # TriggerMode enum: Free Run, Standard, Synchronous, Global, Software
FREE_RUN = 0


def test_software_trigger_produces_exactly_one_frame(ca):
    acquire.full_frame(ca)
    ca.put_and_wait_rbv("cam1:AcquireTime", 0.05)
    ca.put_and_wait_rbv("cam1:ImageMode", 0)
    ca.put_and_wait_rbv("cam1:TriggerMode", SOFTWARE)
    c0 = ca.get_int("cam1:ArrayCounter_RBV")
    ca.put("cam1:Acquire", 1, wait=False)
    ca.wait_for("cam1:DetectorState_RBV", lambda s: s == "Acquire", timeout=5.0, as_string=True)
    time.sleep(1.0)
    assert ca.get_int("cam1:ArrayCounter_RBV") == c0, "a frame arrived without a trigger"
    ca.put("cam1:SoftwareTrigger", 1)
    ca.wait_for("cam1:ArrayCounter_RBV", lambda v: int(v) == c0 + 1, timeout=10.0)
    ca.wait_for("cam1:DetectorState_RBV", lambda s: s != "Acquire", timeout=10.0, as_string=True)
    acquire.wait_idle(ca)
    # a second trigger without re-arming (Single mode finished) produces nothing
    ca.put("cam1:SoftwareTrigger", 1)
    time.sleep(1.0)
    assert ca.get_int("cam1:ArrayCounter_RBV") == c0 + 1
    ca.put_and_wait_rbv("cam1:TriggerMode", FREE_RUN)


@pytest.mark.parametrize("rel,vals", [("cam1:TriggerEdge", (1, 0)), ("cam1:TriggerExposure", (1, 0))])
def test_trigger_input_setpoints_roundtrip(ca, rel, vals):
    for v in vals:
        ca.put_and_wait_rbv(rel, v)


def test_trigger_delay_roundtrip(ca):
    ca.put_and_wait_rbv("cam1:TriggerDelay", 0.001, tol=1e-6)
    ca.put_and_wait_rbv("cam1:TriggerDelay", 0.0, tol=1e-6)
