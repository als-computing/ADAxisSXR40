"""Build and run tools/h5check, and parse its output.

No h5py on this host, so the C tool (linked against ADSupport's HDF5, a library that is
NOT the IOC's own) is how a written file is verified. All HDF5 filters areaDetector can
write (zlib, szip, blosc, bitshuffle/LZ4, LZ4) are compiled into that library; the
HDF5_PLUGIN_PATH we set is belt-and-braces.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import expected


class H5CheckError(AssertionError):
    """h5check could not open or fully read the file."""


def build_h5check(out: Path | None = None) -> Path:
    out = Path(out or expected.TESTS_DIR / ".build/h5check")
    src = expected.H5CHECK_SRC
    if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    s = expected.ADSUPPORT
    cmd = ["gcc", "-O2", "-o", str(out), str(src), f"-I{s}/include", f"-I{s}/include/os/Linux",
           f"-L{s}/lib/linux-x86_64", f"-Wl,-rpath,{s}/lib/linux-x86_64",
           "-lhdf5", "-lhdf5_hl", "-lszip", "-lzlib", "-lm"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("h5check build failed:\n" + " ".join(cmd) + "\n" + r.stderr)
    return out


@dataclass
class FrameStat:
    which: str
    index: int
    min: int
    max: int
    mean: float
    zeros_pct: float


@dataclass
class H5Report:
    dims: tuple[int, ...] = ()
    dtype: str = ""
    chunk: tuple[int, ...] = ()
    filters: tuple[int, ...] = ()
    filters_unavailable: tuple[int, ...] = ()
    frames: list[FrameStat] = field(default_factory=list)
    uid_n: int | None = None
    uid_first: int | None = None
    uid_last: int | None = None
    uid_missing: int | None = None
    uid_nonmono: int | None = None
    camera_fps: float | None = None
    host_fps: float | None = None
    interval_min_ms: float | None = None
    interval_max_ms: float | None = None
    attributes: tuple[str, ...] = ()
    datasets: tuple[str, ...] = ()
    read_failed: bool = False
    raw: str = ""

    @property
    def ramp_present(self) -> bool:
        mn, mx, mean = expected.RAMP_SIGNATURE
        return bool(self.frames) and all(f.min == mn and f.max == mx and abs(f.mean - mean) < 1.0
                                         for f in self.frames)

    @property
    def frame_means(self) -> list[float]:
        return [f.mean for f in self.frames]


RE_DIMS = re.compile(r"dims=\[([\d x]+)\] type=(\w+)")
RE_CHUNK = re.compile(r"chunk=\[([\d x]+)\]")
RE_FILTERS = re.compile(r"filters=\[([\d,]*)\]")
RE_FILTER_AVAIL = re.compile(r"filter (\d+): (available|UNAVAILABLE)")
RE_FRAME = re.compile(r"(first|middle|last)\s+frame\s+(\d+): min=(\d+) max=(\d+) mean=([\d.]+) zeros=([\d.]+)%")
RE_UID = re.compile(r"UniqueId: n=(\d+) first=(\d+) last=(\d+) span=\d+ missing=(\d+) nonmonotonic=(\d+)")
RE_CAM_FPS = re.compile(r"TimeStamp \(camera\): span=[\d.]+ s -> ([\d.]+) fps")
RE_INTERVAL = re.compile(r"frame interval min=([\d.]+) ms max=([\d.]+) ms")
RE_HOST_FPS = re.compile(r"EpicsTS \(host\):\s+span=[\d.]+ s -> ([\d.]+) fps")
RE_ATTRS = re.compile(r"^\s*NDAttributes:(.*)$")
RE_DATASETS = re.compile(r"^\s*datasets:(.*)$")


def parse_h5check(text: str) -> H5Report:
    rep = H5Report(raw=text)
    for line in text.splitlines():
        if m := RE_DIMS.search(line):
            rep.dims = tuple(int(x) for x in m.group(1).split("x"))
            rep.dtype = m.group(2)
            if c := RE_CHUNK.search(line):
                rep.chunk = tuple(int(x) for x in c.group(1).split("x"))
            if fl := RE_FILTERS.search(line):
                rep.filters = tuple(int(x) for x in fl.group(1).split(",") if x)
        elif m := RE_FILTER_AVAIL.search(line):
            if m.group(2) == "UNAVAILABLE":
                rep.filters_unavailable += (int(m.group(1)),)
        elif m := RE_FRAME.search(line):
            rep.frames.append(FrameStat(m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)),
                                        float(m.group(5)), float(m.group(6))))
        elif "READ FAILED" in line:
            rep.read_failed = True
        elif m := RE_UID.search(line):
            rep.uid_n, rep.uid_first, rep.uid_last = int(m.group(1)), int(m.group(2)), int(m.group(3))
            rep.uid_missing, rep.uid_nonmono = int(m.group(4)), int(m.group(5))
        elif m := RE_CAM_FPS.search(line):
            rep.camera_fps = float(m.group(1))
            if iv := RE_INTERVAL.search(line):
                rep.interval_min_ms, rep.interval_max_ms = float(iv.group(1)), float(iv.group(2))
        elif m := RE_HOST_FPS.search(line):
            rep.host_fps = float(m.group(1))
        elif m := RE_ATTRS.match(line):
            rep.attributes = tuple(m.group(1).split())
        elif m := RE_DATASETS.match(line):
            rep.datasets = tuple(m.group(1).split())
    return rep


def run_h5check(binary: Path, path: Path, timeout: float = 300, *, strict: bool = True,
                list_attrs: bool = False) -> H5Report:
    env = dict(os.environ)
    env.setdefault("HDF5_PLUGIN_PATH", str(expected.ADSUPPORT / "lib/linux-x86_64"))
    args = [str(binary)] + (["-l"] if list_attrs else []) + [str(path)]
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env)
    rep = parse_h5check(r.stdout)
    if r.returncode == 1:
        raise H5CheckError(f"h5check cannot open {path}: {r.stdout.strip()} {r.stderr.strip()}")
    if strict and (r.returncode != 0 or rep.read_failed):
        raise H5CheckError(f"h5check could not read every frame of {path} (rc={r.returncode}, "
                           f"unavailable filters={rep.filters_unavailable}):\n{r.stdout}")
    return rep


def mount_fstype(path: Path) -> str:
    best, fstype = "", ""
    try:
        with open("/proc/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 3 and str(path).startswith(parts[1]) and len(parts[1]) > len(best):
                    best, fstype = parts[1], parts[2]
    except OSError:
        pass
    return fstype


def check_outdir(path: str | Path, min_free_bytes: int = 1 << 30) -> Path:
    p = Path(os.path.expanduser(str(path)))
    p.mkdir(parents=True, exist_ok=True)
    fs = mount_fstype(p.resolve())
    if fs == "tmpfs":
        raise RuntimeError(f"{p} is on tmpfs; file-writer tests need real storage (roi-rate-test.sh NOTE 4)")
    free = shutil.disk_usage(p).free
    if free < min_free_bytes:
        raise RuntimeError(f"{p}: only {free/1e9:.1f} GB free")
    if not os.access(p, os.W_OK):
        raise RuntimeError(f"{p} is not writable")
    return p
