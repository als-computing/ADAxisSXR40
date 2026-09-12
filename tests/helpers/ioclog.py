"""Reading the IOC console log (procServ output).

Both IOC logs are CRLF with ANSI colour codes. Each (re)start is delimited by the
procServ banner `@@@ The PID of new child "<name>" is: <pid>`. Our capability-audit
line is printed BEFORE `Starting iocInit`, so a boot slice must begin at that banner.
"""
from __future__ import annotations

import re
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-9;]*m")
RE_AUDIT = re.compile(r"reportCapabilitySupport: capability audit: (\d+)/(\d+) capabilities, (\d+)/(\d+) properties")
RE_AUTOSAVE = re.compile(r"auto_settings\.sav: (\d+) of (\d+) PV's connected")
RE_IOCINIT_DONE = re.compile(r"iocRun: All initialization complete")


def read_clean(path: str | Path) -> list[str]:
    with open(path, encoding="utf-8", errors="replace") as f:
        return [ANSI.sub("", line).rstrip("\r\n") for line in f]


def last_boot_slice(lines: list[str], child: str) -> tuple[list[str], int | None]:
    """Lines from the most recent procServ child start onward, and that child's PID."""
    marker = f'@@@ The PID of new child "{child}" is: '
    idx, pid = None, None
    for i, line in enumerate(lines):
        if marker in line:
            idx = i
            try:
                pid = int(line.split(marker, 1)[1].strip())
            except ValueError:
                pid = None
    if idx is None:
        return lines, None
    return lines[idx:], pid


def count(lines: list[str], pattern: str) -> int:
    rx = re.compile(pattern)
    return sum(1 for line in lines if rx.search(line))


def find_all(lines: list[str], pattern: str) -> list[re.Match]:
    rx = re.compile(pattern)
    return [m for line in lines for m in [rx.search(line)] if m]


def write_error_records(lines: list[str], prefix: str) -> set[str]:
    rx = re.compile(re.escape(prefix) + r"cam1:(\w+) devAsyn\w+::processCallbackOutput process write error")
    return {m.group(1) for m in find_all(lines, rx.pattern)}


def capability_audit(lines: list[str]) -> list[tuple[int, int, int, int]]:
    return [tuple(int(g) for g in m.groups()) for m in find_all(lines, RE_AUDIT.pattern)]


def autosave_connected(lines: list[str]) -> list[tuple[int, int]]:
    return [(int(m.group(1)), int(m.group(2))) for m in find_all(lines, RE_AUTOSAVE.pattern)]
