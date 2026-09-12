"""Throughput regression: run the sweep script at three heights and compare with the record.

Reference numbers: helpers/expected.RATE_REFERENCE_FPS, taken from
info/performance/2026-08-26-roi-frame-rate-vm-renesas-bl1101ad01.md and the 2026-09-10
two-driver comparison on this host. Tolerance 5 %.
"""
import os
import re
import subprocess
from pathlib import Path

import pytest

from helpers import expected as ours

pytestmark = [pytest.mark.full, pytest.mark.usefixtures("camera", "restore_settings")]

SCRIPT = Path(__file__).with_name("roi-rate-test.sh")
RE_ROW = re.compile(r"acquire-only\s+([\d.]+) fps")


def run_point(height: int, prefix: str) -> float:
    env = dict(os.environ)
    env["PATH"] = f"{ours.EPICS_BIN}:{env.get('PATH', '')}"
    env["AXIS_PREFIX"] = prefix
    r = subprocess.run([str(SCRIPT), str(height), "100", "nowrite"], capture_output=True, text=True,
                       timeout=120, env=env)
    m = RE_ROW.search(r.stdout)
    assert r.returncode == 0 and m, f"h={height}: rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    return float(m.group(1))


@pytest.mark.parametrize("height", [4096, 512, 32])
def test_acquire_only_rate_within_tolerance(opts, exp, height, record_property):
    fps = run_point(height, opts.prefix)
    ref = exp.RATE_REFERENCE_FPS[height]
    record_property(f"fps_{height}", fps)
    assert abs(fps - ref) / ref <= exp.RATE_TOLERANCE, \
        f"h={height}: {fps} fps vs reference {ref} (±{exp.RATE_TOLERANCE:.0%})"
