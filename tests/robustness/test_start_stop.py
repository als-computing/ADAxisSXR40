"""20 start/stop cycles at a 32-row ROI: the geometry that deadlocked the IOC in August.

Plugins are taken out of the loop (ArrayCallbacks 0) as in the measurement script. Each
stop is followed by the port-thread liveness probe; a DeadlockSuspected here fails with
the cycle number and stops every later hardware test in the session.
"""
import time

import pytest

from helpers import acquire

pytestmark = [pytest.mark.full, pytest.mark.usefixtures("camera", "restore_settings")]

CYCLES = 20
ROWS = 32


def test_twenty_start_stop_cycles_at_32_rows(ca, record_property):
    ca.put_and_wait_rbv("cam1:ArrayCallbacks", 0)
    ca.put_and_wait_rbv("cam1:AcquireTime", 0.00002)
    got = acquire.set_geometry(ca, 0, 0, 4096, ROWS)
    assert got[3] == ROWS, got
    ca.put_and_wait_rbv("cam1:ImageMode", 2)
    rates = []
    for i in range(1, CYCLES + 1):
        c0 = ca.get_int("cam1:ArrayCounter_RBV")
        ca.put("cam1:Acquire", 1, wait=False)
        time.sleep(1.0)
        c1 = ca.get_int("cam1:ArrayCounter_RBV")
        ca.put("cam1:Acquire", 0, wait=False)
        try:
            acquire.wait_idle(ca)
        except acquire.DeadlockSuspected as e:
            pytest.fail(f"cycle {i}/{CYCLES}: {e}")
        assert c1 > c0, f"cycle {i}: no frames in 1 s"
        rates.append(c1 - c0)
    record_property("frames_per_second_per_cycle", rates)
    assert min(rates) > 500, f"unexpectedly slow cycle at {ROWS} rows: {rates}"
