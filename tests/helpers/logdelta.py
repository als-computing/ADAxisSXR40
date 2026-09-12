"""Watch the IOC console log for error lines that appear while tests run.

The boot slice is checked by boot/test_boot_log.py. This class covers everything after
that: `mark()` a byte offset, later ask for the lines written since, and classify them
with the error/allow patterns in policy.py. Tests that provoke errors on purpose wrap
themselves in `window(allow=[...])` so those lines are exempted in the session summary.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path

from . import ioclog, policy


class LogDelta:
    def __init__(self, path: Path, *, allow: list[str] = (), errors: list[str] = ()):
        self.path = Path(path)
        self.errors = [re.compile(p) for p in (errors or policy.LOG_ERROR_PATTERNS)]
        self.allow = [re.compile(p) for p in list(policy.LOG_ALLOW_PATTERNS) + list(allow)]
        self.start = self.mark()
        self.windows: list[tuple[int, int, list[re.Pattern]]] = []

    def mark(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    def new_lines(self, since: int | None = None) -> list[tuple[int, str]]:
        """(offset, cleaned line) for every line written after `since` (default: session start)."""
        since = self.start if since is None else since
        out = []
        try:
            with open(self.path, "rb") as f:
                f.seek(since)
                pos = since
                for raw in f:
                    line = ioclog.ANSI.sub("", raw.decode("utf-8", "replace")).rstrip("\r\n")
                    out.append((pos, line))
                    pos += len(raw)
        except OSError:
            pass
        return out

    def is_error(self, line: str, extra_allow: list[re.Pattern] = ()) -> bool:
        if not any(p.search(line) for p in self.errors):
            return False
        if any(p.search(line) for p in self.allow) or any(p.search(line) for p in extra_allow):
            return False
        return True

    def new_error_lines(self, since: int | None = None, allow_extra: list[str] = ()) -> list[str]:
        extra = [re.compile(p) for p in allow_extra]
        return [l for _, l in self.new_lines(since) if self.is_error(l, extra)]

    @contextmanager
    def window(self, allow: list[str]):
        """Lines written inside this block that match `allow` are exempt in summary()."""
        a = self.mark()
        try:
            yield
        finally:
            self.windows.append((a, self.mark(), [re.compile(p) for p in allow]))

    def summary(self) -> tuple[list[str], list[str]]:
        """(flagged, exempted) error lines since session start."""
        flagged, exempted = [], []
        for off, line in self.new_lines(self.start):
            if not self.is_error(line):
                continue
            in_window = any(a <= off < b and any(p.search(line) for p in pats) for a, b, pats in self.windows)
            (exempted if in_window else flagged).append(line)
        return flagged, exempted
