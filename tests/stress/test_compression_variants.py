"""Every HDF5 compression the writer offers, for correctness rather than speed.

256 rows, 10 s, the camera held by the exposure at each spec's `camera_cap_fps` (50 fps,
~100 MB/s; zlib 10 fps since its single thread manages ~27 fps here) so the compressors
are not raced. Assertions: complete capture, no drops, the
file readable with all filters, contiguous unique ids. Speed and ratio are recorded only.
"""
import pytest

from helpers import stressrun

pytestmark = [pytest.mark.stress, pytest.mark.usefixtures("stress_ready", "restore_settings")]


@pytest.mark.parametrize("spec", stressrun.ALL_COMPRESSIONS, ids=[s.name for s in stressrun.ALL_COMPRESSIONS])
def test_compression(ca, exp, ioc, outdir, h5check, byte_budget, ioc_pid, log_delta, stress_results,
                     record_property, spec):
    cap = spec.camera_cap_fps
    rec = stressrun.run_stream(ca, height=256, duration=10, compression=spec, exposure_s=1.0 / cap,
                               rate_cap_fps=cap, outdir=outdir, h5check=h5check, budget=byte_budget,
                               pid=ioc_pid, log_delta=log_delta, driver=ioc.driver, test_id=f"compression {spec.name}")
    stress_results.add(rec)
    record_property("writer_fps", rec.writer_fps)
    record_property("compression_ratio", rec.compression_ratio)
    assert rec.captured == rec.frames, f"captured {rec.captured}/{rec.frames} with {spec.name}"
    assert not any(rec.dropped.values()), f"dropped arrays with {spec.name}: {rec.dropped}"
    assert rec.uid_missing == 0
    assert rec.log_new_errors == 0, rec.notes
    if spec.compression:
        assert rec.compression_ratio and rec.compression_ratio > 0
