"""Acquisition helpers, ported from info/performance/roi-rate-test.sh.

`wait_idle()` is the deadlock probe: DetectorState alone is not proof of life (upstream
ADTucsen marks Idle while its port thread hangs in TUCAM_Cap_Stop), so it also
round-trips ArrayCounter with a value that differs from the current readback.
"""
from __future__ import annotations

import time

from .ca import CA, ReadbackTimeout

IDLE_STATES = {"Idle", "Aborted", "Error"}


class DeadlockSuspected(Exception):
    """The driver's port thread stopped processing writes. See info/incidents/stop-deadlock.md."""


def wait_idle(ca: CA, *, idle_timeout: float = 10.0, probe_timeout: float = 5.0) -> None:
    deadline = time.monotonic() + idle_timeout
    state = None
    while time.monotonic() < deadline:
        state = ca.get_str("cam1:DetectorState_RBV")
        if state != "Acquire":
            break
        time.sleep(0.5)
    if state == "Acquire":
        raise DeadlockSuspected(
            "driver did not return to idle after Acquire=0 -- stopCapture deadlock "
            "(info/incidents/stop-deadlock.md). Run no further hardware tests.")
    # Liveness probe: a write that must round-trip, with a value that differs from now.
    # The original count is written back afterwards so tests can keep using ArrayCounter.
    c0 = ca.get_int("cam1:ArrayCounter_RBV")
    probe = c0 + 1
    ca.put("cam1:ArrayCounter", probe, wait=False)
    try:
        ca.wait_for("cam1:ArrayCounter_RBV", lambda v: int(v) == probe, timeout=probe_timeout)
    except ReadbackTimeout as e:
        raise DeadlockSuspected(
            "the driver's port thread is no longer processing writes (ArrayCounter probe "
            f"never took): {e}. See info/incidents/stop-deadlock.md") from None
    ca.put("cam1:ArrayCounter", c0, wait=False)
    ca.wait_for("cam1:ArrayCounter_RBV", lambda v: int(v) == c0, timeout=probe_timeout)


def stop(ca: CA) -> None:
    ca.put("cam1:Acquire", 0, wait=False)
    wait_idle(ca)


def acquire_single(ca: CA, *, timeout: float = 15.0) -> int:
    """One frame in Single mode. Returns the new ArrayCounter_RBV."""
    ca.put_and_wait_rbv("cam1:ImageMode", 0)
    c0 = ca.get_int("cam1:ArrayCounter_RBV")
    ca.put("cam1:Acquire", 1, wait=False)
    ca.wait_for("cam1:ArrayCounter_RBV", lambda v: int(v) >= c0 + 1, timeout=timeout)
    ca.wait_for("cam1:DetectorState_RBV", lambda s: s in IDLE_STATES, timeout=timeout, as_string=True)
    wait_idle(ca)
    return ca.get_int("cam1:ArrayCounter_RBV")


def acquire_multiple(ca: CA, n: int, *, timeout: float | None = None) -> int:
    ca.put_and_wait_rbv("cam1:ImageMode", 1)
    ca.put_and_wait_rbv("cam1:NumImages", n)
    c0 = ca.get_int("cam1:ArrayCounter_RBV")
    exp = float(ca.get("cam1:AcquireTime_RBV"))
    timeout = timeout or max(15.0, n * (exp + 0.15) * 2)
    ca.put("cam1:Acquire", 1, wait=False)
    ca.wait_for("cam1:ArrayCounter_RBV", lambda v: int(v) >= c0 + n, timeout=timeout)
    ca.wait_for("cam1:DetectorState_RBV", lambda s: s in IDLE_STATES, timeout=15.0, as_string=True)
    wait_idle(ca)
    return ca.get_int("cam1:ArrayCounter_RBV")


def run_continuous(ca: CA, seconds: float) -> int:
    """Continuous acquisition for `seconds`; returns frames counted while running."""
    ca.put_and_wait_rbv("cam1:ImageMode", 2)
    c0 = ca.get_int("cam1:ArrayCounter_RBV")
    ca.put("cam1:Acquire", 1, wait=False)
    time.sleep(seconds)
    c1 = ca.get_int("cam1:ArrayCounter_RBV")
    stop(ca)
    return c1 - c0


def set_geometry(ca: CA, minx: int, miny: int, sizex: int, sizey: int,
                 *, timeout: float = 10.0) -> tuple[int, int, int, int]:
    """Offsets first, then sizes. Returns the four readbacks (the driver may align)."""
    for rel, v in (("cam1:MinX", minx), ("cam1:MinY", miny),
                   ("cam1:SizeX", sizex), ("cam1:SizeY", sizey)):
        ca.put(rel, v, wait=True)
    # wait until every readback stops changing (alignment/clamping happen in setROI)
    def settled():
        vals = [ca.get_int(r) for r in ("cam1:MinX_RBV", "cam1:MinY_RBV", "cam1:SizeX_RBV", "cam1:SizeY_RBV")]
        time.sleep(0.3)
        vals2 = [ca.get_int(r) for r in ("cam1:MinX_RBV", "cam1:MinY_RBV", "cam1:SizeX_RBV", "cam1:SizeY_RBV")]
        return vals == vals2, tuple(vals2)
    deadline = time.monotonic() + timeout
    while True:
        ok, vals = settled()
        if ok or time.monotonic() > deadline:
            return vals


def full_frame(ca: CA, size: int = 4096) -> tuple[int, int, int, int]:
    return set_geometry(ca, 0, 0, size, size)


def prime_frame(ca: CA, expect_y: int, *, retries: int = 3) -> None:
    """HDF5 stream mode fixes the dataset geometry from the LAST array it saw: produce
    one frame at the current geometry and require the counter to advance."""
    for _ in range(retries):
        c0 = ca.get_int("cam1:ArrayCounter_RBV")
        acquire_single(ca)
        if ca.get_int("cam1:ArraySizeY_RBV") == expect_y and ca.get_int("cam1:ArrayCounter_RBV") != c0:
            return
    raise AssertionError(f"prime frame did not produce a NEW frame at height {expect_y}")
