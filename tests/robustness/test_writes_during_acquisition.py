"""Parameter writes while acquiring must not stall the port thread."""
import time

import pytest

from helpers import acquire

pytestmark = [pytest.mark.full, pytest.mark.usefixtures("camera", "restore_settings")]


def test_exposure_writes_during_continuous_acquisition(ca):
    acquire.full_frame(ca)
    ca.put_and_wait_rbv("cam1:ArrayCallbacks", 0)
    ca.put_and_wait_rbv("cam1:AcquireTime", 0.05)
    ca.put_and_wait_rbv("cam1:ImageMode", 2)
    c0 = ca.get_int("cam1:ArrayCounter_RBV")
    ca.put("cam1:Acquire", 1, wait=False)
    ca.wait_for("cam1:ArrayCounter_RBV", lambda v: int(v) > c0, timeout=5.0)
    for i in range(5):
        ca.put("cam1:AcquireTime", 0.05 + 0.01 * (i % 2), wait=True, timeout=5.0)
        time.sleep(0.4)
    c_mid = ca.get_int("cam1:ArrayCounter_RBV")
    time.sleep(1.0)
    assert ca.get_int("cam1:ArrayCounter_RBV") > c_mid, "acquisition stalled after writes"
    acquire.stop(ca)          # includes the liveness probe
    assert ca.get_str("cam1:DetectorState_RBV") == "Idle"
