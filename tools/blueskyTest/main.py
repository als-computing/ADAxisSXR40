"""Scan a virtual motor against the live XV4040 IOC under bluesky, write the run through
bluesky's TiledWriter into a temporary tiled server, then check the HDF5 file both directly
and as tiled serves it.

    tools/blueskyTest/run.sh                  # 5 points, file deleted after checking
    tools/blueskyTest/run.sh --points 10 --keep
    tools/blueskyTest/run.sh --no-tiled       # documents + file only

What it proves: the ophyd device in area_detectors.py stages, triggers and unstages the
detector the way a queue-server plan will; every point produces a datum; the run's HDF5 file
exists where the resource document says, holds exactly one frame per point with the
detector's geometry, contiguous unique ids and real pixel statistics; and the TiledWriter
accepts the run and serves the image stack with the right shape and the same pixels.
Exit 0 when all of that holds, 1 otherwise. Works against ADAxisSXR40 and ADTucsen alike.
"""
import argparse
import datetime as dt
import os
import secrets
import socket
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

import h5py
import numpy as np
from bluesky import RunEngine
from bluesky.callbacks import LiveTable
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


class TempTiled:
    """`tiled serve catalog --temp` on a free local port, readable storage = our data root."""

    def __init__(self, readable_root: str):
        self.key = secrets.token_hex(16)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.uri = f"http://127.0.0.1:{self.port}"
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "tiled", "serve", "catalog", "--temp", "--api-key", self.key,
             "--port", str(self.port), "-r", readable_root],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.client = None

    def connect(self, timeout: float = 60.0):
        from tiled.client import from_uri
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"tiled server exited with {self.proc.returncode}")
            try:
                self.client = from_uri(self.uri, api_key=self.key)
                return self.client
            except Exception as e:  # noqa: BLE001  -- not up yet
                last = e
                time.sleep(0.5)
        raise RuntimeError(f"tiled server did not answer within {timeout} s: {last}")

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--points", type=int, default=5, help="scan points (frames), default 5")
    p.add_argument("--keep", action="store_true", help="keep the HDF5 file after checking")
    p.add_argument("--exposure", type=float, default=0.05, help="AcquireTime per frame, s")
    p.add_argument("--no-tiled", action="store_true", help="skip the TiledWriter round trip")
    args = p.parse_args(argv)

    det = ad.xv4040
    if det is None:
        return fail("detector did not connect (see the message above)")
    # exposure is an experiment parameter, set on the IOC like a plan would (bps.mv), not staged;
    # remembered here and put back at the end so the IOC is left as found
    exposure_before = det.cam.acquire_time.get()
    det.cam.acquire_time.set(args.exposure).wait(timeout=10)
    print(f"IOC {det.prefix} model={det.cam.model.get()!r} manufacturer={det.cam.manufacturer.get()!r} "
          f"state={det.cam.detector_state.get(as_string=True)} exposure={det.cam.acquire_time.get():.3f} s")
    if det.cam.detector_state.get(as_string=True) not in ("Idle", "Aborted"):
        return fail(f"detector is {det.cam.detector_state.get(as_string=True)}; not starting a scan")

    ensure_write_dir(det)
    # The device warms up by itself at stage() when the geometry changed (AUTO_WARMUP); calling
    # it here as well makes the test independent of that setting and prints the geometry early.
    det.hdf5.warmup()
    rows, cols = det.cam.array_size.array_size_y.get(), det.cam.array_size.array_size_x.get()
    print(f"geometry after warm-up: {rows} x {cols}")

    tiled = None
    if not args.no_tiled:
        try:
            import tiled  # noqa: F401
            from bluesky.callbacks.tiled_writer import TiledWriter
        except ImportError:
            print("tiled not installed in this venv; skipping the TiledWriter round trip (--no-tiled)")
        else:
            tiled = TempTiled(ad.XV4040_FILES_ROOT)
            client = tiled.connect()
            print(f"tiled {client.context.server_info.library_version} serving a temporary catalog on {tiled.uri}")

    docs = Docs()
    RE = RunEngine({})
    RE.subscribe(docs)
    RE.subscribe(LiveTable(["motor", f"{det.name}_stats1_mean_value", f"{det.name}_stats1_max_value"]))
    if tiled:
        RE.subscribe(TiledWriter(tiled.client))
    n = args.points
    path = None
    try:
        t0 = time.monotonic()
        uid, = RE(scan([det], motor, -1, 1, n), md={"purpose": "ADAxisSXR40 tools/blueskyTest"})
        wall = time.monotonic() - t0
        print(f"run {uid[:8]} finished in {wall:.1f} s")

        # ---- documents ----------------------------------------------------------------------
        events = docs.by_name["event"]
        stop = docs.by_name["stop"][-1]
        if stop["exit_status"] != "success":
            return fail(f"run exit_status {stop['exit_status']}: {stop.get('reason')}")
        if len(events) != n:
            return fail(f"{len(events)} events, expected {n}")
        key = f"{det.name}_image"
        if any(key not in e["data"] for e in events):
            return fail(f"event data lacks {key}: keys {sorted(events[0]['data'])}")
        desc = docs.by_name["descriptor"][0]["data_keys"][key]
        print(f"descriptor {key}: shape={desc.get('shape')} dtype_numpy={desc.get('dtype_numpy')} "
              f"dtype_str={desc.get('dtype_str')} external={desc.get('external')}")
        datums = docs.by_name["datum"]
        points = sorted(d["datum_kwargs"]["point_number"] for d in datums)
        if points != list(range(n)):
            return fail(f"datum point numbers {points}")
        resources = docs.by_name["resource"]
        if len(resources) != 1:
            return fail(f"expected one resource, got {len(resources)}")
        res = resources[0]
        path = Path(res["root"]) / res["resource_path"]
        print(f"resource: spec={res['spec']} root={res['root']} path={res['resource_path']}")
        print(f"          kwargs={res['resource_kwargs']}")
        print(f"file on disk: {path}")
        if not path.exists():
            return fail(f"file {path} does not exist")

        # ---- the file, directly ----------------------------------------------------------------
        try:
            with h5py.File(path, "r") as f:
                data = f["/entry/data/data"]
                shape, dtype = data.shape, data.dtype
                uids = f["/entry/instrument/NDAttributes/NDArrayUniqueId"][()].ravel()
                means = [float(np.mean(data[i, ::16, ::16])) for i in range(shape[0])]     # subsampled
                mins = [int(np.min(data[i, ::16, ::16])) for i in range(shape[0])]
                maxs = [int(np.max(data[i, ::16, ::16])) for i in range(shape[0])]
                first_frame_mean = float(np.mean(data[0]))
        except Exception as e:  # noqa: BLE001
            return fail(f"cannot read {path}: {e}")
        size_mb = path.stat().st_size / 1e6
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

        # ---- the same run as tiled serves it ---------------------------------------------------
        if tiled:
            try:
                run = tiled.client[uid]
                node = run["primary"][key]
                tshape, tdtype = tuple(node.shape), np.dtype(node.dtype)
                frame0 = node[0]
                t_mean = float(np.mean(frame0))
                print(f"tiled: {uid[:8]}/primary/{key} shape={tshape} dtype={tdtype} frame0 mean={t_mean:.1f} "
                      f"(h5py {first_frame_mean:.1f}); other keys: "
                      f"{sorted(k for k in run['primary'] if not k.startswith('ts_'))}")
                if tshape != (n, rows, cols):
                    problems.append(f"tiled shape {tshape} != ({n}, {rows}, {cols})")
                if tdtype != np.uint16:
                    problems.append(f"tiled dtype {tdtype} != uint16")
                if abs(t_mean - first_frame_mean) > 1e-6:
                    problems.append(f"tiled frame 0 mean {t_mean} != file {first_frame_mean}")
            except Exception as e:  # noqa: BLE001
                problems.append(f"tiled could not serve the image: {type(e).__name__}: {e}")

        if problems:
            return fail("; ".join(problems))
        print(f"OK: {n} points, one file, {n} frames of {rows}x{cols} uint16, ids contiguous"
              f"{', served by tiled' if tiled else ''}, {'kept' if args.keep else 'deleted'}")
        return 0
    finally:
        if tiled:
            tiled.stop()
        if path and path.exists() and not args.keep:
            path.unlink()
        try:
            det.cam.acquire_time.set(exposure_before).wait(timeout=10)
        except Exception as e:  # noqa: BLE001
            print(f"could not restore AcquireTime {exposure_before}: {e}")


if __name__ == "__main__":
    sys.exit(main())
