"""What a region depends on: the declarations and macros it uses from the rest of the file."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from . import lexer, syntax
from .stdlib import C_KEYWORDS

if TYPE_CHECKING:
    from .analysis import Analysis
    from .declarations import Declaration
    from .includes import KnownNames
    from .regions import Region

Span = tuple[int, int]

MAX_SHOWN_LINES = 15
CONTROL_WORDS = {b"return", b"goto", b"break", b"continue"}
ONE_LINE_KINDS = {"function", "prototype", "variable", "macro", "enum-constant"}


@dataclass
class RegionContext:
    declarations: list[tuple[str, str, str]] = field(default_factory=list)
    macro_warnings: list[str] = field(default_factory=list)
    from_headers: dict[str, str] = field(default_factory=dict)
    unknown: list[str] = field(default_factory=list)
    define_warnings: list[str] = field(default_factory=list)


def region_context(
    analysis: Analysis, regions: Sequence[Region], known: KnownNames
) -> RegionContext:
    spans = [(region.start, region.end) for region in regions if not region.is_slot]
    context = RegionContext()
    local_names = _local_names(analysis, spans)
    for name in sorted(_identifiers_in(analysis, spans)):
        outside = [
            declaration
            for declaration in analysis.declarations.by_name.get(name, [])
            if not any(start <= declaration.start < end for start, end in spans)
        ]
        if outside:
            for declaration in outside:
                context.declarations.append((name, declaration.kind, _shown(analysis, declaration)))
                if declaration.kind == "macro":
                    context.macro_warnings.extend(_macro_warnings(analysis, declaration.start))
        elif name in known.names:
            context.from_headers[name] = known.origins.get(name, "a header")
        elif name not in local_names and name not in C_KEYWORDS:
            context.unknown.append(name)
    context.define_warnings = _defines_above_ranges(analysis, regions)
    return context


def _identifiers_in(analysis: Analysis, spans: Sequence[Span]) -> set[str]:
    """Names the regions use (not struct fields), minus the names they declare themselves."""
    declared = {
        declaration.name
        for start, end in spans
        for declaration in analysis.declarations.within(start, end)
    }
    used = set()
    for node in syntax.walk(analysis.root):
        is_name = node.type in ("identifier", "type_identifier")
        if is_name and any(start <= node.start_byte < end for start, end in spans):
            used.add(syntax.text(node))
    return used - declared


def _local_names(analysis: Analysis, spans: Sequence[Span]) -> set[str]:
    names = set()
    for function in analysis.functions:
        touches = any(function.start < end and start < function.end for start, end in spans)
        if touches and function.node is not None:
            scope = analysis.scope(function.node)
            names.update(symbol.name for symbol in scope.symbols)
            names.update(scope.labels)
    return names


def _shown(analysis: Analysis, declaration: Declaration) -> str:
    if declaration.kind in ONE_LINE_KINDS:
        return declaration.signature
    lines = analysis.text(declaration.start, declaration.end).splitlines()
    if len(lines) > MAX_SHOWN_LINES:
        lines = [*lines[:MAX_SHOWN_LINES], "    ..."]
    return "\n".join(lines)


def _macro_warnings(analysis: Analysis, start: int) -> list[str]:
    token = next((item for item in analysis.tokens if item.start == start), None)
    macro = lexer.macro_definition(token) if token is not None else None
    if macro is None:
        return []
    name = macro.name.decode("utf-8", "replace")
    words = [item.text for item in lexer.tokenize(macro.body) if item.kind == lexer.IDENTIFIER]
    warnings = []
    hidden = sorted(word.decode() for word in set(words) & CONTROL_WORDS)
    if hidden:
        warnings.append(
            f"`{name}` hides `{'`, `'.join(hidden)}`: code that uses it cannot move into a helper "
            "without changing where that jump goes."
        )
    for parameter in macro.parameters or ():
        if words.count(parameter) >= 2:  # noqa: PLR2004  a second use means a second evaluation
            warnings.append(
                f"`{name}` evaluates its argument `{parameter.decode()}` more than once: never pass "
                "it an expression with side effects."
            )
    return warnings


def _defines_above_ranges(analysis: Analysis, regions: Sequence[Region]) -> list[str]:
    warnings = []
    for region in regions:
        if region.kind != "lines" or region.function is None:
            continue
        function = next((item for item in analysis.functions if item.name == region.function), None)
        if function is None:
            continue
        for token in lexer.tokens_between(analysis.tokens, function.start, region.start):
            is_define = (
                token.kind == lexer.DIRECTIVE and lexer.directive_name(token.text) == b"define"
            )
            if is_define:
                shown = lexer.normalize_directive(token.text).decode("utf-8", "replace")
                warnings.append(
                    f"`{shown}` (line {analysis.source.line_of(token.start)}) is defined inside "
                    f"`{function.name}` above the range. A helper placed in the slot before the "
                    "function cannot use it."
                )
    return warnings
