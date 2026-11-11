"""Rules about names: cryptic locals and parameters, and reused parameters."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .. import syntax
from ..findings import ADVICE, RULE
from .engine import RuleContext, on, on_function

if TYPE_CHECKING:
    from tree_sitter import Node

# Short names that read well by convention: loop counters, coordinates,
# characters, file handles and result codes.
CONVENTIONAL_SHORT_NAMES = {
    "i", "j", "k", "n", "x", "y", "z", "c", "ch", "fd", "fp", "id", "ok", "rc", "dx", "dy", "dz", "_",
}  # fmt: skip

PLACEHOLDER_NAMES = re.compile(
    r"^(?:tmp|temp|foo|bar|baz|dummy|var)\d*$|^(?:val|data|buf|ptr|str|arr|res|ret|[a-z])\d+$"
)


def _is_cryptic(name: str) -> bool:
    if name in CONVENTIONAL_SHORT_NAMES:
        return False
    is_short = len(name) <= 2  # noqa: PLR2004  two characters rarely say what a value holds
    return is_short or bool(PLACEHOLDER_NAMES.match(name))


def _report_name(context: RuleContext, name_node: Node, role: str) -> None:
    name = syntax.text(name_node)
    if name in context.frozen_names or not _is_cryptic(name):
        return
    context.report(
        "cryptic-name",
        RULE,
        name_node,
        f"Rename the {role} `{name}` to say what it holds or counts. A local or parameter can be "
        "renamed inside the region; `verify` confirms the rename keeps every use bound to the "
        "same declaration.",
    )


@on_function
def cryptic_parameter_names(node: Node, context: RuleContext) -> None:
    for parameter in syntax.parameter_nodes(node):
        if parameter.type == "identifier":
            _report_name(context, parameter, "parameter")
            continue
        name = syntax.declared_name(parameter.child_by_field_name("declarator"))
        if name is not None:
            _report_name(context, name, "parameter")


@on("declaration")
def cryptic_local_names(node: Node, context: RuleContext) -> None:
    if syntax.enclosing(node, {"compound_statement", "for_statement"}) is None:
        return
    in_for_header = node.parent is not None and node.parent.type == "for_statement"
    for declarator in node.children_by_field_name("declarator"):
        name = syntax.declared_name(declarator)
        if name is None:
            continue
        if in_for_header and syntax.text(name) in ("i", "j", "k"):
            continue
        _report_name(context, name, "variable")


@on("assignment_expression", "update_expression")
def param_reassign(node: Node, context: RuleContext) -> None:
    function = context.function.node if context.function else None
    if function is None:
        return
    field = "left" if node.type == "assignment_expression" else "argument"
    target = node.child_by_field_name(field)
    if target is None:
        return
    target = syntax.unwrap_parentheses(target)
    if target.type != "identifier":
        return
    symbol = context.analysis.scope(function).symbol_of(target)
    if symbol is None or symbol.kind != "parameter":
        return
    context.report(
        "param-reassign",
        ADVICE,
        node,
        f"This changes the parameter `{symbol.name}`, so later code no longer sees what the "
        "caller passed. Copy it into a local whose name says what it tracks, for example "
        f"`size_t remaining = {symbol.name};`.",
    )
