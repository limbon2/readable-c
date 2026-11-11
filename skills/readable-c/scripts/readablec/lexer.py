"""A small C lexer over bytes.

It never fails: a byte it does not recognize becomes an OTHER token, and an
unterminated comment or literal ends at the end of its line or of the file. The
guard uses it to tell whether the code next to a region still means the same
after an edit, so it follows the rules that carry meaning across lines: block
comments, line continuations and preprocessor directives.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

IDENTIFIER = "identifier"
NUMBER = "number"
STRING = "string"
CHAR = "char"
PUNCTUATOR = "punctuator"
COMMENT = "comment"
DIRECTIVE = "directive"
OTHER = "other"

CONTINUED_LINE = "continued line"

_TOKEN_PATTERN = re.compile(
    rb"""
      (?P<newline>\n)
    | (?P<space>[ \t\f\v\r]+)
    | (?P<splice>\\\r?\n)
    | (?P<block_comment>/\*.*?(?P<block_end>\*/|\Z))
    | (?P<line_comment>//(?:\\\r?\n|[^\n])*)
    | (?P<string>(?:u8|[uUL])?"(?:\\\r\n|\\.|[^"\\\n])*(?P<string_end>")?)
    | (?P<char>(?:u8|[uUL])?'(?:\\\r\n|\\.|[^'\\\n])*(?P<char_end>')?)
    | (?P<identifier>[A-Za-z_$\x80-\xff][A-Za-z0-9_$\x80-\xff]*)
    | (?P<number>\.?[0-9](?:[eEpP][+-]|[0-9A-Za-z_.])*)
    | (?P<punctuator>\.\.\.|<<=|>>=|->|\+\+|--|<<|>>|<=|>=|==|!=|&&|\|\||[*/%+\-&^|]=|\#\#
                     |[\[\](){}.&*+\-~!/%<>^|?:;=,\#])
    | (?P<other>.)
    """,
    re.VERBOSE | re.DOTALL,
)

# A directive runs to the end of its line, across continuations and across
# block comments that span lines.
_DIRECTIVE_PATTERN = re.compile(rb"\#(?:\\\r?\n|/\*.*?\*/|[^\n])*", re.DOTALL)

_DIRECTIVE_NOISE = re.compile(rb"/\*.*?\*/|//[^\n]*|\\\r?\n", re.DOTALL)
_WHITESPACE_RUN = re.compile(rb"[ \t\f\v\r\n]+")

CONDITIONAL_OPENERS = {b"if", b"ifdef", b"ifndef"}
CONDITIONAL_BRANCHES = {b"elif", b"elifdef", b"elifndef", b"else"}

DEPTH_CHANGES = {
    b"{": ("braces", 1),
    b"}": ("braces", -1),
    b"(": ("parens", 1),
    b")": ("parens", -1),
    b"[": ("brackets", 1),
    b"]": ("brackets", -1),
}


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    start: int
    end: int
    text: bytes
    terminated: bool = True


def tokenize(data: bytes) -> list[Token]:
    """Every token of `data`, comments and directives included, in order."""
    tokens: list[Token] = []
    position = 0
    at_line_start = True
    while position < len(data):
        starts_directive = at_line_start and data[position] == ord("#")
        if starts_directive:
            tokens.append(_directive_token(data, position))
            position = tokens[-1].end
            at_line_start = False
            continue
        match = _TOKEN_PATTERN.match(data, position)
        assert match is not None, "the pattern ends with a catch-all alternative"
        kind = match.lastgroup
        if kind == "newline":
            at_line_start = True
        elif kind not in ("space", "splice"):
            token = _token_from_match(match, kind)
            tokens.append(token)
            # Comments count as white space, so `/* x */ #define` is still a directive.
            at_line_start = at_line_start and token.kind == COMMENT
        position = match.end()
    return tokens


def _directive_token(data: bytes, start: int) -> Token:
    match = _DIRECTIVE_PATTERN.match(data, start)
    assert match is not None, "the pattern matches a lone #"
    end = match.end()
    if data[end - 1 : end] == b"\r":
        end -= 1
    return Token(DIRECTIVE, start, end, data[start:end])


def _token_from_match(match: re.Match[bytes], kind: str | None) -> Token:
    start, end = match.span()
    text = match.group()
    if kind == "block_comment":
        return Token(COMMENT, start, end, text, terminated=match.group("block_end") == b"*/")
    if kind == "line_comment":
        return Token(COMMENT, start, end, text)
    if kind == "string":
        return Token(STRING, start, end, text, terminated=match.group("string_end") is not None)
    if kind == "char":
        return Token(CHAR, start, end, text, terminated=match.group("char_end") is not None)
    simple_kinds = {
        "identifier": IDENTIFIER,
        "number": NUMBER,
        "punctuator": PUNCTUATOR,
    }
    return Token(simple_kinds.get(kind or "", OTHER), start, end, text)


def normalize_directive(text: bytes) -> bytes:
    """A directive without comments, continuations or extra white space: `#if X`."""
    without_noise = _DIRECTIVE_NOISE.sub(b" ", text)
    collapsed = _WHITESPACE_RUN.sub(b" ", without_noise).strip()
    return b"#" + collapsed[1:].lstrip()


def directive_name(text: bytes) -> bytes:
    """The directive's keyword, such as `define` or `ifdef`; empty for a lone `#`."""
    words = normalize_directive(text)[1:].split(b" ", 1)
    keyword = re.match(rb"[A-Za-z_]+", words[0])
    return keyword.group() if keyword else b""


@dataclass(frozen=True)
class MacroDefinition:
    name: bytes
    parameters: tuple[bytes, ...] | None
    body: bytes
    start: int
    end: int

    @property
    def is_function_like(self) -> bool:
        return self.parameters is not None


_DEFINE_PATTERN = re.compile(
    rb"\#\s*define\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)(?P<params>\([^)]*\))?(?P<body>.*)\Z",
    re.DOTALL,
)


def macro_definition(token: Token) -> MacroDefinition | None:
    """The macro a `#define` token defines, or None for other tokens."""
    if token.kind != DIRECTIVE:
        return None
    match = _DEFINE_PATTERN.match(normalize_directive(token.text))
    if match is None:
        return None
    parameters = None
    if match.group("params") is not None:
        inside = match.group("params")[1:-1]
        parameters = tuple(part.strip() for part in inside.split(b",") if part.strip())
    return MacroDefinition(
        name=match.group("name"),
        parameters=parameters,
        body=match.group("body").strip(),
        start=token.start,
        end=token.end,
    )


@dataclass(frozen=True)
class LexicalContext:
    """What the lexer is in the middle of at one position.

    Two copies of the same text mean the same thing when they start in equal
    contexts, which is how the guard checks the code between regions.
    """

    inside: str | None
    braces: int
    parens: int
    brackets: int
    conditionals: tuple[bytes, ...]


def contexts_at(
    data: bytes, tokens: Sequence[Token], offsets: Iterable[int]
) -> list[LexicalContext]:
    """The lexical context at each offset, in the order the offsets are given."""
    ordered = sorted(enumerate(offsets), key=lambda pair: pair[1])
    results: list[LexicalContext | None] = [None] * len(ordered)
    depths = {"braces": 0, "parens": 0, "brackets": 0}
    conditionals: list[bytes] = []
    token_index = 0
    for result_index, offset in ordered:
        while token_index < len(tokens) and tokens[token_index].end <= offset:
            _apply_token(tokens[token_index], depths, conditionals)
            token_index += 1
        inside = None
        covers_offset = token_index < len(tokens) and tokens[token_index].start < offset
        if covers_offset:
            inside = tokens[token_index].kind
        elif _follows_continuation(data, offset):
            inside = CONTINUED_LINE
        results[result_index] = LexicalContext(
            inside=inside,
            braces=depths["braces"],
            parens=depths["parens"],
            brackets=depths["brackets"],
            conditionals=tuple(conditionals),
        )
    return [result for result in results if result is not None]


def _apply_token(token: Token, depths: dict[str, int], conditionals: list[bytes]) -> None:
    if token.kind == PUNCTUATOR and token.text in DEPTH_CHANGES:
        counter, change = DEPTH_CHANGES[token.text]
        depths[counter] += change
    elif token.kind == DIRECTIVE:
        name = directive_name(token.text)
        normalized = normalize_directive(token.text)
        if name in CONDITIONAL_OPENERS:
            conditionals.append(normalized)
        elif name in CONDITIONAL_BRANCHES and conditionals:
            conditionals[-1] = conditionals[-1] + b" | " + normalized
        elif name == b"endif":
            if conditionals:
                conditionals.pop()
            else:
                conditionals.append(b"#endif without #if")


def _follows_continuation(data: bytes, offset: int) -> bool:
    preceding = data[max(0, offset - 3) : offset]
    return preceding.endswith((b"\\\n", b"\\\r\n"))


def significant(tokens: Iterable[Token]) -> list[tuple[str, bytes]]:
    """The tokens that carry meaning: no comments, directives without their spelling."""
    result = []
    for token in tokens:
        if token.kind == COMMENT:
            continue
        text = normalize_directive(token.text) if token.kind == DIRECTIVE else token.text
        result.append((token.kind, text))
    return result


def tokens_between(tokens: Sequence[Token], start: int, end: int) -> list[Token]:
    """The tokens that start inside [start, end)."""
    return [token for token in tokens if start <= token.start < end]
