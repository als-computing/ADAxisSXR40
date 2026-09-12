"""Thin Channel Access wrapper over pyepics with a write allow-list.

Every test talks to the IOC through one `CA` instance (the `ca` fixture). Reads are
plain; writes are refused unless the relative PV name is in `policy.SAFE_WRITES`.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Iterable

import epics

from . import policy


class CATimeout(Exception):
    """A get or connect did not complete in time."""


class ReadbackTimeout(AssertionError):
    """A write went through but the readback never followed."""


class ForbiddenWrite(Exception):
    """A test tried to write a PV outside the allow-list."""


@dataclass
class PVMeta:
    name: str
    connected: bool
    rtyp: str | None = None
    type: str | None = None          # native CA type: double, long, enum, char, short, string, ...
    count: int | None = None
    enum_strs: tuple = ()
    precision: int | None = None
    units: str = ""
    value: Any = None


def _strip_form(t: str | None) -> str | None:
    if t is None:
        return None
    for pfx in ("time_", "ctrl_"):
        if t.startswith(pfx):
            return t[len(pfx):]
    return t


class CA:
    def __init__(self, prefix: str, timeout: float = 5.0,
                 allow: Iterable[str] = policy.SAFE_WRITES,
                 forbid: Iterable[str] = policy.FORBIDDEN_WRITES):
        self.prefix = prefix
        self.timeout = timeout
        self.allow = frozenset(allow)
        self.forbid = frozenset(forbid)
        self._pvs: dict[str, epics.PV] = {}
        self.writes: list[tuple[str, Any]] = []      # audit trail of every put

    # ---- naming --------------------------------------------------------------------
    def full(self, rel: str) -> str:
        return rel if rel.startswith(self.prefix) else self.prefix + rel

    def pv(self, rel: str) -> epics.PV:
        name = self.full(rel)
        pv = self._pvs.get(name)
        if pv is None:
            # No monitors: 32 MiB image arrays must never be subscribed by accident.
            pv = epics.PV(name, auto_monitor=False, connection_timeout=self.timeout)
            self._pvs[name] = pv
        return pv

    def connect(self, rel: str, timeout: float | None = None) -> bool:
        return self.pv(rel).wait_for_connection(timeout=timeout or self.timeout)

    def connect_many(self, rels: Iterable[str], timeout: float | None = None) -> dict[str, bool]:
        """Create all PVs first (searches go out in parallel), then wait on each."""
        rels = list(rels)
        for r in rels:
            self.pv(r)
        deadline = time.monotonic() + (timeout or self.timeout)
        out = {}
        for r in rels:
            remaining = max(0.05, deadline - time.monotonic())
            out[r] = self.pv(r).wait_for_connection(timeout=remaining)
        return out

    # ---- reads ------------------------------------------------------------------------
    def get(self, rel: str, *, as_string: bool = False, timeout: float | None = None) -> Any:
        pv = self.pv(rel)
        if not pv.wait_for_connection(timeout=timeout or self.timeout):
            raise CATimeout(f"{pv.pvname}: not connected")
        v = pv.get(as_string=as_string, timeout=timeout or self.timeout, use_monitor=False)
        if v is None:
            raise CATimeout(f"{pv.pvname}: get timed out")
        return v

    def get_str(self, rel: str) -> str:
        v = self.get(rel, as_string=True)
        return v.rstrip("\x00") if isinstance(v, str) else str(v)

    def get_int(self, rel: str) -> int:
        return int(round(float(self.get(rel))))

    def enum_strs(self, rel: str) -> tuple:
        pv = self.pv(rel)
        if not pv.wait_for_connection(timeout=self.timeout):
            raise CATimeout(f"{pv.pvname}: not connected")
        pv.get_ctrlvars(timeout=self.timeout)
        return tuple(pv.enum_strs or ())

    def meta(self, rel: str, *, read_value: bool = True, max_array: int = 65536) -> PVMeta:
        pv = self.pv(rel)
        name = pv.pvname
        if not pv.wait_for_connection(timeout=self.timeout):
            return PVMeta(name=name, connected=False)
        pv.get_ctrlvars(timeout=self.timeout)
        base = name.split(".")[0]
        rtyp = None
        if "." not in name or name.endswith(".VAL"):
            r = epics.caget(base + ".RTYP", timeout=self.timeout)
            rtyp = str(r) if r is not None else None
        typ = _strip_form(pv.type)
        count = int(pv.count or 1)
        value = None
        if read_value:
            if typ == "char" and count <= 4096:
                value = pv.get(as_string=True, timeout=self.timeout, use_monitor=False)
                if isinstance(value, str):
                    value = value.rstrip("\x00")
            elif count <= max_array:
                value = pv.get(timeout=self.timeout, use_monitor=False)
                if hasattr(value, "tolist"):
                    value = value.tolist()
        units = pv.units if pv.units else ""
        return PVMeta(name=name, connected=True, rtyp=rtyp, type=typ, count=count,
                      enum_strs=tuple(pv.enum_strs or ()), precision=pv.precision,
                      units=units, value=value)

    # ---- writes -------------------------------------------------------------------------
    def _check_writable(self, rel: str) -> None:
        key = rel[len(self.prefix):] if rel.startswith(self.prefix) else rel
        if key in self.forbid:
            raise ForbiddenWrite(f"{key} is in policy.FORBIDDEN_WRITES")
        if key not in self.allow:
            raise ForbiddenWrite(f"{key} is not in policy.SAFE_WRITES")

    def put(self, rel: str, value: Any, *, wait: bool = True, timeout: float | None = None) -> None:
        self._check_writable(rel)
        pv = self.pv(rel)
        if not pv.wait_for_connection(timeout=timeout or self.timeout):
            raise CATimeout(f"{pv.pvname}: not connected")
        self.writes.append((pv.pvname, value))
        key = rel[len(self.prefix):] if rel.startswith(self.prefix) else rel
        if key in policy.NO_CALLBACK:
            wait = False                       # busy records: completion = "done", not "accepted"
        pv.put(value, wait=wait, timeout=timeout or self.timeout)

    def rbv_name(self, rel: str) -> str | None:
        if rel in policy.NO_RBV or "." in rel:
            return None
        return rel + "_RBV"

    def put_and_wait_rbv(self, rel: str, value: Any, *, rbv: str | None = None,
                         expect: Any = None, tol: float | None = None,
                         timeout: float = 10.0, poll: float = 0.2) -> Any:
        """Write, then poll the readback until it equals `expect` (default: `value`)."""
        rbv = rbv or self.rbv_name(rel)
        if rbv is None:
            raise ValueError(f"{rel} has no readback; use put()")
        want = value if expect is None else expect
        if tol is None:
            tol = policy.FLOAT_TOL.get(rel, 0.0)
        self.put(rel, value, wait=True)
        deadline = time.monotonic() + timeout
        last = None
        as_str = isinstance(want, str)
        while time.monotonic() < deadline:
            last = self.get(rbv, as_string=as_str)
            if _matches(last, want, tol):
                return last
            time.sleep(poll)
        raise ReadbackTimeout(f"{self.full(rbv)} = {last!r}, wanted {want!r} "
                              f"(tol {tol}) after writing {value!r} to {self.full(rel)}")

    def wait_for(self, rel: str, predicate, *, timeout: float = 10.0, poll: float = 0.25,
                 as_string: bool = False) -> Any:
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            last = self.get(rel, as_string=as_string)
            if predicate(last):
                return last
            time.sleep(poll)
        raise ReadbackTimeout(f"{self.full(rel)}: condition not met within {timeout}s (last={last!r})")


def _matches(got: Any, want: Any, tol: float) -> bool:
    if isinstance(want, str):
        return str(got).rstrip("\x00") == want
    try:
        g, w = float(got), float(want)
    except (TypeError, ValueError):
        return got == want
    if math.isnan(g) or math.isnan(w):
        return False
    if tol:
        return abs(g - w) <= tol
    return g == w
