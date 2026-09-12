"""Captures at changing ROI heights, the way a beamline session actually moves: full frame,
a strip, a mid-size window, full frame again. The August incident geometry (32 rows after
a fast stop) sits in the middle of the sequence; the deadlock probe runs after every stop."""
import pytest

from helpers import stressrun

pytestmark = [pytest.mark.stress, pytest.mark.usefixtures("stress_ready", "restore_settings")]

SEQUENCE = [(0, 4096), (1, 32), (2, 1024), (3, 4096)]


@pytest.mark.parametrize("step,height", SEQUENCE, ids=[f"{i}-{h}rows" for i, h in SEQUENCE])
def test_capture_after_roi_change(ca, exp, ioc, outdir, h5check, byte_budget, ioc_pid, log_delta,
                                  stress_results, step, height):
    rec = stressrun.run_stream(ca, height=height, duration=5, outdir=outdir, h5check=h5check,
                               budget=byte_budget, pid=ioc_pid, log_delta=log_delta, driver=ioc.driver,
                               test_id=f"roi step {step}")
    stress_results.add(rec)
    stressrun.assert_clean_run(rec, exp, check_rate=False)   # 5 s runs understate the rate (fixed cost)
