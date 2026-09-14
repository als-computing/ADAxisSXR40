"""Drive a REAL bluesky queue-server with area_detectors.py as a startup file.

    tools/blueskyTest/run.sh qserver            # via run.sh
    .venv/bin/python qserver_test.py [--points N] [--keep]

What runs, all on this host and all torn down at the end:
    1. an embedded Redis (redislite) on a free port          -- the manager's queue store
    2. a temporary tiled server (tiled serve catalog --temp) -- where the TiledWriter writes
    3. `start-re-manager --startup-dir <tmp>` where <tmp> holds
         00_base.py            RunEngine + TiledWriter subscription, motor, scan, count
         02_area_detectors.py  a copy of area_detectors.py (unchanged)
    4. over the manager's ZMQ API: environment_open, queue warmup_xv4040 then
       scan([xv4040], motor, -1, 1, N), queue_start, wait, history_get, environment_close
    5. the run named in the history is read back from tiled: image stack (N, rows, cols) uint16;
       the HDF5 file it points to is checked and deleted (unless --keep)

Exit 0 when the queue ran both items to completion and tiled serves the images, 1 otherwise.
"""
import argparse
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import h5py
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from main import TempTiled, ensure_write_dir, fail  # noqa: E402  (same helpers as main.py)

BASE_STARTUP = '''\
"""00_base.py: the RunEngine the worker keeps (--keep-re), with the TiledWriter subscribed,
plus a virtual motor and the plans the queue may use."""
import os
from bluesky import RunEngine
from bluesky.callbacks.tiled_writer import TiledWriter
from bluesky.plans import count, scan          # noqa: F401  (exposed to the queue)
from ophyd.sim import motor                    # noqa: F401
from tiled.client import from_uri

RE = RunEngine({})
RE.subscribe(TiledWriter(from_uri(os.environ["QS_TILED_URI"], api_key=os.environ["QS_TILED_KEY"])))
'''


PERMISSIONS = '''\
# user_group_permissions.yaml: the queue-server's stock layout (profile_collection_sim).
user_groups:
  root:
    allowed_plans: [null]
    forbidden_plans: [":^_"]
    allowed_devices: [null]
    forbidden_devices: [":^_:?.*"]
    allowed_functions: [null]
    forbidden_functions: [":^_"]
  primary:
    allowed_plans: [":.*"]
    forbidden_plans: [null]
    allowed_devices: [":?.*:depth=5"]
    forbidden_devices: [null]
    allowed_functions: [null]
    forbidden_functions: [null]
'''


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Manager:
    """start-re-manager as a subprocess plus a synchronous ZMQ client to it."""

    def __init__(self, startup_dir: Path, redis_addr: str, env: dict):
        from bluesky_queueserver import ZMQCommSendThreads
        self.ctrl = free_port()
        self.info = free_port()
        self.log = open(startup_dir.parent / "re-manager.log", "w")
        self.proc = subprocess.Popen(
            [str(Path(sys.executable).parent / "start-re-manager"), "--startup-dir", str(startup_dir),
             "--redis-addr", redis_addr, "--keep-re",
             "--zmq-control-addr", f"tcp://*:{self.ctrl}", "--zmq-info-addr", f"tcp://*:{self.info}",
             "--zmq-publish-console", "OFF", "--verbose"],
            stdout=self.log, stderr=subprocess.STDOUT, env=env)
        self.zmq = ZMQCommSendThreads(zmq_server_address=f"tcp://localhost:{self.ctrl}", timeout_recv=20000)

    def call(self, method, params=None):
        r = self.zmq.send_message(method=method, params=params or {})
        if isinstance(r, dict) and r.get("success") is False:
            raise RuntimeError(f"{method}: {r.get('msg')}")
        return r

    def wait(self, pred, what, timeout):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"re-manager exited with {self.proc.returncode}; see {self.log.name}")
            try:
                last = self.call("status")
                if pred(last):
                    return last
            except Exception as e:  # noqa: BLE001  -- not answering yet
                last = e
            time.sleep(1.0)
        raise TimeoutError(f"waiting for {what}: last status {last}")

    def stop(self):
        try:
            self.call("manager_stop", {"option": "safe_off"})
            self.proc.wait(timeout=30)
        except Exception:  # noqa: BLE001
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.log.close()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--points", type=int, default=3)
    p.add_argument("--keep", action="store_true", help="keep the HDF5 file and the temp dir")
    args = p.parse_args(argv)
    n = args.points

    import area_detectors as ad
    if ad.xv4040 is None:
        return fail("detector did not connect (see the message above)")
    ensure_write_dir(ad.xv4040)

    tmp = Path(tempfile.mkdtemp(prefix="xv4040-qserver-"))
    startup = tmp / "startup"
    startup.mkdir()
    (startup / "00_base.py").write_text(BASE_STARTUP)
    (startup / "user_group_permissions.yaml").write_text(PERMISSIONS)
    shutil.copy(HERE / "area_detectors.py", startup / "02_area_detectors.py")

    import redislite
    redis = redislite.Redis(serverconfig={"port": str(free_port())}, dbfilename=str(tmp / "redis.db"))
    redis_addr = f"127.0.0.1:{redis.server_config['port']}"
    tiled = TempTiled(ad.XV4040_FILES_ROOT)
    client = tiled.connect()
    env = dict(os.environ, QS_TILED_URI=tiled.uri, QS_TILED_KEY=tiled.key)
    print(f"redis {redis_addr}; tiled {tiled.uri}; startup dir {startup}")

    mgr = Manager(startup, redis_addr, env)
    path = None
    try:
        mgr.wait(lambda s: s.get("manager_state") == "idle", "manager to start", 60)
        print("manager up:", {k: mgr.call("status")[k] for k in ("manager_state", "worker_environment_exists")})
        mgr.call("environment_open")
        st = mgr.wait(lambda s: s.get("worker_environment_exists") and s.get("manager_state") == "idle",
                      "worker environment (loads the startup files, connects the IOC)", 180)
        print("environment open; existing devices/plans loaded:", st.get("plans_allowed_uid") is not None)
        devices = mgr.call("devices_allowed", {"user_group": "primary"})["devices_allowed"]
        plans = mgr.call("plans_allowed", {"user_group": "primary"})["plans_allowed"]
        print("devices allowed:", sorted(k for k in devices if not k.startswith("_")))
        print("plans allowed:", sorted(plans))
        if "xv4040" not in devices or "warmup_xv4040" not in plans:
            return fail("xv4040 device or warmup_xv4040 plan not registered by the worker")

        mgr.call("queue_clear")
        mgr.call("history_clear")
        for item in ({"name": "warmup_xv4040", "item_type": "plan"},
                     {"name": "scan", "args": [["xv4040"], "motor", -1, 1, n], "item_type": "plan"}):
            r = mgr.call("queue_item_add", {"item": item, "user": "blueskyTest", "user_group": "primary"})
            print("queued:", r["item"]["name"], r["item"].get("args", ""))
        t0 = time.monotonic()
        mgr.call("queue_start")
        st = mgr.wait(lambda s: s.get("items_in_history", 0) >= 2 and s.get("manager_state") == "idle"
                      and s.get("items_in_queue", 0) == 0, "the queue to finish", 300)
        print(f"queue finished in {time.monotonic() - t0:.1f} s")

        history = mgr.call("history_get")["items"]
        for h in history:
            res = h["result"]
            print(f"history: {h['name']:16s} exit_status={res.get('exit_status')} run_uids={res.get('run_uids')} "
                  f"{'msg=' + res['msg'] if res.get('msg') else ''}")
        bad = [h["name"] for h in history if h["result"].get("exit_status") != "completed"]
        if bad:
            return fail(f"queue items did not complete: {bad}")
        uid = history[-1]["result"]["run_uids"][0]

        # ---- the run as tiled serves it, and the file it points to -------------------------
        run = client[uid]
        node = run["primary"]["xv4040_image"]
        rows, cols = ad.xv4040.cam.array_size.array_size_y.get(), ad.xv4040.cam.array_size.array_size_x.get()
        print(f"tiled: {uid[:8]}/primary/xv4040_image shape={tuple(node.shape)} dtype={node.dtype}; "
              f"keys {sorted(k for k in run['primary'] if not k.startswith('ts_'))}")
        # the asset: tiled knows the file's URI
        ds = node.data_sources()[0] if hasattr(node, "data_sources") else None
        uri = ds.assets[0].data_uri if ds and ds.assets else None
        print("asset uri:", uri)
        path = Path(uri.replace("file://localhost", "")) if uri and uri.startswith("file://localhost") else None
        problems = []
        if tuple(node.shape) != (n, rows, cols):
            problems.append(f"tiled shape {tuple(node.shape)} != ({n}, {rows}, {cols})")
        if np.dtype(node.dtype) != np.uint16:
            problems.append(f"tiled dtype {node.dtype} != uint16")
        if path is None or not path.exists():
            problems.append(f"HDF5 file behind the run not found: {uri}")
        else:
            with h5py.File(path, "r") as f:
                fshape = f["/entry/data/data"].shape
                fmean = float(np.mean(f["/entry/data/data"][0]))
            tmean = float(np.mean(node[0]))
            print(f"file {path.name}: shape={fshape}; frame0 mean file={fmean:.1f} tiled={tmean:.1f}")
            if fshape != (n, rows, cols) or abs(fmean - tmean) > 1e-6:
                problems.append("file and tiled disagree")
        if problems:
            return fail("; ".join(problems))
        print(f"OK: queue-server ran warmup_xv4040 and scan([xv4040], motor, -1, 1, {n}); "
              f"tiled serves {n} frames of {rows}x{cols} uint16")
        return 0
    finally:
        try:
            mgr.call("environment_close")
            mgr.wait(lambda s: not s.get("worker_environment_exists"), "environment to close", 60)
        except Exception as e:  # noqa: BLE001
            print("environment_close:", e)
        mgr.stop()
        tiled.stop()
        try:
            redis.shutdown()
        except Exception:  # noqa: BLE001
            pass
        if path and path.exists() and not args.keep:
            path.unlink()
        if not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print("kept", tmp, "and", path)


if __name__ == "__main__":
    sys.exit(main())
