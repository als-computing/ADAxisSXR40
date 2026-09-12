"""Capture every PV of the serving IOC into a JSON baseline, and compare a live IOC against one.

Values are compared only for the names in compat_rules.VALUE_MUST_MATCH; everything else
is compared on existence, record type, CA type, element count, enum strings, precision
and units. That is what makes two IOCs interchangeable for a client.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import expected, ioclog
from .ca import CA

SCHEMA = 1


def pvlist_names(addr: str = "127.0.0.1", timeout: float = 30.0) -> list[str]:
    """All record names the server at `addr` exposes (pvlist <address> prints one per line)."""
    r = subprocess.run([str(expected.EPICS_BIN / "pvlist"), addr], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"pvlist {addr}: {r.stderr.strip()}")
    return sorted({l.strip() for l in r.stdout.splitlines() if l.strip() and not l.startswith("GUID")})


def capture_all(ca: CA, names: list[str], *, chunk: int = 400) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(names), chunk):
        part = names[i:i + chunk]
        ca.connect_many(part, timeout=10.0)
        for n in part:
            m = ca.meta(n, read_value=True, max_array=1024)
            if not m.connected:
                out[n] = {"connected": False}
                continue
            v = m.value
            if isinstance(v, list) and len(v) > 64:
                v = None
            out[n] = {"connected": True, "rtyp": m.rtyp, "type": m.type, "count": m.count,
                      "enum_strs": list(m.enum_strs) if m.enum_strs else None,
                      "precision": m.precision, "units": m.units, "value": v}
    return out


def boot_meta(exp) -> dict:
    try:
        lines = ioclog.read_clean(exp.LOG)
    except OSError:
        return {}
    sl, pid = ioclog.last_boot_slice(lines, exp.PROCSERV_CHILD)
    audit = ioclog.capability_audit(sl)
    auto = ioclog.autosave_connected(sl)
    return {"boot_pid": pid, "log": str(exp.LOG),
            "capability_audit": list(audit[-1]) if audit else None,
            "autosave_connected": list(auto[-1]) if auto else None,
            "write_error_records": sorted(ioclog.write_error_records(sl, expected.PREFIX_DEFAULT))}


def write_baseline(path: Path, driver: str, prefix: str, pvs: dict, meta: dict) -> None:
    doc = {"schema": SCHEMA,
           "meta": {"driver": driver, "prefix": prefix, "host": socket.gethostname(),
                    "captured_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                    "pv_count": len(pvs), "connected": sum(1 for v in pvs.values() if v.get("connected")),
                    **meta},
           "pvs": pvs}
    path.write_text(json.dumps(doc, indent=1, sort_keys=True))


def load_baseline(path: Path) -> dict:
    doc = json.loads(Path(path).read_text())
    if doc.get("schema") != SCHEMA:
        raise ValueError(f"{path}: schema {doc.get('schema')} != {SCHEMA}")
    return doc


@dataclass
class Finding:
    name: str
    category: str
    baseline: object
    live: object
    verdict: str          # "INTENDED" | "FAIL"


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    def by(self, category: str, verdict: str | None = None) -> list[Finding]:
        return [f for f in self.findings if f.category == category and (verdict is None or f.verdict == verdict)]

    def fails(self) -> list[Finding]:
        return [f for f in self.findings if f.verdict == "FAIL"]


def _rel(name: str, prefix: str) -> str:
    return name[len(prefix):] if name.startswith(prefix) else name


def compare(baseline: dict, live: dict, rules, prefix: str) -> Report:
    rep = Report()
    b, l = baseline["pvs"], live

    def add(name, cat, bv, lv, intended):
        rep.findings.append(Finding(name, cat, bv, lv, "INTENDED" if intended else "FAIL"))

    bset, lset = {n for n, v in b.items() if v.get("connected")}, {n for n, v in l.items() if v.get("connected")}
    for n in sorted(lset - bset):
        r = _rel(n, prefix)
        add(n, "only_in_live", None, l[n].get("rtyp"), r in rules.ONLY_IN_OURS_OK)
    for n in sorted(bset - lset):
        r = _rel(n, prefix)
        add(n, "only_in_baseline", b[n].get("rtyp"), None,
            any(re.search(p, r) for p in rules.ONLY_IN_THEIRS_OK_PATTERNS))
    for n in sorted(bset & lset):
        r = _rel(n, prefix)
        bb, ll = b[n], l[n]
        if bb.get("rtyp") != ll.get("rtyp"):
            add(n, "rtyp_mismatch", bb.get("rtyp"), ll.get("rtyp"), False)
        if bb.get("type") != ll.get("type"):
            add(n, "type_mismatch", bb.get("type"), ll.get("type"), r in rules.TYPE_DIFF_OK)
        if bb.get("count") != ll.get("count"):
            add(n, "count_mismatch", bb.get("count"), ll.get("count"), r in rules.COUNT_DIFF_OK)
        be, le = tuple(bb.get("enum_strs") or ()), tuple(ll.get("enum_strs") or ())
        if _strip(be) != _strip(le):
            ok = r in rules.ENUM_DIFF_OK and _strip(le) == tuple(rules.ENUM_DIFF_OK[r])
            add(n, "enum_mismatch", be, le, ok)
        if (bb.get("precision"), bb.get("units")) != (ll.get("precision"), ll.get("units")):
            add(n, "prec_egu_mismatch", (bb.get("precision"), bb.get("units")),
                (ll.get("precision"), ll.get("units")), r in rules.PREC_EGU_DIFF_OK)
        if r in rules.VALUE_MUST_MATCH and bb.get("value") != ll.get("value"):
            add(n, "value_mismatch", bb.get("value"), ll.get("value"), r in rules.VALUE_DIFF_OK)
    return rep


def _strip(t):
    t = list(t)
    while t and t[-1] == "":
        t.pop()
    return tuple(t)


def format_report(rep: Report, baseline_meta: dict, live_meta: dict) -> str:
    lines = [f"baseline: {baseline_meta.get('driver')} captured {baseline_meta.get('captured_utc')} "
             f"({baseline_meta.get('pv_count')} PVs)",
             f"live:     {live_meta.get('driver')} ({live_meta.get('pv_count')} PVs)", ""]
    for verdict in ("INTENDED", "FAIL"):
        items = [f for f in rep.findings if f.verdict == verdict]
        lines.append(f"== {verdict}: {len(items)} ==")
        for f in items:
            lines.append(f"  {f.category:18s} {f.name}: baseline={f.baseline!r} live={f.live!r}")
        lines.append("")
    return "\n".join(lines)
