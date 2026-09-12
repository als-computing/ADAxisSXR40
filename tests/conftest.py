"""pytest configuration for the ADAxisSXR40 functional suite.

Channel Access is pinned to the local IOC BEFORE pyepics is imported: the host has two
interfaces, and without this CA reports "Identical process variable names on multiple
servers" for the one IOC seen on both. pvAccess is NOT pinned: the server answers
broadcast searches only.
"""
from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

os.environ.setdefault("EPICS_CA_ADDR_LIST", "127.0.0.1")
os.environ["EPICS_CA_AUTO_ADDR_LIST"] = "NO"
os.environ.setdefault("EPICS_CA_MAX_ARRAY_BYTES", "40000000")
for _k in ("EPICS_PVA_ADDR_LIST", "EPICS_PVA_AUTO_ADDR_LIST"):
    os.environ.pop(_k, None)

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

from helpers import acquire, h5, iocdetect, ioclog, policy, stressrun  # noqa: E402
from helpers import expected as ours  # noqa: E402
from helpers.ca import CA  # noqa: E402
from helpers.logdelta import LogDelta  # noqa: E402
from helpers.snapshot import Snapshot, safe_stop  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / ".results"


# ---- options ---------------------------------------------------------------------------
def pytest_addoption(parser):
    g = parser.getgroup("axis")
    g.addoption("--full", action="store_true", help="run the full tier (writes, robustness, workflow, compat)")
    g.addoption("--prefix", default=ours.PREFIX_DEFAULT, help="PV prefix (default XV4040:)")
    g.addoption("--driver", default="auto", choices=["auto", "ours", "adtucsen"],
                help="which driver to expect; auto = detect from systemd/processes")
    g.addoption("--outdir", default=os.path.expanduser("~/axis-perf-tmp"),
                help="real-disk directory for file-writer tests")
    g.addoption("--baseline", default=None, help="ADTucsen baseline JSON for compat tests")
    g.addoption("--h5check", default=None, help="path to a built h5check binary")
    g.addoption("--ca-timeout", type=float, default=5.0)
    s = parser.getgroup("axis stress tier (tests/run.sh stress)")
    s.addoption("--stress", action="store_true", help="enable the stress tier (set by run.sh stress)")
    s.addoption("--stress-durations", default="10,25", help="seconds per matrix run, comma list")
    s.addoption("--stress-heights", default="4096,256", help="ROI heights, comma list, or 'all' for the 9 sweep heights")
    s.addoption("--provoke", action="store_true", help="run the deliberately provoked writer-queue test")
    s.addoption("--record", action="store_true", help="also write the results into info/performance/")
    s.addoption("--max-bytes", type=float, default=80.0, help="GB the stress session may write in total")
    s.addoption("--long-minutes", type=float, default=5.0, help="length of the long continuous run")


def pytest_configure(config):
    config._ioc = iocdetect.detect(config.getoption("--driver"))
    config._deadlock = False
    RESULTS_DIR.mkdir(exist_ok=True)


def pytest_collection_modifyitems(config, items):
    ioc = config._ioc
    full = config.getoption("--full")
    stress = config.getoption("--stress")
    for item in items:
        is_stress = bool(item.get_closest_marker("stress"))
        if is_stress and not stress:
            item.add_marker(pytest.mark.skip(reason="stress tier: tests/run.sh stress"))
        if stress and not is_stress:
            item.add_marker(pytest.mark.skip(reason="stress session: non-stress test"))
        if not full and not stress and item.get_closest_marker("full"):
            item.add_marker(pytest.mark.skip(reason="full tier: pass --full"))
        if is_stress and "provoke" in item.nodeid and not config.getoption("--provoke"):
            item.add_marker(pytest.mark.skip(reason="provoked writer-queue test: pass --provoke"))
        if ioc.driver != ours.DRIVER:
            if item.get_closest_marker("ours_only"):
                item.add_marker(pytest.mark.skip(reason=f"ADAxisSXR40-only test; {ioc.driver} is serving"))
            ff = item.get_closest_marker("fork_fix")
            if ff:
                why = ff.kwargs.get("reason", "behaviour fixed in the fork, absent upstream")
                item.add_marker(pytest.mark.xfail(strict=False, reason=f"ADTucsen: {why}"))


def pytest_report_header(config):
    ioc = config._ioc
    lines = [f"IOC serving {config.getoption('--prefix')}: {ioc.driver} "
             f"(unit active={ioc.unit_active}, st.cmd pid={ioc.st_cmd_pid}, log boot pid={ioc.boot_pid})"]
    if config.getoption("--stress"):
        so = _stress_opts(config)
        lines.append(f"stress tier: durations={so['durations']} s, heights={so['heights']}, "
                     f"max {so['max_bytes']/1e9:.0f} GB, long run {so['long_minutes']} min, "
                     f"provoke={so['provoke']}, record={so['record']}")
    return lines


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call" and rep.failed and call.excinfo is not None:
        if call.excinfo.errisinstance(acquire.DeadlockSuspected):
            item.config._deadlock = True


def _stress_opts(config) -> dict:
    heights = config.getoption("--stress-heights")
    heights = list(ours.SWEEP_HEIGHTS) if heights.strip() == "all" else [int(h) for h in heights.split(",") if h.strip()]
    return {"durations": [float(d) for d in config.getoption("--stress-durations").split(",") if d.strip()],
            "heights": heights, "provoke": config.getoption("--provoke"), "record": config.getoption("--record"),
            "max_bytes": int(config.getoption("--max-bytes") * 1e9), "long_minutes": config.getoption("--long-minutes")}


# ---- fixtures ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def opts(request):
    return request.config.option


@pytest.fixture(scope="session")
def ioc(request):
    info = request.config._ioc
    if info.driver == "none":
        pytest.exit(f"no IOC serving {request.config.getoption('--prefix')} on 127.0.0.1 "
                    "(neither ioc-axissxr40 nor ioc-xv4040 is running)", returncode=2)
    return info


@pytest.fixture(scope="session")
def exp(ioc):
    """Expectations module for the driver that is serving."""
    return ioc.exp


@pytest.fixture(scope="session")
def ca(opts, ioc):
    return CA(opts.prefix, timeout=opts.ca_timeout)


@pytest.fixture(scope="session")
def camera(ca, request):
    """Skip hardware tests when the camera is not attached or a deadlock was seen."""
    ok, why = iocdetect.camera_connected(ca)
    if not ok:
        pytest.skip(why)
    return why


@pytest.fixture(autouse=True)
def _no_hardware_after_deadlock(request):
    if request.config._deadlock and "camera" in request.fixturenames:
        pytest.skip("port-thread deadlock suspected earlier in this session; no further hardware tests")


@pytest.fixture(scope="session")
def boot_log(ioc, exp):
    """Lines of the running IOC's console log since its last start."""
    try:
        lines = ioclog.read_clean(exp.LOG)
    except OSError as e:
        pytest.skip(f"cannot read {exp.LOG}: {e}")
    sl, pid = ioclog.last_boot_slice(lines, exp.PROCSERV_CHILD)
    if pid is None:
        pytest.skip(f"{exp.LOG}: no procServ start banner; IOC not started via the unit?")
    if ioc.st_cmd_pid and pid != ioc.st_cmd_pid:
        pytest.skip(f"{exp.LOG} last boot pid {pid} != running st.cmd pid {ioc.st_cmd_pid}; log is stale")
    return sl


@pytest.fixture(scope="session")
def ioc_pid(ioc):
    if not ioc.st_cmd_pid:
        pytest.skip("IOC process id unknown; cannot sample its memory")
    return ioc.st_cmd_pid


# ---- log delta ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def log_delta(request):
    """Error lines the IOC logs while the tests run (beyond the boot slice).

    Warns at the end of the session and writes tests/.results/log-delta.txt; the stress
    tier additionally fails the responsible run (stressrun.assert_clean_run)."""
    ioc = request.config._ioc
    if ioc.driver == "none" or ioc.exp is None or not ioc.log_is_current or not os.access(ioc.exp.LOG, os.R_OK):
        yield None
        return
    ld = LogDelta(ioc.exp.LOG)
    yield ld
    flagged, exempted = ld.summary()
    path = RESULTS_DIR / "log-delta.txt"
    body = [f"# new IOC log error lines during the session ({len(flagged)} flagged, {len(exempted)} exempted by tests)"]
    body += flagged + ["", "# exempted (inside a test's declared error window):"] + exempted
    path.write_text("\n".join(body) + "\n")
    if flagged:
        warnings.warn(f"{len(flagged)} new IOC log error line(s) during the session; see {path}")


# ---- snapshot / restore (helpers/snapshot.py) -----------------------------------------
@pytest.fixture(scope="session", autouse=True)
def session_snapshot(request):
    """Safety net: whatever the tests did, the IOC ends the session as it started."""
    cfg = request.config
    if cfg._ioc.driver == "none":
        yield None
        return
    ca = CA(cfg.getoption("--prefix"), timeout=cfg.getoption("--ca-timeout"))
    snap = Snapshot(ca, policy.SNAPSHOT_PVS)
    yield snap
    if cfg._deadlock:
        (RESULTS_DIR / "restore-failures.txt").write_text(
            "restore skipped: port-thread deadlock suspected; no writes attempted\n")
        return
    try:
        safe_stop(ca)
        problems = snap.restore()
    except acquire.DeadlockSuspected as e:
        problems = [f"deadlock during restore: {e}"]
    path = RESULTS_DIR / "restore-failures.txt"
    if problems:
        path.write_text("\n".join(problems) + "\n")
        warnings.warn("session restore left %d setting(s) different; see %s" % (len(problems), path))
    elif path.exists():
        path.unlink()


@pytest.fixture
def restore_settings(ca, request):
    """Per-test snapshot of the writable settings, restored at teardown."""
    snap = Snapshot(ca, policy.SNAPSHOT_PVS)
    yield snap
    if request.config._deadlock:
        return
    try:
        safe_stop(ca)
        problems = snap.restore()
    except acquire.DeadlockSuspected:
        request.config._deadlock = True
        return
    assert not problems, "settings not restored after test:\n  " + "\n  ".join(problems)


@pytest.fixture(scope="module")
def module_settings(ca, request):
    """Module-scoped snapshot for fixtures that set up once for several tests."""
    snap = Snapshot(ca)
    yield snap
    if request.config._deadlock:
        return
    try:
        safe_stop(ca)
        problems = snap.restore()
    except acquire.DeadlockSuspected:
        request.config._deadlock = True
        return
    if problems:
        (RESULTS_DIR / "restore-failures.txt").write_text("\n".join(problems) + "\n")
        raise AssertionError("module settings not restored:\n  " + "\n  ".join(problems))


# ---- files -----------------------------------------------------------------------------------
@pytest.fixture(scope="session")
def h5check(opts):
    """Built h5check binary (tools/h5check), or the path given with --h5check."""
    if opts.h5check:
        return Path(opts.h5check)
    try:
        return h5.build_h5check()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"h5check unavailable: {e}")


@pytest.fixture(scope="session")
def outdir(opts):
    """Real-disk directory for file-writer tests (never tmpfs)."""
    try:
        return h5.check_outdir(opts.outdir)
    except RuntimeError as e:
        pytest.skip(str(e))


# ---- stress tier ------------------------------------------------------------------------------
@pytest.fixture(scope="session")
def stress_opts(request):
    return _stress_opts(request.config)


@pytest.fixture(scope="session")
def byte_budget(stress_opts):
    return stressrun.ByteBudget(stress_opts["max_bytes"])


@pytest.fixture(scope="session")
def stress_ready(camera, outdir, h5check, ioc_pid, ca, exp):
    """Everything a sustained run needs; also turns on pool statistics polling."""
    ca.put("cam1:PoolPollStats", 1)
    if ca.get_str("HDF1:NDArrayPort_RBV") != exp.NDARRAY_PORT:
        pytest.skip("HDF1 is not wired to the camera port")
    return True


@pytest.fixture(scope="session")
def stress_results(request, ca, ioc, opts, outdir, stress_opts):
    """Collects every RunRecord; writes JSON always and markdown with --record."""
    res = stressrun.Results(stressrun.session_meta(ca, ioc, opts, outdir, stress_opts))
    yield res
    date = res.meta["date"]
    res.write_json(RESULTS_DIR / f"stress-{date}.json")
    if stress_opts["record"]:
        perf = ours.MODULE_ROOT / "info/performance"
        stem = f"{date}-stress-{res.meta['driver']}-{res.meta['host']}"
        path = perf / f"{stem}.md"
        n = 2
        while path.exists():
            path = perf / f"{stem}-{n}.md"
            n += 1
        res.write_markdown(path)
        print(f"\nstress results recorded in {path}")
