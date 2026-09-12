"""One sustained HDF5 streaming run, measured: the unit of the stress tier.

`run_stream()` generalises files/test_hdf5_stream.py: Multiple mode with NumImages ==
NumCapture so the camera stops itself (in continuous mode the frames still streaming while
the file closes are counted as drops although the file is complete), a sampler thread
watching the writer queue and the array pool, RSS of the IOC process before and after,
the log delta, h5check on the result, and the file deleted before returning.
"""
from __future__ import annotations

import datetime as dt
import os
import platform
import shutil
import socket
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import epics
import pytest

from . import acquire, expected, h5
from .ca import CA
from .snapshot import safe_stop


# ---- compression ----------------------------------------------------------------------
@dataclass(frozen=True)
class CompressionSpec:
    name: str
    compression: int                          # HDF1:Compression enum index
    puts: tuple[tuple[str, int], ...] = ()    # extra (rel, value) writes
    camera_cap_fps: float = 50.0              # hold the camera here (256 rows) so the filter is not raced


NONE = CompressionSpec("none", 0)
ZLIB = CompressionSpec("zlib1", 3, (("HDF1:ZLevel", 1),), camera_cap_fps=10.0)   # ~27 fps single-threaded
BLOSC = CompressionSpec("blosc-lz4-bit-1", 4, (("HDF1:BloscCompressor", 1), ("HDF1:BloscShuffle", 2), ("HDF1:BloscLevel", 1)))
BSLZ4 = CompressionSpec("bslz4", 5)
LZ4 = CompressionSpec("lz4", 6)
ALL_COMPRESSIONS = (NONE, ZLIB, BLOSC, BSLZ4, LZ4)


# ---- record -------------------------------------------------------------------------------
@dataclass
class RunRecord:
    date: str
    host: str
    driver: str
    test: str
    height: int
    duration_s: float
    frames: int
    wall_s: float
    camera_fps: float | None
    writer_fps: float
    ref_writer_fps: float | None
    MBps: float
    captured: int
    dropped: dict[str, int]
    peak_queue_use: int
    queue_size: int
    peak_pool_mb: float
    pool_before_mb: float
    rss_before_mb: float
    rss_after_mb: float
    file_mb: float
    uid_missing: int | None
    min_interval_ms: float | None
    max_interval_ms: float | None
    compression: str
    compression_ratio: float | None
    log_new_errors: int
    frame_means: list[float] = field(default_factory=list)
    notes: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


# ---- small utilities --------------------------------------------------------------------
def rss_kb(pid: int) -> int:
    with open(f"/proc/{pid}/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    raise OSError(f"no VmRSS in /proc/{pid}/status")


def bytes_per_frame(height: int, width: int = 4096) -> int:
    return width * height * 2


def frames_for(duration_s: float, height: int, rate_cap_fps: float | None = None) -> int:
    ref = expected.WRITER_REFERENCE_FPS[height]
    fps = min(ref, rate_cap_fps) if rate_cap_fps else ref
    return max(5, int(round(duration_s * fps)))


class ByteBudget:
    """Cumulative cap on bytes written in one session, plus a free-space check per run."""

    def __init__(self, max_bytes: int):
        self.max_bytes = int(max_bytes)
        self.used = 0

    def reserve(self, n: int) -> None:
        if self.used + n > self.max_bytes:
            pytest.skip(f"session byte cap: {self.used/1e9:.1f} GB used + {n/1e9:.1f} GB > "
                        f"{self.max_bytes/1e9:.0f} GB (--max-bytes)")
        self.used += n

    @staticmethod
    def require_free(path: Path, n: int, factor: float = 1.5) -> None:
        free = shutil.disk_usage(path).free
        if free < n * factor:
            pytest.skip(f"{path}: {free/1e9:.1f} GB free < {n*factor/1e9:.1f} GB needed for this run")


class Sampler(threading.Thread):
    """Poll a few PVs every `period` seconds on a separate CA connection."""

    def __init__(self, prefix: str, rels: list[str], period: float = 0.5, timeout: float = 2.0):
        super().__init__(daemon=True, name="stress-sampler")
        self.prefix, self.rels, self.period, self.timeout = prefix, list(rels), period, timeout
        self.samples: dict[str, list[tuple[float, Any]]] = {r: [] for r in self.rels}
        self._stop = threading.Event()

    def run(self) -> None:
        epics.ca.use_initial_context()
        ca = CA(self.prefix, timeout=self.timeout, allow=())
        while not self._stop.is_set():
            t = time.monotonic()
            for r in self.rels:
                try:
                    v = ca.get_str(r) if r.endswith("StatusMessage_RBV") or r.endswith("DetectorState_RBV") else ca.get(r)
                    self.samples[r].append((t, v))
                except Exception:  # noqa: BLE001
                    pass
            self._stop.wait(self.period)

    def stop(self) -> dict[str, list[tuple[float, Any]]]:
        self._stop.set()
        self.join(timeout=10)
        return self.samples

    def peak(self, rel: str, default: float = 0.0) -> float:
        vals = [float(v) for _, v in self.samples.get(rel, []) if v is not None]
        return max(vals) if vals else default

    def any_match(self, rel: str, needle: str) -> bool:
        return any(needle in str(v) for _, v in self.samples.get(rel, []))


# ---- the run ----------------------------------------------------------------------------------
def run_stream(ca: CA, *, height: int, duration: float | None = None, frames: int | None = None,
               compression: CompressionSpec = NONE, exposure_s: float = 20.64e-6,
               outdir: Path, h5check: Path, budget: ByteBudget, pid: int, log_delta=None,
               test_id: str = "", driver: str = "", plugins: tuple[str, ...] = ("image1:", "Pva1:", "Stats1:"),
               file_name: str | None = None, stall_s: float = 20.0, rate_cap_fps: float | None = None,
               keep_file: bool = False) -> RunRecord:
    n = frames or frames_for(duration or 10.0, height, rate_cap_fps)
    bpf = bytes_per_frame(height)
    budget.reserve(n * bpf)
    budget.require_free(outdir, n * bpf)
    ref = expected.WRITER_REFERENCE_FPS.get(height)

    safe_stop(ca)
    got = acquire.set_geometry(ca, 0, 0, 4096, height)
    assert got[3] == height, f"SizeY {height} did not take: {got}"
    ca.put_and_wait_rbv("cam1:AcquireTime", exposure_s, tol=1e-4)
    ca.put_and_wait_rbv("cam1:ArrayCallbacks", 1)
    for p in plugins:
        ca.put_and_wait_rbv(f"{p}EnableCallbacks", 1)
        ca.put(f"{p}DroppedArrays", 0)
    ca.put_and_wait_rbv("HDF1:EnableCallbacks", 1)
    ca.put_and_wait_rbv("HDF1:FilePath", str(outdir) + "/")
    assert ca.get_int("HDF1:FilePathExists_RBV") == 1, f"IOC cannot see {outdir}"
    ca.put_and_wait_rbv("HDF1:FileName", file_name or f"stress{height}")
    ca.put_and_wait_rbv("HDF1:FileTemplate", "%s%s_%3.3d.h5")
    ca.put_and_wait_rbv("HDF1:FileWriteMode", 2)
    ca.put_and_wait_rbv("HDF1:AutoIncrement", 1)
    ca.put_and_wait_rbv("HDF1:AutoSave", 0)
    ca.put_and_wait_rbv("HDF1:NumCapture", n)
    try:
        ca.put_and_wait_rbv("HDF1:Compression", compression.compression, timeout=5.0)
    except AssertionError:
        pytest.skip(f"HDF5 filter {compression.name} not available in this IOC (Compression_RBV did not take)")
    for rel, val in compression.puts:
        ca.put_and_wait_rbv(rel, val)
    ca.put("HDF1:DroppedArrays", 0)
    ca.put("cam1:PoolPollStats", 1)
    acquire.prime_frame(ca, expect_y=height)

    rss0 = rss_kb(pid)
    pool0 = float(ca.get("cam1:PoolUsedMem"))
    mark = log_delta.mark() if log_delta else None
    ca.put_and_wait_rbv("cam1:ImageMode", 1)
    ca.put_and_wait_rbv("cam1:NumImages", n)
    ca.put("HDF1:Capture", 1)
    ca.wait_for("HDF1:Capture_RBV", lambda v: int(v) == 1, timeout=10)
    sampler = Sampler(ca.prefix, ["HDF1:QueueUse", "cam1:PoolUsedMem", "cam1:StatusMessage_RBV"])
    sampler.start()
    t0 = time.monotonic()
    ca.put("cam1:Acquire", 1, wait=False)
    expected_s = n / (ref or 5.0)
    hard = t0 + 2 * expected_s + 60
    last_nc, last_progress = -1, t0
    incomplete = ""
    while True:
        time.sleep(0.5)
        now = time.monotonic()
        cap = ca.get_int("HDF1:Capture_RBV")
        nc = ca.get_int("HDF1:NumCaptured_RBV")
        if cap == 0:
            break
        if nc != last_nc:
            last_nc, last_progress = nc, now
        elif now - last_progress > 3.0 and ca.get_int("cam1:Acquire_RBV") == 0 \
                and ca.get_str("cam1:DetectorState_RBV") in acquire.IDLE_STATES:
            # Camera finished its NumImages and the writer queue is drained, yet the file is
            # short: frames were dropped at a plugin queue. Not a stall; close the file and
            # let the caller's drop/captured assertions report it with numbers.
            incomplete = f"camera finished, writer stopped at {nc}/{n} frames after {now - t0:.0f} s"
            ca.put("HDF1:Capture", 0)
            ca.wait_for("HDF1:Capture_RBV", lambda v: int(v) == 0, timeout=60)
            break
        if now - last_progress > stall_s or now > hard:
            sampler.stop()
            safe_stop(ca)
            pytest.fail(f"capture stalled at {nc}/{n} frames after {now - t0:.0f} s (Capture_RBV={cap})")
    wall = time.monotonic() - t0
    ca.wait_for("cam1:DetectorState_RBV", lambda s: s in acquire.IDLE_STATES, timeout=15, as_string=True)
    acquire.wait_idle(ca)                      # deadlock probe
    samples = sampler.stop()

    captured = ca.get_int("HDF1:NumCaptured_RBV")
    dropped = {"hdf1": ca.get_int("HDF1:DroppedArrays_RBV")}
    for p in plugins:
        dropped[p.rstrip(":").lower()] = ca.get_int(f"{p}DroppedArrays_RBV")
    path = Path(ca.get_str("HDF1:FullFileName_RBV"))
    size = path.stat().st_size if path.exists() else 0
    rss1 = rss_kb(pid)
    try:
        rep = h5.run_h5check(h5check, path, strict=True) if path.exists() else h5.H5Report()
    finally:
        if path.exists() and not keep_file:
            os.remove(path)
    errs = log_delta.new_error_lines(since=mark) if log_delta else []
    return RunRecord(
        date=dt.datetime.now().isoformat(timespec="seconds"), host=socket.gethostname(), driver=driver,
        test=test_id, height=height, duration_s=duration or wall, frames=n, wall_s=round(wall, 3),
        camera_fps=rep.camera_fps, writer_fps=round(n / wall, 2), ref_writer_fps=ref,
        MBps=round(n * bpf / wall / 1e6, 1), captured=captured, dropped=dropped,
        peak_queue_use=int(sampler.peak("HDF1:QueueUse")), queue_size=ca.get_int("HDF1:QueueSize_RBV"),
        peak_pool_mb=round(sampler.peak("cam1:PoolUsedMem"), 1), pool_before_mb=round(pool0, 1),
        rss_before_mb=round(rss0 / 1024, 1), rss_after_mb=round(rss1 / 1024, 1), file_mb=round(size / 1e6, 1),
        uid_missing=rep.uid_missing, min_interval_ms=rep.interval_min_ms, max_interval_ms=rep.interval_max_ms,
        compression=compression.name, compression_ratio=(round(n * bpf / size, 2) if compression.compression and size else None),
        log_new_errors=len(errs), frame_means=rep.frame_means,
        notes="\n".join(([incomplete] if incomplete else []) + errs[:5]),
    )


def assert_clean_run(rec: RunRecord, exp, *, check_rate: bool = True) -> None:
    assert rec.captured == rec.frames, f"captured {rec.captured}/{rec.frames}"
    assert not any(rec.dropped.values()), f"dropped arrays: {rec.dropped}"
    assert rec.uid_missing == 0, f"uid gaps in file: {rec.uid_missing}"
    if check_rate and rec.ref_writer_fps:
        assert abs(rec.writer_fps - rec.ref_writer_fps) / rec.ref_writer_fps <= exp.WRITER_TOLERANCE, \
            f"writer {rec.writer_fps} fps vs reference {rec.ref_writer_fps} (±{exp.WRITER_TOLERANCE:.0%})"
    assert rec.peak_pool_mb < exp.POOL_PEAK_FRACTION * exp.POOL_MAX_MB, f"pool peaked at {rec.peak_pool_mb} MB"
    # NDArrayPool buffers are never returned below maxMemory, so a run that needs more (a
    # larger ROI than any before, a deeper backlog) legitimately grows RSS by the pool's
    # growth; anything beyond that margin is a leak in the driver or a plugin.
    pool_growth = max(0.0, rec.peak_pool_mb - rec.pool_before_mb)
    rss_growth = rec.rss_after_mb - rec.rss_before_mb
    assert rss_growth - pool_growth < exp.RSS_GROWTH_MAX_MB, \
        f"IOC RSS grew {rss_growth:.0f} MB during one run, only {pool_growth:.0f} MB of it array-pool buffers"
    assert rec.log_new_errors == 0, f"new IOC log errors during the run:\n{rec.notes}"
    if rec.camera_fps and rec.max_interval_ms is not None:
        nominal = 1000.0 / rec.camera_fps
        bound = 2 * nominal if rec.height >= exp.JITTER_STRICT_MIN_HEIGHT else max(2 * nominal, exp.JITTER_STALL_MS)
        assert rec.max_interval_ms < bound, f"max frame interval {rec.max_interval_ms} ms > {bound:.1f} ms"


# ---- results ------------------------------------------------------------------------------------
class Results:
    def __init__(self, meta: dict):
        self.meta = meta
        self.runs: list[RunRecord] = []
        self.extra: dict[str, Any] = {}

    def add(self, rec: RunRecord) -> None:
        self.runs.append(rec)

    def write_json(self, path: Path) -> None:
        """Append this session to the day's file: {"sessions": [{"meta", "runs", "extra"}, ...]}."""
        import json
        sessions = []
        if path.exists():
            try:
                old = json.loads(path.read_text())
                sessions = old.get("sessions", []) if isinstance(old, dict) else []
            except ValueError:
                sessions = []
        me = {"meta": self.meta, "runs": [r.as_dict() for r in self.runs], "extra": self.extra}
        sessions = [s for s in sessions if s.get("meta", {}).get("session_id") != self.meta.get("session_id")]
        sessions.append(me)
        path.write_text(json.dumps({"sessions": sessions}, indent=1, default=str))

    def write_markdown(self, path: Path) -> None:
        m = self.meta
        lines = [f"# Stress run — {m.get('host')}, {m.get('date')}", "",
                 "Produced by `tests/run.sh stress` (`--record`). One row per sustained HDF5 streaming run; the",
                 "file was verified with `tools/h5check` and deleted. Reference writer rates: "
                 "`2026-08-26-roi-frame-rate-vm-renesas-bl1101ad01.md`.", "",
                 "## Conditions", "", "| | |", "|---|---|"]
        for k in ("date", "host", "driver", "prefix", "ioc_pid", "adcore", "driver_version", "kernel",
                  "outdir", "fstype", "free_gb", "options"):
            if k in m:
                lines.append(f"| {k} | `{m[k]}` |")
        lines += ["", "## Runs", "",
                  "| test | height | dur s | frames | wall s | cam fps | writer fps | ref fps | MB/s | captured | dropped hdf1/img/pva/stats | queue peak/size | pool MB before→peak | RSS MB before→after | file MB | uid missing | interval max ms | compression (ratio) | log errors |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in self.runs:
            d = r.dropped
            lines.append(f"| {r.test} | {r.height} | {r.duration_s:.0f} | {r.frames} | {r.wall_s:.1f} | "
                         f"{r.camera_fps or ''} | {r.writer_fps} | {r.ref_writer_fps or ''} | {r.MBps} | {r.captured} | "
                         f"{d.get('hdf1',0)}/{d.get('image1',0)}/{d.get('pva1',0)}/{d.get('stats1',0)} | "
                         f"{r.peak_queue_use}/{r.queue_size} | {r.pool_before_mb}→{r.peak_pool_mb} | {r.rss_before_mb}→{r.rss_after_mb} | "
                         f"{r.file_mb} | {r.uid_missing} | {r.max_interval_ms} | {r.compression}"
                         f"{f' ({r.compression_ratio}x)' if r.compression_ratio else ''} | {r.log_new_errors} |")
        import json
        for name, data in self.extra.items():
            lines += ["", f"## {name}", "", "```json", json.dumps(data, indent=1, default=str), "```"]
        path.write_text("\n".join(lines) + "\n")


def session_meta(ca: CA, ioc, opts, outdir: Path, options: dict) -> dict:
    def g(rel):
        try:
            return ca.get_str(rel)
        except Exception:  # noqa: BLE001
            return None
    return {"date": dt.date.today().isoformat(), "session_id": dt.datetime.now().isoformat(timespec="seconds"),
            "host": socket.gethostname(), "driver": ioc.driver,
            "prefix": opts.prefix, "ioc_pid": ioc.st_cmd_pid, "adcore": g("cam1:ADCoreVersion_RBV"),
            "driver_version": g("cam1:DriverVersion_RBV"), "kernel": platform.release(),
            "outdir": str(outdir), "fstype": h5.mount_fstype(outdir.resolve()),
            "free_gb": round(shutil.disk_usage(outdir).free / 1e9, 1), "options": options}
