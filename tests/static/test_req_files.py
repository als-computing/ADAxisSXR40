"""autosave request files: every PV exists, nothing duplicated, nothing dangerous saved."""
import re
from pathlib import Path

import pytest

from helpers import expected as ours
from helpers import inventory

pytestmark = pytest.mark.smoke

REQ_SEARCH = [ours.MODULE_ROOT / "axisSXR40App/Db", inventory.adcore_dir() / "db",
              inventory.adcore_dir() / "iocBoot", Path("/usr/local/epics/support/autosave/db"),
              Path("/usr/local/epics/support/calc/calcApp/Db"), Path("/usr/local/epics/support/calc/db")]


def req_lines(path: Path):
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        yield line


requires_adcore = pytest.mark.skipif(not (inventory.adcore_dir() / "db").exists(),
                                     reason="ADCore not installed here (CI): include resolution needs its templates")


@requires_adcore
def test_settings_req_pvs_exist_in_templates():
    recs = inventory.load_cam_records()
    missing, names = [], []
    for line in req_lines(ours.SETTINGS_REQ):
        if line.startswith("file "):
            continue
        name = line.split()[0].replace("$(P)$(R)", "cam1:")
        names.append(name)
        if name not in recs:
            missing.append(name)
    assert not missing, f"axisSXR40_settings.req names PVs that no template defines: {missing}"


def test_settings_req_has_no_duplicates():
    names = [l.split()[0] for l in req_lines(ours.SETTINGS_REQ) if not l.startswith("file ")]
    dups = sorted({n for n in names if names.count(n) > 1})
    assert not dups, f"duplicate entries in axisSXR40_settings.req: {dups}"


def test_tec_enable_is_not_autosaved():
    text = "\n".join(req_lines(ours.SETTINGS_REQ)) + "\n".join(req_lines(ours.AUTO_SETTINGS_REQ))
    assert "TECEnable" not in text, "TECEnable must not be autosaved (see the HAZARD note in the template)"


@requires_adcore
def test_included_req_files_resolve():
    for path in (ours.SETTINGS_REQ, ours.AUTO_SETTINGS_REQ):
        for line in req_lines(path):
            if line.startswith("file "):
                fname = re.match(r'file\s+"([^"]+)"', line).group(1)
                assert any((d / fname).exists() for d in REQ_SEARCH), \
                    f"{path.name} includes {fname}, not found in {[str(d) for d in REQ_SEARCH]}"


def test_auto_settings_req_comments_have_no_macros():
    # autosave macro-expands comment lines too and logs "macLib: macro X is undefined"
    bad = [l for l in ours.AUTO_SETTINGS_REQ.read_text().splitlines() if l.lstrip().startswith("#") and "$(" in l]
    assert not bad, f"comment lines with $( ) in auto_settings.req: {bad}"


def test_no_stale_local_commonplugin_req():
    stale = ours.IOC_BOOT / "commonPlugin_settings.req"
    assert not stale.exists(), (f"{stale} shadows ADCore's current file via the './' request path and "
                                "silently drops newer plugins from autosave (2026-09-11 bug)")
