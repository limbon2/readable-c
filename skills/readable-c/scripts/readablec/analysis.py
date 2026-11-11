"""Everything the tool knows about one version of a file, computed once and on demand."""

from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

from . import conventions, declarations, functions, lexer, scopes, syntax
from .source import SourceText

if TYPE_CHECKING:
    from tree_sitter import Node


class Analysis:
    def __init__(self, data: bytes, path: Path | None = None) -> None:
        self.source = SourceText(data, path)
        self.tree = syntax.parse(data)
        self.root: Node = self.tree.root_node
        self._scopes: dict[tuple[int, int], scopes.FunctionScope] = {}

    @property
    def data(self) -> bytes:
        return self.source.data

    @cached_property
    def tokens(self) -> list[lexer.Token]:
        return lexer.tokenize(self.source.data)

    @cached_property
    def functions(self) -> list[functions.FunctionSpan]:
        return functions.index_functions(self.source, self.root, self.tokens)

    @cached_property
    def declarations(self) -> declarations.FileDeclarations:
        return declarations.collect(self.source, self.root, self.tokens)

    @cached_property
    def conventions(self) -> conventions.Conventions:
        return conventions.detect(self.source, self.root, self.tokens)

    @cached_property
    def file_scope_names(self) -> set[str]:
        return self.declarations.names()

    def scope(self, function: Node) -> scopes.FunctionScope:
        cache_key = scopes.key(function)
        if cache_key not in self._scopes:
            self._scopes[cache_key] = scopes.resolve(function, self.file_scope_names)
        return self._scopes[cache_key]

    def text(self, start: int, end: int) -> str:
        return self.source.data[start:end].decode(
            self.conventions.encoding.name, errors="backslashreplace"
        )
