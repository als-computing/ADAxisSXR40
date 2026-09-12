"""Our live IOC against the recorded ADTucsen baseline: only the intended differences."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compat_rules as rules  # noqa: E402

from helpers import compat, ioclog  # noqa: E402

pytestmark = [pytest.mark.full, pytest.mark.compat, pytest.mark.ours_only]

RESULTS = Path(__file__).resolve().parents[1] / ".results"


@pytest.fixture(scope="module")
def baseline(opts):
    if opts.baseline:
        return compat.load_baseline(Path(opts.baseline))
    files = sorted(Path(__file__).with_name("baselines").glob("adtucsen-*.json"))
    if not files:
        pytest.skip("no ADTucsen baseline: swap to ioc-xv4040 and run `tests/run.sh capture` (see tests/README.md)")
    return compat.load_baseline(files[-1])


@pytest.fixture(scope="module")
def report(ca, opts, ioc, baseline, record_testsuite_property):
    names = [n for n in compat.pvlist_names() if n.startswith(opts.prefix)]
    live = compat.capture_all(ca, names)
    rep = compat.compare(baseline, live, rules, opts.prefix)
    text = compat.format_report(rep, baseline["meta"], {"driver": ioc.driver, "pv_count": len(live)})
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "compat-report.txt").write_text(text)
    record_testsuite_property("compat_report", str(RESULTS / "compat-report.txt"))
    return rep, live


def test_baseline_is_adtucsen(baseline, opts):
    assert baseline["meta"]["driver"] == "adtucsen"
    assert baseline["meta"]["prefix"] == opts.prefix


def test_only_in_ours_is_exactly_the_intended_set(report, opts):
    rep, _ = report
    got = {f.name[len(opts.prefix):] for f in rep.by("only_in_live")}
    assert got == rules.ONLY_IN_OURS_OK, f"unexpected extra records on our IOC: {sorted(got - rules.ONLY_IN_OURS_OK)}; " \
                                          f"missing intended: {sorted(rules.ONLY_IN_OURS_OK - got)}"


def test_nothing_unexplained_exists_only_on_adtucsen(report):
    rep, _ = report
    bad = [f.name for f in rep.by("only_in_baseline", "FAIL")]
    assert not bad, f"PVs on ADTucsen missing from ours: {bad[:20]} ({len(bad)})"


@pytest.mark.parametrize("category", ["rtyp_mismatch", "type_mismatch", "count_mismatch",
                                      "enum_mismatch", "prec_egu_mismatch", "value_mismatch"])
def test_no_unintended_differences(report, category):
    rep, _ = report
    bad = rep.by(category, "FAIL")
    assert not bad, "\n".join(f"{f.name}: baseline={f.baseline!r} live={f.live!r}" for f in bad[:20])


def test_intended_enum_difference_is_present(report):
    """If FrameFormat ever matches his, RGB888 came back (or he removed it): re-check the docs."""
    rep, _ = report
    names = {f.name.split(":", 1)[1] for f in rep.by("enum_mismatch", "INTENDED")}
    assert names == set(rules.ENUM_DIFF_OK), names


def test_write_error_sets(report, baseline, boot_log, opts):
    theirs = set(baseline["meta"].get("write_error_records") or [])
    ours = ioclog.write_error_records(boot_log, opts.prefix)
    assert theirs == rules.WRITE_ERRORS_THEIRS, sorted(theirs)
    assert ours == rules.WRITE_ERRORS_OURS, sorted(ours)


def test_autosave_counts(baseline, boot_log):
    theirs = baseline["meta"].get("autosave_connected")
    assert theirs and theirs[0] == rules.AUTOSAVE_COUNT_THEIRS, theirs
    ours = ioclog.autosave_connected(boot_log)[-1]
    assert ours[0] == rules.AUTOSAVE_COUNT_OURS, ours
