"""Readability findings, and how the findings after an edit relate to those before it."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass

RULE = "rule"
ADVICE = "advice"


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str
    line: int
    column: int
    message: str
    function: str | None
    snippet: str

    def to_json(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, object]) -> Finding:
        return cls(
            rule=str(data["rule"]),
            severity=str(data["severity"]),
            line=int(str(data["line"])),
            column=int(str(data["column"])),
            message=str(data["message"]),
            function=None if data.get("function") is None else str(data["function"]),
            snippet=str(data["snippet"]),
        )


def mark_new(current: Sequence[Finding], baseline: Sequence[Finding]) -> list[tuple[Finding, bool]]:
    """Pair each current finding with True when the edit introduced it.

    Findings match by rule, function and snippet first. What is left matches by
    count within the same rule and function, so a renamed variable does not
    turn an old finding into a new one.
    """
    unmatched: dict[tuple[str, str | None], list[str]] = defaultdict(list)
    for finding in baseline:
        unmatched[(finding.rule, finding.function)].append(finding.snippet)
    leftovers = []
    result: list[tuple[Finding, bool]] = []
    for finding in current:
        group = unmatched[(finding.rule, finding.function)]
        if finding.snippet in group:
            group.remove(finding.snippet)
            result.append((finding, False))
        else:
            leftovers.append(finding)
    for finding in leftovers:
        group = unmatched[(finding.rule, finding.function)]
        if group:
            group.pop()
            result.append((finding, False))
        else:
            result.append((finding, True))
    return sorted(result, key=lambda pair: (pair[0].line, pair[0].column))
