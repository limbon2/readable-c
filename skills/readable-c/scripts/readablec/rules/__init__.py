"""The readability rules: what `check` reports inside the regions."""

from __future__ import annotations

from .engine import RuleReport, run_rules

__all__ = ["RuleReport", "run_rules"]
