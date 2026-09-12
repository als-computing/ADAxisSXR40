"""The file writers' error paths: a bad path or template must fail loudly and leave acquisition alone.

NDPluginFile semantics (ADCore R3-14): Capture=1 in Stream mode opens the file at once; on
failure Capture resets to 0, WriteStatus=1 and WriteMessage reads "Error opening file
<name>, status=N" (or "Error creating full file name"). FilePathExists_RBV only tests that
the directory exists, so an unwritable directory reads 1 and fails at open.
"""
import os
import time

import pytest

from helpers import acquire

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("camera", "restore_settings")]

# Everything the plugin and the HDF5 library print when a file cannot be opened on purpose.
ALLOW = [r"(?i)openFileBase|Error opening file|error creating full file name",
         r"HDF5-DIAG|^\s*#\d{3}:|^\s*(major|minor):",
         r"NDFileHDF5::openFile ERROR|Failed to create a new output file|NDFileTIFF:openFile error opening file"]


@pytest.fixture
def hdf(ca, outdir):
    acquire.full_frame(ca)
    ca.put_and_wait_rbv("cam1:AcquireTime", 0.02)
    ca.put_and_wait_rbv("cam1:ArrayCallbacks", 1)
    ca.put_and_wait_rbv("HDF1:EnableCallbacks", 1)
    ca.put_and_wait_rbv("HDF1:FileWriteMode", 2)
    ca.put_and_wait_rbv("HDF1:NumCapture", 5)
    ca.put_and_wait_rbv("HDF1:AutoSave", 0)
    ca.put_and_wait_rbv("HDF1:FileName", "errpath")
    ca.put_and_wait_rbv("HDF1:FileTemplate", "%s%s_%3.3d.h5")
    acquire.prime_frame(ca, expect_y=4096)
    return outdir


def _capture_is_refused(ca):
    ca.put("HDF1:Capture", 1)
    time.sleep(2.0)
    assert ca.get_int("HDF1:Capture_RBV") == 0, "Capture was accepted with an unusable file path"
    assert ca.get_int("HDF1:WriteStatus") == 1, "WriteStatus did not flag the error"
    msg = ca.get_str("HDF1:WriteMessage")
    assert msg.strip(), "WriteMessage is empty: the operator would have no clue"
    return msg


def _acquisition_unaffected(ca):
    c0 = ca.get_int("cam1:ArrayCounter_RBV")
    acquire.acquire_single(ca)
    assert ca.get_int("cam1:ArrayCounter_RBV") == c0 + 1
    assert ca.get_str("cam1:DetectorState_RBV") == "Idle"


def test_nonexistent_file_path(ca, hdf, log_delta):
    bad = hdf / f"does-not-exist-{os.getpid()}"
    with (log_delta.window(ALLOW) if log_delta else _null()):
        ca.put_and_wait_rbv("HDF1:FilePath", str(bad) + "/")
        assert ca.get_int("HDF1:FilePathExists_RBV") == 0
        msg = _capture_is_refused(ca)
        assert "rror" in msg, msg
        _acquisition_unaffected(ca)


def test_unwritable_directory(ca, hdf, log_delta, ioc_pid):
    if os.geteuid() == 0:
        pytest.skip("running as root: every directory is writable")
    with open(f"/proc/{ioc_pid}/status") as f:
        uid = next(int(l.split()[1]) for l in f if l.startswith("Uid:"))
    if uid != os.geteuid():
        pytest.skip("IOC runs as another user; directory permissions differ")
    ro = hdf / f"ro-{os.getpid()}"
    ro.mkdir(exist_ok=True)
    ro.chmod(0o555)
    try:
        with (log_delta.window(ALLOW) if log_delta else _null()):
            ca.put_and_wait_rbv("HDF1:FilePath", str(ro) + "/")
            assert ca.get_int("HDF1:FilePathExists_RBV") == 1, "existence check passes; the open must fail"
            msg = _capture_is_refused(ca)
            assert "Error opening file" in msg and ro.name in msg, msg
            _acquisition_unaffected(ca)
    finally:
        ro.chmod(0o755)
        ro.rmdir()


def test_empty_file_template(ca, hdf, log_delta):
    with (log_delta.window(ALLOW) if log_delta else _null()):
        ca.put_and_wait_rbv("HDF1:FilePath", str(hdf) + "/")
        ca.put("HDF1:FileTemplate", "")
        time.sleep(0.5)
        msg = _capture_is_refused(ca)
        assert "rror" in msg, msg
        assert ca.get_str("HDF1:FullFileName_RBV").strip() == ""
        _acquisition_unaffected(ca)


def test_tiff_single_with_bad_path(ca, outdir, log_delta):
    acquire.full_frame(ca)
    ca.put_and_wait_rbv("cam1:AcquireTime", 0.02)
    ca.put_and_wait_rbv("cam1:ArrayCallbacks", 1)
    with (log_delta.window(ALLOW) if log_delta else _null()):
        ca.put_and_wait_rbv("TIFF1:EnableCallbacks", 1)
        ca.put_and_wait_rbv("TIFF1:FilePath", str(outdir / f"nope-{os.getpid()}") + "/")
        ca.put_and_wait_rbv("TIFF1:FileName", "errpath")
        ca.put_and_wait_rbv("TIFF1:FileTemplate", "%s%s_%3.3d.tif")
        ca.put_and_wait_rbv("TIFF1:FileWriteMode", 0)
        ca.put_and_wait_rbv("TIFF1:AutoSave", 1)
        c0 = ca.get_int("cam1:ArrayCounter_RBV")
        acquire.acquire_single(ca)
        ca.wait_for("TIFF1:WriteStatus", lambda v: int(v) == 1, timeout=10)
        assert ca.get_str("TIFF1:WriteMessage").strip()
        assert ca.get_int("cam1:ArrayCounter_RBV") == c0 + 1
        assert ca.get_str("cam1:DetectorState_RBV") == "Idle"


class _null:
    def __enter__(self):
        return None

    def __exit__(self, *a):
        return False
