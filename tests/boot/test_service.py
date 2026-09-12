"""The service layer: one IOC, one PVA server, the guard refuses a second."""
import subprocess

import pytest

from helpers import expected as ours
from helpers import iocdetect

pytestmark = pytest.mark.smoke


def test_exactly_one_ioc_unit_is_active(ioc, exp):
    assert iocdetect.systemctl_is_active(exp.UNIT) or not ioc.unit_active
    assert not iocdetect.systemctl_is_active(exp.OTHER_UNIT), f"{exp.OTHER_UNIT} is active at the same time"


def test_exactly_one_listener_on_pva_port(exp):
    listeners = iocdetect.listeners_on_port(exp.PVA_PORT)
    assert len(listeners) == 1, listeners


def test_pvlist_shows_exactly_one_server():
    if not (ours.EPICS_BIN / "pvlist").exists():
        pytest.skip("pvlist not available")
    guids = iocdetect.pvlist_guids(ours.EPICS_BIN)
    assert len(guids) == 1, f"pvAccess servers seen: {guids}"


@pytest.mark.ours_only
def test_guard_refuses_while_an_ioc_holds_the_port(tmp_path):
    """Runs the real guard script by hand: our own IOC holds 5075, so it must refuse (exit 75)."""
    guard = ours.SYSTEMD_DIR / "ioc-axissxr40-guard.sh"
    r = subprocess.run([str(guard)], capture_output=True, text=True, timeout=30,
                       env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LOGS_DIRECTORY": str(tmp_path)})
    assert r.returncode == 75, f"exit {r.returncode}: {r.stdout} {r.stderr}"
    assert "REFUSING TO START" in r.stdout
    assert (tmp_path / "axisSXR40-guard.log").exists(), "refusal must also be written to the guard log"


def test_our_unit_is_installed_but_not_enabled():
    r = subprocess.run(["systemctl", "is-enabled", ours.UNIT], capture_output=True, text=True)
    state = r.stdout.strip()
    if state == "not-found":
        pytest.skip("ioc-axissxr40.service not installed on this host")
    assert state == "disabled", f"ioc-axissxr40 must not start at boot while ioc-xv4040 is the default (is: {state})"
