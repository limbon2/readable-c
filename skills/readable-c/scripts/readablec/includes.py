"""The names a file can use from the headers it includes.

Standard headers come from a table. Quoted headers are found next to the file,
in the folders given with --include, or by name inside the project, and then
parsed for their own declarations and macros, a few levels deep.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import declarations, lexer, stdlib, syntax
from .source import SourceText

MAX_DEPTH = 3
MAX_SEARCHED_FILES = 20000
SKIPPED_FOLDERS = {".git", ".hg", ".svn", "node_modules", "build", "out", "dist", "target", ".venv"}

_INCLUDE = re.compile(rb'#\s*include\s*([<"])([^>"]+)[>"]')


@dataclass
class KnownNames:
    names: set[str] = field(default_factory=set)
    origins: dict[str, str] = field(default_factory=dict)
    missing_headers: list[str] = field(default_factory=list)
    unknown_system_headers: list[str] = field(default_factory=list)


def included_headers(tokens: Sequence[lexer.Token]) -> list[tuple[str, bool]]:
    """(header, is_system) for every #include, in order."""
    found = []
    for token in tokens:
        if token.kind != lexer.DIRECTIVE:
            continue
        match = _INCLUDE.match(lexer.normalize_directive(token.text))
        if match is not None:
            found.append((match.group(2).decode("utf-8", "replace"), match.group(1) == b"<"))
    return found


def known_names(
    path: Path | None, tokens: Sequence[lexer.Token], include_dirs: Sequence[Path] = ()
) -> KnownNames:
    known = KnownNames()
    root = _project_root(path) if path is not None else None
    _add_headers(known, path, tokens, include_dirs=include_dirs, root=root, depth=0, seen=set())
    return known


def _add_headers(
    known: KnownNames,
    path: Path | None,
    tokens: Sequence[lexer.Token],
    *,
    include_dirs: Sequence[Path],
    root: Path | None,
    depth: int,
    seen: set[Path],
) -> None:
    for header, is_system in included_headers(tokens):
        standard = stdlib.names_for(header)
        if standard is not None:
            _add(known, standard, f"<{header}>")
            continue
        found = _find_header(header, path, include_dirs, root)
        if found is None:
            target = known.unknown_system_headers if is_system else known.missing_headers
            if header not in target:
                target.append(header)
            continue
        if found in seen or depth >= MAX_DEPTH:
            continue
        seen.add(found)
        data = found.read_bytes()
        header_tokens = lexer.tokenize(data)
        header_source = SourceText(data, found)
        tree = syntax.parse(data)
        declared = declarations.collect(header_source, tree.root_node, header_tokens)
        _add(known, declared.names(), header)
        _add_headers(
            known,
            found,
            header_tokens,
            include_dirs=include_dirs,
            root=root,
            depth=depth + 1,
            seen=seen,
        )


def _add(known: KnownNames, names: set[str] | frozenset[str], origin: str) -> None:
    for name in names:
        if name not in known.names:
            known.names.add(name)
            known.origins[name] = origin


def _find_header(
    header: str, including: Path | None, include_dirs: Sequence[Path], root: Path | None
) -> Path | None:
    candidates = []
    if including is not None:
        candidates.append(including.parent / header)
    candidates.extend(folder / header for folder in include_dirs)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    if root is None:
        return None
    return _search_project(root, Path(header).name)


def _search_project(root: Path, file_name: str) -> Path | None:
    searched = 0
    for folder, subfolders, files in os.walk(root):
        subfolders[:] = [name for name in subfolders if name not in SKIPPED_FOLDERS]
        searched += len(files)
        if file_name in files:
            return (Path(folder) / file_name).resolve()
        if searched > MAX_SEARCHED_FILES:
            return None
    return None


def _project_root(path: Path) -> Path | None:
    """The nearest folder above `path` that holds a .git entry."""
    for folder in path.resolve().parents:
        if (folder / ".git").exists():
            return folder
    return None
