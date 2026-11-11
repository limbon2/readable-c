"""Questions about C syntax nodes that both the rules and the verification ask."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import syntax

if TYPE_CHECKING:
    from tree_sitter import Node

COMPARISONS = {"==", "!=", "<", "<=", ">", ">="}
LOGICAL = {"&&", "||"}
BITWISE = {"&", "|", "^"}
SHIFTS = {"<<", ">>"}
ARITHMETIC = {"+", "-", "*", "/", "%"}
JUMPS = {"return_statement", "break_statement", "continue_statement", "goto_statement"}
LITERALS = {
    "number_literal",
    "char_literal",
    "string_literal",
    "concatenated_string",
    "true",
    "false",
    "null",
}
SIDE_EFFECT_TYPES = {
    "assignment_expression",
    "update_expression",
    "call_expression",
    "gnu_asm_expression",
}


def operator(node: Node) -> str:
    found = node.child_by_field_name("operator")
    return syntax.text(found) if found is not None else ""


def is_negation(node: Node) -> bool:
    return node.type == "unary_expression" and operator(node) == "!"


def is_composition(node: Node) -> bool:
    """True for `&&` and `||`, the operators that combine conditions."""
    return node.type == "binary_expression" and operator(node) in LOGICAL


def condition_parts(node: Node) -> list[Node]:
    """The parts that `&&` and `||` combine, looking through parentheses and `!(...)`."""
    current = syntax.unwrap_parentheses(node)
    if is_composition(current):
        left = current.child_by_field_name("left")
        right = current.child_by_field_name("right")
        return [*condition_parts(left), *condition_parts(right)] if left and right else [current]
    if is_negation(current):
        argument = current.child_by_field_name("argument")
        if argument is not None and is_composition(syntax.unwrap_parentheses(argument)):
            return condition_parts(argument)
    return [current]


def is_path(node: Node) -> bool:
    """A name or a member path without calls: `count`, `cfg->limit`, `rows[i]`, `*cursor`."""
    current = syntax.unwrap_parentheses(node)
    if current.type == "identifier":
        return True
    if current.type == "field_expression":
        argument = current.child_by_field_name("argument")
        return argument is not None and is_path(argument)
    if current.type == "subscript_expression":
        argument = current.child_by_field_name("argument")
        index = current.child_by_field_name("index")
        is_simple_index = index is not None and index.type in ("identifier", "number_literal")
        return argument is not None and is_simple_index and is_path(argument)
    if current.type == "pointer_expression" and operator(current) == "*":
        argument = current.child_by_field_name("argument")
        return argument is not None and is_path(argument)
    return False


def is_plain_argument(node: Node) -> bool:
    """An argument that needs no explanation: a literal, a path, `&path`, `sizeof`."""
    current = syntax.unwrap_parentheses(node)
    if current.type in LITERALS or current.type == "sizeof_expression":
        return True
    if current.type == "unary_expression" and operator(current) == "-":
        argument = current.child_by_field_name("argument")
        return argument is not None and argument.type == "number_literal"
    if current.type == "pointer_expression" and operator(current) == "&":
        argument = current.child_by_field_name("argument")
        return argument is not None and is_path(argument)
    return is_path(current)


def is_named(node: Node) -> bool:
    """True when a part of a condition reads as a name."""
    current = syntax.unwrap_parentheses(node)
    if current.type in LITERALS or current.type == "sizeof_expression":
        return True
    if current.type == "call_expression":
        function = current.child_by_field_name("function")
        arguments = current.child_by_field_name("arguments")
        plain = arguments is None or all(
            is_plain_argument(argument) for argument in syntax.named_children(arguments)
        )
        return function is not None and is_path(function) and plain
    if is_negation(current):
        argument = current.child_by_field_name("argument")
        return argument is not None and is_named(argument)
    if current.type == "cast_expression":
        value = current.child_by_field_name("value")
        return value is not None and is_named(value)
    return is_path(current)


def is_boolean_valued(node: Node) -> bool:
    """True when the expression's value is always 0 or 1: comparisons, `&&`, `||`, `!`."""
    current = syntax.unwrap_parentheses(node)
    if current.type == "binary_expression":
        return operator(current) in COMPARISONS | LOGICAL
    return is_negation(current)


def always_jumps(node: Node | None) -> bool:
    """True when the statement always leaves: return, break, continue or goto on every path."""
    if node is None:
        return False
    if node.type in JUMPS:
        return True
    if node.type == "compound_statement":
        statements = syntax.named_children(node)
        return bool(statements) and always_jumps(statements[-1])
    if node.type == "labeled_statement":
        label = node.child_by_field_name("label")
        statements = [child for child in syntax.named_children(node) if child != label]
        return bool(statements) and always_jumps(statements[-1])
    if node.type == "if_statement":
        alternative = else_statement(node)
        return (
            alternative is not None
            and always_jumps(node.child_by_field_name("consequence"))
            and always_jumps(alternative)
        )
    return False


def else_statement(if_statement: Node) -> Node | None:
    clause = if_statement.child_by_field_name("alternative")
    if clause is None:
        return None
    statements = syntax.named_children(clause)
    return statements[0] if statements else None


def is_zero(node: Node) -> bool:
    """`0`, `0x0`, `0L`, `'\\0'` or `NULL`."""
    current = syntax.unwrap_parentheses(node)
    if current.type == "null":
        return True
    if current.type == "number_literal":
        digits = syntax.text(current).rstrip("uUlL").lower()
        return digits in ("0", "00", "0x0", "0x00")
    if current.type == "char_literal":
        return syntax.text(current) in ("'\\0'", "'\\x0'", "'\\x00'")
    return False


def has_side_effects(node: Node) -> bool:
    return any(child.type in SIDE_EFFECT_TYPES for child in syntax.walk(node))


def can_trap(node: Node) -> bool:
    """True when evaluating the expression could fault: dereference, indexing, division, calls."""
    for child in syntax.walk(node):
        if child.type in ("subscript_expression", "call_expression"):
            return True
        if child.type == "pointer_expression" and operator(child) == "*":
            return True
        if child.type == "field_expression" and operator(child) == "->":
            return True
        if child.type == "binary_expression" and operator(child) in ("/", "%"):
            return True
    return False


def indentation_of_line(data: bytes, line_start: int) -> bytes:
    end = line_start
    while end < len(data) and data[end] in (0x20, 0x09):
        end += 1
    return data[line_start:end]
