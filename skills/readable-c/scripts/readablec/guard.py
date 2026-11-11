"""The guard: proof that nothing outside the regions changed, in bytes or in meaning.

The original file is a sequence F0 R1 F1 ... Rn Fn of frozen segments F and
regions R. The current file passes when it is F0 X1 F1 ... Xn Fn for some new
region texts X, and when each frozen segment still starts in the same lexical
context (not inside a comment, at the same brace depth, inside the same #if
groups), so that its unchanged bytes still parse the same way.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from . import lexer
from .issues import ERROR, REVIEW, Issue
from .regions import Region
from .source import UTF8_BOM, SourceText, count_line_endings

Span = tuple[int, int]


class AlignmentError(Exception):
    """The current text does not contain the frozen segments in order."""

    def __init__(self, segment: int, reason: str) -> None:
        super().__init__(f"segment {segment}: {reason}")
        self.segment = segment
        self.reason = reason


@dataclass
class GuardResult:
    spans: list[Span] | None
    issues: list[Issue]

    @property
    def ok(self) -> bool:
        return self.spans is not None and not any(issue.severity == ERROR for issue in self.issues)


def frozen_segments(original: bytes, regions: Sequence[Region]) -> list[bytes]:
    segments = []
    cursor = 0
    for region in regions:
        segments.append(original[cursor : region.start])
        cursor = region.end
    segments.append(original[cursor:])
    return segments


def align_segments(segments: Sequence[bytes], current: bytes) -> list[Span]:
    """Where each region lies in `current`, given the frozen segments around them."""
    first, last = segments[0], segments[-1]
    if not current.startswith(first):
        raise AlignmentError(0, "the text before the first region changed")
    if not current.endswith(last):
        raise AlignmentError(len(segments) - 1, "the text after the last region changed")
    low, high = len(first), len(current) - len(last)
    if high < low:
        raise AlignmentError(len(segments) - 1, "the file is shorter than its frozen text")
    middle = segments[1:-1]
    leftmost = _positions_from_left(middle, current, low, high)
    rightmost = _positions_from_right(middle, current, low, high)
    if leftmost != rightmost:
        raise AlignmentError(1, "the frozen text between two regions appears more than once")
    starts = [*leftmost, high]
    ends = [low] + [
        position + len(segment) for position, segment in zip(leftmost, middle, strict=True)
    ]
    return list(zip(ends, starts, strict=True))


def _positions_from_left(middle: Sequence[bytes], current: bytes, low: int, high: int) -> list[int]:
    positions = []
    cursor = low
    for index, segment in enumerate(middle, start=1):
        found = current.find(segment, cursor, high)
        if found < 0:
            raise AlignmentError(index, "the text between two regions changed")
        positions.append(found)
        cursor = found + len(segment)
    return positions


def _positions_from_right(
    middle: Sequence[bytes], current: bytes, low: int, high: int
) -> list[int]:
    positions = []
    cursor = high
    for index in range(len(middle), 0, -1):
        segment = middle[index - 1]
        found = current.rfind(segment, low, cursor)
        if found < 0:
            raise AlignmentError(index, "the text between two regions changed")
        positions.append(found)
        cursor = found
    return list(reversed(positions))


def check(original: bytes, regions: Sequence[Region], current: bytes) -> GuardResult:
    """Align the regions, then compare the context of every frozen segment and the directives."""
    try:
        spans = align_segments(frozen_segments(original, regions), current)
    except AlignmentError as error:
        return GuardResult(None, diagnose(original, regions, current, error))
    issues = boundary_issues(original, regions, current, spans)
    issues.extend(directive_issues(original, regions, current, spans))
    return GuardResult(spans, issues)


def boundary_issues(
    original: bytes, regions: Sequence[Region], current: bytes, spans: Sequence[Span]
) -> list[Issue]:
    before = lexer.contexts_at(
        original, lexer.tokenize(original), [region.end for region in regions]
    )
    after = lexer.contexts_at(current, lexer.tokenize(current), [end for _, end in spans])
    lines = SourceText(current)
    issues = []
    for number, (old, new, (_, end)) in enumerate(zip(before, after, spans, strict=True), start=1):
        if old == new:
            continue
        line = lines.line_of(end) if end < len(current) else lines.line_count
        issues.append(
            Issue(
                "guard",
                ERROR,
                f"Region {number} leaves something open, so the frozen code after it changes "
                f"meaning: {'; '.join(_context_changes(old, new))}. Close every comment, string "
                "and #if group inside the region, balance its brackets, and do not end it with "
                "a backslash.",
                line,
            )
        )
    return issues


def _context_changes(old: lexer.LexicalContext, new: lexer.LexicalContext) -> list[str]:
    changes = []
    if old.inside != new.inside:
        changes.append(f"it now starts {_where(new.inside)} (before: {_where(old.inside)})")
    for name, before, after in (
        ("brace", old.braces, new.braces),
        ("parenthesis", old.parens, new.parens),
        ("bracket", old.brackets, new.brackets),
    ):
        if before != after:
            changes.append(f"{name} depth is {after} (before: {before})")
    if old.conditionals != new.conditionals:
        changes.append(
            f"#if nesting is {_nesting(new.conditionals)} (before: {_nesting(old.conditionals)})"
        )
    return changes


def _where(inside: str | None) -> str:
    if inside is None:
        return "in plain code"
    if inside == lexer.CONTINUED_LINE:
        return "as a continuation of the line above"
    return f"inside a {inside}"


def _nesting(conditionals: tuple[bytes, ...]) -> str:
    if not conditionals:
        return "none"
    return " > ".join(entry.decode("utf-8", "replace") for entry in conditionals)


def directive_issues(
    original: bytes, regions: Sequence[Region], current: bytes, spans: Sequence[Span]
) -> list[Issue]:
    """Preprocessor directives added to or removed from the regions."""
    original_tokens = lexer.tokenize(original)
    current_tokens = lexer.tokenize(current)
    before = _directives_in(original_tokens, [(region.start, region.end) for region in regions])
    after = _directives_in(current_tokens, list(spans))
    used_outside = _identifiers_outside(original_tokens, regions)
    issues = []
    for text, count in (after - before).items():
        issues.extend(_judge_directive(text, count, "adds", used_outside))
    for text, count in (before - after).items():
        issues.extend(_judge_directive(text, count, "removes", used_outside))
    return issues


def _directives_in(tokens: Sequence[lexer.Token], spans: Sequence[Span]) -> Counter[bytes]:
    found: Counter[bytes] = Counter()
    for token in tokens:
        inside = any(start <= token.start < end for start, end in spans)
        if inside and token.kind == lexer.DIRECTIVE:
            found[lexer.normalize_directive(token.text)] += 1
    return found


def _identifiers_outside(tokens: Sequence[lexer.Token], regions: Sequence[Region]) -> set[bytes]:
    return {
        token.text
        for token in tokens
        if token.kind == lexer.IDENTIFIER
        and not any(region.start <= token.start < region.end for region in regions)
    }


def _judge_directive(text: bytes, count: int, verb: str, used_outside: set[bytes]) -> list[Issue]:
    shown = text.decode("utf-8", "replace")
    times = "" if count == 1 else f" ({count} times)"
    is_define = lexer.directive_name(text) == b"define"
    macro = (
        lexer.macro_definition(lexer.Token(lexer.DIRECTIVE, 0, len(text), text))
        if is_define
        else None
    )
    if macro is None:
        return [
            Issue(
                "directives",
                ERROR,
                f"The edit {verb} `{shown}`{times}. A region refactor keeps every include and "
                "#if, #undef and #pragma directive; propose such changes in the report instead.",
            )
        ]
    name = macro.name.decode("utf-8", "replace")
    if macro.name in used_outside:
        return [
            Issue(
                "directives",
                ERROR,
                f"The edit {verb} `{shown}`, and `{name}` is used outside the regions, so frozen "
                "code would change meaning.",
            )
        ]
    if macro.is_function_like and verb == "adds":
        return [
            Issue(
                "directives",
                ERROR,
                f"The edit adds the function-like macro `{name}`. Use a static function instead.",
            )
        ]
    return [
        Issue(
            "directives",
            REVIEW,
            f"The edit {verb} `{shown}`. Say in the report why the region needs it.",
        )
    ]


def diagnose(
    original: bytes, regions: Sequence[Region], current: bytes, error: AlignmentError
) -> list[Issue]:
    """Explain why the frozen text no longer lines up, and how to fix it."""
    causes = _byte_level_changes(original, current)
    segments = frozen_segments(original, regions)
    aligns_after_normalizing = True
    try:
        align_segments(
            _normalize_segments(segments), normalize(current, is_start=True, is_end=True).data
        )
    except AlignmentError:
        aligns_after_normalizing = False
    issues = []
    if causes and aligns_after_normalizing:
        issues.append(
            Issue(
                "guard",
                ERROR,
                "Text outside the regions changed at the byte level only: "
                + "; ".join(causes)
                + ". Your edit tool probably rewrote the whole file. Run `repair` to restore the "
                "frozen bytes and convert the regions back to the file's format.",
            )
        )
        return issues
    original_line, current_line = first_difference(original, regions, current, error.segment)
    old_source, new_source = SourceText(original), SourceText(current)
    shown_old = (
        _show(old_source.line_bytes(original_line))
        if original_line <= old_source.line_count
        else ""
    )
    shown_new = (
        _show(new_source.line_bytes(current_line)) if current_line <= new_source.line_count else ""
    )
    issues.append(
        Issue(
            "guard",
            ERROR,
            f"Text outside the regions changed ({error.reason}). The first difference is on "
            f"original line {original_line}: `{shown_old}`, which now reads `{shown_new}` "
            f"(current line {current_line}). Undo the edits outside the regions, or run `restore` "
            "to put the original regions back. Changes outside the regions belong in the report "
            "as proposals.",
            current_line,
        )
    )
    if causes:
        issues.append(
            Issue("guard", ERROR, "Also changed at the byte level: " + "; ".join(causes) + ".")
        )
    return issues


def first_difference(
    original: bytes, regions: Sequence[Region], current: bytes, failed: int
) -> tuple[int, int]:
    """The original and current line where frozen segment `failed` stops matching."""
    segments = frozen_segments(original, regions)
    segment_offsets = [0] + [region.end for region in regions]
    segment = segments[failed]
    is_last_segment = failed == len(segments) - 1 and failed > 0
    if failed == 0:
        matched, found_at = _common_prefix(segment, current), 0
        original_offset, current_offset = matched, matched
    elif is_last_segment:
        matched = _common_suffix(segment, current)
        original_offset = segment_offsets[failed] + len(segment) - matched - 1
        current_offset = len(current) - matched - 1
    else:
        search_from = _end_of_segments(segments[:failed], current)
        matched, found_at = _longest_prefix_found(segment, current, search_from)
        original_offset = segment_offsets[failed] + matched
        current_offset = found_at + matched
    original_offset = max(0, min(original_offset, len(original) - 1))
    current_offset = max(0, min(current_offset, len(current) - 1))
    return SourceText(original).line_of(original_offset), SourceText(current).line_of(
        current_offset
    )


def _end_of_segments(segments: Sequence[bytes], current: bytes) -> int:
    """Where the leftmost match of `segments`, in order, ends in `current`."""
    cursor = 0
    for segment in segments:
        found = current.find(segment, cursor)
        if found < 0:
            return cursor
        cursor = found + len(segment)
    return cursor


def _common_prefix(first: bytes, second: bytes) -> int:
    length = 0
    for left, right in zip(first, second, strict=False):
        if left != right:
            break
        length += 1
    return length


def _common_suffix(first: bytes, second: bytes) -> int:
    return _common_prefix(first[::-1], second[::-1])


def _longest_prefix_found(segment: bytes, current: bytes, search_from: int) -> tuple[int, int]:
    """The longest prefix of `segment` found in `current`, and where: (length, offset)."""
    low, high = 0, len(segment)
    found_at = search_from
    while low < high:
        middle = (low + high + 1) // 2
        position = current.find(segment[:middle], search_from)
        if position >= 0:
            low, found_at = middle, position
        else:
            high = middle - 1
    return low, found_at


def _byte_level_changes(original: bytes, current: bytes) -> list[str]:
    causes = []
    before, after = count_line_endings(original), count_line_endings(current)
    if before.describe() != after.describe():
        causes.append(f"line endings went from {before.describe()} to {after.describe()}")
    had_bom, has_bom = original.startswith(UTF8_BOM), current.startswith(UTF8_BOM)
    if had_bom != has_bom:
        causes.append("the UTF-8 BOM was " + ("removed" if had_bom else "added"))
    ended_with_break = original.endswith((b"\n", b"\r"))
    ends_with_break = current.endswith((b"\n", b"\r"))
    if ended_with_break != ends_with_break:
        causes.append(
            "the line break at the end of the file was "
            + ("removed" if ended_with_break else "added")
        )
    if _is_utf8(current) and not _is_utf8(original):
        causes.append(
            "bytes that were not UTF-8 changed (the file was re-encoded or its characters replaced)"
        )
    return causes


def _is_utf8(data: bytes) -> bool:
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _show(line: bytes) -> str:
    return line.rstrip(b"\r\n").decode("utf-8", "backslashreplace")


@dataclass
class Normalized:
    """Text with byte-level noise removed, and the original offset of every byte."""

    data: bytes
    offsets: list[int]


_TRAILING_SPACE = re.compile(rb"[ \t]+(?=\r?\n|\r|\Z)")


def normalize(data: bytes, *, is_start: bool, is_end: bool) -> Normalized:
    """Remove what edit tools change by accident: BOM, CRLF, trailing white space,
    the final line break, and the exact spelling of non-ASCII text."""
    output = bytearray()
    offsets: list[int] = []
    position = len(UTF8_BOM) if is_start and data.startswith(UTF8_BOM) else 0
    trailing = {match.start(): match.end() for match in _TRAILING_SPACE.finditer(data)}
    while position < len(data):
        if position in trailing:
            position = trailing[position]
            continue
        byte = data[position]
        if byte == ord("\r"):
            output.append(ord("\n"))
            offsets.append(position)
            position += 2 if data[position + 1 : position + 2] == b"\n" else 1
        elif byte >= 0x80:  # noqa: PLR2004  the first byte value outside ASCII
            output.append(ord("?"))
            offsets.append(position)
            while position < len(data) and data[position] >= 0x80:  # noqa: PLR2004  same boundary
                position += 1
        else:
            output.append(byte)
            offsets.append(position)
            position += 1
    if is_end:
        while output.endswith(b"\n"):
            output.pop()
            offsets.pop()
    offsets.append(len(data))
    return Normalized(bytes(output), offsets)


def _normalize_segments(segments: Sequence[bytes]) -> list[bytes]:
    last = len(segments) - 1
    return [
        normalize(segment, is_start=index == 0, is_end=index == last).data
        for index, segment in enumerate(segments)
    ]


class RepairError(RuntimeError):
    """The file cannot be repaired automatically."""


def repair(
    original: bytes, regions: Sequence[Region], current: bytes, encoding: str | None
) -> bytes:
    """Rebuild the file from the original frozen bytes and the current region texts.

    Region text gets the original line endings. When the file was re-encoded,
    lines that match an original line take its bytes back, and other non-ASCII
    lines are encoded with `encoding`.
    """
    segments = frozen_segments(original, regions)
    normalized_current = normalize(current, is_start=True, is_end=True)
    try:
        spans = align_segments(_normalize_segments(segments), normalized_current.data)
    except AlignmentError as error:
        raise RepairError(
            "Text outside the regions changed beyond line endings, white space and encoding "
            f"({error.reason}); `repair` cannot fix that. Undo those edits or run `restore`."
        ) from error
    offsets = normalized_current.offsets
    line_ending = count_line_endings(original).dominant
    was_reencoded = _is_utf8(current) and not _is_utf8(original)
    pieces = [segments[0]]
    for index, (region, (start, end)) in enumerate(zip(regions, spans, strict=True), start=1):
        text = current[offsets[start] : offsets[end]] if end > start else b""
        original_text = original[region.start : region.end]
        pieces.append(
            _repair_region_text(text, original_text, line_ending, was_reencoded, encoding)
        )
        pieces.append(segments[index])
    return b"".join(pieces)


def _repair_region_text(
    text: bytes, original_text: bytes, line_ending: bytes, was_reencoded: bool, encoding: str | None
) -> bytes:
    known_lines = {
        normalize(line, is_start=False, is_end=True).data: line.rstrip(b"\r\n")
        for line in original_text.splitlines(keepends=True)
    }
    lines = text.splitlines(keepends=True)
    repaired = []
    for line in lines:
        has_break = line.endswith((b"\n", b"\r"))
        content = line.rstrip(b"\r\n")
        if was_reencoded and not content.isascii():
            content = _reencode_line(content, known_lines, encoding)
        repaired.append(content + (line_ending if has_break else b""))
    return b"".join(repaired)


def _reencode_line(content: bytes, known_lines: dict[bytes, bytes], encoding: str | None) -> bytes:
    key = normalize(content, is_start=False, is_end=True).data
    if key in known_lines:
        return known_lines[key]
    if encoding is None:
        raise RepairError(
            "A changed line in a region holds non-ASCII text and the file is not UTF-8. "
            "Run `repair --encoding <codec>` with the file's encoding (see `doctor`)."
        )
    try:
        return content.decode("utf-8").encode(encoding)
    except (UnicodeDecodeError, UnicodeEncodeError, LookupError) as error:
        raise RepairError(f"Cannot convert a changed line to {encoding}: {error}.") from error


def restore(
    original: bytes, regions: Sequence[Region], current: bytes, spans: Sequence[Span]
) -> bytes:
    """The current file with the original text back in every region."""
    pieces = []
    cursor = 0
    for region, (start, end) in zip(regions, spans, strict=True):
        pieces.append(current[cursor:start])
        pieces.append(original[region.start : region.end])
        cursor = end
    pieces.append(current[cursor:])
    return b"".join(pieces)
