"""The bytes of a C file, its lines, and the byte-level facts that edits must keep."""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

UTF8_BOM = b"\xef\xbb\xbf"

LINE_ENDING_NAMES = {b"\r\n": "CRLF", b"\n": "LF", b"\r": "CR"}


@dataclass(frozen=True)
class LineEndingCounts:
    """How many line breaks are CRLF, a lone LF and a lone CR."""

    crlf: int
    lf: int
    cr: int

    @property
    def dominant(self) -> bytes:
        """The line ending most lines use, or LF for a file without line breaks."""
        counts = {b"\r\n": self.crlf, b"\n": self.lf, b"\r": self.cr}
        most_used = max(counts, key=counts.__getitem__)
        has_line_breaks = counts[most_used] > 0
        return most_used if has_line_breaks else b"\n"

    @property
    def is_mixed(self) -> bool:
        kinds_used = [count for count in (self.crlf, self.lf, self.cr) if count > 0]
        return len(kinds_used) > 1

    def describe(self) -> str:
        """`CRLF`, `LF`, `none`, or the counts of each kind when they are mixed."""
        if self.is_mixed:
            return f"mixed ({self.crlf} CRLF, {self.lf} LF, {self.cr} CR)"
        if self.crlf + self.lf + self.cr == 0:
            return "none"
        return LINE_ENDING_NAMES[self.dominant]


def count_line_endings(data: bytes) -> LineEndingCounts:
    crlf = data.count(b"\r\n")
    return LineEndingCounts(
        crlf=crlf,
        lf=data.count(b"\n") - crlf,
        cr=data.count(b"\r") - crlf,
    )


class SourceText:
    """A file's bytes with line lookup. A line ends after its LF; lines are 1-based."""

    def __init__(self, data: bytes, path: Path | None = None) -> None:
        self.data = data
        self.path = path

    @classmethod
    def read(cls, path: Path) -> SourceText:
        return cls(path.read_bytes(), path)

    @cached_property
    def line_starts(self) -> list[int]:
        """The offset of the first byte of every line."""
        if not self.data:
            return []
        starts = [0]
        newline = self.data.find(b"\n")
        while newline != -1:
            starts.append(newline + 1)
            newline = self.data.find(b"\n", newline + 1)
        # A final line break ends the last line; it does not start an empty one.
        ends_with_line_break = starts[-1] == len(self.data)
        if ends_with_line_break:
            starts.pop()
        return starts

    @property
    def line_count(self) -> int:
        return len(self.line_starts)

    def line_of(self, offset: int) -> int:
        """The line that holds the byte at `offset` (the last line for the end offset)."""
        return max(1, bisect.bisect_right(self.line_starts, offset))

    def line_start(self, line: int) -> int:
        return self.line_starts[line - 1]

    def line_end(self, line: int) -> int:
        """The offset just past the line's line ending."""
        if line < self.line_count:
            return self.line_starts[line]
        return len(self.data)

    def line_bytes(self, line: int) -> bytes:
        """The line's bytes without its line ending."""
        return self.data[self.line_start(line) : self.line_end(line)].rstrip(b"\r\n")

    @cached_property
    def line_endings(self) -> LineEndingCounts:
        return count_line_endings(self.data)

    @property
    def has_bom(self) -> bool:
        return self.data.startswith(UTF8_BOM)

    @property
    def ends_with_line_break(self) -> bool:
        return self.data.endswith((b"\n", b"\r"))
