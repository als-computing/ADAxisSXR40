"""Will the detector run for a long time? Continuous acquisition with plugins off for
--long-minutes (default 5), sampling the frame rate, the IOC's memory and the telemetry
PVs every 30 s. No disk involved: this isolates the camera, SDK and driver."""
import time

import pytest

from helpers import acquire, stressrun

pytestmark = [pytest.mark.stress, pytest.mark.usefixtures("stress_ready", "restore_settings")]

SAMPLE_S = 30.0


def _stamp(ca, rel):
    pv = ca.pv(rel)
    pv.get(use_monitor=False, timeout=5)
    return pv.timestamp


def test_long_continuous_acquisition(ca, exp, ioc_pid, stress_opts, stress_results, record_property):
    minutes = stress_opts["long_minutes"]
    telemetry = exp.LONG_RUN_TELEMETRY            # his template has no ring counters
    has_ring = "cam1:BuffFrames_RBV" in telemetry
    acquire.full_frame(ca)
    ca.put_and_wait_rbv("cam1:ArrayCallbacks", 0)
    ca.put_and_wait_rbv("cam1:AcquireTime", 0.02)
    ca.put_and_wait_rbv("cam1:ImageMode", 2)
    samples = []
    stamps0 = {r: _stamp(ca, r) for r in telemetry}
    rss0 = stressrun.rss_kb(ioc_pid)
    c_prev = ca.get_int("cam1:ArrayCounter_RBV")
    ca.put("cam1:Acquire", 1, wait=False)
    t_start = time.monotonic()
    t_prev = t_start
    n = max(2, int(round(minutes * 60 / SAMPLE_S)))
    for i in range(n):
        time.sleep(SAMPLE_S)
        now = time.monotonic()
        c = ca.get_int("cam1:ArrayCounter_RBV")
        samples.append({"t_s": round(now - t_start), "fps": round((c - c_prev) / (now - t_prev), 2),
                        "rss_mb": round(stressrun.rss_kb(ioc_pid) / 1024, 1),
                        "buff_frames": ca.get_int("cam1:BuffFrames_RBV") if has_ring else None,
                        "transfer_rate": float(ca.get("cam1:TransferRate_RBV")),
                        "temp_c": float(ca.get("cam1:TemperatureActual"))})
        c_prev, t_prev = c, now
    acquire.stop(ca)                                    # includes the port-thread probe
    stamps1 = {r: _stamp(ca, r) for r in telemetry}
    stress_results.extra["long_continuous"] = {"minutes": minutes, "samples": samples,
                                               "rss_start_mb": round(rss0 / 1024, 1)}
    record_property("samples", samples)

    first = samples[0]["fps"]
    slow = [s for s in samples[1:] if s["fps"] < exp.LONG_RUN_MIN_RATE_FRACTION * first]
    assert not slow, f"frame rate sagged below {exp.LONG_RUN_MIN_RATE_FRACTION:.0%} of the first interval: {slow}"
    lo, hi = exp.FULL_FRAME_FPS
    assert lo <= first <= hi, f"first interval {first} fps"
    # Starting a continuous acquisition allocates ~256 MB once (SDK transfer buffers, 8 full
    # frames; released at stop). A leak is growth *while* acquiring: first sample to last.
    startup = samples[0]["rss_mb"] - rss0 / 1024
    growth = samples[-1]["rss_mb"] - samples[0]["rss_mb"]
    stress_results.extra["long_continuous"]["rss_startup_alloc_mb"] = round(startup, 1)
    record_property("rss_startup_alloc_mb", round(startup, 1))
    assert growth < exp.RSS_GROWTH_MAX_MB, \
        f"IOC RSS grew {growth:.0f} MB between the first and last sample ({minutes} min; start-up alloc {startup:.0f} MB)"
    stale = [r for r in telemetry if stamps1[r] == stamps0[r]]
    assert not stale, f"telemetry PVs stopped updating during the run: {stale}"
    assert any(s["transfer_rate"] > 0 for s in samples), "TransferRate never read above 0"
    assert ca.get_str("cam1:DetectorState_RBV") == "Idle"
