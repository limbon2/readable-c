"""Name checks that stand in for the compiler: unresolved names, shadowing, frozen names.

A region refactor must not introduce a name the code cannot resolve, must not
hide a name the region used from outside, and must keep every name that frozen
code depends on, with the same type. Comments that still mention a renamed name
are reported too, because a rename that misses a comment leaves it wrong.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING

from .. import dialect, lexer, stdlib, syntax
from ..issues import ERROR, REVIEW, Issue
from ..stdlib import C_KEYWORDS

if TYPE_CHECKING:
    from tree_sitter import Node

    from ..analysis import Analysis
    from ..functions import FunctionSpan
    from ..includes import KnownNames
    from ..regions import Region

Span = tuple[int, int]


def _inside(position: int, spans: Sequence[Span]) -> bool:
    return any(start <= position < end for start, end in spans)


def _touched(analysis: Analysis, spans: Sequence[Span]) -> list[FunctionSpan]:
    return [
        function
        for function in analysis.functions
        if function.node is not None
        and any(
            function.start < end and start < function.end for start, end in spans if start < end
        )
    ]


def external_names(analysis: Analysis) -> set[str]:
    """Names the file uses that are not locals: globals, functions, macros, types."""
    names = set()
    for function in analysis.functions:
        if function.node is None:
            continue
        scope = analysis.scope(function.node)
        names.update(syntax.text(node) for node in scope.external)
    function_spans = sorted((function.start, function.end) for function in analysis.functions)
    span_index = 0
    for token in analysis.tokens:
        while span_index < len(function_spans) and function_spans[span_index][1] <= token.start:
            span_index += 1
        in_function = (
            span_index < len(function_spans) and function_spans[span_index][0] <= token.start
        )
        if token.kind == lexer.IDENTIFIER and not in_function:
            names.add(token.text.decode("utf-8", "surrogateescape"))
    for node in syntax.walk(analysis.root):
        if node.type == "type_identifier":
            names.add(syntax.text(node))
    return names


def unresolved_names(
    old: Analysis, new: Analysis, new_spans: Sequence[Span], known: KnownNames
) -> list[Issue]:
    allowed = (
        new.file_scope_names | external_names(old) | known.names | stdlib.ALWAYS_KNOWN | C_KEYWORDS
    )
    reported: set[str] = set()
    issues = []
    for name, line in _external_uses(new, new_spans):
        if name in allowed or name in reported:
            continue
        reported.add(name)
        hidden = known.missing_headers + known.unknown_system_headers
        if hidden:
            issues.append(
                Issue(
                    "names",
                    REVIEW,
                    f"`{name}` is new and the tool cannot find where it is declared. It may come from "
                    f"a header the tool could not read ({', '.join(hidden)}). Confirm that it exists, "
                    "or fix the typo or missed rename.",
                    line,
                )
            )
        else:
            issues.append(
                Issue(
                    "names",
                    ERROR,
                    f"`{name}` is not declared in the region, in this file or in a header it includes, "
                    "and the original code did not use it. Fix the typo or the missed rename.",
                    line,
                )
            )
    return issues


def _external_uses(new: Analysis, spans: Sequence[Span]) -> list[tuple[str, int]]:
    uses = []
    for function in _touched(new, spans):
        assert function.node is not None, "_touched keeps parsed functions only"
        scope = new.scope(function.node)
        uses.extend(
            (syntax.text(node), syntax.start_line(node))
            for node in scope.external
            if _inside(node.start_byte, spans)
        )
        for node in syntax.walk(function.node):
            if node.type == "type_identifier" and _inside(node.start_byte, spans):
                uses.append((syntax.text(node), syntax.start_line(node)))
    return uses


def scope_issues(
    old: Analysis, old_spans: Sequence[Span], new: Analysis, new_spans: Sequence[Span]
) -> list[Issue]:
    """Shadowing, repeated declarations, changed constants and missing labels."""
    old_facts = _scope_facts(old, old_spans)
    issues = []
    for function in _touched(new, new_spans):
        assert function.node is not None, "_touched keeps parsed functions only"
        scope = new.scope(function.node)
        name = function.name
        for symbol, hidden in scope.shadowing:
            fact = ("shadow", name, symbol.name)
            if _inside(symbol.declarator.start_byte, new_spans) and fact not in old_facts:
                issues.append(
                    Issue(
                        "names",
                        ERROR,
                        f"The new local `{symbol.name}` hides {hidden}, so code that meant the outer "
                        "one now reads this one. Pick another name.",
                        syntax.start_line(symbol.declarator),
                    )
                )
        for node in scope.redeclarations:
            fact = ("redeclared", name, syntax.text(node))
            if _inside(node.start_byte, new_spans) and fact not in old_facts:
                issues.append(
                    Issue(
                        "names",
                        ERROR,
                        f"`{syntax.text(node)}` is declared twice in the same block; the compiler "
                        "rejects that.",
                        syntax.start_line(node),
                    )
                )
        for symbol in scope.symbols:
            is_changed_constant = (
                "const" in symbol.qualifiers and symbol.is_variable and scope.is_modified(symbol)
            )
            if is_changed_constant and _inside(symbol.declarator.start_byte, new_spans):
                issues.append(
                    Issue(
                        "names",
                        ERROR,
                        f"`{symbol.name}` is declared const but assigned later; the compiler rejects that.",
                        syntax.start_line(symbol.declarator),
                    )
                )
        for label in scope.goto_targets:
            if syntax.text(label) not in scope.labels and _inside(label.start_byte, new_spans):
                issues.append(
                    Issue(
                        "names",
                        ERROR,
                        f"`goto {syntax.text(label)}` has no matching label in `{name}`.",
                        syntax.start_line(label),
                    )
                )
    return issues


def _scope_facts(analysis: Analysis, spans: Sequence[Span]) -> set[tuple[str, str, str]]:
    facts = set()
    for function in _touched(analysis, spans):
        assert function.node is not None, "_touched keeps parsed functions only"
        scope = analysis.scope(function.node)
        facts.update(("shadow", function.name, symbol.name) for symbol, _ in scope.shadowing)
        facts.update(
            ("redeclared", function.name, syntax.text(node)) for node in scope.redeclarations
        )
    return facts


def frozen_issues(
    new: Analysis, new_spans: Sequence[Span], frozen: Sequence[dict[str, object]]
) -> list[Issue]:
    issues = []
    for entry in frozen:
        scope_kind = entry.get("scope")
        name = str(entry["name"])
        if scope_kind == "file":
            issues.extend(_check_frozen_file_name(new, entry, name))
        elif scope_kind == "local":
            issues.extend(_check_frozen_local(new, new_spans, entry, name))
        elif scope_kind == "label":
            issues.extend(_check_frozen_label(new, entry, name))
    return issues


def _check_frozen_file_name(new: Analysis, entry: dict[str, object], name: str) -> list[Issue]:
    declarations = [
        item for item in new.declarations.by_name.get(name, []) if item.kind == entry["kind"]
    ]
    if not declarations:
        return [
            Issue(
                "frozen",
                ERROR,
                f"`{name}` ({entry['kind']}) is used outside the regions but is no longer declared. "
                "Keep its name and declaration.",
            )
        ]
    if all(item.signature != entry["signature"] for item in declarations):
        return [
            Issue(
                "frozen",
                ERROR,
                f"`{name}` is used outside the regions, so its declaration must stay `{entry['signature']}`; "
                f"it is now `{declarations[0].signature}`. Parameter names may change, nothing else.",
            )
        ]
    return []


def _check_frozen_local(
    new: Analysis, new_spans: Sequence[Span], entry: dict[str, object], name: str
) -> list[Issue]:
    function = next(
        (
            item
            for item in new.functions
            if item.name == entry.get("function") and item.node is not None
        ),
        None,
    )
    if function is None or function.node is None:
        return [
            Issue(
                "frozen",
                ERROR,
                f"The function `{entry.get('function')}` that uses `{name}` is gone.",
            )
        ]
    scope = new.scope(function.node)
    outside_uses = [
        node
        for node in syntax.walk(function.node)
        if node.type == "identifier"
        and syntax.text(node) == name
        and not _inside(node.start_byte, new_spans)
    ]
    for use in outside_uses:
        symbol = scope.symbol_of(use)
        is_same = (
            symbol is not None
            and _inside(symbol.declarator.start_byte, new_spans)
            and _without_const(symbol.type_text) == _without_const(str(entry["type"]))
        )
        if not is_same:
            return [
                Issue(
                    "frozen",
                    ERROR,
                    f"Code after the region uses the local `{name}` declared in the region. Keep "
                    f"declaring it at the same block level with the type `{entry['type']}`.",
                    syntax.start_line(use),
                )
            ]
    return []


def _check_frozen_label(new: Analysis, entry: dict[str, object], name: str) -> list[Issue]:
    function = next(
        (
            item
            for item in new.functions
            if item.name == entry.get("function") and item.node is not None
        ),
        None,
    )
    if function is None or function.node is None or name not in new.scope(function.node).labels:
        return [
            Issue(
                "frozen",
                ERROR,
                f"A `goto` outside the region jumps to the label `{name}`. Keep the label.",
            )
        ]
    return []


def _without_const(type_text: str) -> str:
    return " ".join(word for word in type_text.replace("*", " * ").split() if word != "const")


MIN_WORD_NAME = 3


def stale_comment_issues(
    old: Analysis, old_spans: Sequence[Span], new: Analysis, new_spans: Sequence[Span]
) -> list[Issue]:
    """Comments in a region function that still mention a local or parameter that the
    function no longer declares, which is what a rename leaves behind when it misses them.

    Only comment lines carried over unchanged from the original count: a missed rename
    leaves old comments behind, while a new comment that names a protocol field such as
    `msgType` names it on purpose."""
    old_functions = {function.name: function for function in _touched(old, old_spans)}
    issues = []
    for function in _touched(new, new_spans):
        before = old_functions.get(function.name)
        if before is None:
            continue
        assert before.node is not None and function.node is not None, (
            "_touched keeps parsed functions"
        )
        old_names = {symbol.name for symbol in old.scope(before.node).symbols if symbol.is_variable}
        new_names = {symbol.name for symbol in new.scope(function.node).symbols}
        gone = sorted(old_names - new_names - new.file_scope_names)
        if not gone:
            continue
        kept_lines = _comment_lines(old, before.start, before.end)
        for token in lexer.tokens_between(new.tokens, function.start, function.end):
            is_region_comment = token.kind == lexer.COMMENT and _inside(token.start, new_spans)
            if not is_region_comment:
                continue
            carried_over = [line for line in _split_comment(token.text) if line in kept_lines]
            text = "\n".join(carried_over)
            for name in gone:
                if _mentions(text, name):
                    issues.append(
                        Issue(
                            "comments",
                            REVIEW,
                            f"This comment still mentions `{name}`, which `{function.name}` no longer "
                            "declares: a rename or removal left it behind. Update the comment.",
                            new.source.line_of(token.start),
                        )
                    )
    return issues


def _comment_lines(analysis: Analysis, start: int, end: int) -> set[str]:
    return {
        line
        for token in lexer.tokens_between(analysis.tokens, start, end)
        if token.kind == lexer.COMMENT
        for line in _split_comment(token.text)
    }


def _split_comment(text: bytes) -> list[str]:
    """The lines of a comment without markers and layout, so moved comments still match."""
    lines = []
    for raw in text.decode("utf-8", "replace").splitlines():
        line = raw.strip().removeprefix("/*").removesuffix("*/").removeprefix("//")
        line = " ".join(line.strip().lstrip("*").split())
        if line:
            lines.append(line)
    return lines


def _mentions(text: str, name: str) -> bool:
    escaped = re.escape(name)
    if len(name) >= MIN_WORD_NAME:
        return re.search(rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])", text) is not None
    # One- and two-letter names collide with ordinary words ("a", "i", "is"), so
    # only uses that read as code count: `cb`, cb->server, cb.server, cb[0], cb(.
    as_code = rf"`{escaped}`|(?<![A-Za-z0-9_]){escaped}(?:->|\.[A-Za-z_]|\[|\()"
    return re.search(as_code, text) is not None


def dialect_issues(old: Analysis, new: Analysis, new_spans: Sequence[Span]) -> list[Issue]:
    before = dialect.find_constructs(old.source, old.root, old.tokens)
    issues = []
    for start, end in new_spans:
        if start >= end:
            continue
        after = dialect.find_constructs(new.source, new.root, new.tokens, start, end)
        for construct, line in dialect.new_constructs(before, after).items():
            issues.append(
                Issue(
                    "dialect",
                    ERROR,
                    f"The region now uses {dialect.CONSTRUCTS[construct]}, which the original file never "
                    "uses. The project may compile as C89 or with an old compiler; write it the way the "
                    "rest of the file does.",
                    line,
                )
            )
    return issues


def parse_issues(
    old: Analysis, old_regions: Sequence[Region], new: Analysis, new_spans: Sequence[Span]
) -> list[Issue]:
    old_spans = [(region.start, region.end) for region in old_regions]
    before = [node for node in syntax.error_nodes(old.root) if _overlaps_spans(node, old_spans)]
    after = [node for node in syntax.error_nodes(new.root) if _overlaps_spans(node, new_spans)]
    if len(after) <= len(before):
        return []
    lines = sorted({syntax.start_line(node) for node in after})
    return [
        Issue(
            "parse",
            ERROR,
            f"The region has new syntax errors (lines {', '.join(map(str, lines[:8]))}); before the "
            f"edit it had {len(before)}. Fix the code so that it parses.",
            lines[0],
        )
    ]


def _overlaps_spans(node: Node, spans: Sequence[Span]) -> bool:
    start = node.start_byte
    end = max(node.end_byte, start + 1)
    return any(start < span_end and span_start < end for span_start, span_end in spans)


def frozen_entries(old: Analysis, regions: Sequence[Region]) -> list[dict[str, object]]:
    """What the code outside the regions needs from inside them, recorded at `start`."""
    region_spans = [(region.start, region.end) for region in regions if not region.is_slot]
    outside_names = {
        token.text.decode("utf-8", "surrogateescape")
        for token in old.tokens
        if token.kind == lexer.IDENTIFIER and not _inside(token.start, region_spans)
    }
    entries: list[dict[str, object]] = []
    for start, end in region_spans:
        for declaration in old.declarations.within(start, end):
            if declaration.name in outside_names:
                entries.append(
                    {
                        "scope": "file",
                        "name": declaration.name,
                        "kind": declaration.kind,
                        "signature": declaration.signature,
                    }
                )
    for region in regions:
        if region.kind != "lines" or region.function is None:
            continue
        function = next(
            (
                item
                for item in old.functions
                if item.name == region.function and item.node is not None
            ),
            None,
        )
        if function is None or function.node is None:
            continue
        entries.extend(_frozen_locals(old, function, region))
    return entries


def _frozen_locals(
    old: Analysis, function: FunctionSpan, region: Region
) -> list[dict[str, object]]:
    assert function.node is not None, "callers pass parsed functions"
    scope = old.scope(function.node)
    span = [(region.start, region.end)]
    entries: list[dict[str, object]] = []
    for symbol in scope.symbols:
        declared_inside = _inside(symbol.declarator.start_byte, span)
        used_outside = any(not _inside(use.start_byte, span) for use in scope.uses_of(symbol))
        if declared_inside and used_outside and symbol.is_variable:
            entries.append(
                {
                    "scope": "local",
                    "name": symbol.name,
                    "function": function.name,
                    "type": symbol.type_text,
                }
            )
    for label in scope.labels.values():
        defined_inside = _inside(label.statement.start_byte, span)
        jumped_from_outside = any(
            syntax.text(target) == label.name and not _inside(target.start_byte, span)
            for target in scope.goto_targets
        )
        if defined_inside and jumped_from_outside:
            entries.append({"scope": "label", "name": label.name, "function": function.name})
    return entries
