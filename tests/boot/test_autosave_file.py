"""The autosave save file of the running IOC: complete, deduplicated, covering every plugin."""
import os
import time

import pytest

pytestmark = pytest.mark.smoke


@pytest.fixture(scope="module")
def sav(exp, opts):
    path = exp.AUTOSAVE_SAV
    if not path.exists():
        pytest.skip(f"{path} does not exist")
    lines = path.read_text(errors="replace").splitlines()
    names = [l.split()[0] for l in lines if l.startswith(opts.prefix)]
    return path, lines, names


def test_file_is_complete(sav):
    path, lines, _ = sav
    non_empty = [l for l in lines if l.strip()]
    assert non_empty[-1].strip() == "<END>", f"{path} is truncated"
    assert non_empty[0].startswith("# save/restore") or non_empty[0].startswith("#"), non_empty[0]


def test_pv_count_matches_the_log_constant(sav, exp):
    _, _, names = sav
    assert len(names) == exp.AUTOSAVE_PV_COUNT


@pytest.mark.ours_only
def test_no_duplicate_pv_names(sav):
    _, _, names = sav
    dups = sorted({n for n in names if names.count(n) > 1})
    assert not dups, f"duplicates in the save file: {dups}"


def test_every_saved_name_has_the_ioc_prefix(sav, opts):
    _, lines, _ = sav
    foreign = [l for l in lines if l.strip() and not l.startswith(("#", "<END>", opts.prefix))]
    assert not foreign, f"lines with another prefix (stale save file?): {foreign[:5]}"


def test_plugin_settings_are_saved(sav, exp, opts):
    _, _, names = sav
    short = []
    for pfx, minimum in exp.AUTOSAVE_REQUIRED_PREFIXES.items():
        n = sum(1 for x in names if x.startswith(opts.prefix + pfx))
        if n < minimum:
            short.append(f"{pfx} {n} < {minimum}")
    assert not short, ("plugin settings missing from autosave (stale commonPlugin_settings.req?): "
                       + ", ".join(short))


def test_save_file_is_being_rewritten(sav, ioc):
    path, _, _ = sav
    newest = max(os.path.getmtime(p) for p in path.parent.glob("auto_settings.sav*") if p.is_file())
    age = time.time() - newest
    if ioc.st_cmd_pid:
        try:
            with open(f"/proc/{ioc.st_cmd_pid}/stat") as f:
                start_ticks = int(f.read().split()[21])
            uptime = float(open("/proc/uptime").read().split()[0])
            proc_age = uptime - start_ticks / os.sysconf("SC_CLK_TCK")
            if proc_age < 600:
                pytest.skip(f"IOC up only {proc_age:.0f}s; autosave may not have written yet")
        except OSError:
            pass
    assert age < 600, f"newest autosave file is {age:.0f}s old; autosave is not saving"
