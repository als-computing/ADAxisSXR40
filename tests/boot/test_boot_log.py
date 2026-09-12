"""Boot health from the console log of the IOC that is serving (ours or Damon's).

Reads only the slice since the last procServ child start. Expectations come from the
detected driver's module, so the same tests run against ioc-xv4040.
"""
import re

import pytest

from helpers import ioclog

pytestmark = pytest.mark.smoke


def test_log_slice_is_the_running_boot(ioc, boot_log):
    assert ioc.log_is_current, f"log boot pid {ioc.boot_pid} != running pid {ioc.st_cmd_pid}"
    assert ioclog.count(boot_log, ioclog.RE_IOCINIT_DONE.pattern) == 1


def test_capability_audit_line(boot_log, exp):
    audits = ioclog.capability_audit(boot_log)
    if exp.HAS_CAPABILITY_AUDIT:
        assert audits == [exp.CAPABILITY_AUDIT], f"audit lines: {audits}"
    else:
        assert audits == [], "ADTucsen has no capability audit"


def test_autosave_connected_everything(boot_log, exp):
    got = ioclog.autosave_connected(boot_log)
    assert len(got) == 1, f"expected one autosave summary line, got {got}"
    n, m = got[0]
    assert n == m, f"autosave connected only {n} of {m} PVs"
    assert n == exp.AUTOSAVE_PV_COUNT, (f"autosave connected {n} PVs, expected {exp.AUTOSAVE_PV_COUNT} "
                                        f"(update AUTOSAVE_PV_COUNT in {exp.__name__} only after explaining the change)")


def test_write_errors_are_exactly_the_unsupported_controls(boot_log, exp, opts):
    got = ioclog.write_error_records(boot_log, opts.prefix)
    want = set(exp.WRITE_ERROR_RECORDS)
    assert got == want, f"unexpected: {sorted(got - want)}; missing: {sorted(want - got)}"


@pytest.mark.parametrize("pattern,why", [
    (r"dbFindRecord for .* failed", "autosave restoring PVs that do not exist (stale prefix in the .sav?)"),
    (r"readReqFile: unable to open", "a request file is missing from the search path"),
    (r"macLib: macro .* is undefined", "a $( ) macro in a request-file comment"),
    (r"cannot find parameter", "template drvInfo without a driver parameter"),
    (r"init_record Error", "record init failed"),
    (r"AXIS_NO_TEMP_POLL is set", "the diagnostic env var leaked into production"),
])
def test_no_startup_warnings(boot_log, pattern, why):
    hits = [l for l in messages(boot_log) if re.search(pattern, l)]
    assert not hits, f"{why}: {hits[:5]} ({len(hits)} total)"


def test_no_crash_signatures(boot_log, exp):
    hits = [l for l in messages(boot_log) if re.search(exp.CRASH_SIGNATURES, l)]
    assert not hits, hits[:5]


def messages(lines):
    """Drop iocsh's echo of st.cmd comment lines: they quote the very warnings we grep for."""
    return [l for l in lines if not l.lstrip().startswith("#")]
