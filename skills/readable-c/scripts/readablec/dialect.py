"""The tracked C language features a stretch of code uses."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import lexer, syntax
from .standard import C23

if TYPE_CHECKING:
    from tree_sitter import Node

    from .source import SourceText

CONSTRUCTS = {
    "line-comment": "`//` comments",
    "mixed-declarations": "declarations after statements in a block",
    "for-declaration": "declarations in a `for` initializer",
    "bool": "`bool`, `true` and `false`",
    "_Bool": "the `_Bool` type",
    "inline": "`inline` functions",
    "designated-initializer": "designated initializers (`.field =`, `[index] =`)",
    "compound-literal": "compound literals (`(type){ ... }`)",
    "restrict": "`restrict` pointers",
    "long-long": "`long long`",
    "static-assert": "`_Static_assert` or `static_assert`",
    "static-assert-one-argument": "a static assertion without a message",
    "generic": "`_Generic` selections",
    "constexpr": "`constexpr` constants",
    "nullptr": "`nullptr`",
    "attribute": "`[[...]]` attributes",
    "func-name": "`__func__`",
}

MINIMUM_EDITION = {
    **dict.fromkeys(CONSTRUCTS, 1999),
    "static-assert": 2011,
    "generic": 2011,
    "static-assert-one-argument": C23,
    "constexpr": C23,
    "nullptr": C23,
    "attribute": C23,
}

_LONG_LONG_SUFFIX = re.compile(r"[lL]{2}[uU]?$|[uU][lL]{2}$")


@dataclass(frozen=True)
class Occurrence:
    kind: str
    start: int
    spelling: str = ""
    depends_on: int | None = None

    @property
    def identity(self) -> tuple[str, str]:
        return self.kind, self.spelling


def find_constructs(
    source: SourceText,
    root: Node,
    tokens: Sequence[lexer.Token],
    start: int = 0,
    end: int | None = None,
) -> dict[str, int]:
    """Each construct used in [start, end), with the first line that uses it."""
    stop = end if end is not None else len(source.data)
    found: dict[str, int] = {}
    for occurrence in occurrences(root, tokens, start, stop):
        offset = occurrence.start
        if offset >= stop and occurrence.depends_on is not None:
            offset = occurrence.depends_on
        found.setdefault(occurrence.kind, source.line_of(offset))
    return found


def occurrences(
    root: Node, tokens: Sequence[lexer.Token], start: int, stop: int
) -> list[Occurrence]:
    found = []
    for token in tokens:
        is_in_range = start <= token.start < stop
        is_line_comment = token.kind == lexer.COMMENT and token.text.startswith(b"//")
        if is_in_range and is_line_comment:
            found.append(Occurrence("line-comment", token.start))
    for node in _nodes_in_range(root, start, stop):
        if node.type == "compound_statement":
            found.extend(_mixed_declarations(node, start, stop))
        if node.start_byte < start:
            continue
        if node.type == "call_expression":
            assertion = _assertion(node)
            if assertion is not None:
                found.append(assertion)
        construct = _construct_of(node)
        if construct is None:
            continue
        spelling = syntax.text(node) if construct == "bool" else ""
        found.append(Occurrence(construct, node.start_byte, spelling))
    return found


def _nodes_in_range(root: Node, start: int, stop: int) -> list[Node]:
    result = []
    stack = [root]
    while stack:
        node = stack.pop()
        if not syntax.overlaps(node, start, stop):
            continue
        result.append(node)
        stack.extend(reversed(node.children))
    return result


# Constructs recognized by a node's type and spelling.
_SPELLED_CONSTRUCTS = {
    ("primitive_type", "bool"): "bool",
    ("true", "true"): "bool",
    ("false", "false"): "bool",
    ("primitive_type", "_Bool"): "_Bool",
    ("type_identifier", "_Bool"): "_Bool",
    ("storage_class_specifier", "inline"): "inline",
    ("type_qualifier", "restrict"): "restrict",
    ("type_qualifier", "constexpr"): "constexpr",
    ("null", "nullptr"): "nullptr",
    ("identifier", "__func__"): "func-name",
}

_NODE_CONSTRUCTS = {
    "compound_literal_expression": "compound-literal",
    "generic_expression": "generic",
    "attribute_declaration": "attribute",
}


def _construct_of(node: Node) -> str | None:
    node_type = node.type
    if node_type in _NODE_CONSTRUCTS:
        return _NODE_CONSTRUCTS[node_type]
    if node_type == "for_statement":
        initializer = node.child_by_field_name("initializer")
        is_declaration = initializer is not None and initializer.type == "declaration"
        return "for-declaration" if is_declaration else None
    if node_type == "initializer_pair":
        is_designated = node.child_by_field_name("designator") is not None
        return "designated-initializer" if is_designated else None
    spelling = syntax.text(node) if node.child_count == 0 or node_type in _SPELLED else ""
    if _is_long_long(node_type, spelling):
        return "long-long"
    return _SPELLED_CONSTRUCTS.get((node_type, spelling))


def _assertion(node: Node) -> Occurrence | None:
    call = node.child_by_field_name("function")
    if call is None or call.type != "identifier":
        return None
    spelling = syntax.text(call)
    if spelling not in {"_Static_assert", "static_assert"}:
        return None
    arguments = node.child_by_field_name("arguments")
    one_argument = arguments is not None and len(syntax.named_children(arguments)) == 1
    kind = "static-assert-one-argument" if one_argument else "static-assert"
    return Occurrence(kind, node.start_byte, spelling)


def _is_long_long(node_type: str, spelling: str) -> bool:
    if node_type == "sized_type_specifier":
        return spelling.split().count("long") > 1
    return node_type == "number_literal" and bool(_LONG_LONG_SUFFIX.search(spelling))


# Node types whose whole text is worth reading even though they have children.
_SPELLED = {
    "storage_class_specifier",
    "type_qualifier",
    "sized_type_specifier",
    "true",
    "false",
    "null",
    "primitive_type",
    "type_identifier",
}


# A local `enum { ... };` or `struct s { ... };` parses as a bare specifier, but it
# is a declaration all the same.
DECLARATION_TYPES = {
    "declaration",
    "type_definition",
    "enum_specifier",
    "struct_specifier",
    "union_specifier",
}


def _mixed_declarations(block: Node, start: int, stop: int) -> list[Occurrence]:
    found = []
    first_statement = None
    for child in block.named_children:
        is_declaration = child.type in DECLARATION_TYPES
        if is_declaration and first_statement is not None:
            is_in_range = start <= child.start_byte < stop or start <= first_statement < stop
            if is_in_range:
                found.append(
                    Occurrence("mixed-declarations", child.start_byte, depends_on=first_statement)
                )
        is_neutral = child.type == "comment" or child.type.startswith("preproc")
        if first_statement is None and not is_neutral and not is_declaration:
            first_statement = child.start_byte
    return found


def new_constructs(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    """Constructs that `after` uses and `before` never did."""
    return {construct: line for construct, line in after.items() if construct not in before}
