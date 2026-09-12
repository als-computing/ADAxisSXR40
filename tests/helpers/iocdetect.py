"""Which IOC is serving the prefix right now, and is the camera attached?

Never starts or stops anything. Detection order: systemd unit state, then a running
st.cmd process, then the capability-audit line in our log.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from types import ModuleType

from . import expected as ours
from . import expected_adtucsen as theirs
from . import ioclog


@dataclass
class IOCInfo:
    driver: str                 # "adaxissxr40" | "adtucsen" | "none"
    exp: ModuleType | None      # expectations module for that driver
    unit_active: bool = False
    st_cmd_pid: int | None = None
    boot_pid: int | None = None

    @property
    def log_is_current(self) -> bool:
        return self.boot_pid is not None and self.boot_pid == self.st_cmd_pid


def systemctl_is_active(unit: str) -> bool:
    try:
        r = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.stdout.strip() == "active"


def pgrep_pid(pattern: str) -> int | None:
    try:
        r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    pids = [int(p) for p in r.stdout.split() if p.isdigit()]
    return pids[0] if pids else None


def _boot_pid(exp: ModuleType) -> int | None:
    try:
        lines = ioclog.read_clean(exp.LOG)
    except OSError:
        return None
    return ioclog.last_boot_slice(lines, exp.PROCSERV_CHILD)[1]


def detect(force: str = "auto") -> IOCInfo:
    if force == "ours":
        cands = [ours]
    elif force == "adtucsen":
        cands = [theirs]
    else:
        cands = [ours, theirs]
    # 1. systemd
    for exp in cands:
        if systemctl_is_active(exp.UNIT):
            return IOCInfo(exp.DRIVER, exp, True, pgrep_pid(exp.ST_CMD_PATTERN), _boot_pid(exp))
    # 2. an IOC started by hand
    for exp in cands:
        pid = pgrep_pid(exp.ST_CMD_PATTERN)
        if pid:
            return IOCInfo(exp.DRIVER, exp, False, pid, _boot_pid(exp))
    return IOCInfo("none", None)


def camera_connected(ca) -> tuple[bool, str]:
    """roi-rate-test.sh pre-flight: state not Disconnected and MaxSizeX plausible."""
    try:
        state = ca.get_str("cam1:DetectorState_RBV")
        maxx = ca.get_int("cam1:MaxSizeX_RBV")
    except Exception as e:  # noqa: BLE001
        return False, f"no response from {ca.prefix}cam1 ({e}); is the IOC running?"
    if state == "Disconnected" or maxx <= 1:
        return False, (f"detector not connected (state={state!r}, MaxSizeX={maxx}); check power "
                       f"and USB (lsusb -d 5453:e41b), then restart the IOC")
    return True, f"state={state}, MaxSizeX={maxx}"


def listeners_on_port(port: int) -> list[str]:
    try:
        r = subprocess.run(["ss", "-Hltnp", f"sport = :{port}"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [l for l in r.stdout.splitlines() if l.strip()]


def pvlist_guids(epics_bin) -> list[str]:
    """Server discovery uses the default broadcast environment: with the address list
    pinned to 127.0.0.1 (as the tests do for CA/PVA data access) pvlist finds nothing."""
    import os
    env = {k: v for k, v in os.environ.items() if not k.startswith("EPICS_PVA_")}
    try:
        r = subprocess.run([str(epics_bin / "pvlist")], capture_output=True, text=True, timeout=15, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return re.findall(r"GUID (0x[0-9A-Fa-f]+)", r.stdout)
