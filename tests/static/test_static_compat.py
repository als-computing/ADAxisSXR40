"""Template-level comparison with ADTucsen: the differences must be exactly the intended ones."""
import re

import pytest

from helpers import expected as ours
from helpers import inventory

pytestmark = pytest.mark.smoke

# Field-level differences we intend between records both templates define.
INTENDED_FIELD_DIFFS = {
    "cam1:FrameFormat": {"TWST", "TWVL"},        # ours removes RGB888
    "cam1:FrameFormat_RBV": {"TWST", "TWVL"},
}


@pytest.fixture(scope="module")
def both():
    if not ours.ADTUCSEN_TEMPLATE.exists():
        pytest.skip("ADTucsen template not present on this host")
    return inventory.own_records(ours.TEMPLATE), inventory.own_records(ours.ADTUCSEN_TEMPLATE)


def _norm(fields: dict) -> dict:
    # drvInfo prefixes differ by design (AXIS_ vs T_); everything else must match
    return {k: re.sub(r"\)\s*T_", ")AXIS_", v) for k, v in fields.items()}


def test_only_in_ours_is_the_documented_set(both):
    o, t = both
    assert {n.replace("cam1:", "") for n in set(o) - set(t)} == set(ours.TEMPLATE_ONLY_OURS)


def test_nothing_exists_only_in_adtucsen(both):
    o, t = both
    assert set(t) - set(o) == set()


def test_common_records_have_same_type(both):
    o, t = both
    bad = {n: (o[n].rtyp, t[n].rtyp) for n in set(o) & set(t) if o[n].rtyp != t[n].rtyp}
    assert not bad


def test_field_differences_are_exactly_the_intended_ones(both):
    o, t = both
    diffs = {}
    for n in sorted(set(o) & set(t)):
        a, b = _norm(o[n].fields), _norm(t[n].fields)
        d = {k for k in set(a) | set(b) if a.get(k) != b.get(k)}
        if d:
            diffs[n] = d
    assert diffs == INTENDED_FIELD_DIFFS, f"unexpected template differences vs ADTucsen: {diffs}"


def test_adtucsen_frame_format_still_has_rgb888(both):
    """If upstream ever drops RGB888 too, this difference stops being 'ours' and the docs change."""
    _, t = both
    assert inventory.enum_strings(t["cam1:FrameFormat"]) == ("Raw", "Usual", "RGB888")
