"""10 s of full-frame continuous acquisition with the live plugins on: nothing dropped."""
import time

import pytest

from helpers import acquire

pytestmark = [pytest.mark.full, pytest.mark.usefixtures("camera", "restore_settings")]

PLUGINS = ("image1:", "Pva1:", "Stats1:")


def test_no_drops_at_full_rate(ca, exp):
    acquire.full_frame(ca)
    ca.put_and_wait_rbv("cam1:AcquireTime", 0.02)
    ca.put_and_wait_rbv("cam1:ArrayCallbacks", 1)
    for p in PLUGINS:
        ca.put_and_wait_rbv(f"{p}EnableCallbacks", 1)
        ca.put(f"{p}DroppedArrays", 0)
    ca.put_and_wait_rbv("cam1:ImageMode", 2)
    c0 = ca.get_int("cam1:ArrayCounter_RBV")
    ca.put("cam1:Acquire", 1, wait=False)
    time.sleep(8.0)
    rate = float(ca.get("cam1:ArrayRate_RBV"))
    time.sleep(2.0)
    c1 = ca.get_int("cam1:ArrayCounter_RBV")
    acquire.stop(ca)
    lo, hi = exp.FULL_FRAME_FPS
    assert lo <= rate <= hi, f"ArrayRate_RBV {rate} fps during full-frame continuous"
    assert c1 - c0 >= int(lo * 9), f"only {c1 - c0} frames in ~10 s"
    dropped = {p: ca.get_int(f"{p}DroppedArrays_RBV") for p in PLUGINS}
    assert not any(dropped.values()), f"dropped arrays: {dropped}"
    ca.wait_for("cam1:NumQueuedArrays", lambda v: int(v) == 0, timeout=10.0)
