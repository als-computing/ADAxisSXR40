"""The same frame over Channel Access (image1:ArrayData) and pvAccess (Pva1:Image) is identical."""
import pytest

from helpers import acquire, pva

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("camera", "restore_settings")]

ROWS = 32


def test_ca_and_pva_carry_the_same_pixels_and_id(ca, opts):
    if not pva.available("pvget"):
        pytest.skip("pvget not available")
    acquire.set_geometry(ca, 0, 0, 4096, ROWS)
    ca.put_and_wait_rbv("cam1:AcquireTime", 0.02)
    ca.put_and_wait_rbv("cam1:ArrayCallbacks", 1)
    ca.put_and_wait_rbv("image1:EnableCallbacks", 1)
    ca.put_and_wait_rbv("Pva1:EnableCallbacks", 1)
    acquire.acquire_single(ca)
    n = 4096 * ROWS
    ca_pixels = ca.pv("image1:ArrayData").get(count=n, timeout=30, use_monitor=False)
    assert ca_pixels is not None and len(ca_pixels) == n
    name = f"{opts.prefix}Pva1:Image"
    assert pva.dimensions(name) == [4096, ROWS]
    pva_pixels = pva.value_array(name)
    assert len(pva_pixels) == n, f"PVA delivered {len(pva_pixels)} values"
    # CA publishes the 16-bit data as Int16 (st.cmd TYPE=Int16); PVA keeps it unsigned.
    ca_u16 = [int(v) & 0xFFFF for v in ca_pixels]
    pva_u16 = [int(v) & 0xFFFF for v in pva_pixels]
    assert ca_u16 == pva_u16, "pixel data differs between CA and PVA"
    assert pva.unique_id(name) == ca.get_int("image1:UniqueId_RBV")
