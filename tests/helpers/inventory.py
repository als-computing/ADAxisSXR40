"""Parse EPICS .template files into records, following `include` lines.

The templates are the specification the IOC actually loads, so the inventory is
parsed at test time rather than kept as a generated list that could go stale.
Record names are returned relative to the IOC prefix: `$(P)$(R)MinX` -> `cam1:MinX`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import expected

RE_RECORD = re.compile(r'^\s*record\s*\(\s*(\w+)\s*,\s*"([^"]+)"\s*\)')
RE_FIELD = re.compile(r'^\s*field\s*\(\s*(\w+)\s*,\s*"([^"]*)"\s*\)')
RE_INCLUDE = re.compile(r'^\s*include\s+"([^"]+)"')
# @asyn($(PORT),$(ADDR),$(TIMEOUT))NAME -- the argument list itself contains parentheses
RE_DRVINFO = re.compile(r"@asyn\((?:[^()]|\([^()]*\))*\)\s*(\w+)")

ENUM_FIELDS = ("ZRST", "ONST", "TWST", "THST", "FRST", "FVST", "SXST", "SVST",
               "EIST", "NIST", "TEST", "ELST", "TVST", "TTST", "FTST", "FFST")
ENUM_VALUES = ("ZRVL", "ONVL", "TWVL", "THVL", "FRVL", "FVVL", "SXVL", "SVVL",
               "EIVL", "NIVL", "TEVL", "ELVL", "TVVL", "TTVL", "FTVL", "FFVL")


@dataclass
class Rec:
    name: str                       # relative, e.g. "cam1:MinX"
    rtyp: str
    fields: dict[str, str] = field(default_factory=dict)
    source: str = ""                # template file that (last) defined it
    sources: list[str] = field(default_factory=list)


def adcore_dir() -> Path:
    env = expected.IOC_BOOT / "envPaths"
    if env.exists():
        m = re.search(r'epicsEnvSet\("ADCORE","([^"]+)"\)', env.read_text())
        if m and Path(m.group(1)).exists():
            return Path(m.group(1))
    return expected.ADCORE_DEFAULT


def parse_template(path: Path, *, follow_includes: bool = True, search: list[Path] | None = None,
                   cam: str = expected.CAM, _seen: set | None = None) -> dict[str, Rec]:
    path = Path(path)
    search = search or [path.parent, adcore_dir() / "db", adcore_dir() / "ADApp/Db"]
    _seen = _seen if _seen is not None else set()
    recs: dict[str, Rec] = {}
    cur: Rec | None = None
    for raw in path.read_text(errors="replace").splitlines():
        line = raw.split("#", 1)[0] if not raw.lstrip().startswith("#") else ""
        if not line.strip():
            continue
        m = RE_INCLUDE.match(line)
        if m:
            if follow_includes and m.group(1) not in _seen:
                _seen.add(m.group(1))
                for d in search:
                    p = d / m.group(1)
                    if p.exists():
                        for k, v in parse_template(p, follow_includes=True, search=search,
                                                   cam=cam, _seen=_seen).items():
                            recs[k] = _merge(recs.get(k), v)
                        break
            continue
        m = RE_RECORD.match(line)
        if m:
            name = m.group(2).replace("$(P)$(R)", cam).replace("$(P)", "")
            cur = Rec(name=name, rtyp=m.group(1), source=str(path), sources=[str(path)])
            recs[name] = _merge(recs.get(name), cur)
            cur = recs[name]
            continue
        m = RE_FIELD.match(line)
        if m and cur is not None:
            cur.fields[m.group(1)] = m.group(2)
        if line.strip().startswith("}"):
            cur = None
    return recs


def _merge(old: Rec | None, new: Rec) -> Rec:
    if old is None:
        return new
    old.fields.update(new.fields)
    old.rtyp = new.rtyp
    old.source = new.source
    old.sources += [s for s in new.sources if s not in old.sources]
    return old


def load_cam_records() -> dict[str, Rec]:
    """Our template plus everything it includes (ADBase, NDArrayBase)."""
    return parse_template(expected.TEMPLATE)


def own_records(path: Path) -> dict[str, Rec]:
    """Only the records the given template defines itself (no includes)."""
    return parse_template(path, follow_includes=False)


def enum_strings(rec: Rec) -> tuple[str, ...]:
    if rec.rtyp in ("mbbo", "mbbi"):
        strs = [rec.fields.get(f, "") for f in ENUM_FIELDS]
        while strs and strs[-1] == "":
            strs.pop()
        return tuple(strs)
    if rec.rtyp in ("bo", "bi"):
        z, o = rec.fields.get("ZNAM"), rec.fields.get("ONAM")
        return tuple(s for s in (z, o) if s is not None)
    return ()


def enum_values(rec: Rec) -> list[tuple[int, int | None, str]]:
    """(index, VL value or None, string) for every defined enum string of an mbb record."""
    out = []
    for i, (sf, vf) in enumerate(zip(ENUM_FIELDS, ENUM_VALUES)):
        if sf in rec.fields:
            v = rec.fields.get(vf)
            out.append((i, int(v) if v not in (None, "") else None, rec.fields[sf]))
    return out


def expected_ca_type(rec: Rec) -> str | None:
    t = rec.rtyp
    if t in ("ai", "ao", "calc", "calcout"):
        return "double"
    if t in ("longin", "longout"):
        return "long"
    if t in ("bi", "bo", "mbbi", "mbbo", "busy"):
        return "enum"
    if t in ("stringin", "stringout"):
        return "string"
    if t in ("waveform", "subArray"):
        return {"CHAR": "char", "UCHAR": "char", "SHORT": "short", "USHORT": "short",
                "LONG": "long", "ULONG": "long", "DOUBLE": "double", "FLOAT": "float",
                "STRING": "string"}.get(rec.fields.get("FTVL", "").upper())
    return None  # asyn, fanout, seq, ...: not asserted


def drvinfo(rec: Rec) -> str | None:
    for f in ("OUT", "INP"):
        v = rec.fields.get(f)
        if v:
            m = RE_DRVINFO.search(v)
            if m:
                return m.group(1)
    return None


def setpoint_rbv_pairs(recs: dict[str, Rec]) -> list[tuple[str, str]]:
    return sorted((n[:-4], n) for n in recs if n.endswith("_RBV") and n[:-4] in recs)
