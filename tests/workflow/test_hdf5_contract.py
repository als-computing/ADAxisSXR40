"""What downstream analysis may rely on finding in a file this IOC writes.

Dataset paths and the NDAttributes set are asserted exactly, so an added or renamed
attribute is a deliberate edit of helpers/expected.py, not a silent change.
"""
import os
from pathlib import Path

import pytest

from helpers import acquire, h5

pytestmark = [pytest.mark.full, pytest.mark.usefixtures("camera")]

ROWS = 256
N = 20


@pytest.fixture(scope="module")
def report(ca, outdir, h5check, module_settings):
    acquire.set_geometry(ca, 0, 0, 4096, ROWS)
    ca.put_and_wait_rbv("cam1:AcquireTime", 0.02)
    ca.put_and_wait_rbv("cam1:ArrayCallbacks", 1)
    ca.put_and_wait_rbv("HDF1:EnableCallbacks", 1)
    ca.put_and_wait_rbv("HDF1:FilePath", str(outdir) + "/")
    ca.put_and_wait_rbv("HDF1:FileName", "contract")
    ca.put_and_wait_rbv("HDF1:FileTemplate", "%s%s_%3.3d.h5")
    ca.put_and_wait_rbv("HDF1:FileWriteMode", 2)
    ca.put_and_wait_rbv("HDF1:Compression", 0)
    ca.put_and_wait_rbv("HDF1:AutoIncrement", 1)
    ca.put_and_wait_rbv("HDF1:AutoSave", 0)
    ca.put_and_wait_rbv("HDF1:StoreAttr", 1)
    ca.put_and_wait_rbv("HDF1:StorePerform", 1)
    ca.put_and_wait_rbv("HDF1:NumCapture", N)
    acquire.prime_frame(ca, expect_y=ROWS)
    ca.put("HDF1:Capture", 1)
    ca.wait_for("HDF1:Capture_RBV", lambda v: int(v) == 1, timeout=10)
    acquire.acquire_multiple(ca, N)
    ca.wait_for("HDF1:Capture_RBV", lambda v: int(v) == 0, timeout=60)
    path = Path(ca.get_str("HDF1:FullFileName_RBV"))
    try:
        yield h5.run_h5check(h5check, path, list_attrs=True)
    finally:
        if path.exists():
            os.remove(path)


def test_dataset_paths(report, exp):
    for ds in exp.EXPECTED_DATASETS:
        assert ds in report.datasets, f"{ds} missing; datasets present: {report.datasets}"


def test_ndattributes_set(report, exp):
    assert set(report.attributes) == set(exp.EXPECTED_NDATTRIBUTES), \
        f"NDAttributes changed: present {sorted(report.attributes)}, expected {sorted(exp.EXPECTED_NDATTRIBUTES)}"


def test_layout(report):
    assert report.dims == (N, ROWS, 4096)
    assert report.dtype == "uint16"
    assert report.chunk == (1, ROWS, 4096)
    assert report.filters == ()
    assert report.uid_missing == 0
