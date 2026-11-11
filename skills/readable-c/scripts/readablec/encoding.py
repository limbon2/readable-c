"""Which text encoding a file uses, so its bytes can be shown and written back.

Legacy C files often carry comments in a single-byte code page such as CP1251.
The tool never re-encodes the bytes it keeps; it only needs a good guess to show
the text to an agent and to encode new lines that contain non-ASCII text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# The most frequent letters of Russian text, used to tell the Cyrillic code pages apart.
FREQUENT_CYRILLIC = set("оеаинтсрвлОЕАИНТСРВЛ")

WORD_WITH_HIGH_BYTES = re.compile(rb"[A-Za-z\x80-\xff]*[\x80-\xff][A-Za-z\x80-\xff]*")


@dataclass(frozen=True)
class EncodingInfo:
    """The encoding of a file. `name` is a Python codec name."""

    name: str
    is_utf8: bool
    is_ascii: bool
    is_guess: bool

    def describe(self) -> str:
        if self.is_ascii:
            return "ASCII"
        if self.is_utf8:
            return "UTF-8"
        return f"not UTF-8; looks like {self.name} (a guess)"


def detect_encoding(data: bytes) -> EncodingInfo:
    if data.isascii():
        return EncodingInfo(name="utf-8", is_utf8=True, is_ascii=True, is_guess=False)
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return EncodingInfo(
            name=guess_legacy_encoding(data), is_utf8=False, is_ascii=False, is_guess=True
        )
    return EncodingInfo(name="utf-8", is_utf8=True, is_ascii=False, is_guess=False)


def guess_legacy_encoding(data: bytes) -> str:
    """The single-byte code page that decodes the non-ASCII words most plausibly."""
    words = WORD_WITH_HIGH_BYTES.findall(data)
    if not words:
        return "latin_1"
    # Cyrillic and Greek words have no ASCII letters at all; words of Western
    # and Central European languages mix ASCII letters with accented ones.
    whole_high_words = [word for word in words if not re.search(rb"[A-Za-z]", word)]
    looks_non_latin = len(whole_high_words) * 2 > len(words)
    candidates = ("cp1251", "koi8_r", "cp866") if looks_non_latin else ("cp1252", "cp1250")
    sample = b" ".join(words[:2000])
    return max(candidates, key=lambda name: _plausibility(sample, name))


def _plausibility(sample: bytes, encoding: str) -> float:
    text = sample.decode(encoding, errors="replace")
    letters = [char for char in text if not char.isascii() and char.isalpha()]
    if not letters:
        return 0.0
    letter_share = len(letters) / max(1, sum(1 for char in text if not char.isascii()))
    frequent_share = sum(1 for char in letters if char in FREQUENT_CYRILLIC) / len(letters)
    lowercase_share = sum(1 for char in letters if char.islower()) / len(letters)
    return letter_share + frequent_share + lowercase_share
