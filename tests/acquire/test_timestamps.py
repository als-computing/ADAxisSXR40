"""Frame timestamps and ids.

The driver stamps each NDArray (timeStamp, epicsTS, uniqueId) and the plugins publish
those on their own records (image1:TimeStamp_RBV ...). The camera record's own
cam1:TimeStamp_RBV / EpicsTSSec_RBV / UniqueId_RBV stay at 0: neither ADAxisSXR40 nor
ADTucsen calls setDoubleParam(NDTimeStamp) & co. after a frame. Documented below as an
expected failure so it is visible, not hidden.
"""
import time

import pytest

from helpers import acquire

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("camera", "restore_settings")]

POSIX_TO_EPICS_EPOCH = 631152000  # 1990-01-01


@pytest.fixture
def frames(ca):
    acquire.full_frame(ca)
    ca.put_and_wait_rbv("cam1:AcquireTime", 0.05)
    ca.put_and_wait_rbv("cam1:ArrayCallbacks", 1)
    ca.put_and_wait_rbv("image1:EnableCallbacks", 1)
    return acquire


def test_plugin_timestamps_advance_and_track_host_time(ca, frames):
    frames.acquire_single(ca)
    ts0 = float(ca.get("image1:TimeStamp_RBV"))
    frames.acquire_multiple(ca, 5)
    ts1 = float(ca.get("image1:TimeStamp_RBV"))
    assert ts1 > ts0, f"image1:TimeStamp did not advance: {ts0} -> {ts1}"
    sec = int(ca.get("image1:EpicsTSSec_RBV"))
    host = time.time() - POSIX_TO_EPICS_EPOCH
    assert abs(host - sec) < 5.0, f"EpicsTSSec {sec} vs host {host:.0f} (EPICS epoch)"


def test_unique_id_advances_per_frame(ca, frames):
    frames.acquire_single(ca)
    u0 = ca.get_int("image1:UniqueId_RBV")
    frames.acquire_multiple(ca, 3)
    u1 = ca.get_int("image1:UniqueId_RBV")
    assert u1 == u0 + 3, f"uniqueId {u0} -> {u1} over 3 frames"


@pytest.mark.xfail(strict=False, reason="driver does not publish NDTimeStamp/NDEpicsTS/NDUniqueId on cam1 "
                                        "(same in ADTucsen); plugins carry them. Known gap.")
def test_camera_record_timestamps_are_published(ca, frames):
    frames.acquire_single(ca)
    assert float(ca.get("cam1:TimeStamp_RBV")) > 0
    assert int(ca.get("cam1:EpicsTSSec_RBV")) > 0
