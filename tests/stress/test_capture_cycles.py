"""30 capture-to-a-new-file cycles without restarting anything: numbering, leaks, drift.

1024 rows x 50 frames per file (420 MB, deleted after its check), 12.6 GB in total. Each
cycle is a full run_stream, so the deadlock probe and h5check run 30 times.
"""
import pytest

from helpers import stressrun

pytestmark = [pytest.mark.stress, pytest.mark.usefixtures("stress_ready", "restore_settings")]

CYCLES = 30
HEIGHT = 1024
FRAMES = 50


def test_thirty_capture_cycles(ca, exp, ioc, outdir, h5check, byte_budget, ioc_pid, log_delta,
                               stress_results, record_property):
    ca.put_and_wait_rbv("HDF1:FileNumber", 0)
    rss = []
    for i in range(CYCLES):
        rec = stressrun.run_stream(ca, height=HEIGHT, frames=FRAMES, outdir=outdir, h5check=h5check,
                                   budget=byte_budget, pid=ioc_pid, log_delta=log_delta, driver=ioc.driver,
                                   test_id=f"cycle {i + 1}", file_name="cycle")
        stress_results.add(rec)
        assert rec.captured == FRAMES and not any(rec.dropped.values()), f"cycle {i + 1}: {rec}"
        assert rec.uid_missing == 0 and rec.log_new_errors == 0, f"cycle {i + 1}: {rec.notes}"
        assert ca.get_int("HDF1:FileNumber_RBV") == i + 1, "AutoIncrement did not advance FileNumber"
        rss.append(rec.rss_after_mb)
    stress_results.extra["capture_cycles"] = {"rss_after_each_mb": rss}
    record_property("rss_mb", rss)
    growth = rss[-1] - rss[0]
    assert growth < exp.RSS_GROWTH_MAX_MB, f"IOC RSS grew {growth:.0f} MB over {CYCLES} cycles"
    # least-squares slope, MB per cycle
    n = len(rss)
    xm, ym = (n - 1) / 2, sum(rss) / n
    slope = sum((i - xm) * (y - ym) for i, y in enumerate(rss)) / sum((i - xm) ** 2 for i in range(n))
    record_property("rss_slope_mb_per_cycle", round(slope, 3))
    assert slope < 1.0, f"IOC RSS drifting {slope:.2f} MB per capture cycle"
