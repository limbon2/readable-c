"""Runs the rules over the functions inside the regions.

Each rule is a function that receives a node of the types it registered for.
The engine walks every function that shares bytes with a region, skips ERROR
nodes (and reports them as not checked), and keeps only findings that start
inside a region.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .. import syntax
from ..findings import Finding

if TYPE_CHECKING:
    from tree_sitter import Node

    from ..analysis import Analysis
    from ..conventions import Conventions
    from ..functions import FunctionSpan

Span = tuple[int, int]
RuleFunction = Callable[["Node", "RuleContext"], None]

_WHITESPACE = re.compile(r"\s+")
MAX_SNIPPET = 120


@dataclass
class RuleContext:
    analysis: Analysis
    spans: Sequence[Span]
    frozen_names: set[str]
    function: FunctionSpan | None = None
    findings: list[Finding] = field(default_factory=list)

    @property
    def conventions(self) -> Conventions:
        return self.analysis.conventions

    def in_spans(self, node: Node) -> bool:
        return any(start <= node.start_byte < end for start, end in self.spans)

    def report(self, rule: str, severity: str, node: Node, message: str) -> None:
        if not self.in_spans(node):
            return
        snippet = _WHITESPACE.sub(" ", syntax.text(node)).strip()
        self.findings.append(
            Finding(
                rule=rule,
                severity=severity,
                line=syntax.start_line(node),
                column=node.start_point.column + 1,
                message=message,
                function=self.function.name if self.function else None,
                snippet=snippet[:MAX_SNIPPET],
            )
        )


@dataclass
class RuleReport:
    findings: list[Finding]
    unchecked: list[tuple[int, int, str]]


_REGISTRY: dict[str, list[RuleFunction]] = {}
_FUNCTION_RULES: list[RuleFunction] = []
_LINE_RULES: list[Callable[[RuleContext], None]] = []


def on(*node_types: str) -> Callable[[RuleFunction], RuleFunction]:
    """Register a rule for nodes of the given types."""

    def register(rule: RuleFunction) -> RuleFunction:
        for node_type in node_types:
            _REGISTRY.setdefault(node_type, []).append(rule)
        return rule

    return register


def on_function(rule: RuleFunction) -> RuleFunction:
    """Register a rule that receives each function definition once."""
    _FUNCTION_RULES.append(rule)
    return rule


def on_lines(rule: Callable[[RuleContext], None]) -> Callable[[RuleContext], None]:
    """Register a rule that reads the region's lines and tokens instead of the tree."""
    _LINE_RULES.append(rule)
    return rule


def run_rules(
    analysis: Analysis, spans: Sequence[Span], frozen_names: set[str] | None = None
) -> RuleReport:
    from . import conditions, control_flow, naming, style  # noqa: F401, PLC0415  importing registers the rules

    context = RuleContext(
        analysis, [span for span in spans if span[0] < span[1]], frozen_names or set()
    )
    unchecked: list[tuple[int, int, str]] = []
    for function in _functions_in_spans(analysis, context.spans):
        context.function = function
        if function.node is None:
            unchecked.append(
                (function.first_line, function.last_line, f"`{function.name}` does not parse")
            )
            continue
        for rule in _FUNCTION_RULES:
            rule(function.node, context)
        unchecked.extend(_walk(function.node, context))
    context.function = None
    for line_rule in _LINE_RULES:
        line_rule(context)
    findings = sorted(
        context.findings, key=lambda finding: (finding.line, finding.column, finding.rule)
    )
    return RuleReport(findings, _inside(unchecked, analysis, context.spans))


def _functions_in_spans(analysis: Analysis, spans: Sequence[Span]) -> list[FunctionSpan]:
    return [
        function
        for function in analysis.functions
        if any(function.start < end and start < function.end for start, end in spans)
    ]


def _walk(function_node: Node, context: RuleContext) -> list[tuple[int, int, str]]:
    unchecked = []
    stack = [function_node]
    while stack:
        node = stack.pop()
        if node.is_error or node.is_missing:
            unchecked.append(
                (syntax.start_line(node), syntax.end_line(node), "the code does not parse")
            )
            continue
        for rule in _REGISTRY.get(node.type, ()):
            rule(node, context)
        stack.extend(reversed(node.children))
    return unchecked


def _inside(
    unchecked: list[tuple[int, int, str]], analysis: Analysis, spans: Sequence[Span]
) -> list[tuple[int, int, str]]:
    result = []
    for first, last, reason in unchecked:
        start = analysis.source.line_start(first)
        end = analysis.source.line_end(last)
        if any(start < span_end and span_start < end for span_start, span_end in spans):
            result.append((first, last, reason))
    return result
