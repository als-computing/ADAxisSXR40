"""Stream 10 full frames to HDF5, then verify the file with an HDF5 library that is not the IOC's."""
import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from helpers import acquire, h5

pytestmark = [pytest.mark.full, pytest.mark.usefixtures("camera")]

N = 10


@dataclass
class Capture:
    captured: int
    dropped: int
    path: Path
    report: h5.H5Report


@pytest.fixture(scope="module")
def capture(ca, outdir, h5check, module_settings):
    acquire.full_frame(ca)
    ca.put_and_wait_rbv("cam1:AcquireTime", 0.02)
    ca.put_and_wait_rbv("cam1:ArrayCallbacks", 1)
    ca.put_and_wait_rbv("HDF1:EnableCallbacks", 1)
    ca.put_and_wait_rbv("HDF1:FilePath", str(outdir) + "/")
    assert ca.get_int("HDF1:FilePathExists_RBV") == 1, f"IOC cannot see {outdir}"
    ca.put_and_wait_rbv("HDF1:FileName", "fntest")
    ca.put_and_wait_rbv("HDF1:FileTemplate", "%s%s_%3.3d.h5")
    ca.put_and_wait_rbv("HDF1:FileWriteMode", 2)          # Stream
    ca.put_and_wait_rbv("HDF1:Compression", 0)
    ca.put_and_wait_rbv("HDF1:AutoIncrement", 1)
    ca.put_and_wait_rbv("HDF1:AutoSave", 0)
    ca.put_and_wait_rbv("HDF1:NumCapture", N)
    ca.put("HDF1:DroppedArrays", 0)
    acquire.prime_frame(ca, expect_y=4096)               # stream mode fixes geometry from the last array seen
    ca.put("HDF1:Capture", 1)
    ca.wait_for("HDF1:Capture_RBV", lambda v: int(v) == 1, timeout=10)
    acquire.acquire_multiple(ca, N)
    ca.wait_for("HDF1:Capture_RBV", lambda v: int(v) == 0, timeout=60)
    path = Path(ca.get_str("HDF1:FullFileName_RBV"))
    cap = Capture(ca.get_int("HDF1:NumCaptured_RBV"), ca.get_int("HDF1:DroppedArrays_RBV"), path,
                  h5.run_h5check(h5check, path) if path.exists() else h5.H5Report())
    yield cap
    ca.put("HDF1:Capture", 0)
    if path.exists():
        os.remove(path)


def test_capture_complete(capture):
    assert capture.captured == N
    assert capture.dropped == 0


def test_file_exists_with_the_right_size(capture):
    assert capture.path.exists(), capture.path
    size = capture.path.stat().st_size
    payload = N * 4096 * 4096 * 2
    assert payload <= size <= payload + 4 * 1024 * 1024, f"{size} bytes"


def test_h5check_structure(capture):
    r = capture.report
    assert r.dims == (N, 4096, 4096) and r.dtype == "uint16", r.raw
    assert r.uid_n == N and r.uid_missing == 0 and r.uid_nonmono == 0
    assert r.uid_last - r.uid_first == N - 1


def test_camera_fps_from_file_timestamps(capture, exp):
    lo, hi = exp.FULL_FRAME_FPS
    assert lo * 0.8 <= capture.report.camera_fps <= hi * 1.2, capture.report.camera_fps


@pytest.mark.hardware_state
@pytest.mark.xfail(strict=False, reason="camera emits a synthetic ramp (known-gaps TODO §8)")
def test_frames_are_dark_images(capture, exp):
    assert not capture.report.ramp_present, capture.report.frames
    assert all(f.mean < exp.DARK_FRAME_MEAN_MAX_ADU for f in capture.report.frames)


def test_frame_interval_jitter(capture):
    """Full frame (>= JITTER_STRICT_MIN_HEIGHT): no interval above twice the nominal period.
    Measured ratio 1.02 on this host; the SDK delivers in bursts only at small ROIs."""
    r = capture.report
    assert r.camera_fps and r.interval_max_ms is not None, r.raw
    nominal_ms = 1000.0 / r.camera_fps
    assert r.interval_max_ms < 2 * nominal_ms, (r.interval_min_ms, r.interval_max_ms, nominal_ms)
