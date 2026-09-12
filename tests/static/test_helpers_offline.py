"""The helpers themselves, exercised without an IOC."""
import pytest

from helpers import acquire, h5, ioclog
from helpers.ca import ReadbackTimeout

pytestmark = pytest.mark.smoke


class FakeCA:
    """Just enough of helpers.ca.CA for wait_idle(): a stuck or a healthy port thread."""

    def __init__(self, *, stuck: bool, state: str = "Idle", counter: int = 5):
        self.stuck, self.state, self.counter = stuck, state, counter
        self.puts = []

    def get_str(self, rel):
        assert rel == "cam1:DetectorState_RBV"
        return self.state

    def get_int(self, rel):
        return self.counter

    def put(self, rel, value, wait=True):
        self.puts.append((rel, value))
        if not self.stuck:
            self.counter = value

    def wait_for(self, rel, pred, timeout=1.0, poll=0.1, as_string=False):
        if pred(self.counter):
            return self.counter
        raise ReadbackTimeout(f"{rel} stuck at {self.counter}")


def test_wait_idle_detects_a_dead_port_thread():
    with pytest.raises(acquire.DeadlockSuspected):
        acquire.wait_idle(FakeCA(stuck=True), idle_timeout=0.1, probe_timeout=0.1)


def test_wait_idle_detects_acquire_that_never_stops():
    with pytest.raises(acquire.DeadlockSuspected):
        acquire.wait_idle(FakeCA(stuck=False, state="Acquire"), idle_timeout=0.6, probe_timeout=0.1)


def test_wait_idle_passes_and_probes_with_a_different_value():
    ca = FakeCA(stuck=False, counter=0)
    acquire.wait_idle(ca, idle_timeout=0.1, probe_timeout=0.1)
    assert ca.puts[0] == ("cam1:ArrayCounter", 1), "probe must differ from the current readback (0)"
    assert ca.puts[-1] == ("cam1:ArrayCounter", 0), "and be put back"


SAMPLE_LOG = (
    '\x1b[1mepicsEnvSet("PREFIX", "XV4040:")\x1b[0m\r\n'
    '@@@ The PID of new child "axissxr40" is: 100\r\n'
    "2026/09/10 15:45:52.695 axisSXR40:reportCapabilitySupport: capability audit: 11/15 capabilities, 8/12 properties supported by this camera\r\n"
    "@@@ The PID of new child \"axissxr40\" is: 224484\r\n"
    "2026/09/10 16:00:52.795 axisSXR40:reportCapabilitySupport: capability audit: 11/15 capabilities, 8/12 properties supported by this camera\r\n"
    "\x1b[32;1mepics> \x1b[0m2026/09/10 16:00:53 XV4040:cam1:HDRK devAsynFloat64::processCallbackOutput process write error \r\n"
    "2026/09/10 16:00:54 XV4040:cam1:GainMode devAsynInt32::processCallbackOutput process write error \r\n"
    "auto_settings.sav: 2373 of 2373 PV's connected\r\n"
)


def test_ioclog_slices_last_boot_and_strips_ansi(tmp_path):
    p = tmp_path / "x.log"
    p.write_bytes(SAMPLE_LOG.encode())
    lines = ioclog.read_clean(p)
    assert not any("\x1b" in l or "\r" in l for l in lines)
    sl, pid = ioclog.last_boot_slice(lines, "axissxr40")
    assert pid == 224484
    assert ioclog.capability_audit(sl) == [(11, 15, 8, 12)]
    assert ioclog.autosave_connected(sl) == [(2373, 2373)]
    assert ioclog.write_error_records(sl, "XV4040:") == {"HDRK", "GainMode"}
    assert ioclog.count(sl, "capability audit") == 1


SAMPLE_H5CHECK = """/x/perf4096_001.h5 rank=3 dims=[100 x 4096 x 4096] type=uint16 chunk=[1 x 4096 x 4096] filters=[32001]
  filter 32001: available
  first  frame     0: min=0 max=65280 mean=32640.0 zeros=0.39%
  middle frame    50: min=0 max=65280 mean=32640.0 zeros=0.39%
  last   frame    99: min=0 max=65280 mean=32640.0 zeros=0.39%
  UniqueId: n=100 first=1 last=100 span=100 missing=0 nonmonotonic=0
  TimeStamp (camera): span=11.467 s -> 8.6 fps over 100 frames; frame interval min=112.38 ms max=117.98 ms
  EpicsTS (host):     span=11.467 s -> 8.6 fps
  NDAttributes: ColorMode NDArrayEpicsTSSec NDArrayEpicsTSnSec NDArrayTimeStamp NDArrayUniqueId
  datasets: /entry/data/data /entry/instrument/detector/data /entry/instrument/performance/timestamp /entry/instrument/NDAttributes
"""


def test_h5check_parser():
    rep = h5.parse_h5check(SAMPLE_H5CHECK)
    assert rep.dims == (100, 4096, 4096) and rep.dtype == "uint16" and rep.chunk == (1, 4096, 4096)
    assert [f.index for f in rep.frames] == [0, 50, 99]
    assert (rep.uid_n, rep.uid_first, rep.uid_last, rep.uid_missing, rep.uid_nonmono) == (100, 1, 100, 0, 0)
    assert rep.camera_fps == 8.6 and rep.host_fps == 8.6
    assert (rep.interval_min_ms, rep.interval_max_ms) == (112.38, 117.98)
    assert rep.filters == (32001,) and rep.filters_unavailable == ()
    assert set(rep.attributes) == {"ColorMode", "NDArrayEpicsTSSec", "NDArrayEpicsTSnSec", "NDArrayTimeStamp", "NDArrayUniqueId"}
    assert "/entry/data/data" in rep.datasets and not rep.read_failed
    assert rep.ramp_present, "this sample IS the synthetic ramp"


def test_h5check_parser_flags_read_failures():
    rep = h5.parse_h5check(SAMPLE_H5CHECK.replace("  middle frame    50: min=0 max=65280 mean=32640.0 zeros=0.39%",
                                                  "  frame 50: READ FAILED"))
    assert rep.read_failed and len(rep.frames) == 2


def test_logdelta_flags_only_unallowed_errors(tmp_path):
    from helpers.logdelta import LogDelta
    p = tmp_path / "ioc.log"
    p.write_bytes(b"boot line\r\n")
    ld = LogDelta(p)
    with open(p, "ab") as f:
        f.write(b"2026/09/11 10:00:00 XV4040:cam1:HDRK devAsynFloat64::processCallbackOutput process write error \r\n")
        f.write(b"\x1b[1m# error mentioned in an echoed comment\x1b[0m\r\n")
        f.write(b"[OpenPhxCore]:Failed to open channel.\r\n")
    m = ld.mark()
    with ld.window(allow=[r"Error opening file"]):
        with open(p, "ab") as f:
            f.write(b"2026/09/11 10:00:01 NDPluginFile::openFileBase Error opening file /x/y.h5, status=3\r\n")
    with open(p, "ab") as f:
        f.write(b"2026/09/11 10:00:02 axisSXR40:grabImage: data size mismatch: calculated=1 reported=2\r\n")
    flagged, exempted = ld.summary()
    assert flagged == ["2026/09/11 10:00:02 axisSXR40:grabImage: data size mismatch: calculated=1 reported=2"]
    assert len(exempted) == 1 and "Error opening file" in exempted[0]
    assert ld.new_error_lines(since=m) == [exempted[0], flagged[0]]


def test_check_outdir_rejects_tmpfs(tmp_path):
    if h5.mount_fstype(tmp_path.resolve()) != "tmpfs":
        pytest.skip("pytest tmp_path is not on tmpfs here")
    with pytest.raises(RuntimeError, match="tmpfs"):
        h5.check_outdir(tmp_path)
