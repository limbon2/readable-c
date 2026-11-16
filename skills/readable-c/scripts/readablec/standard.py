"""Read explicit C standards from a project's build configuration."""

from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass, replace
from enum import Enum, auto
from pathlib import Path

C23 = 2023

_EDITIONS = {
    "89": 1990,
    "90": 1990,
    "94": 1995,
    "95": 1995,
    "99": 1999,
    "9x": 1999,
    "11": 2011,
    "1x": 2011,
    "17": 2017,
    "18": 2017,
    "23": C23,
    "2x": C23,
    "iso9899:1990": 1990,
    "iso9899:199409": 1995,
    "iso9899:1999": 1999,
    "iso9899:199x": 1999,
    "iso9899:2011": 2011,
    "iso9899:2017": 2017,
    "iso9899:2018": 2017,
    "iso9899:2024": C23,
}


@dataclass(frozen=True)
class CStandard:
    year: int
    source: str

    @property
    def name(self) -> str:
        return f"C{self.year % 100:02}"


class _CompileMode(Enum):
    DEFAULT = auto()
    UNKNOWN = auto()


def parse(spelling: str, source: str) -> CStandard | None:
    edition = spelling.lower()
    if edition.startswith(("c", "gnu")):
        edition = edition.removeprefix("gnu") if edition.startswith("gnu") else edition[1:]
    year = _EDITIONS.get(edition)
    return CStandard(year, source) if year is not None else None


def detect(path: Path) -> CStandard | None:
    """Use the oldest explicit edition for this file in the known compile commands.

    A matching entry with an unknown explicit edition prevents a source-based guess.
    With no matching entries or only default modes, try a simple CMake declaration.
    """
    path = path.resolve()
    folders = _project_folders(path)
    editions = [
        edition for database in _databases(folders) for edition in _compile_editions(database, path)
    ]
    if any(edition is not _CompileMode.DEFAULT for edition in editions):
        known = [edition for edition in editions if isinstance(edition, CStandard)]
        if len(known) != len(editions):
            return None
        oldest = min(known, key=lambda edition: edition.year)
        if any(edition.year != oldest.year for edition in known):
            return replace(oldest, source=f"{oldest.source} (oldest matching edition)")
        return oldest
    return _cmake_standard(folders) if path.suffix == ".c" else None


def _project_folders(path: Path) -> list[Path]:
    folders = []
    for folder in path.parents:
        folders.append(folder)
        if (folder / ".git").exists():
            break
    return folders


def _databases(folders: list[Path]) -> list[Path]:
    candidates = {}
    for folder in folders:
        builds = [folder / "build", folder / "out" / "build"]
        if (folder / "CMakeLists.txt").is_file():
            builds.extend(sorted(folder.glob("cmake-build-*")))
            builds.extend(sorted(folder.glob("build-*")))
        presets = [preset for build in builds[:2] for preset in sorted(build.glob("*/"))]
        for location in [folder, *builds, *presets]:
            database = location / "compile_commands.json"
            if database.is_file():
                candidates.setdefault(database.resolve(), database)
    return list(candidates.values())


def _compile_editions(database: Path, path: Path) -> list[CStandard | _CompileMode]:
    try:
        commands = json.loads(database.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    if not isinstance(commands, list):
        return []
    return [
        _compile_standard(_arguments(entry), str(database))
        for entry in commands
        if _source_matches(entry, database.parent, path)
    ]


def _source_matches(entry: object, parent: Path, path: Path) -> bool:
    if not isinstance(entry, dict):
        return False
    directory = entry.get("directory")
    file = entry.get("file")
    if not isinstance(directory, str) or not isinstance(file, str):
        return False
    try:
        return (parent / directory / file).resolve() == path
    except (OSError, RuntimeError, ValueError):
        return False


def _arguments(entry: dict[str, object]) -> list[str] | None:
    arguments = entry.get("arguments")
    if isinstance(arguments, list) and all(isinstance(argument, str) for argument in arguments):
        return arguments
    command = entry.get("command")
    if isinstance(command, str):
        try:
            return shlex.split(command)
        except ValueError:
            pass
    return None


def _compile_standard(arguments: list[str] | None, source: str) -> CStandard | _CompileMode:
    if not arguments:
        return _CompileMode.UNKNOWN
    edition: CStandard | _CompileMode = _CompileMode.DEFAULT
    for argument in arguments[1:]:
        if argument.startswith("@"):
            # A response file can contain flags that override the visible command.
            return _CompileMode.UNKNOWN
        if argument.startswith(("-std=", "--std=")):
            edition = parse(argument.partition("=")[2], source) or _CompileMode.UNKNOWN
        elif argument.startswith("/std:"):
            edition = parse(argument.partition(":")[2], source) or _CompileMode.UNKNOWN
        elif argument in {"-ansi", "--ansi"}:
            edition = CStandard(_EDITIONS["90"], source)
    return edition


_CMAKE_STANDARD_REFERENCE = re.compile(
    r"\b(?:CMAKE_C_STANDARD|C_STANDARD|c_std_\d+|CMAKE_C_FLAGS\w*)\b|(?:-std=|/std:)"
)
_CMAKE_NOISE = re.compile(
    r'#?\[(?P<equals>=*)\[.*?\](?P=equals)\]|#[^\r\n]*|"(?P<quoted>(?:[^"\\]|\\.)*)"', re.S
)
_CMAKE_SET_STANDARD = re.compile(
    r'^\s*(?i:set)\s*\(\s*CMAKE_C_STANDARD\s+(?:"(?P<quoted>\d+)"|(?P<bare>\d+))\s*\)',
    re.M,
)
_CMAKE_EARLIER_COMMAND = re.compile(
    r"^[ \t]*(?:if|foreach|while|block|function|macro|return|"
    r"add_library|add_executable|add_subdirectory)\s*\(",
    re.I | re.M,
)


def _cmake_argument(match: re.Match[str]) -> str:
    token = match[0]
    if token.startswith("#"):
        return " "
    quoted = match["quoted"]
    if quoted is not None and quoted.isdigit():
        return token
    return " C_STANDARD " if _CMAKE_STANDARD_REFERENCE.search(token) else '""'


def _cmake_standard(folders: list[Path]) -> CStandard | None:
    found = []
    for folder in folders:
        config = folder / "CMakeLists.txt"
        try:
            text = config.read_text(encoding="utf-8-sig")
        except (OSError, ValueError):
            continue
        text = _CMAKE_NOISE.sub(_cmake_argument, text)
        if not _CMAKE_STANDARD_REFERENCE.search(text):
            continue
        setup = _CMAKE_SET_STANDARD.search(text)
        if setup is None:
            return None
        before = text[: setup.start()]
        if before.count("(") != before.count(")") or _CMAKE_EARLIER_COMMAND.search(before):
            return None
        rest = before + text[setup.end() :]
        if _CMAKE_STANDARD_REFERENCE.search(rest):
            return None
        spelling = setup["quoted"] or setup["bare"]
        found.append(parse(spelling, f"{config} (requested default)"))
    if not found or found[0] is None:
        return None
    first = found[0]
    if any(edition is None or edition.year != first.year for edition in found):
        return None
    return first
