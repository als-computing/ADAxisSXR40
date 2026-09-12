"""The NDArrayPool does not grow run over run: a second identical run reuses the first run's buffers."""
import time

import pytest

from helpers import acquire

pytestmark = [pytest.mark.full, pytest.mark.usefixtures("camera", "restore_settings")]

FRAME_MB = 32.0


def _used(ca):
    return float(ca.get("cam1:PoolUsedMem"))


def test_pool_memory_stable_across_two_runs(ca):
    acquire.full_frame(ca)
    ca.put_and_wait_rbv("cam1:ArrayCallbacks", 1)
    ca.put_and_wait_rbv("cam1:AcquireTime", 0.02)
    ca.put("cam1:PoolPollStats", 1)
    acquire.run_continuous(ca, 5.0)
    time.sleep(3.0)
    after_first = _used(ca)
    acquire.run_continuous(ca, 5.0)
    time.sleep(3.0)
    after_second = _used(ca)
    ca.wait_for("cam1:NumQueuedArrays", lambda v: int(v) == 0, timeout=10.0)
    assert after_second <= after_first + 2 * FRAME_MB, \
        f"pool grew from {after_first:.0f} MB to {after_second:.0f} MB between identical runs"
