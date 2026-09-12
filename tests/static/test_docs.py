"""Documentation hygiene: links resolve, the index lists every folder."""
import re
from pathlib import Path

import pytest

from helpers import expected as ours

pytestmark = pytest.mark.smoke

RE_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
SKIP_PREFIXES = ("http://", "https://", "mailto:", "#")


def md_files():
    files = [ours.MODULE_ROOT / "README.md", ours.MODULE_ROOT / "RELEASE.md"]
    files += sorted((ours.MODULE_ROOT / "info").rglob("*.md"))
    files += sorted((ours.MODULE_ROOT / "tests").rglob("*.md"))
    files += sorted((ours.MODULE_ROOT / "tools").rglob("*.md"))
    return [f for f in files if f.exists()]


@pytest.mark.parametrize("md", md_files(), ids=lambda p: str(p.relative_to(ours.MODULE_ROOT)))
def test_relative_links_resolve(md):
    text = md.read_text(errors="replace")
    broken = []
    for target in RE_LINK.findall(text):
        if target.startswith(SKIP_PREFIXES):
            continue
        path = target.split("#", 1)[0]
        if not path:
            continue
        if not (md.parent / path).exists():
            broken.append(target)
    assert not broken, f"broken links in {md.name}: {broken}"


def test_info_index_lists_every_folder():
    index = (ours.MODULE_ROOT / "info/README.md").read_text()
    folders = sorted(p.name for p in (ours.MODULE_ROOT / "info").iterdir() if p.is_dir())
    missing = [f for f in folders if f"{f}/" not in index]
    assert not missing, f"info/README.md does not mention: {missing}"
    assert "tests/" in index, "info/README.md should point at the test suite"


def test_module_readme_mentions_tests():
    text = (ours.MODULE_ROOT / "README.md").read_text()
    assert "tests/run.sh" in text
