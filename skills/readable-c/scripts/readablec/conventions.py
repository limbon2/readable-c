"""How a file is written, so that new code in a region blends in with the rest."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from . import dialect, lexer, syntax
from .encoding import EncodingInfo, detect_encoding

if TYPE_CHECKING:
    from tree_sitter import Node

    from .source import SourceText

BOOLEAN_TYPEDEFS = ("BOOL", "BOOLEAN", "boolean", "bool_t", "boolean_t", "Bool", "gboolean")

NAMING_STYLES = (
    ("UPPER_CASE", re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$|^[A-Z]{2,}[0-9]*$")),
    ("snake_case", re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")),
    ("camelCase", re.compile(r"^[a-z][a-z0-9]*(?:[A-Z][a-z0-9]*)+$")),
    ("PascalCase", re.compile(r"^[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)*$")),
    ("lowercase", re.compile(r"^[a-z][a-z0-9]*$")),
)

SPACE_INDENT_WIDTHS = (8, 4, 3, 2)


@dataclass
class Conventions:
    line_endings: str
    dominant_line_ending: bytes
    has_bom: bool
    encoding: EncodingInfo
    ends_with_line_break: bool
    indent_char: str
    indent_width: int | None
    function_brace: str
    block_brace: str
    constructs: dict[str, int]
    boolean_type: str
    naming: dict[str, str] = field(default_factory=dict)
    constant_style: str = "unknown"
    longest_line: int = 0
    typical_line_limit: int = 0

    @property
    def looks_like_c89(self) -> bool:
        return dialect.looks_like_c89(self.constructs)

    @property
    def allows_mixed_declarations(self) -> bool:
        return "mixed-declarations" in self.constructs

    def describe(self) -> list[str]:
        indent = self.indent_char
        if self.indent_width:
            indent += f", width {self.indent_width}"
        if self.looks_like_c89:
            dialect_note = (
                "no C99 features seen: declare variables at the start of a block, "
                "use /* */ comments, no bool"
            )
        else:
            used = ", ".join(sorted(name for name in self.constructs if name in dialect.C99_HINTS))
            dialect_note = f"C99 features in use: {used}"
        naming = ", ".join(f"{kind}: {style}" for kind, style in sorted(self.naming.items()))
        return [
            f"line endings: {self.line_endings}"
            + (", UTF-8 BOM" if self.has_bom else "")
            + ("" if self.ends_with_line_break else ", no line break at the end"),
            f"encoding: {self.encoding.describe()}",
            f"indentation: {indent}",
            f"braces: functions {self.function_brace}, blocks {self.block_brace}",
            f"dialect: {dialect_note}",
            f"boolean type: {self.boolean_type}",
            f"naming: {naming or 'not enough names to tell'}",
            f"constants: {self.constant_style}",
            f"line length: most lines fit in {self.typical_line_limit} columns "
            f"(longest {self.longest_line})",
        ]


def detect(source: SourceText, root: Node, tokens: Sequence[lexer.Token]) -> Conventions:
    indent_char, indent_width = _indentation(source, tokens)
    lengths = sorted(len(source.line_bytes(line)) for line in range(1, source.line_count + 1))
    return Conventions(
        line_endings=source.line_endings.describe(),
        dominant_line_ending=source.line_endings.dominant,
        has_bom=source.has_bom,
        encoding=detect_encoding(source.data),
        ends_with_line_break=source.ends_with_line_break,
        indent_char=indent_char,
        indent_width=indent_width,
        function_brace=_function_brace_style(root),
        block_brace=_block_brace_style(root),
        constructs=dialect.find_constructs(source, root, tokens),
        boolean_type=_boolean_type(root, tokens),
        naming=_naming(root, tokens),
        constant_style=_constant_style(root, tokens),
        longest_line=lengths[-1] if lengths else 0,
        typical_line_limit=lengths[int(len(lengths) * 0.95)] if lengths else 0,
    )


def code_line_starts(source: SourceText, tokens: Sequence[lexer.Token]) -> list[int]:
    """Lines whose start is code: not inside a comment, string or directive continuation."""
    covered: set[int] = set()
    for token in tokens:
        spans_lines = token.kind in (lexer.COMMENT, lexer.STRING, lexer.DIRECTIVE)
        if spans_lines:
            first = source.line_of(token.start)
            last = source.line_of(max(token.start, token.end - 1))
            covered.update(range(first + 1, last + 1))
    return [line for line in range(1, source.line_count + 1) if line not in covered]


def leading_whitespace(line_bytes: bytes) -> bytes:
    return line_bytes[: len(line_bytes) - len(line_bytes.lstrip(b" \t"))]


def _indentation(source: SourceText, tokens: Sequence[lexer.Token]) -> tuple[str, int | None]:
    tab_lines = 0
    space_indents: list[int] = []
    for line in code_line_starts(source, tokens):
        content = source.line_bytes(line)
        if not content.strip():
            continue
        indent = leading_whitespace(content)
        if indent.startswith(b"\t"):
            tab_lines += 1
        elif indent:
            space_indents.append(len(indent))
    total = tab_lines + len(space_indents)
    if total == 0:
        return "unknown", None
    if tab_lines * 5 >= total * 4:
        return "tabs", None
    if len(space_indents) * 5 < total * 4:
        return "mixed tabs and spaces", None
    for width in SPACE_INDENT_WIDTHS:
        multiples = sum(1 for indent in space_indents if indent % width == 0)
        if multiples * 10 >= len(space_indents) * 9:
            return "spaces", width
    return "spaces", None


def _function_brace_style(root: Node) -> str:
    votes: Counter[str] = Counter()
    for function in syntax.function_definitions(root):
        declarator = function.child_by_field_name("declarator")
        body = function.child_by_field_name("body")
        if declarator is None or body is None:
            continue
        same_line = declarator.end_point.row == body.start_point.row
        votes["on the same line" if same_line else "on the next line"] += 1
    return _majority(votes)


def _block_brace_style(root: Node) -> str:
    votes: Counter[str] = Counter()
    for node in syntax.walk(root):
        if node.type not in ("if_statement", "while_statement", "for_statement"):
            continue
        body = node.child_by_field_name("consequence") or node.child_by_field_name("body")
        condition = node.child_by_field_name("condition")
        if body is None or condition is None or body.type != "compound_statement":
            continue
        same_line = condition.end_point.row == body.start_point.row
        votes["on the same line" if same_line else "on the next line"] += 1
    return _majority(votes)


def _majority(votes: Counter[str]) -> str:
    if not votes:
        return "unknown"
    winner, count = votes.most_common(1)[0]
    total = sum(votes.values())
    if count * 5 < total * 4:
        return f"mixed (mostly {winner})"
    return winner


def _boolean_type(root: Node, tokens: Sequence[lexer.Token]) -> str:
    includes_stdbool = any(
        token.kind == lexer.DIRECTIVE and b"stdbool.h" in token.text for token in tokens
    )
    used_types: Counter[str] = Counter()
    for node in syntax.walk(root):
        if node.type == "primitive_type" and syntax.text(node) == "bool":
            used_types["bool"] += 1
        elif node.type == "type_identifier" and syntax.text(node) in BOOLEAN_TYPEDEFS:
            used_types[syntax.text(node)] += 1
    if includes_stdbool or used_types["bool"]:
        return "bool (<stdbool.h>)"
    project_types = [name for name, _ in used_types.most_common() if name != "bool"]
    if project_types:
        return f"{project_types[0]} (a project type; check what TRUE and FALSE are)"
    return "int (no boolean type in use)"


def naming_style(name: str) -> str:
    for style, pattern in NAMING_STYLES:
        if pattern.match(name):
            return style
    return "other"


MIN_NAMES_FOR_A_STYLE = 2


def _naming(root: Node, tokens: Sequence[lexer.Token]) -> dict[str, str]:
    functions = syntax.function_definitions(root)
    names = {
        "functions": [name for name in map(syntax.function_name, functions) if name],
        "locals": [
            name
            for function in functions
            for name in _declared_names(function.child_by_field_name("body"), "declaration")
        ],
        "types": _declared_names(root, "type_definition"),
        "macros": [
            macro.name.decode("utf-8", "replace")
            for macro in map(lexer.macro_definition, tokens)
            if macro is not None
        ],
    }
    result = {}
    for kind, kind_names in names.items():
        votes = _style_votes(kind_names)
        if votes:
            result[kind] = _majority(votes)
    return result


def _declared_names(root: Node | None, node_type: str) -> list[str]:
    if root is None:
        return []
    names = []
    for node in syntax.walk(root):
        if node.type != node_type:
            continue
        for declarator in node.children_by_field_name("declarator"):
            declared = syntax.declared_name(declarator)
            if declared is not None:
                names.append(syntax.text(declared))
    return names


def _style_votes(names: list[str]) -> Counter[str]:
    """Styles of the names. Plain lowercase words fit every style, so they only count
    when nothing else does; too few names say nothing."""
    votes = Counter(naming_style(name) for name in names)
    telling = Counter({style: count for style, count in votes.items() if style != "lowercase"})
    chosen = telling or votes
    return chosen if sum(chosen.values()) >= MIN_NAMES_FOR_A_STYLE else Counter()


def _constant_style(root: Node, tokens: Sequence[lexer.Token]) -> str:
    votes: Counter[str] = Counter()
    for token in tokens:
        macro = lexer.macro_definition(token)
        is_constant_macro = (
            macro is not None and not macro.is_function_like and _is_literal(macro.body)
        )
        if is_constant_macro:
            votes["#define"] += 1
    for node in syntax.walk(root):
        if node.type == "enumerator":
            votes["enum"] += 1
        elif node.type == "declaration" and _is_const_declaration(node):
            votes["static const"] += 1
    if not votes:
        return "none defined in this file"
    return _majority(votes)


_LITERAL = re.compile(rb"^\(?\s*-?\s*(?:0[xX][0-9a-fA-F]+|[0-9][0-9.eE+-]*)[uUlLfF]*\s*\)?$")


def _is_literal(body: bytes) -> bool:
    return bool(_LITERAL.match(body))


def _is_const_declaration(declaration: Node) -> bool:
    words = {
        syntax.text(child)
        for child in declaration.children
        if child.type in ("type_qualifier", "storage_class_specifier")
    }
    return {"static", "const"} <= words
