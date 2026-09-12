"""The plugin chain: loaded, wired to the driver port, enabled at boot, delivering."""
import pytest

from helpers import acquire, pva
from helpers import expected as ours

pytestmark = pytest.mark.smoke


def test_callbacks_enabled_at_boot(ca, exp):
    assert ca.get_int("cam1:ArrayCallbacks_RBV") == 1
    off = [p for p in exp.PLUGINS_FORCED_ON if ca.get_int(f"{p}EnableCallbacks_RBV") != 1]
    assert not off, f"plugins st.cmd should have enabled: {off}"


@pytest.mark.parametrize("plugin", sorted(ours.PLUGINS_LOADED))
def test_plugin_loaded_and_wired(ca, exp, plugin):
    assert ca.get_str(f"{plugin}PluginType_RBV"), f"{plugin} has no PluginType"
    port = ca.get_str(f"{plugin}NDArrayPort_RBV")
    assert port, f"{plugin} has no NDArrayPort"


@pytest.mark.parametrize("plugin", ["image1:", "Pva1:", "HDF1:", "TIFF1:", "Stats1:", "CB1:", "Codec1:"])
def test_first_stage_plugins_listen_to_the_camera_port(ca, exp, plugin):
    assert ca.get_str(f"{plugin}NDArrayPort_RBV") == exp.NDARRAY_PORT


def test_image1_array_size(ca, exp):
    m = ca.meta("image1:ArrayData", read_value=False)
    assert m.count == exp.NELM_IMAGE1
    assert m.type == "short"


def test_file_template_defaults(ca, exp):
    if not exp.FILE_TEMPLATES:
        pytest.skip("this IOC sets no FileTemplate defaults in st.cmd")
    for plugin, tmpl in exp.FILE_TEMPLATES.items():
        assert ca.get_str(f"{plugin}FileTemplate_RBV") == tmpl


def test_pool_cap_is_in_force(ca, exp, restore_settings):
    ca.put("cam1:PoolPollStats", 1)
    ca.put("cam1:PoolMaxMem.PROC", 1)
    got = ca.wait_for("cam1:PoolMaxMem", lambda v: float(v) > 0, timeout=5.0)
    assert abs(float(got) - exp.POOL_MAX_MB) <= exp.POOL_MAX_TOL_MB, f"PoolMaxMem={got} MB"


@pytest.mark.usefixtures("camera", "restore_settings")
def test_pva_image_type_and_dimensions(ca, opts):
    if not pva.available("pvget") or not pva.available("pvinfo"):
        pytest.skip("pvget/pvinfo not available")
    name = f"{opts.prefix}Pva1:Image"
    assert ca.get_str("Pva1:PvName_RBV") == name
    assert pva.pvinfo_type(name) == "epics:nt/NTNDArray:1.0"
    acquire.full_frame(ca)
    ca.put_and_wait_rbv("Pva1:EnableCallbacks", 1)
    ca.put_and_wait_rbv("cam1:ArrayCallbacks", 1)
    acquire.acquire_single(ca)
    assert pva.dimensions(name) == [4096, 4096]
    assert pva.unique_id(name) == ca.get_int("cam1:UniqueId_RBV")


@pytest.mark.usefixtures("camera", "restore_settings")
def test_stats1_receives_frames(ca):
    ca.put_and_wait_rbv("Stats1:EnableCallbacks", 1)
    c0 = ca.get_int("Stats1:ArrayCounter_RBV")
    acquire.acquire_single(ca)
    ca.wait_for("Stats1:ArrayCounter_RBV", lambda v: int(v) == c0 + 1, timeout=5.0)
