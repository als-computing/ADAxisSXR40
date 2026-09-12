"""Snapshot and restore of the writable settings, in policy order."""
from __future__ import annotations

import time

from . import acquire, policy
from .ca import CA


def same(a, b, tol: float = 0.0) -> bool:
    if isinstance(a, str) or isinstance(b, str):
        return str(a).rstrip("\x00") == str(b).rstrip("\x00")
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return a == b
    return abs(fa - fb) <= (tol or abs(fb) * policy.DEFAULT_REL_TOL + 1e-9)


class Snapshot:
    def __init__(self, ca: CA, rels=policy.SNAPSHOT_PVS):
        self.ca = ca
        self.values: dict[str, object] = {}
        self.rbvs: dict[str, object] = {}
        for rel in rels:
            try:
                if not ca.connect(rel, timeout=2.0):
                    continue
                self.values[rel] = ca.meta(rel).value
                rbv = ca.rbv_name(rel)
                if rbv and ca.connect(rbv, timeout=2.0):
                    self.rbvs[rel] = ca.meta(rbv).value
            except Exception:  # noqa: BLE001
                continue

    def restore(self) -> list[str]:
        """Write everything back in policy order; return human-readable mismatches."""
        problems = []
        for rel in policy.SNAPSHOT_PVS:
            if rel not in self.values:
                continue
            want = self.values[rel]
            if rel in policy.RESTORE_ONLY_IF_CHANGED and rel in self.rbvs:
                try:
                    cur = self.ca.meta(self.ca.rbv_name(rel)).value
                    if same(cur, self.rbvs[rel]):
                        continue            # writing it would recreate plugin threads for nothing
                except Exception:  # noqa: BLE001
                    pass
            try:
                self.ca.put(rel, want, wait=True)
            except Exception as e:  # noqa: BLE001
                problems.append(f"{rel}: put({want!r}) failed: {e}")
        time.sleep(0.5)
        for rel, want_rbv in self.rbvs.items():
            try:
                rbv = self.ca.rbv_name(rel)
                got = self.ca.meta(rbv).value
                if not same(got, want_rbv, policy.FLOAT_TOL.get(rel, 0.0)):
                    problems.append(f"{rbv}: {got!r} != snapshot {want_rbv!r}")
            except Exception as e:  # noqa: BLE001
                problems.append(f"{rel}: verify failed: {e}")
        return problems


def safe_stop(ca: CA) -> None:
    """Stop acquisition and any file capture, then prove the port thread is alive."""
    try:
        ca.put("cam1:Acquire", 0, wait=False)
    except Exception:  # noqa: BLE001
        pass
    for rel in ("HDF1:Capture",):
        try:
            # Only when a capture is actually running: writing Capture 0 to an idle plugin in
            # Single mode logs "NDPluginFile:doCapture ERROR: capture not supported in Single mode".
            if ca.connect(rel, timeout=1.0) and ca.get_int(rel + "_RBV") != 0:
                ca.put(rel, 0, wait=False)
        except Exception:  # noqa: BLE001
            pass
    acquire.wait_idle(ca)
