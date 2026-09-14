"""ioc-axissxr40-health.sh classification, driven with fake caget/lsusb: no IOC, no camera.

The table is the contract the launcher and the README rely on: exit code, the word the line
starts with, and which verdicts still earn the watchdog heartbeat.
"""
import datetime as dt
import os
import subprocess
from pathlib import Path

import pytest

from helpers import expected as ours

pytestmark = pytest.mark.smoke

HEALTH = ours.SYSTEMD_DIR / "ioc-axissxr40-health.sh"
HEARTBEAT_CODES = {0, 2}         # OK, CAMERA ABSENT: a restart would not help


def fake_tools(tmp_path: Path, *, camera: bool, state: str | None, temp_age_s: float | None) -> dict:
    """Return an env in which lsusb/caget answer as the scenario says."""
    (tmp_path / "lsusb").write_text("#!/bin/sh\nexit %d\n" % (0 if camera else 1))
    lines = ["#!/bin/sh", 'case "$*" in']
    if state is None:
        lines.append("  *DetectorState*) exit 1 ;;")
    else:
        lines.append(f'  *DetectorState*) echo "{state}" ;;')
    if temp_age_s is None:
        lines.append("  *TemperatureActual*) exit 1 ;;")
    else:
        stamp = (dt.datetime.now() - dt.timedelta(seconds=temp_age_s)).strftime("%Y-%m-%d %H:%M:%S.%f")
        lines.append(f'  *TemperatureActual*) echo "XV4040:cam1:TemperatureActual  {stamp}  -3.1" ;;')
    lines += ["esac", "exit 0"]
    (tmp_path / "caget").write_text("\n".join(lines) + "\n")
    for f in ("lsusb", "caget"):
        os.chmod(tmp_path / f, 0o755)
    env = {"PATH": f"{tmp_path}:/usr/bin:/bin", "CAGET": str(tmp_path / "caget"), "CA_TIMEOUT_S": "1"}
    return env


def run(env):
    r = subprocess.run([str(HEALTH)], capture_output=True, text=True, timeout=30, env=env)
    return r.returncode, r.stdout.strip()


@pytest.mark.parametrize("camera,state,temp_age,code,word", [
    (True, "Idle", 0.4, 0, "OK:"),
    (True, "Acquire", 2.0, 0, "OK:"),
    (False, "Idle", 0.4, 2, "CAMERA ABSENT:"),
    (False, "Error", None, 2, "CAMERA ABSENT:"),          # camera off wins: nothing to restart
    (True, None, None, 3, "UNRESPONSIVE:"),
    (True, "Error", 0.4, 4, "ERROR:"),
    (True, "Disconnected", 0.4, 4, "ERROR:"),
    (True, "Idle", 187.0, 5, "POLL FROZEN:"),
    (True, "Idle", None, 3, "UNRESPONSIVE:"),              # state answers, temperature does not
], ids=["ok-idle", "ok-acquire", "camera-absent", "camera-absent-over-error", "hung",
        "error", "disconnected", "poll-frozen", "temp-hung"])
def test_verdicts(tmp_path, camera, state, temp_age, code, word):
    rc, line = run(fake_tools(tmp_path, camera=camera, state=state, temp_age_s=temp_age))
    assert rc == code, line
    assert line.startswith(word), line
    assert line.count("\n") == 0, "exactly one line: it becomes the unit's Status: text"
    assert line.endswith(")"), "ends with the time of the check in parentheses"


def test_poll_check_skipped_when_poll_disabled(tmp_path):
    env = fake_tools(tmp_path, camera=True, state="Idle", temp_age_s=999.0)
    env["AXIS_NO_TEMP_POLL"] = "1"
    rc, line = run(env)
    assert rc == 0 and "poll disabled" in line, line


def test_heartbeat_codes_match_launcher():
    """The launcher sends WATCHDOG=1 for exactly the codes in HEARTBEAT_CODES."""
    text = (ours.SYSTEMD_DIR / "ioc-axissxr40-run.sh").read_text()
    codes = "|".join(str(c) for c in sorted(HEARTBEAT_CODES))
    assert f"{codes}) notify --status=\"$verdict\" WATCHDOG=1" in text, "launcher heartbeat case differs from the table"


def test_ca_is_pinned_to_this_host():
    code = "\n".join(l for l in HEALTH.read_text().splitlines() if l.strip() and not l.lstrip().startswith("#"))
    assert "EPICS_CA_ADDR_LIST=127.0.0.1" in code and "EPICS_CA_AUTO_ADDR_LIST=NO" in code
    assert "systemctl" not in code and "ioc-xv4040" not in code, "the check reads PVs; it never acts on a unit"
