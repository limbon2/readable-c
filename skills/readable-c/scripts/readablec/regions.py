"""Regions: the parts of a file that a refactor may change.

A region is a run of whole lines. A function region holds the definition and
the comments directly above it. A line range inside a function snaps outward to
whole statements and gets a helper slot: an empty region just before the
function, where extracted static helpers go. Everything else is frozen.
"""

from __future__ import annotations

import difflib
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from . import syntax
from .functions import FunctionSpan

if TYPE_CHECKING:
    from tree_sitter import Node

    from .source import SourceText

STATEMENT_CONTAINERS = {
    "compound_statement",
    "case_statement",
    "preproc_if",
    "preproc_ifdef",
    "preproc_else",
    "preproc_elif",
}

TOP_LEVEL_SKIP = {"comment"}


class RegionError(ValueError):
    """The requested region does not exist or cannot be used."""


@dataclass(frozen=True)
class Region:
    """Bytes [start, end) of the original file. A slot has start == end."""

    start: int
    end: int
    kind: str
    label: str
    function: str | None = None

    @property
    def is_slot(self) -> bool:
        return self.kind == "slot"

    def to_json(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, object]) -> Region:
        return cls(
            start=int(str(data["start"])),
            end=int(str(data["end"])),
            kind=str(data["kind"]),
            label=str(data["label"]),
            function=None if data.get("function") is None else str(data["function"]),
        )


@dataclass
class Resolution:
    regions: list[Region]
    notes: list[str]


def resolve(
    source: SourceText,
    root: Node,
    functions: Sequence[FunctionSpan],
    *,
    function_names: Sequence[str] = (),
    line_ranges: Sequence[tuple[int, int]] = (),
    whole_file: bool = False,
) -> Resolution:
    """Turn a request (function names, line ranges or the whole file) into regions."""
    if whole_file:
        return Resolution([Region(0, len(source.data), "file", "the whole file")], [])
    notes: list[str] = []
    regions: list[Region] = []
    for name in function_names:
        regions.extend(_function_regions(name, functions, notes))
    for first, last in line_ranges:
        regions.extend(_line_range_regions(source, root, functions, (first, last), notes=notes))
    if not regions:
        raise RegionError("Name at least one function (--function), line range (--lines) or --all.")
    return Resolution(merge(source, regions), notes)


def _function_regions(
    name: str, functions: Sequence[FunctionSpan], notes: list[str]
) -> list[Region]:
    matches = [function for function in functions if function.name == name]
    if not matches:
        known = sorted({function.name for function in functions})
        close = difflib.get_close_matches(name, known, n=3)
        hint = f" Did you mean {', '.join(close)}?" if close else ""
        raise RegionError(f"No definition of a function named `{name}` in this file.{hint}")
    if len(matches) > 1:
        lines = ", ".join(str(match.first_line) for match in matches)
        notes.append(f"`{name}` is defined {len(matches)} times (lines {lines}); all are selected.")
    for match in matches:
        if not match.is_parsed:
            notes.append(
                f"`{name}` (line {match.first_line}) does not parse cleanly, so rules and the "
                "syntax-tree checks skip it; the token checks still apply."
            )
    return [
        Region(match.start, match.end, "function", f"function {name}", function=name)
        for match in matches
    ]


def _line_range_regions(
    source: SourceText,
    root: Node,
    functions: Sequence[FunctionSpan],
    line_range: tuple[int, int],
    *,
    notes: list[str],
) -> list[Region]:
    first, last = line_range
    if not 1 <= first <= last <= source.line_count:
        raise RegionError(
            f"Lines {first}-{last} are outside the file, which has {source.line_count} lines."
        )
    span_start, span_end = source.line_start(first), source.line_end(last)
    touched = [
        function
        for function in functions
        if function.start < span_end and span_start < function.end
    ]
    if len(touched) == 1 and _is_inside_body(source, touched[0], first, last):
        return _range_inside_function(source, touched[0], first, last, notes)
    return [_whole_items(source, root, functions, (first, last), notes=notes)]


def _is_inside_body(source: SourceText, function: FunctionSpan, first: int, last: int) -> bool:
    body_open_line = source.line_of(function.body_start)
    return body_open_line < first and last < function.last_line


def _range_inside_function(
    source: SourceText, function: FunctionSpan, first: int, last: int, notes: list[str]
) -> list[Region]:
    snapped_first, snapped_last = first, last
    if function.node is None:
        notes.append(
            f"`{function.name}` does not parse cleanly, so lines {first}-{last} are used as given, "
            "without snapping to whole statements."
        )
    else:
        body = function.node.child_by_field_name("body")
        if body is not None:
            snapped_first, snapped_last = _snap_to_statements(body, first, last)
        if (snapped_first, snapped_last) != (first, last):
            notes.append(
                f"Lines {first}-{last} grew to {snapped_first}-{snapped_last} to cover whole statements."
            )
    label = f"lines {snapped_first}-{snapped_last} in {function.name}"
    lines_region = Region(
        source.line_start(snapped_first),
        source.line_end(snapped_last),
        "lines",
        label,
        function=function.name,
    )
    slot = Region(
        function.start, function.start, "slot", f"helper slot before {function.name}", function.name
    )
    return [slot, lines_region]


def _snap_to_statements(body: Node, first: int, last: int) -> tuple[int, int]:
    container = body
    while True:
        inner = _inner_container(container, first, last)
        if inner is None:
            break
        container = inner
    children = [
        child
        for child in _statements_of(container)
        if syntax.start_line(child) <= last and first <= syntax.end_line(child)
    ]
    if not children:
        return first, last
    snapped_first = min(first, *(syntax.start_line(child) for child in children))
    snapped_last = max(last, *(syntax.end_line(child) for child in children))
    return snapped_first, snapped_last


def _inner_container(container: Node, first: int, last: int) -> Node | None:
    """A statement container inside `container` whose inner lines hold all of [first, last]."""
    for node in syntax.walk(container):
        if node is container or node.type not in STATEMENT_CONTAINERS:
            continue
        inner_first = syntax.start_line(node) + 1
        inner_last = syntax.end_line(node) - (0 if node.type == "case_statement" else 1)
        holds_range = inner_first <= first and last <= inner_last
        if holds_range and node.start_byte >= container.start_byte:
            return node
    return None


def _statements_of(container: Node) -> list[Node]:
    if container.type == "case_statement":
        value = container.child_by_field_name("value")
        return [child for child in container.named_children if child != value]
    return [child for child in container.named_children if child.type != "preproc_directive"]


def _whole_items(
    source: SourceText,
    root: Node,
    functions: Sequence[FunctionSpan],
    line_range: tuple[int, int],
    *,
    notes: list[str],
) -> Region:
    first, last = line_range
    span_start, span_end = source.line_start(first), source.line_end(last)
    starts = [span_start]
    ends = [span_end]
    for function in functions:
        if function.start < span_end and span_start < function.end:
            starts.append(function.start)
            ends.append(function.end)
    for item in _top_level_items(root):
        if syntax.overlaps(item, span_start, span_end):
            starts.append(source.line_start(syntax.start_line(item)))
            ends.append(source.line_end(syntax.end_line(item)))
    start, end = min(starts), max(ends)
    grown_first, grown_last = source.line_of(start), source.line_of(max(start, end - 1))
    if (grown_first, grown_last) != (first, last):
        notes.append(
            f"Lines {first}-{last} grew to {grown_first}-{grown_last} to cover whole items."
        )
    return Region(start, end, "lines", f"lines {grown_first}-{grown_last}")


def _top_level_items(root: Node) -> list[Node]:
    items = []
    stack = [root]
    while stack:
        node = stack.pop()
        for child in node.named_children:
            if child.type in syntax.TOP_LEVEL_CONTAINERS:
                stack.append(child)
            elif child.type not in TOP_LEVEL_SKIP:
                items.append(child)
    return items


def merge(source: SourceText, regions: Sequence[Region]) -> list[Region]:
    """Regions in order, with overlapping ones and ones only white space apart joined."""
    ordered = sorted(regions, key=lambda region: (region.start, region.end, region.is_slot))
    merged: list[Region] = []
    for region in ordered:
        if not merged:
            merged.append(region)
            continue
        previous = merged[-1]
        gap = source.data[previous.end : region.start] if region.start > previous.end else b""
        touches = region.start <= previous.end or not gap.strip()
        if touches:
            merged[-1] = _join(previous, region)
        else:
            merged.append(region)
    return merged


def _join(first: Region, second: Region) -> Region:
    if second.is_slot and first.start <= second.start <= first.end and not first.is_slot:
        return first
    if first.is_slot and second.start <= first.start <= second.end and not second.is_slot:
        return second
    if first.is_slot and second.is_slot:
        return first
    kind = first.kind if first.kind == second.kind else "lines"
    labels = first.label if first.label == second.label else f"{first.label} + {second.label}"
    function = first.function if first.function == second.function else None
    return Region(
        min(first.start, second.start), max(first.end, second.end), kind, labels, function
    )


def describe(source: SourceText, region: Region) -> str:
    if region.is_slot:
        return f"{region.label} (empty; at line {source.line_of(region.start)})"
    first = source.line_of(region.start)
    last = source.line_of(max(region.start, region.end - 1))
    return f"{region.label} (lines {first}-{last})"
