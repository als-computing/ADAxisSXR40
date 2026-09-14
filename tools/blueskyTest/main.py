"""Scan a virtual motor against the live XV4040 IOC under bluesky, then check the HDF5 file.

    tools/blueskyTest/run.sh                  # 5 points, file deleted after checking
    tools/blueskyTest/run.sh --points 10 --keep

What it proves: the ophyd device in area_detectors.py stages, triggers and unstages the
detector the way a queue-server plan will; every point produces a datum; the run's HDF5 file
exists where the resource document says, holds exactly one frame per point with the
detector's geometry, contiguous unique ids and real pixel statistics. Exit 0 when all of
that holds, 1 otherwise. Works against ADAxisSXR40 and ADTucsen alike.
"""
import argparse
import datetime as dt
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import h5py
import numpy as np
from bluesky import RunEngine
from bluesky.plans import scan
from ophyd.sim import motor                   # a virtual motor (SynAxis)

import area_detectors as ad


class Docs:
    """Collects the run's documents by name."""

    def __init__(self):
        self.by_name = defaultdict(list)

    def __call__(self, name, doc):
        self.by_name[name].append(doc)


def fail(msg):
    print(f"FAIL: {msg}")
    return 1


def ensure_write_dir(det) -> Path:
    """The IOC (possibly another user) creates the file; the directory must exist and be open."""
    write_path = Path(dt.datetime.now().strftime(det.hdf5.write_path_template))
    os.makedirs(write_path, exist_ok=True)
    root = Path(ad.XV4040_FILES_ROOT)
    for p in [write_path] + [q for q in write_path.parents if root in q.parents or q == root]:
        try:
            os.chmod(p, 0o777)          # the IOC may run as another user (ioc-xv4040: daenglis)
        except PermissionError:
            pass
    return write_path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--points", type=int, default=5, help="scan points (frames), default 5")
    p.add_argument("--keep", action="store_true", help="keep the HDF5 file after checking")
    p.add_argument("--exposure", type=float, default=0.05, help="AcquireTime per frame, s")
    args = p.parse_args(argv)

    det = ad.xv4040
    if det is None:
        return fail("detector did not connect (see the message above)")
    det.cam.stage_sigs["acquire_time"] = args.exposure
    print(f"IOC {det.prefix} model={det.cam.model.get()!r} manufacturer={det.cam.manufacturer.get()!r} "
          f"state={det.cam.detector_state.get(as_string=True)}")
    if det.cam.detector_state.get(as_string=True) not in ("Idle", "Aborted"):
        return fail(f"detector is {det.cam.detector_state.get(as_string=True)}; not starting a scan")

    ensure_write_dir(det)
    det.hdf5.warmup()
    rows, cols = det.hdf5.array_size.height.get(), det.hdf5.array_size.width.get()
    print(f"geometry after warm-up: {rows} x {cols}")

    docs = Docs()
    RE = RunEngine({})
    RE.subscribe(docs)
    t0 = time.monotonic()
    uid, = RE(scan([det], motor, -1, 1, args.points), md={"purpose": "ADAxisSXR40 tools/blueskyTest"})
    wall = time.monotonic() - t0
    print(f"run {uid[:8]} finished in {wall:.1f} s")

    # ---- documents --------------------------------------------------------------------------
    n = args.points
    events = docs.by_name["event"]
    stop = docs.by_name["stop"][-1]
    if stop["exit_status"] != "success":
        return fail(f"run exit_status {stop['exit_status']}: {stop.get('reason')}")
    if len(events) != n:
        return fail(f"{len(events)} events, expected {n}")
    key = f"{det.name}_image"
    if any(key not in e["data"] for e in events):
        return fail(f"event data lacks {key}: keys {sorted(events[0]['data'])}")
    datums = docs.by_name["datum"]
    points = sorted(d["datum_kwargs"]["point_number"] for d in datums)
    if points != list(range(n)):
        return fail(f"datum point numbers {points}")
    resources = docs.by_name["resource"]
    if len(resources) != 1 or resources[0]["spec"] != "AD_HDF5":
        return fail(f"expected one AD_HDF5 resource, got {[(r['spec'], r['resource_path']) for r in resources]}")
    res = resources[0]
    path = Path(res["root"]) / res["resource_path"]
    print(f"resource: root={res['root']} path={res['resource_path']} kwargs={res['resource_kwargs']}")
    if not path.exists():
        return fail(f"file {path} does not exist")

    # ---- the file -----------------------------------------------------------------------------
    try:
        with h5py.File(path, "r") as f:
            data = f["/entry/data/data"]
            shape, dtype = data.shape, data.dtype
            uids = f["/entry/instrument/NDAttributes/NDArrayUniqueId"][()].ravel()
            means = [float(np.mean(data[i, ::16, ::16])) for i in range(shape[0])]     # subsampled
            mins = [int(np.min(data[i, ::16, ::16])) for i in range(shape[0])]
            maxs = [int(np.max(data[i, ::16, ::16])) for i in range(shape[0])]
    except Exception as e:  # noqa: BLE001
        return fail(f"cannot read {path}: {e}")
    finally:
        size_mb = path.stat().st_size / 1e6 if path.exists() else 0.0
        if not args.keep and path.exists():
            path.unlink()

    print(f"file: {path.name} {size_mb:.1f} MB shape={shape} dtype={dtype}")
    print(f"unique ids: {uids.tolist()}")
    print("frame means (subsampled): " + " ".join(f"{m:.0f}" for m in means))
    problems = []
    if shape != (n, rows, cols):
        problems.append(f"shape {shape} != ({n}, {rows}, {cols})")
    if dtype != np.uint16:
        problems.append(f"dtype {dtype} != uint16")
    if len(uids) != n or any(int(b - a) != 1 for a, b in zip(uids, uids[1:])):
        problems.append(f"unique ids not contiguous: {uids.tolist()}")
    if any(mx == mn for mn, mx in zip(mins, maxs)):
        problems.append("a frame is constant (no image data)")
    if all(abs(m - 32640.0) < 1.0 for m in means):
        problems.append("every frame has mean 32640: the camera's synthetic ramp, not sensor data")
    if problems:
        return fail("; ".join(problems))
    print(f"OK: {n} points, one file, {n} frames of {rows}x{cols} uint16, ids contiguous, "
          f"{'kept' if args.keep else 'deleted'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
