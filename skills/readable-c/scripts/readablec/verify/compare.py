"""The equivalence tiers, function by function.

Tier 0: the tokens are equal once comments and layout are ignored.
Tier 1: the canonical forms are equal (see canonical.py).
Tier 2: neither; the inventory lists what changed, for the agent to explain.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .. import lexer, syntax
from ..analysis import Analysis
from ..functions import FunctionSpan
from ..issues import REVIEW, Issue
from . import inventory
from .canonical import Canonicalizer, constant_values

Span = tuple[int, int]


@dataclass
class FunctionResult:
    name: str
    tier: int | None
    summary: str
    line: int | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "function": self.name,
            "tier": self.tier,
            "summary": self.summary,
            "line": self.line,
        }


def compare(
    old: Analysis, old_spans: Sequence[Span], new: Analysis, new_spans: Sequence[Span]
) -> tuple[list[FunctionResult], list[Issue]]:
    old_functions = _touched(old, old_spans)
    new_functions = _touched(new, new_spans)
    old_constants, new_constants = constant_values(old), constant_values(new)
    results: list[FunctionResult] = []
    unproven_old: list[FunctionSpan] = []
    unproven_new: list[FunctionSpan] = []
    for old_function, new_function in _pairs(old_functions, new_functions):
        if new_function is None and old_function is not None:
            results.append(FunctionResult(old_function.name, None, "removed from the region"))
            unproven_old.append(old_function)
            continue
        if old_function is None and new_function is not None:
            results.append(
                FunctionResult(
                    new_function.name,
                    2,
                    "new function (a helper): explain it",
                    new_function.first_line,
                )
            )
            unproven_new.append(new_function)
            continue
        assert old_function is not None and new_function is not None, "a pair has at least one side"
        result = _compare_pair(
            old,
            old_function,
            new,
            new_function,
            old_constants=old_constants,
            new_constants=new_constants,
        )
        results.append(result)
        if result.tier == 2:  # noqa: PLR2004  tier 2 means not proven
            unproven_old.append(old_function)
            unproven_new.append(new_function)
    issues = _inventory_issues(
        old,
        unproven_old,
        new,
        unproven_new,
        old_constants=old_constants,
        new_constants=new_constants,
    )
    issues.extend(_file_scope_issues(old, old_spans, new, new_spans))
    return results, issues


def _touched(analysis: Analysis, spans: Sequence[Span]) -> list[FunctionSpan]:
    return [
        function
        for function in analysis.functions
        if any(function.start < end and start < function.end for start, end in spans if start < end)
    ]


def _pairs(
    old_functions: list[FunctionSpan], new_functions: list[FunctionSpan]
) -> list[tuple[FunctionSpan | None, FunctionSpan | None]]:
    remaining = list(new_functions)
    pairs: list[tuple[FunctionSpan | None, FunctionSpan | None]] = []
    for old_function in old_functions:
        match = next(
            (function for function in remaining if function.name == old_function.name), None
        )
        if match is not None:
            remaining.remove(match)
        pairs.append((old_function, match))
    pairs.extend((None, function) for function in remaining)
    return pairs


def _tokens(analysis: Analysis, function: FunctionSpan) -> list[tuple[str, bytes]]:
    return lexer.significant(lexer.tokens_between(analysis.tokens, function.start, function.end))


def _compare_pair(
    old: Analysis,
    old_function: FunctionSpan,
    new: Analysis,
    new_function: FunctionSpan,
    *,
    old_constants: dict,
    new_constants: dict,
) -> FunctionResult:
    name = new_function.name
    if _tokens(old, old_function) == _tokens(new, new_function):
        return FunctionResult(
            name, 0, "same tokens: only comments and layout changed", new_function.first_line
        )
    parsed = all(
        function.node is not None and not function.node.has_error
        for function in (old_function, new_function)
    )
    if not parsed:
        return FunctionResult(
            name,
            2,
            "does not parse cleanly, so only tier 0 could prove it; explain every change",
            new_function.first_line,
        )
    assert old_function.node is not None and new_function.node is not None, "checked above"
    before = Canonicalizer(old, old_function.node, old_constants)
    after = Canonicalizer(new, new_function.node, new_constants)
    if before.canonical_function() == after.canonical_function():
        return FunctionResult(
            name,
            1,
            "same normalized syntax tree: the refactor keeps behavior",
            new_function.first_line,
        )
    line = _first_difference(before, after, old_function, new_function)
    return FunctionResult(name, 2, "restructured: check the review items and explain them", line)


def _first_difference(
    before: Canonicalizer,
    after: Canonicalizer,
    old_function: FunctionSpan,
    new_function: FunctionSpan,
) -> int:
    old_body = old_function.node.child_by_field_name("body") if old_function.node else None
    new_body = new_function.node.child_by_field_name("body") if new_function.node else None
    if old_body is None or new_body is None:
        return new_function.first_line
    old_items = before.statements(syntax.named_children(old_body))
    for index, statement in enumerate(syntax.named_children(new_body)):
        items = after.statements([statement])
        if not items:
            continue
        if index >= len(old_items) or items[0] != old_items[min(index, len(old_items) - 1)]:
            return syntax.start_line(statement)
    return new_function.first_line


def _inventory_issues(
    old: Analysis,
    old_functions: list[FunctionSpan],
    new: Analysis,
    new_functions: list[FunctionSpan],
    *,
    old_constants: dict,
    new_constants: dict,
) -> list[Issue]:
    if not old_functions and not new_functions:
        return []
    before = inventory.collect(_forms(old, old_functions, old_constants))
    after = inventory.collect(_forms(new, new_functions, new_constants))
    return [
        Issue(
            "equivalence",
            REVIEW,
            f"Restructured code changed its inventory: {line}. Explain why in the report.",
        )
        for line in inventory.differences(before, after)
    ]


def _forms(
    analysis: Analysis, functions: list[FunctionSpan], constants: dict
) -> list[tuple[tuple, dict[int, str]]]:
    forms = []
    for function in functions:
        if function.node is None:
            continue
        canonicalizer = Canonicalizer(analysis, function.node, constants)
        forms.append((canonicalizer.canonical_function(), canonicalizer.ordinal_names))
    return forms


def _file_scope_issues(
    old: Analysis, old_spans: Sequence[Span], new: Analysis, new_spans: Sequence[Span]
) -> list[Issue]:
    """Tokens in the regions outside any function: declarations, macros, globals."""
    before = _outside_functions(old, old_spans)
    after = _outside_functions(new, new_spans)
    if before == after:
        return []
    return [
        Issue(
            "equivalence",
            REVIEW,
            "Code outside functions inside the regions changed (declarations, prototypes, macros "
            "or globals). Explain each change in the report.",
        )
    ]


def _outside_functions(analysis: Analysis, spans: Sequence[Span]) -> list[tuple[str, bytes]]:
    function_spans = [(function.start, function.end) for function in analysis.functions]
    selected = []
    for start, end in spans:
        for token in lexer.tokens_between(analysis.tokens, start, end):
            if not any(first <= token.start < last for first, last in function_spans):
                selected.append(token)
    return lexer.significant(selected)
