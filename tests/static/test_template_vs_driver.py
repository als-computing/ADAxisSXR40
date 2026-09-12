"""The template and the driver must agree, without an IOC.

The T_* -> AXIS_* rename once left 42 parameters inert because the template kept the
old drvInfo strings. These checks make that class of mistake fail at `pytest static`.
"""
import re

import pytest

from helpers import expected as ours
from helpers import inventory

pytestmark = pytest.mark.smoke

READBACK_ONLY = {"cam1:Bus_RBV", "cam1:ProductID_RBV", "cam1:TransferRate_RBV",
                 "cam1:BuffFrames_RBV", "cam1:BuffTotal_RBV"}
# DefectCorrection's menu skips value 2 (0 None, 1 Calculate, 3 Correction): inherited from
# ADTucsen and the control is unsupported on this camera anyway. Documented, not fixed.
KNOWN_ENUM_GAPS = {"cam1:DefectCorrection", "cam1:DefectCorrection_RBV"}


@pytest.fixture(scope="module")
def own():
    return inventory.own_records(ours.TEMPLATE)


@pytest.fixture(scope="module")
def driver_params():
    text = ours.DRIVER_SRC.read_text(errors="replace")
    defines = set(re.findall(r'#define\s+AxisSXR40\w+String\s+"(AXIS_\w+)"', text))
    created = set(re.findall(r"createParam\((AxisSXR40\w+String)", text))
    return defines, created, text


def test_every_template_drvinfo_has_a_driver_param(own, driver_params):
    defines, _, _ = driver_params
    used = {inventory.drvinfo(r) for r in own.values() if inventory.drvinfo(r)}
    used = {u for u in used if u.startswith("AXIS_")}
    missing = sorted(used - defines)
    assert not missing, f"template references drvInfo strings the driver never defines: {missing}"


def test_every_driver_param_is_reachable_from_the_template(own, driver_params):
    defines, _, _ = driver_params
    used = {inventory.drvinfo(r) for r in own.values() if inventory.drvinfo(r)}
    unused = sorted(defines - used)
    assert not unused, f"driver parameters with no record in the template: {unused}"


def test_every_define_is_created(driver_params):
    defines, created, text = driver_params
    names = set(re.findall(r'#define\s+(AxisSXR40\w+String)\s+"AXIS_\w+"', text))
    assert names == created, f"defined but never createParam'd: {sorted(names - created)}; " \
                             f"created without define: {sorted(created - names)}"


def test_every_rbv_has_a_setpoint(own):
    orphans = sorted(n for n in own if n.endswith("_RBV") and n[:-4] not in own and n not in READBACK_ONLY)
    assert not orphans, f"readbacks without a setpoint (add to READBACK_ONLY if intended): {orphans}"


def test_every_setpoint_has_a_readback(own):
    no_rbv = sorted(n for n, r in own.items()
                    if not n.endswith("_RBV") and r.rtyp in ("ao", "bo", "mbbo", "longout")
                    and n + "_RBV" not in own and n != "cam1:SoftwareTrigger")
    assert not no_rbv, f"setpoints without a readback: {no_rbv}"


def test_enum_values_are_contiguous(own):
    gaps = {}
    for n, r in own.items():
        if r.rtyp not in ("mbbo", "mbbi"):
            continue
        ev = inventory.enum_values(r)
        if not ev:
            continue  # dynamic enum filled by the driver at runtime
        indices = [idx for idx, _, _ in ev]
        values = [val for _, val, _ in ev if val is not None]
        if indices != list(range(len(indices))) or any(v != i for i, v in zip(indices, values)):
            gaps[n] = ev
    assert set(gaps) == KNOWN_ENUM_GAPS, f"unexpected enum value gaps: {gaps}"


def test_setpoint_and_rbv_enums_match(own):
    bad = []
    for sp, rbv in inventory.setpoint_rbv_pairs(own):
        a, b = inventory.enum_strings(own[sp]), inventory.enum_strings(own[rbv])
        if a != b:
            bad.append((sp, a, b))
    assert not bad, f"setpoint/readback enum strings differ: {bad}"


def test_frame_format_has_no_rgb888(own):
    assert inventory.enum_strings(own["cam1:FrameFormat"]) == ours.FRAME_FORMAT_ENUM


def test_extra_records_are_the_documented_five(own):
    theirs = inventory.own_records(ours.ADTUCSEN_TEMPLATE) if ours.ADTUCSEN_TEMPLATE.exists() else None
    if theirs is None:
        pytest.skip("ADTucsen template not present on this host")
    only_ours = {n.replace("cam1:", "") for n in set(own) - set(theirs)}
    assert only_ours == set(ours.TEMPLATE_ONLY_OURS)
