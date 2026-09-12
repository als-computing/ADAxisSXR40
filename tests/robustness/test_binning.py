"""Binning via TUIDC_RESOLUTION: the frame that arrives has the binned geometry."""
import pytest

from helpers import acquire

pytestmark = [pytest.mark.full, pytest.mark.usefixtures("camera", "restore_settings")]


@pytest.mark.parametrize("mode,size", [(1, 2048), (2, 1024), (0, 4096)])
def test_binning_mode_changes_frame_geometry(ca, mode, size):
    acquire.full_frame(ca)
    ca.put_and_wait_rbv("cam1:ArrayCallbacks", 1)
    ca.put_and_wait_rbv("cam1:AcquireTime", 0.02)
    ca.put_and_wait_rbv("cam1:BinMode", mode)
    acquire.acquire_single(ca)
    assert (ca.get_int("cam1:ArraySizeX_RBV"), ca.get_int("cam1:ArraySizeY_RBV")) == (size, size)
    assert ca.get_int("image1:ArraySize0_RBV") == size
    ca.put_and_wait_rbv("cam1:BinMode", 0)
    acquire.full_frame(ca)
