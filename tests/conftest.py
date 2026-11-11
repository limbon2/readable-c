"""Shared helpers: analysing snippets, running rules, comparing versions, running the CLI."""

from __future__ import annotations

import io
import shutil
from collections.abc import Callable, Iterator
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path

import pytest
from readablec import cli
from readablec.analysis import Analysis
from readablec.findings import Finding
from readablec.rules import run_rules
from readablec.verify import compare

FIXTURES = Path(__file__).parent / "fixtures"


def analyse(code: str | bytes) -> Analysis:
    data = code.encode("utf-8") if isinstance(code, str) else code
    return Analysis(data)


def findings(code: str | bytes, rule: str | None = None) -> list[Finding]:
    analysis = analyse(code)
    report = run_rules(analysis, [(0, len(analysis.data))])
    return [finding for finding in report.findings if rule is None or finding.rule == rule]


def tier(before: str, after: str, function: str = "f") -> int | None:
    """The equivalence tier `verify` gives `function` when the whole file is the region."""
    old, new = analyse(before), analyse(after)
    results, _ = compare.compare(old, [(0, len(old.data))], new, [(0, len(new.data))])
    return next(result.tier for result in results if result.name == function)


def review_items(before: str, after: str) -> list[str]:
    old, new = analyse(before), analyse(after)
    _, issues = compare.compare(old, [(0, len(old.data))], new, [(0, len(new.data))])
    return [issue.message for issue in issues]


@dataclass
class CommandResult:
    code: int
    out: str
    err: str


@pytest.fixture
def run_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., CommandResult]:
    """Run the CLI in a temporary folder, with the snapshots kept there too."""
    monkeypatch.setenv("READABLE_C_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.chdir(tmp_path)

    def run(*arguments: str) -> CommandResult:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(arguments))
        return CommandResult(code, out.getvalue(), err.getvalue())

    return run


@pytest.fixture
def fixture_copy(tmp_path: Path) -> Iterator[Callable[[str], Path]]:
    def copy(name: str) -> Path:
        target = tmp_path / name
        shutil.copyfile(FIXTURES / name, target)
        return target

    yield copy
