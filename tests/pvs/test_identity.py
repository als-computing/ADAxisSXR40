"""Identity and constant readbacks: who is this camera, what geometry, which driver."""
import pytest

from helpers import expected as ours

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("camera")]


@pytest.mark.parametrize("rec,want", sorted(ours.IDENTITY.items()))
def test_identity_string(ca, rec, want):
    assert ca.get_str(f"cam1:{rec}") == want


def test_driver_version(ca, exp):
    assert ca.get_str("cam1:DriverVersion_RBV") == exp.DRIVER_VERSION


def test_adcore_version(ca, exp):
    assert ca.get_str("cam1:ADCoreVersion_RBV").startswith(exp.ADCORE_VERSION_PREFIX)


def test_max_size(ca, exp):
    assert ca.get_int("cam1:MaxSizeX_RBV") == exp.MAX_SIZE
    assert ca.get_int("cam1:MaxSizeY_RBV") == exp.MAX_SIZE


def test_data_type_and_color_mode(ca):
    assert ca.get_str("cam1:DataType_RBV") == "UInt16"
    assert ca.get_str("cam1:ColorMode_RBV") == "Mono"


def test_temperature_actual_plausible(ca, exp):
    m = ca.meta("cam1:TemperatureActual")
    lo, hi = exp.TEMP_RANGE_C
    assert lo <= float(m.value) <= hi, f"TemperatureActual={m.value} outside [{lo}, {hi}] C"
    assert m.units == "C"
    assert m.precision == exp.TEMP_ACTUAL_PREC


@pytest.mark.ours_only
def test_buff_total_is_ring_depth(ca, exp):
    assert ca.get_int("cam1:BuffTotal_RBV") == exp.BUFF_TOTAL
    assert 0 <= ca.get_int("cam1:BuffFrames_RBV") <= exp.BUFF_TOTAL


@pytest.mark.ours_only
def test_tec_enable_readable_never_written(ca):
    assert ca.get_int("cam1:TECEnable_RBV") in (0, 1)


def test_detector_idle_with_status_message(ca):
    assert ca.get_str("cam1:DetectorState_RBV") == "Idle"
    assert ca.get_str("cam1:StatusMessage_RBV").strip() != ""
