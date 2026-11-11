"""What the checks report: errors that block, and review items the agent must explain."""

from __future__ import annotations

from dataclasses import asdict, dataclass

ERROR = "error"
REVIEW = "review"


@dataclass(frozen=True)
class Issue:
    """One result of a check. `line` is a line of the current file."""

    check: str
    severity: str
    message: str
    line: int | None = None

    def to_json(self) -> dict[str, object]:
        return asdict(self)
