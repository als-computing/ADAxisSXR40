"""The matrix: sustained HDF5 streaming for each duration at each ROI height.

Durations and heights come from --stress-durations / --stress-heights (defaults 10,25 s at
4096 and 256 rows). Heights run largest first so a small-height deadlock costs nothing
already measured. Every run is checked with h5check and deleted before the next.
"""
import pytest

from conftest import _stress_opts
from helpers import stressrun

pytestmark = [pytest.mark.stress, pytest.mark.usefixtures("stress_ready", "restore_settings")]


def pytest_generate_tests(metafunc):
    if {"duration", "height"} <= set(metafunc.fixturenames):
        so = _stress_opts(metafunc.config)
        params = [(d, h) for d in so["durations"] for h in sorted(so["heights"], reverse=True)]
        metafunc.parametrize("duration,height", params, ids=[f"{int(d)}s-{h}rows" for d, h in params])


def test_stream(ca, exp, ioc, outdir, h5check, byte_budget, ioc_pid, log_delta, stress_results,
                record_property, duration, height):
    rec = stressrun.run_stream(ca, height=height, duration=duration, outdir=outdir, h5check=h5check,
                               budget=byte_budget, pid=ioc_pid, log_delta=log_delta, driver=ioc.driver,
                               test_id=f"matrix {int(duration)}s")
    stress_results.add(rec)
    record_property("writer_fps", rec.writer_fps)
    record_property("MBps", rec.MBps)
    stressrun.assert_clean_run(rec, exp)
