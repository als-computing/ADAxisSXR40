"""pvAccess checks via the base tools (pvget/pvinfo), since p4p is not on the system python."""
from __future__ import annotations

import os
import re
import subprocess

from . import expected


def _env():
    # default discovery (broadcast); a unicast search to 127.0.0.1 gets no answer here
    return {k: v for k, v in os.environ.items() if k not in ("EPICS_PVA_ADDR_LIST", "EPICS_PVA_AUTO_ADDR_LIST")}


def available(tool: str) -> bool:
    return (expected.EPICS_BIN / tool).exists()


def run(tool: str, *args: str, timeout: float = 15.0) -> str:
    r = subprocess.run([str(expected.EPICS_BIN / tool), *args], capture_output=True, text=True,
                       timeout=timeout, env=_env())
    if r.returncode != 0:
        raise RuntimeError(f"{tool} {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


def pvinfo_type(pv: str) -> str:
    m = re.search(r"(epics:nt/\w+:\d+\.\d+)", run("pvinfo", pv))
    return m.group(1) if m else ""


def dimensions(pv: str) -> list[int]:
    out = run("pvget", "-r", "field(dimension)", pv)
    return [int(x) for x in re.findall(r"int size (\d+)", out)]


def unique_id(pv: str) -> int:
    out = run("pvget", "-r", "field(uniqueId)", pv)
    m = re.search(r"int uniqueId (-?\d+)", out)
    return int(m.group(1)) if m else -1


def value_array(pv: str, timeout: float = 60.0) -> list[int]:
    """The image pixels as a flat list. Only for SMALL ROIs: the text form of a full frame
    is hundreds of MB."""
    out = run("pvget", "-r", "field(value)", pv, timeout=timeout)
    # printed as "ushort[]  [1569,1635,...]": skip the empty [] of the type name
    m = re.search(r"\[\s*(-?\d[-\d,\s]*)\]", out, re.S)
    if not m:
        return []
    return [int(x) for x in m.group(1).replace("\n", " ").split(",") if x.strip()]
