#!/usr/bin/env python3
"""Dump every PV of the IOC that is serving into compat/baselines/<driver>-<date>.json.

Run while ioc-xv4040 is active to produce the ADTucsen baseline the compat tests compare
against (the swap is manual: info/systemd/README.md). Writes NO PV.

    tests/run.sh capture [--prefix XV4040:] [--out tests/compat/baselines]
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

os.environ.setdefault("EPICS_CA_ADDR_LIST", "127.0.0.1")
os.environ["EPICS_CA_AUTO_ADDR_LIST"] = "NO"
os.environ.setdefault("EPICS_CA_MAX_ARRAY_BYTES", "40000000")
for _k in ("EPICS_PVA_ADDR_LIST", "EPICS_PVA_AUTO_ADDR_LIST"):
    os.environ.pop(_k, None)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from helpers import compat, expected, iocdetect  # noqa: E402
from helpers.ca import CA  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prefix", default=expected.PREFIX_DEFAULT)
    ap.add_argument("--out", default=str(Path(__file__).with_name("baselines")))
    ap.add_argument("--addr", default="127.0.0.1")
    a = ap.parse_args()

    ioc = iocdetect.detect()
    if ioc.driver == "none":
        print("no IOC is serving; start ioc-xv4040 (or ioc-axissxr40) first", file=sys.stderr)
        return 2
    print(f"serving driver: {ioc.driver} (st.cmd pid {ioc.st_cmd_pid})")
    names = compat.pvlist_names(a.addr)
    names = [n for n in names if n.startswith(a.prefix)]
    print(f"{len(names)} PV names from pvlist {a.addr}; reading metadata (no writes) ...")
    ca = CA(a.prefix, timeout=5.0, allow=())          # empty allow-list: this tool cannot write
    pvs = compat.capture_all(ca, names)
    meta = compat.boot_meta(ioc.exp)
    for rel in ("cam1:DriverVersion_RBV", "cam1:ADCoreVersion_RBV"):
        v = pvs.get(a.prefix + rel, {})
        meta[rel.split(":")[1]] = v.get("value")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{ioc.driver}-{dt.date.today().isoformat()}.json"
    compat.write_baseline(path, ioc.driver, a.prefix, pvs, meta)
    connected = sum(1 for v in pvs.values() if v.get("connected"))
    print(f"wrote {path}\n  connected {connected}/{len(pvs)}"
          f"\n  write errors at boot: {meta.get('write_error_records')}"
          f"\n  autosave: {meta.get('autosave_connected')}  audit: {meta.get('capability_audit')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
