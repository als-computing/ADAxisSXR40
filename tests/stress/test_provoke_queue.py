"""Deliberately make the writer fall behind and check the IOC degrades the right way.

The right way: the plugin drops frames (HDF1:DroppedArrays counts up) and the IOC stays
alive, idle afterwards, with the array pool well under its 2 GB cap and no "out of memory"
status. The wrong way is the pool cap stopping acquisition. This is the one test that
verifies the maxMemory decision in st.cmd behaves as its comment claims.

Only with --provoke (tests/run.sh stress provoke). HDF1:QueueSize is written while idle:
writing it recreates the plugin's threads and discards queued arrays.
"""
import os
import time

import pytest

from helpers import acquire, stressrun

pytestmark = [pytest.mark.stress, pytest.mark.usefixtures("stress_ready", "restore_settings")]


def test_slow_writer_drops_at_the_plugin_not_the_pool(ca, exp, outdir, ioc_pid, log_delta, stress_results,
                                                       record_property):
    q0 = ca.get_int("HDF1:QueueSize_RBV")
    b0 = ca.get_int("HDF1:BlockingCallbacks_RBV")
    path = None
    mark = log_delta.mark() if log_delta else None
    try:
        acquire.full_frame(ca)
        ca.put_and_wait_rbv("cam1:AcquireTime", 0.02)
        ca.put_and_wait_rbv("cam1:ArrayCallbacks", 1)
        ca.put("cam1:PoolPollStats", 1)
        ca.put_and_wait_rbv("HDF1:EnableCallbacks", 1)
        ca.put_and_wait_rbv("HDF1:FilePath", str(outdir) + "/")
        ca.put_and_wait_rbv("HDF1:FileName", "provoke")
        ca.put_and_wait_rbv("HDF1:FileTemplate", "%s%s_%3.3d.h5")
        ca.put_and_wait_rbv("HDF1:FileWriteMode", 2)
        ca.put_and_wait_rbv("HDF1:AutoSave", 0)
        ca.put_and_wait_rbv("HDF1:AutoIncrement", 1)
        ca.put_and_wait_rbv("HDF1:NumCapture", 100000)
        ca.put_and_wait_rbv("HDF1:Compression", 3)          # zlib
        ca.put_and_wait_rbv("HDF1:ZLevel", 6)                # slow on purpose
        acquire.prime_frame(ca, expect_y=4096)
        ca.put_and_wait_rbv("HDF1:BlockingCallbacks", 0)
        ca.put_and_wait_rbv("HDF1:QueueSize", 1)             # idle: thread recreation is harmless here
        ca.put("HDF1:DroppedArrays", 0)
        ca.put("HDF1:Capture", 1)
        ca.wait_for("HDF1:Capture_RBV", lambda v: int(v) == 1, timeout=10)
        sampler = stressrun.Sampler(ca.prefix, ["cam1:PoolUsedMem", "HDF1:QueueUse", "cam1:StatusMessage_RBV",
                                                "cam1:DetectorState_RBV"])
        sampler.start()
        ca.put_and_wait_rbv("cam1:ImageMode", 2)
        ca.put("cam1:Acquire", 1, wait=False)
        time.sleep(10.0)
        ca.put("cam1:Acquire", 0, wait=False)
        acquire.wait_idle(ca)                                # the IOC must still answer
        samples = sampler.stop()
        ca.put("HDF1:Capture", 0)
        ca.wait_for("HDF1:Capture_RBV", lambda v: int(v) == 0, timeout=60)
        path = ca.get_str("HDF1:FullFileName_RBV")
        dropped = ca.get_int("HDF1:DroppedArrays_RBV")
        peak_pool = sampler.peak("cam1:PoolUsedMem")
        outcome = {"dropped_hdf1": dropped, "captured": ca.get_int("HDF1:NumCaptured_RBV"),
                   "peak_pool_mb": peak_pool, "peak_queue_use": sampler.peak("HDF1:QueueUse"),
                   "status_messages": sorted({str(v) for _, v in samples["cam1:StatusMessage_RBV"]})}
        stress_results.extra["provoke"] = outcome
        record_property("provoke", outcome)
        assert ca.get_str("cam1:DetectorState_RBV") == "Idle"
        assert dropped > 0, "the slow writer never fell behind; the test did not provoke anything"
        assert peak_pool < exp.POOL_PEAK_FRACTION * exp.POOL_MAX_MB, f"pool reached {peak_pool} MB"
        assert not sampler.any_match("cam1:StatusMessage_RBV", "out of memory")
        if log_delta:
            bad = [l for l in log_delta.new_lines(mark)[1] if "NDArrayPool alloc failed" in l[1]] if False else \
                  [l for _, l in log_delta.new_lines(mark) if "NDArrayPool alloc failed" in l]
            assert not bad, bad
    finally:
        try:
            ca.put("cam1:Acquire", 0, wait=False)
            ca.put("HDF1:Capture", 0)
            acquire.wait_idle(ca)
        except Exception:  # noqa: BLE001
            pass
        ca.put_and_wait_rbv("HDF1:QueueSize", q0)
        ca.put_and_wait_rbv("HDF1:BlockingCallbacks", b0)
        ca.put_and_wait_rbv("HDF1:Compression", 0)
        if path and os.path.exists(path):
            os.remove(path)
