"""The way Bluesky's ophyd drives an areaDetector with the HDF5 plugin.

stage: file path/name/template, Stream mode, callbacks on, a warm-up frame, Capture on.
trigger: N frames in Multiple mode, wait Idle.  unstage: Capture off, file closed.
Two variants: one file for the whole scan (NumCapture 0 = until unstaged), and one file
per point (NumCapture = frames per point, Capture before each trigger).
"""
import os
from pathlib import Path

import pytest

from helpers import acquire, h5

pytestmark = [pytest.mark.full, pytest.mark.usefixtures("camera", "restore_settings")]

POINTS = 5
FRAMES_PER_POINT = 3


def _stage(ca, outdir, name, num_capture):
    acquire.full_frame(ca)
    ca.put_and_wait_rbv("cam1:AcquireTime", 0.02)
    ca.put_and_wait_rbv("cam1:ArrayCallbacks", 1)
    ca.put_and_wait_rbv("HDF1:EnableCallbacks", 1)
    ca.put_and_wait_rbv("HDF1:FilePath", str(outdir) + "/")
    assert ca.get_int("HDF1:FilePathExists_RBV") == 1
    ca.put_and_wait_rbv("HDF1:FileName", name)
    ca.put_and_wait_rbv("HDF1:FileTemplate", "%s%s_%3.3d.h5")
    ca.put_and_wait_rbv("HDF1:FileWriteMode", 2)
    ca.put_and_wait_rbv("HDF1:Compression", 0)
    ca.put_and_wait_rbv("HDF1:AutoIncrement", 1)
    ca.put_and_wait_rbv("HDF1:AutoSave", 0)
    ca.put_and_wait_rbv("HDF1:FileNumber", 0)
    ca.put_and_wait_rbv("HDF1:NumCapture", num_capture)
    ca.put("HDF1:DroppedArrays", 0)
    acquire.prime_frame(ca, expect_y=4096)             # ophyd's warmup(): a frame before capture


def _trigger(ca, n):
    acquire.acquire_multiple(ca, n)
    return ca.get_int("image1:UniqueId_RBV")


def test_one_file_for_the_whole_scan(ca, outdir, h5check):
    _stage(ca, outdir, "scanA", num_capture=0)
    ca.put("HDF1:Capture", 1)
    ca.wait_for("HDF1:Capture_RBV", lambda v: int(v) == 1, timeout=10)
    uids = [_trigger(ca, FRAMES_PER_POINT) for _ in range(POINTS)]
    ca.put("HDF1:Capture", 0)                            # unstage
    ca.wait_for("HDF1:Capture_RBV", lambda v: int(v) == 0, timeout=30)
    path = Path(ca.get_str("HDF1:FullFileName_RBV"))
    try:
        assert ca.get_int("HDF1:NumCaptured_RBV") == POINTS * FRAMES_PER_POINT
        assert ca.get_int("HDF1:DroppedArrays_RBV") == 0
        assert path.exists(), path
        rep = h5.run_h5check(h5check, path)
        assert rep.dims == (POINTS * FRAMES_PER_POINT, 4096, 4096)
        assert rep.uid_n == POINTS * FRAMES_PER_POINT and rep.uid_missing == 0 and rep.uid_nonmono == 0
        assert rep.uid_last == uids[-1], "last uniqueId in the file is the last frame triggered"
        assert uids == sorted(uids) and len(set(uids)) == POINTS
    finally:
        if path.exists():
            os.remove(path)


def test_one_file_per_point(ca, outdir, h5check):
    _stage(ca, outdir, "scanB", num_capture=FRAMES_PER_POINT)
    files = []
    try:
        for i in range(POINTS):
            ca.put("HDF1:Capture", 1)
            ca.wait_for("HDF1:Capture_RBV", lambda v: int(v) == 1, timeout=10)
            _trigger(ca, FRAMES_PER_POINT)
            ca.wait_for("HDF1:Capture_RBV", lambda v: int(v) == 0, timeout=30)   # auto-closes at NumCapture
            assert ca.get_int("HDF1:FileNumber_RBV") == i + 1
            files.append(Path(ca.get_str("HDF1:FullFileName_RBV")))
        assert len(set(files)) == POINTS and all(f.name == f"scanB_{i:03d}.h5" for i, f in enumerate(files))
        last_uid = None
        for f in files:
            rep = h5.run_h5check(h5check, f)
            assert rep.dims == (FRAMES_PER_POINT, 4096, 4096), f
            assert rep.uid_missing == 0 and rep.uid_nonmono == 0, f
            if last_uid is not None:
                assert rep.uid_first > last_uid, "unique ids must increase across the point files"
            last_uid = rep.uid_last
    finally:
        ca.put("HDF1:Capture", 0)
        for f in files:
            if f.exists():
                os.remove(f)
