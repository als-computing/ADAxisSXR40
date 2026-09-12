"""Every record the templates declare: connects, has the declared type, enum strings, PREC/EGU.

The record list comes from parsing the serving driver's template (ours or ADTucsen's)
plus the ADBase/NDArrayBase files it includes, so it cannot go stale.
"""
import pytest

from helpers import inventory

pytestmark = pytest.mark.smoke

# Unsupported on this camera: readEnum() fails for the setpoint, which CA then exposes as a
# plain integer with no strings; the readback keeps its enum type but has no strings either.
# Same on both drivers (documented in Damon's README as the dead GainMode menu).
LONG_NOT_ENUM = {"cam1:GainMode"}
# ADBase pairs whose strings differ by design (bo "Acquire" vs bi "Acquiring"; ShutterMode).
ENUM_PAIRS_DIFFER_BY_DESIGN = {"cam1:Acquire", "cam1:ShutterMode"}


@pytest.fixture(scope="module")
def records(exp):
    return inventory.parse_template(exp.TEMPLATE)


@pytest.fixture(scope="module")
def metas(ca, records):
    names = sorted(records)
    ca.connect_many(names, timeout=10.0)
    return {n: ca.meta(n, read_value=False) for n in names}


def _strip(t):
    t = list(t)
    while t and t[-1] == "":
        t.pop()
    return tuple(t)


def test_every_template_record_connects(metas):
    missing = sorted(n for n, m in metas.items() if not m.connected)
    assert not missing, f"{len(missing)} template records do not exist on the IOC: {missing[:20]}"


def test_record_types_match_template(records, metas):
    bad = {n: (records[n].rtyp, m.rtyp) for n, m in metas.items()
           if m.connected and m.rtyp and m.rtyp != records[n].rtyp}
    assert not bad, f"RTYP differs from template: {bad}"


def test_ca_native_type_matches_record_class(records, metas):
    bad = {}
    for n, m in metas.items():
        if not m.connected:
            continue
        want = "long" if n in LONG_NOT_ENUM else inventory.expected_ca_type(records[n])
        if want and m.type != want:
            bad[n] = (want, m.type)
    assert not bad, f"CA type differs from record class: {bad}"


def test_setpoint_and_readback_enums_agree(records, metas, ca):
    bad = []
    for sp, rbv in inventory.setpoint_rbv_pairs(records):
        a, b = metas.get(sp), metas.get(rbv)
        if a and b and a.connected and b.connected and a.type == "enum" and b.type == "enum":
            if _strip(a.enum_strs) != _strip(b.enum_strs) and sp not in ENUM_PAIRS_DIFFER_BY_DESIGN:
                bad.append((sp, a.enum_strs, b.enum_strs))
    assert not bad, f"setpoint/readback enum strings differ on the IOC: {bad}"


def test_static_enum_strings_match_template(records, metas, exp):
    dynamic = {f"cam1:{k}{s}" for k in exp.DYNAMIC_ENUMS for s in ("", "_RBV")}
    bad = {}
    for n, r in records.items():
        m = metas[n]
        if not m.connected or n in dynamic or r.rtyp not in ("mbbo", "mbbi", "bo", "bi"):
            continue
        want = inventory.enum_strings(r)
        if want and _strip(m.enum_strs) != _strip(want):
            bad[n] = (want, m.enum_strs)
    assert not bad, f"enum strings differ from template: {bad}"


@pytest.mark.parametrize("base", sorted(["FrameSpeed", "BitDepth", "BinMode", "FanGear", "GainMode"]))
def test_dynamic_enum_strings(ca, exp, base):
    want = exp.DYNAMIC_ENUMS[base]
    for n in (f"cam1:{base}", f"cam1:{base}_RBV"):
        got = ca.enum_strs(n)
        if want is None:
            assert got, f"{n}: driver did not fill the enum"
        else:
            assert _strip(got) == want, f"{n}: {got} != {want}"
    if want == ():
        assert ca.meta(f"cam1:{base}", read_value=False).type == "long"


def test_prec_and_egu_match_template(records, metas):
    bad = {}
    for n, r in records.items():
        m = metas[n]
        if not m.connected or r.rtyp not in ("ai", "ao"):
            continue
        if "PREC" in r.fields and m.precision != int(r.fields["PREC"]):
            bad[n] = ("PREC", r.fields["PREC"], m.precision)
        if "EGU" in r.fields and m.units != r.fields["EGU"]:
            bad[n] = ("EGU", r.fields["EGU"], m.units)
    assert not bad, bad


def test_status_message_is_char_waveform(metas):
    m = metas["cam1:StatusMessage_RBV"]
    assert (m.type, m.count) == ("char", 256)


def test_readback_only_records_read(ca):
    for n in ("cam1:Bus_RBV", "cam1:ProductID_RBV", "cam1:TransferRate_RBV"):
        ca.get(n)
    assert ca.get_str("cam1:Bus_RBV") in ("USB3.0", "USB2.0")
