"""Streaming to HDF5 while somebody is watching: a pvAccess client (helpers/pva_viewer.py on
p4p, standing in for the viewer) subscribes to Pva1:Image with the full request and Stats1
computes, at full frame for 25 s. The drop-free result with nobody watching is not the
operating condition.

pvmonitor cannot stand in: a sub-field request (`field(uniqueId)`) on the NDPluginPva record
never receives an update (QSRV records do), and with the full request it spends seconds
formatting each 32 MiB frame as text.
"""
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from helpers import acquire, pva, stressrun

pytestmark = [pytest.mark.stress, pytest.mark.usefixtures("stress_ready", "restore_settings")]


def _p4p_available() -> bool:
    return subprocess.run([sys.executable, "-c", "import p4p"], capture_output=True).returncode == 0


class Viewer:
    """`python -m helpers.pva_viewer <pv>` as a subprocess, collecting the unique ids it prints."""

    def __init__(self, pv: str):
        self.ids: list[int] = []
        self.bytes = 0
        self.proc = subprocess.Popen([sys.executable, "-m", "helpers.pva_viewer", pv],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                     env=pva._env(), cwd=str(Path(__file__).resolve().parents[1]))
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        for line in self.proc.stdout:
            parts = line.split()
            if len(parts) == 3 and parts[0] == "frame":
                self.ids.append(int(parts[1]))
                self.bytes += int(parts[2])

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)


def test_stream_while_a_viewer_watches(ca, exp, ioc, opts, outdir, h5check, byte_budget, ioc_pid, log_delta,
                                       stress_results, record_property):
    if not _p4p_available():
        pytest.skip("p4p not installed in the test venv (tests/.venv/bin/pip install p4p)")
    ca.put_and_wait_rbv("Stats1:EnableCallbacks", 1)
    ca.put_and_wait_rbv("Stats1:ComputeStatistics", 1)
    ca.put_and_wait_rbv("Pva1:EnableCallbacks", 1)
    ca.put_and_wait_rbv("cam1:ArrayCallbacks", 1)
    viewer = Viewer(f"{opts.prefix}Pva1:Image")
    try:
        acquire.full_frame(ca)
        acquire.acquire_single(ca)                     # lets the monitor connect and prove it receives
        deadline = time.monotonic() + 15
        while not viewer.ids and time.monotonic() < deadline:
            time.sleep(0.5)
        if not viewer.ids:
            pytest.skip("the p4p viewer did not receive the priming frame; PVA client path unavailable")
        viewer.ids.clear()
        rec = stressrun.run_stream(ca, height=4096, duration=25, outdir=outdir, h5check=h5check,
                                   budget=byte_budget, pid=ioc_pid, log_delta=log_delta, driver=ioc.driver,
                                   test_id="load: HDF5 + PVA viewer + Stats")
        time.sleep(2.0)
        received = len(set(viewer.ids))
    finally:
        viewer.stop()
    stress_results.add(rec)
    stress_results.extra["realistic_load"] = {"frames": rec.frames, "viewer_received": received,
                                              "viewer_MB": round(viewer.bytes / 1e6, 1)}
    record_property("viewer_received", received)
    stressrun.assert_clean_run(rec, exp)
    assert received >= exp.PVA_MONITOR_MIN_FRACTION * rec.frames, \
        f"viewer received {received} of {rec.frames} frames (< {exp.PVA_MONITOR_MIN_FRACTION:.0%})"
