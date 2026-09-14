"""st.cmd, launcher scripts and the systemd unit: parse and say what they must say."""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from helpers import expected as ours

pytestmark = pytest.mark.smoke

UNIT = ours.SYSTEMD_DIR / "ioc-axissxr40.service"
RUN = ours.SYSTEMD_DIR / "ioc-axissxr40-run.sh"
GUARD = ours.SYSTEMD_DIR / "ioc-axissxr40-guard.sh"
HEALTH = ours.SYSTEMD_DIR / "ioc-axissxr40-health.sh"
START = ours.IOC_BOOT / "start_epics.sh"


def unit_value(text, key):
    m = re.search(rf"^{key}=(.*)$", text, re.M)
    return m.group(1).strip() if m else None


@pytest.fixture(scope="module")
def st_cmd():
    return ours.ST_CMD.read_text()


def code_lines(text):
    return [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]


def test_st_cmd_balanced_quotes_and_parens(st_cmd):
    bad = [l for l in code_lines(st_cmd) if l.count('"') % 2 or l.count("(") != l.count(")")]
    assert not bad, f"unbalanced lines in st.cmd: {bad}"


@pytest.mark.parametrize("pattern", [
    r'epicsEnvSet\("PREFIX",\s*"XV4040:"\)',
    r'epicsEnvSet\("PORT",\s*"TUCSEN"\)',
    r'epicsEnvSet\("CBUFFS",\s*"20"\)',
    r"NELEMENTS=16777216",
    r'axisSXR40Config\("\$\(PORT\)",\s*\$\(CAMERA\),\s*0x1,\s*0,\s*2000000000,\s*0,\s*0\)',
    r"< \$\(ADCORE\)/iocBoot/commonPlugins\.cmd",
    r'set_requestfile_path\("\$\(CALC\)/calcApp/Db"\)',
    r'dbpf\("\$\(PREFIX\)cam1:ArrayCallbacks",\s*"1"\)',
    r'dbpf\("\$\(PREFIX\)Pva1:EnableCallbacks",\s*"1"\)',
    r'dbpf\("\$\(PREFIX\)HDF1:FileTemplate",\s*"%s%s_%3\.3d\.h5"\)',
    r'create_monitor_set\("auto_settings\.req",\s*30,\s*"P=\$\(PREFIX\)"\)',
])
def test_st_cmd_contains(st_cmd, pattern):
    assert re.search(pattern, "\n".join(code_lines(st_cmd))), f"st.cmd lacks: {pattern}"


def test_st_cmd_has_shebang_and_is_executable():
    assert ours.ST_CMD.read_text().startswith("#!/usr/local/epics/support/areaDetector/ADAxisSXR40/")
    if not Path("/usr/local/epics").exists():
        pytest.skip("not the deployment host; executable bits are not preserved by every checkout")
    assert os.access(ours.ST_CMD, os.X_OK)


@pytest.mark.parametrize("script", [START, RUN, GUARD, HEALTH])
def test_shell_scripts_parse_and_are_executable(script):
    assert script.exists(), script
    assert os.access(script, os.X_OK), f"{script} is not executable"
    r = subprocess.run(["sh", "-n", str(script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_unit_file_contents():
    text = "\n".join(code_lines(UNIT.read_text()))
    for needle in ("RestartPreventExitStatus=75", "LogsDirectory=areadetector", "Restart=always",
                   "After=network-online.target ioc-xv4040.service",
                   f"ExecStart={RUN}", "Environment=EPICS_PVA_SERVER_PORT=5075"):
        assert needle in text, f"unit lacks: {needle}"
    assert "Conflicts=" not in text, "Conflicts= would silently stop Damon's service"
    assert "ExecStartPre=" not in text, "the guard must run in the main process (RestartPreventExitStatus)"


def test_unit_health_and_watchdog_settings():
    """Type=notify + watchdog: the Status: line and the self-restart described in the README."""
    text = "\n".join(code_lines(UNIT.read_text()))
    assert unit_value(text, "Type") == "notify"
    assert unit_value(text, "NotifyAccess") == "all", "systemd-notify runs as a child of the launcher"
    assert unit_value(text, "WatchdogSignal") == "SIGTERM", "SIGABRT would core-dump procServ instead of stopping the IOC"
    interval = int(unit_value(text, "Environment=HEALTH_INTERVAL") or 0)
    watchdog = int(unit_value(text, "WatchdogSec") or 0)
    assert interval >= 30, "the user asked for about one check per minute, never per second"
    assert watchdog > 3 * interval, f"WatchdogSec {watchdog} must exceed three health intervals ({interval} s) so one slow caget cannot trip it"
    assert int(unit_value(text, "TimeoutStartSec") or 0) >= 120, "camera open + iocInit + autosave needs time before READY"
    assert unit_value(text, "StartLimitBurst") == "3" and int(unit_value(text, "StartLimitIntervalSec")) >= 600
    assert "ioc-xv4040" not in re.sub(r"^After=.*$", "", text, flags=re.M), "only After= may mention Damon's unit"


def test_unit_verifies():
    if not shutil.which("systemd-analyze"):
        pytest.skip("systemd-analyze not available")
    r = subprocess.run(["systemd-analyze", "verify", str(UNIT)], capture_output=True, text=True)
    problems = [l for l in (r.stdout + r.stderr).splitlines() if l.strip() and "Unit name" not in l]
    assert not problems, problems


def test_launcher_calls_guard_then_procserv_then_supervises():
    text = "\n".join(code_lines(RUN.read_text()))
    guard = text.index("ioc-axissxr40-guard.sh")
    procserv = text.index("/usr/bin/procServ")
    assert guard < procserv, "the guard must run before procServ is started"
    assert "exit $?" in text[guard:procserv], "a guard refusal (75) must end the launcher before any notify"
    assert "20001" in text, "console port must differ from ioc-xv4040's 20000"
    assert "ioc-axissxr40-health.sh" in text and "--ready" in text and "WATCHDOG=1" in text
    assert "trap on_term TERM INT" in text, "SIGTERM from systemctl stop / the watchdog must reach procServ"
    assert "systemctl" not in text, "the launcher never acts on any unit; systemd's watchdog does the restart"
    assert "ioc-xv4040" not in text


def test_guard_exit_code_and_checks():
    text = GUARD.read_text()
    assert "exit 75" in text
    assert "ioc-xv4040.service" in text and "5075" in text
    assert "activating" in text, "must also refuse while the other unit is activating"


def test_start_epics_uses_the_same_guard():
    text = "\n".join(code_lines(START.read_text()))
    assert "ioc-axissxr40-guard.sh" in text
    assert "EPICS_CA_SERVER_PORT" not in text, "a non-default CA port made this IOC invisible"
