"""Parsing C with tree-sitter, and helpers for walking the syntax tree."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tree_sitter import Node, Parser, Tree

INSTALL_HINT = (
    "The tool needs the Python packages tree-sitter and tree-sitter-c. Run it with "
    "`uv run <skill-folder>/scripts/readable_c.py`, which installs them, or install them "
    "with `pip install --only-binary :all: 'tree-sitter>=0.25,<0.27' tree-sitter-c==0.24.2`."
)

# Declarators that wrap the declared name, and the field that leads to it.
NAME_WRAPPERS = {
    "array_declarator",
    "attributed_declarator",
    "function_declarator",
    "init_declarator",
    "parenthesized_declarator",
    "pointer_declarator",
}

NAME_NODE_TYPES = {"identifier", "field_identifier", "type_identifier"}

# Containers that hold top-level items: the file, and preprocessor groups.
TOP_LEVEL_CONTAINERS = {
    "translation_unit",
    "preproc_if",
    "preproc_ifdef",
    "preproc_else",
    "preproc_elif",
    "preproc_elifdef",
    "linkage_specification",
    "declaration_list",
}


class MissingDependencyError(RuntimeError):
    """tree-sitter or its C grammar is not installed."""


@lru_cache(maxsize=1)
def _parser() -> Parser:
    try:
        import tree_sitter_c  # noqa: PLC0415  imported here so that a missing package gets a clear message
        from tree_sitter import Language, Parser  # noqa: PLC0415  same reason
    except ImportError as error:
        raise MissingDependencyError(INSTALL_HINT) from error
    return Parser(Language(tree_sitter_c.language()))


def parse(data: bytes) -> Tree:
    return _parser().parse(data)


def text(node: Node) -> str:
    """The node's source text. Bytes that are not UTF-8 survive as surrogates."""
    return (node.text or b"").decode("utf-8", errors="surrogateescape")


def walk(node: Node) -> Iterator[Node]:
    """The node and all its descendants, in source order."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def start_line(node: Node) -> int:
    return node.start_point.row + 1


def end_line(node: Node) -> int:
    return node.end_point.row + 1


def unwrap_parentheses(node: Node) -> Node:
    """The expression inside any number of parentheses."""
    current = node
    while current.type == "parenthesized_expression" and current.named_child_count == 1:
        inner = current.named_children[0]
        if inner.type == "comment":
            break
        current = inner
    return current


def named_children(node: Node) -> list[Node]:
    """Named children without comments."""
    return [child for child in node.named_children if child.type != "comment"]


def declared_name(declarator: Node | None) -> Node | None:
    """The identifier a declarator declares, through pointers, arrays and parentheses."""
    current = declarator
    while current is not None:
        if current.type in NAME_NODE_TYPES:
            return current
        if current.type not in NAME_WRAPPERS:
            return None
        inner = current.child_by_field_name("declarator")
        if inner is None:
            inner = next(
                (child for child in current.named_children if child.type != "comment"), None
            )
        current = inner
    return None


def own_function_declarator(function: Node) -> Node | None:
    """The function declarator nearest to the name, which holds the function's own parameters."""
    nearest = None
    current = function.child_by_field_name("declarator")
    while current is not None and current.type not in NAME_NODE_TYPES:
        if current.type == "function_declarator":
            nearest = current
        current = current.child_by_field_name("declarator")
    return nearest


def function_name(function: Node) -> str | None:
    name = declared_name(function.child_by_field_name("declarator"))
    return text(name) if name is not None else None


def parameter_nodes(function: Node) -> list[Node]:
    """The parameter declarations, or the bare identifiers of a K&R definition."""
    declarator = own_function_declarator(function)
    if declarator is None:
        return []
    parameters = declarator.child_by_field_name("parameters")
    if parameters is None:
        return []
    return [
        child
        for child in parameters.named_children
        if child.type in ("parameter_declaration", "identifier", "variadic_parameter")
    ]


def function_definitions(root: Node) -> list[Node]:
    """Function definitions that are not inside another function, in source order."""
    found = []
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "function_definition":
            found.append(node)
            continue
        stack.extend(reversed(node.children))
    return found


def error_nodes(root: Node) -> list[Node]:
    """ERROR nodes and zero-width MISSING nodes, outermost first."""
    found = []
    stack = [root]
    while stack:
        node = stack.pop()
        if node.is_error or node.is_missing:
            found.append(node)
            continue
        if node.has_error:
            stack.extend(reversed(node.children))
    return found


def enclosing(node: Node, types: set[str]) -> Node | None:
    current = node.parent
    while current is not None:
        if current.type in types:
            return current
        current = current.parent
    return None


def overlaps(node: Node, start: int, end: int) -> bool:
    """True when the node shares bytes with [start, end)."""
    return node.start_byte < end and start < node.end_byte
