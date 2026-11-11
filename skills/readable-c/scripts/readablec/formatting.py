"""clang-format, applied only inside the regions.

clang-format's --lines option can still touch text outside the given lines, so
the tool formats the whole file in memory, asks for the list of replacements,
and applies only those that fall inside a region. Options that change tokens
rather than layout are turned off, and the result must have the same tokens.
"""

from __future__ import annotations

import html
import re
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from . import lexer

Span = tuple[int, int]

CONFIG_NAMES = (".clang-format", "_clang-format")

# The project's style, minus every option that can change tokens or touch
# lines outside the regions.
SAFE_STYLE = (
    "{BasedOnStyle: InheritParentConfig, InsertBraces: false, RemoveBracesLLVM: false, "
    "RemoveParentheses: Leave, RemoveSemicolon: false, QualifierAlignment: Leave, "
    "SortIncludes: {Enabled: false}, ReflowComments: Never, InsertNewlineAtEOF: false, "
    "IntegerLiteralSeparator: {Binary: 0, Decimal: 0, Hex: 0}}"
)


class FormatError(RuntimeError):
    """clang-format is missing or failed."""


@dataclass
class FormatResult:
    data: bytes
    applied: int
    skipped: int
    config: Path


def find_config(path: Path) -> Path | None:
    for folder in path.resolve().parents:
        for name in CONFIG_NAMES:
            candidate = folder / name
            if candidate.is_file():
                return candidate
    return None


def executable() -> str | None:
    try:
        import clang_format  # noqa: PLC0415  optional: the tool works without it

        return clang_format.get_executable("clang-format")
    except (ImportError, AttributeError, OSError):
        return shutil.which("clang-format")


def version() -> str | None:
    program = executable()
    if program is None:
        return None
    completed = subprocess.run([program, "--version"], capture_output=True, check=False)
    return completed.stdout.decode("utf-8", "replace").strip() or None


def format_regions(path: Path, data: bytes, spans: Sequence[Span]) -> FormatResult:
    config = find_config(path)
    if config is None:
        raise FormatError(
            "The project has no .clang-format, so there is no agreed style to apply. Match the "
            "surrounding code by hand (see the conventions that `start` printed)."
        )
    program = executable()
    if program is None:
        raise FormatError(
            "clang-format is not available. Run the tool through `uv run`, which installs it."
        )
    completed = subprocess.run(
        [
            program,
            f"--assume-filename={path}",
            f"--style={SAFE_STYLE}",
            "--output-replacements-xml",
        ],
        input=data,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", "replace").strip()
        raise FormatError(f"clang-format failed: {message}")
    replacements = _parse_replacements(completed.stdout)
    inside = [item for item in replacements if _is_inside(item, spans)]
    formatted = _apply(data, inside)
    _require_same_tokens(data, formatted, spans, inside)
    return FormatResult(formatted, len(inside), len(replacements) - len(inside), config)


def _parse_replacements(xml: bytes) -> list[tuple[int, int, bytes]]:
    """clang-format's replacement list. Its shape is fixed, so a pattern reads it without an XML parser."""
    text = xml.decode("utf-8")
    return [
        (
            int(match.group("offset")),
            int(match.group("length")),
            html.unescape(match.group("text")).encode("utf-8"),
        )
        for match in _REPLACEMENT.finditer(text)
    ]


_REPLACEMENT = re.compile(
    r"<replacement offset='(?P<offset>\d+)' length='(?P<length>\d+)'>(?P<text>[^<]*)</replacement>"
)


def _is_inside(replacement: tuple[int, int, bytes], spans: Sequence[Span]) -> bool:
    offset, length, _ = replacement
    end = offset + length
    return any(start <= offset and end <= stop and offset < stop for start, stop in spans)


def _apply(data: bytes, replacements: list[tuple[int, int, bytes]]) -> bytes:
    result = bytearray(data)
    for offset, length, text in sorted(replacements, reverse=True):
        result[offset : offset + length] = text
    return bytes(result)


def _require_same_tokens(
    before: bytes, after: bytes, spans: Sequence[Span], applied: list[tuple[int, int, bytes]]
) -> None:
    def moved(position: int) -> int:
        return position + sum(
            len(text) - length for offset, length, text in applied if offset < position
        )

    old_tokens = _tokens_in(lexer.tokenize(before), spans)
    new_tokens = _tokens_in(
        lexer.tokenize(after), [(moved(start), moved(end)) for start, end in spans]
    )
    if old_tokens != new_tokens:
        raise FormatError(
            "clang-format would change tokens, not only layout; the file was left as it was."
        )


def _tokens_in(tokens: list[lexer.Token], spans: Sequence[Span]) -> list[tuple[str, bytes]]:
    return lexer.significant(
        token for start, end in spans for token in lexer.tokens_between(tokens, start, end)
    )
