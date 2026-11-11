"""Where each function definition is, including the ones tree-sitter cannot parse.

Tree-sitter turns some legacy definitions into ERROR nodes: K&R definitions with
implicit `int`, calling-convention macros such as `WINAPI`, and bodies whose
`#if` branches each open a brace. A text scan over the lexer's tokens finds
those, so that regions and outlines still work for them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import lexer, syntax

if TYPE_CHECKING:
    from tree_sitter import Node

    from .source import SourceText

# Words that can stand before a parenthesis in a definition's head without being
# the function's name: keywords, attributes and calling-convention helpers.
NOT_A_FUNCTION_NAME = {
    b"__asm__",
    b"__attribute__",
    b"__declspec",
    b"_Alignas",
    b"alignas",
    b"asm",
    b"auto",
    b"char",
    b"const",
    b"defined",
    b"double",
    b"enum",
    b"extern",
    b"float",
    b"for",
    b"if",
    b"int",
    b"long",
    b"register",
    b"return",
    b"short",
    b"signed",
    b"sizeof",
    b"static",
    b"struct",
    b"switch",
    b"typeof",
    b"__typeof__",
    b"union",
    b"unsigned",
    b"void",
    b"volatile",
    b"while",
}

AGGREGATE_KEYWORDS = {b"struct", b"union", b"enum"}


@dataclass(frozen=True)
class FunctionSpan:
    """A function definition. `start` includes the comments directly above it."""

    name: str
    start: int
    definition_start: int
    body_start: int
    end: int
    first_line: int
    last_line: int
    node: Node | None

    @property
    def is_parsed(self) -> bool:
        return self.node is not None


def index_functions(
    source: SourceText, root: Node, tokens: Sequence[lexer.Token]
) -> list[FunctionSpan]:
    """Every function definition in the file, in source order."""
    comments_by_end_line = _comments_by_end_line(source, tokens)
    spans = []
    for node in syntax.function_definitions(root):
        name = syntax.function_name(node)
        body = node.child_by_field_name("body")
        if name is None or body is None:
            continue
        spans.append(
            _span(
                source,
                comments_by_end_line,
                name,
                definition_start=node.start_byte,
                body_start=body.start_byte,
                definition_end=node.end_byte,
                node=node,
            )
        )
    parsed_bodies = [(span.body_start, span.end) for span in spans]
    for scanned in scan_functions(tokens):
        name, definition_start, body_start, body_end = scanned
        is_known = any(start <= body_start < end for start, end in parsed_bodies)
        if not is_known:
            spans.append(
                _span(
                    source,
                    comments_by_end_line,
                    name,
                    definition_start=definition_start,
                    body_start=body_start,
                    definition_end=body_end,
                    node=None,
                )
            )
    return sorted(spans, key=lambda span: span.start)


def _span(
    source: SourceText,
    comments_by_end_line: dict[int, lexer.Token],
    name: str,
    *,
    definition_start: int,
    body_start: int,
    definition_end: int,
    node: Node | None,
) -> FunctionSpan:
    first_line = attached_comment_line(
        source, comments_by_end_line, source.line_of(definition_start)
    )
    last_line = source.line_of(max(definition_start, definition_end - 1))
    return FunctionSpan(
        name=name,
        start=source.line_start(first_line),
        definition_start=definition_start,
        body_start=body_start,
        end=source.line_end(last_line),
        first_line=first_line,
        last_line=last_line,
        node=node,
    )


def _comments_by_end_line(
    source: SourceText, tokens: Sequence[lexer.Token]
) -> dict[int, lexer.Token]:
    found = {}
    for token in tokens:
        if token.kind == lexer.COMMENT:
            found[source.line_of(token.end - 1)] = token
    return found


def attached_comment_line(
    source: SourceText, comments_by_end_line: dict[int, lexer.Token], first_line: int
) -> int:
    """The first line of the comments directly above `first_line`, with no blank line between."""
    line = first_line
    while line > 1:
        comment = comments_by_end_line.get(line - 1)
        if comment is None:
            break
        comment_line = source.line_of(comment.start)
        text_before = source.data[source.line_start(comment_line) : comment.start]
        text_after = source.data[comment.end : source.line_end(line - 1)]
        stands_alone = not text_before.strip() and not text_after.strip()
        if not stands_alone:
            break
        line = comment_line
    return line


def scan_functions(tokens: Sequence[lexer.Token]) -> list[tuple[str, int, int, int]]:
    """Function definitions found from tokens alone: (name, start, body start, end).

    It follows the first branch of every `#if`, so bodies whose branches each
    open a brace still balance.
    """
    code = _first_branch_tokens(tokens)
    found = []
    index = 0
    while index < len(code):
        token = code[index]
        opens_brace = token.kind == lexer.PUNCTUATOR and token.text == b"{"
        if not opens_brace:
            index += 1
            continue
        closing = _matching_brace(code, index)
        head = _function_head(code, index)
        if head is not None and closing is not None:
            name_index, start_index = head
            found.append(
                (
                    code[name_index].text.decode("utf-8", "surrogateescape"),
                    code[start_index].start,
                    token.start,
                    code[closing].end,
                )
            )
        index = closing + 1 if closing is not None else index + 1
    return found


def _first_branch_tokens(tokens: Sequence[lexer.Token]) -> list[lexer.Token]:
    """Tokens without comments and without the #else and #elif branches."""
    kept = []
    skip_depth = 0
    nesting = 0
    for token in tokens:
        if token.kind == lexer.COMMENT:
            continue
        if token.kind != lexer.DIRECTIVE:
            if skip_depth == 0:
                kept.append(token)
            continue
        name = lexer.directive_name(token.text)
        if name in lexer.CONDITIONAL_OPENERS:
            nesting += 1
        elif name in lexer.CONDITIONAL_BRANCHES and skip_depth == 0:
            skip_depth = nesting
        elif name == b"endif":
            if skip_depth == nesting:
                skip_depth = 0
            nesting = max(0, nesting - 1)
        if skip_depth == 0:
            kept.append(token)
    return kept


def _matching_brace(code: Sequence[lexer.Token], open_index: int) -> int | None:
    depth = 0
    for index in range(open_index, len(code)):
        token = code[index]
        if token.kind != lexer.PUNCTUATOR:
            continue
        if token.text == b"{":
            depth += 1
        elif token.text == b"}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _function_head(code: Sequence[lexer.Token], brace_index: int) -> tuple[int, int] | None:
    """For a top-level `{`: the index of the function's name and of its first token."""
    before_brace = code[brace_index - 1] if brace_index > 0 else None
    two_before = code[brace_index - 2] if brace_index > 1 else None
    is_aggregate = any(
        candidate is not None and candidate.text in AGGREGATE_KEYWORDS
        for candidate in (before_brace, two_before)
    )
    if is_aggregate:
        return None
    paren_depth = 0
    for index in range(brace_index - 1, -1, -1):
        token = code[index]
        if token.kind == lexer.DIRECTIVE:
            return None
        if token.kind != lexer.PUNCTUATOR:
            continue
        ends_previous_item = token.text in (b"}", b"=") and paren_depth == 0
        if ends_previous_item:
            return None
        if token.text == b")":
            paren_depth += 1
        elif token.text == b"(":
            paren_depth -= 1
            name_index = index - 1
            is_name = (
                paren_depth == 0
                and name_index >= 0
                and code[name_index].kind == lexer.IDENTIFIER
                and code[name_index].text not in NOT_A_FUNCTION_NAME
            )
            if is_name:
                return name_index, _item_start(code, name_index)
    return None


def _item_start(code: Sequence[lexer.Token], name_index: int) -> int:
    """The index of the first token after the previous top-level item."""
    for index in range(name_index - 1, -1, -1):
        token = code[index]
        ends_item = token.kind == lexer.DIRECTIVE or token.text in (b";", b"}")
        if ends_item:
            return index + 1
    return 0
