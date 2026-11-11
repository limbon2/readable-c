"""The C language features a stretch of code uses.

Without a compiler, the main protection against an edit that does not compile
is to use only what the file already uses: a C89 code base rejects `//`
comments, declarations after statements and `bool`.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING

from . import lexer, syntax

if TYPE_CHECKING:
    from tree_sitter import Node

    from .source import SourceText

CONSTRUCTS = {
    "line-comment": "`//` comments",
    "mixed-declarations": "declarations after statements in a block",
    "for-declaration": "declarations in a `for` initializer",
    "bool": "`bool`, `true` and `false` from <stdbool.h>",
    "_Bool": "the `_Bool` type",
    "inline": "`inline` functions",
    "designated-initializer": "designated initializers (`.field =`, `[index] =`)",
    "compound-literal": "compound literals (`(type){ ... }`)",
    "restrict": "`restrict` pointers",
    "long-long": "`long long`",
    "static-assert": "`_Static_assert`",
    "func-name": "`__func__`",
}

C99_HINTS = (
    "line-comment",
    "mixed-declarations",
    "for-declaration",
    "bool",
    "designated-initializer",
)

_LONG_LONG_SUFFIX = re.compile(r"[lL]{2}[uU]?$|[uU][lL]{2}$")


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

    def note(construct: str, line: int) -> None:
        found.setdefault(construct, line)

    for token in tokens:
        is_in_range = start <= token.start < stop
        is_line_comment = token.kind == lexer.COMMENT and token.text.startswith(b"//")
        if is_in_range and is_line_comment:
            note("line-comment", source.line_of(token.start))
    for node in _nodes_in_range(root, start, stop):
        construct = _construct_of(node)
        if construct is not None:
            note(construct, syntax.start_line(node))
    return found


def _nodes_in_range(root: Node, start: int, stop: int) -> list[Node]:
    result = []
    stack = [root]
    while stack:
        node = stack.pop()
        if not syntax.overlaps(node, start, stop):
            continue
        if start <= node.start_byte:
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
    ("identifier", "_Static_assert"): "static-assert",
    ("identifier", "static_assert"): "static-assert",
    ("identifier", "__func__"): "func-name",
}


def _construct_of(node: Node) -> str | None:
    node_type = node.type
    if node_type == "compound_literal_expression":
        return "compound-literal"
    if node_type == "compound_statement":
        return "mixed-declarations" if _declares_after_statement(node) else None
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


def _declares_after_statement(block: Node) -> bool:
    seen_statement = False
    for child in block.named_children:
        is_declaration = child.type in DECLARATION_TYPES
        if is_declaration and seen_statement:
            return True
        is_neutral = child.type == "comment" or child.type.startswith("preproc")
        if not is_neutral and not is_declaration:
            seen_statement = True
    return False


def new_constructs(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    """Constructs that `after` uses and `before` never did."""
    return {construct: line for construct, line in after.items() if construct not in before}


def looks_like_c89(constructs: dict[str, int]) -> bool:
    return not any(construct in constructs for construct in C99_HINTS)
