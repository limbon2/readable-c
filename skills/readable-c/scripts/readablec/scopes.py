"""Which declaration each identifier inside a function refers to.

C scopes are lexical: a block opens a scope, a declaration's name is visible
from the end of its declarator to the end of the block, and labels belong to
the whole function. Knowing the binding of every identifier lets the checks
tell a rename from a capture, and find what a region uses from outside.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from . import syntax

if TYPE_CHECKING:
    from tree_sitter import Node

NodeKey = tuple[int, int]

# Node types whose identifiers are not uses of variables.
SKIPPED_TYPES = {
    "comment",
    "field_identifier",
    "gnu_asm_expression",
    "parameter_list",
    "preproc_call",
    "preproc_def",
    "preproc_function_def",
    "preproc_include",
    "primitive_type",
    "sized_type_specifier",
    "statement_identifier",
    "storage_class_specifier",
    "string_literal",
    "struct_specifier",
    "type_descriptor",
    "type_identifier",
    "type_qualifier",
    "union_specifier",
}


def key(node: Node) -> NodeKey:
    return node.start_byte, node.end_byte


@dataclass(eq=False)
class Symbol:
    name: str
    kind: str
    index: int
    declarator: Node
    statement: Node
    depth: int
    type_text: str
    qualifiers: frozenset[str] = frozenset()
    storage: frozenset[str] = frozenset()
    value: Node | None = None

    @property
    def is_variable(self) -> bool:
        return self.kind in ("parameter", "local", "static")


@dataclass
class FunctionScope:
    function: Node
    symbols: list[Symbol] = field(default_factory=list)
    labels: dict[str, Symbol] = field(default_factory=dict)
    references: dict[NodeKey, Symbol] = field(default_factory=dict)
    uses: dict[int, list[Node]] = field(default_factory=dict)
    external: list[Node] = field(default_factory=list)
    redeclarations: list[Node] = field(default_factory=list)
    shadowing: list[tuple[Symbol, str]] = field(default_factory=list)
    goto_targets: list[Node] = field(default_factory=list)

    def symbol_of(self, node: Node) -> Symbol | None:
        return self.references.get(key(node))

    def uses_of(self, symbol: Symbol) -> list[Node]:
        return self.uses.get(id(symbol), [])

    def is_modified(self, symbol: Symbol) -> bool:
        """True when the symbol is assigned, incremented or has its address taken."""
        return any(_modifies(use) for use in self.uses_of(symbol))

    def is_assigned(self, symbol: Symbol) -> bool:
        """True when the symbol is assigned or incremented; taking its address does not count."""
        return any(_modifies(use, counting_address=False) for use in self.uses_of(symbol))


def _modifies(use: Node, *, counting_address: bool = True) -> bool:
    child = use
    parent = use.parent
    while parent is not None and parent.type == "parenthesized_expression":
        child, parent = parent, parent.parent
    if parent is None:
        return False
    if parent.type == "assignment_expression":
        return parent.child_by_field_name("left") == child
    if parent.type == "update_expression":
        return True
    is_address = parent.type == "pointer_expression" and _operator(parent) == "&"
    return counting_address and is_address


def _operator(node: Node) -> str:
    operator = node.child_by_field_name("operator")
    return syntax.text(operator) if operator is not None else ""


def resolve(function: Node, file_scope_names: set[str] | None = None) -> FunctionScope:
    """Bind every identifier in `function` to its local declaration, if it has one."""
    resolver = _Resolver(function, file_scope_names or set())
    resolver.run()
    return resolver.scope


class _Resolver:
    def __init__(self, function: Node, file_scope_names: set[str]) -> None:
        self.scope = FunctionScope(function)
        self.blocks: list[dict[str, Symbol]] = []
        self.file_scope_names = file_scope_names

    def run(self) -> None:
        function = self.scope.function
        self.blocks.append({})
        self._declare_parameters(function)
        body = function.child_by_field_name("body")
        if body is not None:
            self._collect_labels(body)
            self._visit(body)
        self.blocks.pop()

    def _declare_parameters(self, function: Node) -> None:
        knr_types = _knr_parameter_types(function)
        for parameter in syntax.parameter_nodes(function):
            if parameter.type == "identifier":
                name = syntax.text(parameter)
                self._declare(parameter, parameter, "parameter", knr_types.get(name, "int"))
                continue
            declarator = parameter.child_by_field_name("declarator")
            name_node = syntax.declared_name(declarator)
            if name_node is None:
                continue
            words = _specifier_words(parameter)
            self._declare(
                name_node,
                parameter,
                "parameter",
                _type_text(parameter, declarator),
                qualifiers=words["qualifiers"],
            )

    def _collect_labels(self, body: Node) -> None:
        for node in syntax.walk(body):
            if node.type != "labeled_statement":
                continue
            label = node.child_by_field_name("label")
            if label is None:
                continue
            name = syntax.text(label)
            if name in self.scope.labels:
                self.scope.redeclarations.append(label)
                continue
            self.scope.labels[name] = Symbol(
                name, "label", len(self.scope.labels), label, node, 0, "label"
            )

    def _declare(
        self,
        name_node: Node,
        statement: Node,
        kind: str,
        type_text: str,
        *,
        qualifiers: frozenset[str] = frozenset(),
        storage: frozenset[str] = frozenset(),
        value: Node | None = None,
    ) -> Symbol:
        name = syntax.text(name_node)
        symbol = Symbol(
            name=name,
            kind=kind,
            index=len(self.scope.symbols),
            declarator=name_node,
            statement=statement,
            depth=len(self.blocks) - 1,
            type_text=type_text,
            qualifiers=qualifiers,
            storage=storage,
            value=value,
        )
        innermost = self.blocks[-1]
        is_extern_redeclaration = "extern" in storage or kind == "function"
        if name in innermost and not is_extern_redeclaration:
            self.scope.redeclarations.append(name_node)
        elif any(name in block for block in self.blocks[:-1]):
            self.scope.shadowing.append((symbol, "a local or parameter of an enclosing block"))
        elif name in self.file_scope_names:
            self.scope.shadowing.append((symbol, "a name declared at file scope"))
        innermost[name] = symbol
        self.scope.symbols.append(symbol)
        self.scope.references[key(name_node)] = symbol
        return symbol

    def _lookup(self, name: str) -> Symbol | None:
        for block in reversed(self.blocks):
            if name in block:
                return block[name]
        return None

    def _visit(self, node: Node) -> None:
        handler = _HANDLERS.get(node.type)
        if handler is not None:
            handler(self, node)
            return
        if node.type in SKIPPED_TYPES:
            return
        for child in node.children:
            self._visit(child)

    def _visit_block(self, node: Node) -> None:
        self.blocks.append({})
        for child in node.children:
            self._visit(child)
        self.blocks.pop()

    def _visit_identifier(self, node: Node) -> None:
        symbol = self._lookup(syntax.text(node))
        if symbol is None:
            self.scope.external.append(node)
            return
        self.scope.references[key(node)] = symbol
        self.scope.uses.setdefault(id(symbol), []).append(node)

    def _visit_declaration(self, node: Node) -> None:
        words = _specifier_words(node)
        type_node = node.child_by_field_name("type")
        if type_node is not None and type_node.type == "enum_specifier":
            self._visit_enum(type_node)
        for declarator in node.children_by_field_name("declarator"):
            inner, value = declarator, None
            if declarator.type == "init_declarator":
                inner = declarator.child_by_field_name("declarator")
                value = declarator.child_by_field_name("value")
            name_node = syntax.declared_name(inner)
            if name_node is not None:
                self._declare(
                    name_node,
                    node,
                    _declaration_kind(words["storage"], inner),
                    _type_text(node, inner),
                    qualifiers=words["qualifiers"],
                    storage=words["storage"],
                    value=value,
                )
            self._visit_array_sizes(inner)
            if value is not None:
                self._visit(value)

    def _visit_array_sizes(self, declarator: Node | None) -> None:
        current = declarator
        while current is not None and current.type not in syntax.NAME_NODE_TYPES:
            if current.type == "array_declarator":
                size = current.child_by_field_name("size")
                if size is not None:
                    self._visit(size)
            current = current.child_by_field_name("declarator")

    def _visit_enum(self, node: Node) -> None:
        body = node.child_by_field_name("body")
        if body is None:
            return
        for enumerator in body.named_children:
            if enumerator.type != "enumerator":
                continue
            name_node = enumerator.child_by_field_name("name")
            value = enumerator.child_by_field_name("value")
            if value is not None:
                self._visit(value)
            if name_node is not None:
                self._declare(name_node, enumerator, "enum-constant", "int", value=value)

    def _visit_field_expression(self, node: Node) -> None:
        argument = node.child_by_field_name("argument")
        if argument is not None:
            self._visit(argument)

    def _visit_value_only(self, node: Node) -> None:
        value = node.child_by_field_name("value")
        if value is not None:
            self._visit(value)

    def _visit_goto(self, node: Node) -> None:
        label = node.child_by_field_name("label")
        if label is None:
            return
        self.scope.goto_targets.append(label)
        symbol = self.scope.labels.get(syntax.text(label))
        if symbol is not None:
            self.scope.references[key(label)] = symbol

    def _visit_labeled(self, node: Node) -> None:
        label = node.child_by_field_name("label")
        for child in node.named_children:
            if child != label:
                self._visit(child)

    def _visit_preprocessor_group(self, node: Node) -> None:
        skipped = {node.child_by_field_name("condition"), node.child_by_field_name("name")}
        for child in node.named_children:
            if child not in skipped:
                self._visit(child)

    def _visit_initializer_pair(self, node: Node) -> None:
        for child in node.named_children:
            if child.type != "field_designator":
                self._visit(child)


_HANDLERS = {
    "compound_statement": _Resolver._visit_block,
    "for_statement": _Resolver._visit_block,
    "identifier": _Resolver._visit_identifier,
    "declaration": _Resolver._visit_declaration,
    "enum_specifier": _Resolver._visit_enum,
    "field_expression": _Resolver._visit_field_expression,
    "cast_expression": _Resolver._visit_value_only,
    "sizeof_expression": _Resolver._visit_value_only,
    "compound_literal_expression": _Resolver._visit_value_only,
    "goto_statement": _Resolver._visit_goto,
    "labeled_statement": _Resolver._visit_labeled,
    "preproc_if": _Resolver._visit_preprocessor_group,
    "preproc_ifdef": _Resolver._visit_preprocessor_group,
    "preproc_elif": _Resolver._visit_preprocessor_group,
    "preproc_else": _Resolver._visit_preprocessor_group,
    "initializer_pair": _Resolver._visit_initializer_pair,
}


def _specifier_words(node: Node) -> dict[str, frozenset[str]]:
    qualifiers = set()
    storage = set()
    for child in node.children:
        if child.type == "type_qualifier":
            qualifiers.add(syntax.text(child))
        elif child.type == "storage_class_specifier":
            storage.add(syntax.text(child))
    return {"qualifiers": frozenset(qualifiers), "storage": frozenset(storage)}


def _declaration_kind(storage: frozenset[str], declarator: Node | None) -> str:
    current = declarator
    while current is not None and current.type not in syntax.NAME_NODE_TYPES:
        if current.type == "function_declarator":
            return "function"
        current = current.child_by_field_name("declarator")
    if "extern" in storage:
        return "extern"
    if "static" in storage:
        return "static"
    return "local"


def declarator_shape(declarator: Node | None) -> str:
    """The declarator without its name: `*`, `[]`, `(*)()` and so on."""
    if declarator is None or declarator.type in syntax.NAME_NODE_TYPES:
        return ""
    inner = declarator.child_by_field_name("declarator")
    shape_of_inner = declarator_shape(inner)
    if declarator.type == "pointer_declarator":
        qualifiers = " ".join(
            syntax.text(child) for child in declarator.children if child.type == "type_qualifier"
        )
        return "*" + (qualifiers + " " if qualifiers else "") + shape_of_inner
    if declarator.type == "array_declarator":
        return shape_of_inner + "[]"
    if declarator.type == "function_declarator":
        return shape_of_inner + "()"
    if declarator.type == "parenthesized_declarator":
        return "(" + shape_of_inner + ")"
    return shape_of_inner


def _type_text(declaration: Node, declarator: Node | None) -> str:
    type_node = declaration.child_by_field_name("type")
    base = " ".join(syntax.text(type_node).split()) if type_node is not None else "int"
    shape = declarator_shape(declarator)
    return f"{base} {shape}".strip()


def _knr_parameter_types(function: Node) -> dict[str, str]:
    types = {}
    for child in function.children:
        if child.type != "declaration":
            continue
        for declarator in child.children_by_field_name("declarator"):
            name = syntax.declared_name(declarator)
            if name is not None:
                types[syntax.text(name)] = _type_text(child, declarator)
    return types
