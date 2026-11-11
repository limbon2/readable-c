"""The names a file declares at file scope: functions, globals, types, constants, macros."""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import lexer, syntax

if TYPE_CHECKING:
    from tree_sitter import Node

    from .source import SourceText

_WHITESPACE = re.compile(rb"\s+")


@dataclass(frozen=True)
class Declaration:
    name: str
    kind: str
    start: int
    end: int
    signature: str


class FileDeclarations:
    """File-scope declarations by name. A name can be declared more than once."""

    def __init__(self, declarations: list[Declaration]) -> None:
        self.all = declarations
        self.by_name: dict[str, list[Declaration]] = {}
        for declaration in declarations:
            self.by_name.setdefault(declaration.name, []).append(declaration)

    def names(self) -> set[str]:
        return set(self.by_name)

    def within(self, start: int, end: int) -> list[Declaration]:
        return [item for item in self.all if start <= item.start < end]


def collect(source: SourceText, root: Node, tokens: Sequence[lexer.Token]) -> FileDeclarations:
    found: list[Declaration] = []
    for node in _top_level_nodes(root):
        found.extend(_declarations_of(source, node, tokens))
    for token in tokens:
        macro = lexer.macro_definition(token)
        if macro is not None:
            found.append(
                Declaration(
                    macro.name.decode("utf-8", "surrogateescape"),
                    "macro",
                    token.start,
                    token.end,
                    lexer.normalize_directive(token.text).decode("utf-8", "surrogateescape"),
                )
            )
    return FileDeclarations(sorted(found, key=lambda item: item.start))


def _top_level_nodes(root: Node) -> Iterator[Node]:
    stack = [root]
    while stack:
        node = stack.pop()
        for child in reversed(node.named_children):
            if child.type in syntax.TOP_LEVEL_CONTAINERS or child.type == "ERROR":
                stack.append(child)
            else:
                yield child


def _declarations_of(
    source: SourceText, node: Node, tokens: Sequence[lexer.Token]
) -> list[Declaration]:
    if node.type == "function_definition":
        name = syntax.function_name(node)
        if name is None:
            return []
        return [
            Declaration(
                name,
                "function",
                node.start_byte,
                node.end_byte,
                function_signature(source, node, tokens),
            )
        ]
    if node.type in ("declaration", "type_definition"):
        return _declared_names(source, node, tokens)
    if node.type in ("struct_specifier", "union_specifier", "enum_specifier"):
        return _tags_and_enumerators(source, node, tokens)
    return []


def _declared_names(
    source: SourceText, node: Node, tokens: Sequence[lexer.Token]
) -> list[Declaration]:
    result = []
    type_node = node.child_by_field_name("type")
    if type_node is not None:
        result.extend(_tags_and_enumerators(source, type_node, tokens))
    for declarator in node.children_by_field_name("declarator"):
        inner = (
            declarator.child_by_field_name("declarator")
            if declarator.type == "init_declarator"
            else declarator
        )
        name = syntax.declared_name(inner)
        if name is None:
            continue
        if node.type == "type_definition":
            kind = "typedef"
        elif _declares_function(inner):
            kind = "prototype"
        else:
            kind = "variable"
        signature = _without_initializers(source, node, tokens)
        result.append(
            Declaration(syntax.text(name), kind, node.start_byte, node.end_byte, signature)
        )
    return result


def _tags_and_enumerators(
    source: SourceText, node: Node, tokens: Sequence[lexer.Token]
) -> list[Declaration]:
    result = []
    name = node.child_by_field_name("name")
    body = node.child_by_field_name("body")
    if name is not None and body is not None:
        kind = node.type.removesuffix("_specifier")
        result.append(
            Declaration(
                syntax.text(name),
                kind,
                node.start_byte,
                node.end_byte,
                _clean(source, node, tokens),
            )
        )
    if node.type == "enum_specifier" and body is not None:
        for enumerator in body.named_children:
            constant = enumerator.child_by_field_name("name")
            if enumerator.type == "enumerator" and constant is not None:
                result.append(
                    Declaration(
                        syntax.text(constant),
                        "enum-constant",
                        enumerator.start_byte,
                        enumerator.end_byte,
                        _clean(source, enumerator, tokens),
                    )
                )
    return result


def _declares_function(declarator: Node | None) -> bool:
    current = declarator
    while current is not None and current.type not in syntax.NAME_NODE_TYPES:
        if current.type == "function_declarator":
            return True
        if current.type == "parenthesized_declarator":
            return False
        current = current.child_by_field_name("declarator")
    return False


def function_signature(source: SourceText, function: Node, tokens: Sequence[lexer.Token]) -> str:
    """The definition's head without parameter names, comments or layout."""
    body = function.child_by_field_name("body")
    end = body.start_byte if body is not None else function.end_byte
    removed = [
        (name.start_byte, name.end_byte)
        for parameter in syntax.parameter_nodes(function)
        if parameter.type == "parameter_declaration"
        for name in [syntax.declared_name(parameter.child_by_field_name("declarator"))]
        if name is not None
    ]
    return _text_without(source, function.start_byte, end, removed, tokens)


def _without_initializers(source: SourceText, node: Node, tokens: Sequence[lexer.Token]) -> str:
    removed = []
    for declarator in node.children_by_field_name("declarator"):
        value = (
            declarator.child_by_field_name("value")
            if declarator.type == "init_declarator"
            else None
        )
        if value is not None:
            removed.append((value.start_byte, value.end_byte))
    return _text_without(source, node.start_byte, node.end_byte, removed, tokens)


def _clean(source: SourceText, node: Node, tokens: Sequence[lexer.Token]) -> str:
    return _text_without(source, node.start_byte, node.end_byte, [], tokens)


def _text_without(
    source: SourceText,
    start: int,
    end: int,
    removed: list[tuple[int, int]],
    tokens: Sequence[lexer.Token],
) -> str:
    """The text of [start, end) without the removed spans and comments, on one line."""
    cuts = sorted(
        [
            *removed,
            *(
                (token.start, token.end)
                for token in lexer.tokens_between(tokens, start, end)
                if token.kind == lexer.COMMENT
            ),
        ]
    )
    pieces = []
    cursor = start
    for cut_start, cut_end in cuts:
        if cut_start < cursor:
            continue
        pieces.append(source.data[cursor:cut_start])
        cursor = cut_end
    pieces.append(source.data[cursor:end])
    joined = _WHITESPACE.sub(b" ", b" ".join(pieces)).strip()
    tidied = _SPACE_BEFORE_CLOSER.sub(rb"\1", _SPACE_AFTER_OPENER.sub(rb"\1", joined))
    return tidied.decode("utf-8", "surrogateescape")


_SPACE_BEFORE_CLOSER = re.compile(rb"\s+([),;\]])")
_SPACE_AFTER_OPENER = re.compile(rb"([(\[])\s+")
