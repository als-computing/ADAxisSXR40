"""One TIFF frame through NDFileTIFF in Single mode."""
import os
from pathlib import Path

import pytest

from helpers import acquire

pytestmark = [pytest.mark.full, pytest.mark.usefixtures("camera", "restore_settings")]


def test_tiff_single_frame(ca, outdir):
    acquire.full_frame(ca)
    ca.put_and_wait_rbv("cam1:AcquireTime", 0.02)
    ca.put_and_wait_rbv("cam1:ArrayCallbacks", 1)
    ca.put_and_wait_rbv("TIFF1:EnableCallbacks", 1)
    ca.put_and_wait_rbv("TIFF1:FilePath", str(outdir) + "/")
    ca.put_and_wait_rbv("TIFF1:FileName", "tifftest")
    ca.put_and_wait_rbv("TIFF1:FileTemplate", "%s%s_%3.3d.tif")
    ca.put_and_wait_rbv("TIFF1:FileWriteMode", 0)        # Single
    ca.put_and_wait_rbv("TIFF1:AutoIncrement", 1)
    ca.put_and_wait_rbv("TIFF1:AutoSave", 1)
    before = ca.get_str("TIFF1:FullFileName_RBV")
    acquire.acquire_single(ca)
    name = ca.wait_for("TIFF1:FullFileName_RBV", lambda v: v and v != before, timeout=15, as_string=True)
    path = Path(str(name).rstrip("\x00"))
    try:
        assert path.exists(), path
        size = path.stat().st_size
        assert 4096 * 4096 * 2 <= size <= 4096 * 4096 * 2 + 64 * 1024, size
        assert ca.get_int("TIFF1:WriteStatus") == 0, ca.get_str("TIFF1:WriteMessage")
    finally:
        if path.exists():
            os.remove(path)
