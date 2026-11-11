"""What the commands share: output, loading a refactor in progress, and exit codes."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .. import guard, state
from ..analysis import Analysis
from ..findings import Finding
from ..issues import Issue
from ..regions import Region
from ..source import SourceText

EXIT_CLEAN = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


class CommandError(RuntimeError):
    """A problem the user must fix before the command can run; exits with code 2."""


class Output:
    def __init__(self, as_json: bool) -> None:
        self.as_json = as_json

    def line(self, text: str = "") -> None:
        if not self.as_json:
            print(text)

    def section(self, title: str) -> None:
        if not self.as_json:
            print()
            print(f"== {title}")

    def json(self, data: object) -> None:
        if self.as_json:
            print(json.dumps(data, indent=2, ensure_ascii=False))


def display_path(path: Path) -> str:
    try:
        return os.path.relpath(path)
    except ValueError:
        return str(path)


def read_file(path: Path) -> bytes:
    if not path.is_file():
        raise CommandError(f"{path} is not a file.")
    return path.read_bytes()


def write_file(path: Path, data: bytes) -> None:
    path.write_bytes(data)


@dataclass
class Session:
    """A refactor in progress: the snapshot and where its regions are now."""

    snapshot: state.Snapshot
    current: bytes
    result: guard.GuardResult

    @property
    def spans(self) -> list[tuple[int, int]]:
        return self.result.spans or []

    @property
    def regions(self) -> list[Region]:
        return self.snapshot.regions

    def original_analysis(self) -> Analysis:
        return Analysis(self.snapshot.original, self.snapshot.path)

    def current_analysis(self) -> Analysis:
        return Analysis(self.current, self.snapshot.path)


def open_session(path: Path) -> Session:
    try:
        snapshot = state.load(path)
    except state.StateError as error:
        raise CommandError(str(error)) from error
    current = read_file(path)
    return Session(snapshot, current, guard.check(snapshot.original, snapshot.regions, current))


def print_issue(output: Output, path: Path, issue: Issue) -> None:
    location = f"{display_path(path)}:{issue.line}" if issue.line else display_path(path)
    output.line(f"{location}: {issue.severity}: [{issue.check}] {issue.message}")


def print_finding(output: Output, path: Path, finding: Finding, is_new: bool | None = None) -> None:
    marker = " (new)" if is_new else ""
    output.line(
        f"{display_path(path)}:{finding.line}:{finding.column}: {finding.severity}{marker}: "
        f"[{finding.rule}] {finding.message}"
    )
    output.line(f"    {finding.snippet}")


def numbered_lines(source: SourceText, start: int, end: int, encoding: str) -> list[str]:
    if start >= end:
        return []
    first = source.line_of(start)
    last = source.line_of(end - 1)
    width = len(str(last))
    return [
        f"{str(line).rjust(width)}  {source.line_bytes(line).decode(encoding, errors='backslashreplace')}"
        for line in range(first, last + 1)
    ]


def configure_console() -> None:
    """Print UTF-8 everywhere, and never crash on a byte the console cannot show."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="backslashreplace")
