"""hand-written-library: loops that do what a standard function is named for.

`while (len < cap && name[len] != 0) len++;` is `strnlen(name, cap)`, and a loop that
zeroes an array element by element is `memset`. The function's name tells the reader at
once what the loop leaves them to work out.

The rule reports a loop only when the suggested call does exactly what the loop does: the
counter starts at 0, the bound is a plain `<` or `!=`, and for string functions the
elements are `char` or `wchar_t` (a local or a parameter whose type the tool can see).
`WCHAR` is left alone: it is `wchar_t` on Windows but a 16-bit integer elsewhere.

Search loops with a bound (`while (i < n && buf[i] != ':') i++;`) stay out: `memchr`
returns NULL where the loop stops at `n`, so the code after the loop would change too.
`strcspn` covers the zero-terminated search exactly, and the rule suggests it.

Replacing a loop by a call is a restructuring that `verify` cannot prove (tier 2), so the
rule is advice, and the agent explains the replacement in the report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .. import ctree, syntax
from ..findings import ADVICE
from .engine import RuleContext, on

if TYPE_CHECKING:
    from tree_sitter import Node

RULE_ID = "hand-written-library"
BOUND_OPERATORS = {"<", "!="}
CHAR_TYPES = {"char"}
CAST_CHAR_TYPES = {
    "unsigned char",
    "signed char",
    "uint8_t",
    "int8_t",
    "BYTE",
    "UINT8",
    "INT8",
    "CHAR",
    "UCHAR",
}
WIDE_TYPES = {"wchar_t"}
NOT_PROVEN = "Explain the replacement in the report: verify cannot prove it."
POSIX_NOTE = (
    "{name} is POSIX.1-2008 and MSVC, not C89 or C99: use it when the code base already "
    "does or targets those platforms."
)


@dataclass(frozen=True)
class Strings:
    """How to call the string functions on one element type."""

    cast: str
    length: str
    bounded_length: str
    span: str
    wide: bool


NARROW = Strings("", "strlen", "strnlen", "strcspn", wide=False)
NARROW_CAST = Strings("(const char *)", "strlen", "strnlen", "strcspn", wide=False)
WIDE = Strings("", "wcslen", "wcsnlen", "wcscspn", wide=True)


@dataclass(frozen=True)
class Scan:
    """What one test of a scan loop checks: a bound, the terminating zero, or a value."""

    kind: str
    subject: Node
    value: Node | None = None


def _identifier_text(node: Node | None) -> str | None:
    if node is None:
        return None
    current = syntax.unwrap_parentheses(node)
    return syntax.text(current) if current.type == "identifier" else None


def _increment_target(expression: Node | None) -> str | None:
    """The variable that `v++`, `++v` or `v += 1` steps."""
    if expression is None:
        return None
    current = syntax.unwrap_parentheses(expression)
    if current.type == "update_expression" and ctree.operator(current) == "++":
        return _identifier_text(current.child_by_field_name("argument"))
    if current.type == "assignment_expression" and ctree.operator(current) == "+=":
        right = current.child_by_field_name("right")
        is_one = right is not None and syntax.text(syntax.unwrap_parentheses(right)) == "1"
        return _identifier_text(current.child_by_field_name("left")) if is_one else None
    return None


def _only_statement(body: Node | None) -> Node | None:
    if body is None or body.type != "compound_statement":
        return body
    statements = [child for child in syntax.named_children(body) if child.type != "comment"]
    return statements[0] if len(statements) == 1 else None


def _only_expression(statement: Node | None) -> Node | None:
    if statement is None or statement.type != "expression_statement":
        return None
    expressions = syntax.named_children(statement)
    return syntax.unwrap_parentheses(expressions[0]) if expressions else None


def _is_empty(body: Node | None) -> bool:
    if body is None:
        return False
    children = [child for child in syntax.named_children(body) if child.type != "comment"]
    return body.type in ("expression_statement", "compound_statement") and not children


def _scan_variable(loop: Node) -> str | None:
    """The counter or pointer a loop only steps: `while (...) v++;` or `for (...; v++) ;`."""
    if loop.type == "while_statement":
        statement = _only_statement(loop.child_by_field_name("body"))
        return _increment_target(_only_expression(statement))
    if _is_empty(loop.child_by_field_name("body")):
        return _increment_target(loop.child_by_field_name("update"))
    return None


def _and_parts(node: Node) -> list[Node]:
    current = syntax.unwrap_parentheses(node)
    if current.type == "binary_expression" and ctree.operator(current) == "&&":
        left = current.child_by_field_name("left")
        right = current.child_by_field_name("right")
        if left is not None and right is not None:
            return [*_and_parts(left), *_and_parts(right)]
    return [current]


def _element(node: Node | None, variable: str) -> Node | None:
    """The array in `a[v]`, or the pointer in `*v`: what the loop reads at each step."""
    if node is None:
        return None
    current = syntax.unwrap_parentheses(node)
    if current.type == "subscript_expression":
        index = current.child_by_field_name("index")
        if index is not None and _identifier_text(index) == variable:
            return current.child_by_field_name("argument")
    if current.type == "pointer_expression" and ctree.operator(current) == "*":
        argument = current.child_by_field_name("argument")
        if _identifier_text(argument) == variable:
            return argument
    return None


def _scan_test(part: Node, variable: str) -> Scan | None:
    """Classify one `&&` part of a scan loop's condition."""
    element = _element(part, variable)
    if element is not None:
        return Scan("zero", element)
    left = part.child_by_field_name("left") if part.type == "binary_expression" else None
    right = part.child_by_field_name("right") if part.type == "binary_expression" else None
    if left is None or right is None or ctree.has_side_effects(right):
        return None
    operator = ctree.operator(part)
    if operator in BOUND_OPERATORS and _identifier_text(left) == variable:
        return Scan("bound", right)
    element = _element(left, variable)
    if element is None or operator != "!=":
        return None
    return Scan("zero", element) if ctree.is_zero(right) else Scan("search", element, right)


def _sets_zero(node: Node, variable: str) -> bool:
    """True for `v = 0` and for a declaration that starts `v` at 0."""
    current = _only_expression(node) if node.type == "expression_statement" else node
    if current is None:
        return False
    if current.type == "assignment_expression":
        right = current.child_by_field_name("right")
        is_plain = ctree.operator(current) == "=" and right is not None
        return (
            is_plain
            and _identifier_text(current.child_by_field_name("left")) == variable
            and ctree.is_zero(right)
        )
    if current.type != "declaration":
        return False
    for declarator in current.children_by_field_name("declarator"):
        value = declarator.child_by_field_name("value")
        name = syntax.declared_name(declarator)
        if name is not None and syntax.text(name) == variable:
            return (
                declarator.type == "init_declarator" and value is not None and ctree.is_zero(value)
            )
    return False


def _mentions(node: Node, variable: str) -> bool:
    return any(
        child.type == "identifier" and syntax.text(child) == variable for child in syntax.walk(node)
    )


def _starts_at_zero(loop: Node, variable: str) -> bool:
    """True when the loop's own initializer, or the last statement before it that mentions
    the variable, sets it to 0."""
    if loop.type == "for_statement":
        initializer = loop.child_by_field_name("initializer")
        return initializer is not None and _sets_zero(initializer, variable)
    previous = loop.prev_named_sibling
    while previous is not None and (
        previous.type == "comment" or not _mentions(previous, variable)
    ):
        previous = previous.prev_named_sibling
    return previous is not None and _sets_zero(previous, variable)


def _strings_for(context: RuleContext, node: Node) -> Strings | None:
    """The string functions for a `char` or `wchar_t` pointer or array the tool can see."""
    function = context.function.node if context.function else None
    current = syntax.unwrap_parentheses(node)
    if function is None or current.type != "identifier":
        return None
    symbol = context.analysis.scope(function).symbol_of(current)
    if symbol is None:
        return None
    base, _, shape = symbol.type_text.rpartition(" ")
    if shape.count("*") + shape.count("[") != 1:
        return None
    if base in CHAR_TYPES:
        return NARROW
    if base in CAST_CHAR_TYPES:
        return NARROW_CAST
    return WIDE if base in WIDE_TYPES else None


def _as_string_literal(value: Node, strings: Strings) -> str | None:
    """`'/'` as `"/"`: the set of characters `strcspn` stops at."""
    spelling = syntax.text(value)
    prefix = "L" if strings.wide else ""
    if (
        value.type != "char_literal"
        or not spelling.startswith(prefix + "'")
        or not spelling.endswith("'")
    ):
        return None
    inner = spelling[len(prefix) + 1 : -1]
    replacements = {"\\'": "'", '"': '\\"'}
    return f'{prefix}"{replacements.get(inner, inner)}"'


def _scan_suggestion(
    context: RuleContext, loop: Node, variable: str, tests: list[Scan]
) -> str | None:
    kinds = sorted(test.kind for test in tests)
    subject = next(test.subject for test in tests if test.kind != "bound")
    strings = _strings_for(context, subject)
    if strings is None:
        return None
    is_pointer = syntax.text(subject) == variable
    if not is_pointer and not _starts_at_zero(loop, variable):
        return None
    target = f"{variable} += " if is_pointer else f"{variable} = "
    argument = f"{strings.cast}{syntax.text(subject)}"
    bound = next((test.subject for test in tests if test.kind == "bound"), None)
    count = None if bound is None else syntax.text(bound) + (f" - {variable}" if is_pointer else "")
    if kinds == ["zero"]:
        return f"`{target}{strings.length}({argument});`: the length up to the terminating zero."
    if kinds == ["bound", "zero"]:
        note = POSIX_NOTE.format(name=strings.bounded_length)
        return (
            f"`{target}{strings.bounded_length}({argument}, {count});`: the length up to the "
            f"first zero, at most the bound. {note}"
        )
    search = next(test for test in tests if test.kind == "search")
    stops_at = _as_string_literal(search.value, strings) if search.value is not None else None
    if kinds == ["search", "zero"] and stops_at is not None:
        return (
            f"`{target}{strings.span}({argument}, {stops_at});`: the length up to the first "
            f"{syntax.text(search.value)} or the terminating zero."
        )
    return None


@on("while_statement", "for_statement")
def scan_loop(node: Node, context: RuleContext) -> None:
    variable = _scan_variable(node)
    condition = node.child_by_field_name("condition")
    if variable is None or condition is None:
        return
    tests = [_scan_test(part, variable) for part in _and_parts(condition)]
    found = [test for test in tests if test is not None]
    subjects = {syntax.text(test.subject) for test in found if test.kind != "bound"}
    if len(found) != len(tests) or len(subjects) != 1:
        return
    suggestion = _scan_suggestion(context, node, variable, found)
    if suggestion is not None:
        context.report(
            RULE_ID,
            ADVICE,
            node,
            f"This loop only steps `{variable}` to measure a string. A call names what it does: "
            f"{suggestion} {NOT_PROVEN}",
        )


def _same_element_type(context: RuleContext, first: Node, second: Node) -> bool:
    function = context.function.node if context.function else None
    if function is None or first.type != "identifier" or second.type != "identifier":
        return False
    scope = context.analysis.scope(function)
    symbols = [scope.symbol_of(first), scope.symbol_of(second)]
    if symbols[0] is None or symbols[1] is None:
        return False
    shapes = [symbol.type_text.rpartition(" ") for symbol in symbols]
    one_level = all(shape.count("*") + shape.count("[") == 1 for _, _, shape in shapes)
    return one_level and shapes[0][0] == shapes[1][0]


@on("for_statement")
def element_loop(node: Node, context: RuleContext) -> None:
    """`for (i = 0; i < n; i++) a[i] = 0;` is memset, and `a[i] = b[i]` is memcpy."""
    variable = _increment_target(node.child_by_field_name("update"))
    condition = node.child_by_field_name("condition")
    assignment = _only_expression(_only_statement(node.child_by_field_name("body")))
    if (
        variable is None
        or condition is None
        or assignment is None
        or not _starts_at_zero(node, variable)
    ):
        return
    bound = _scan_test(syntax.unwrap_parentheses(condition), variable)
    is_copy_step = assignment.type == "assignment_expression" and ctree.operator(assignment) == "="
    target = _element(assignment.child_by_field_name("left"), variable) if is_copy_step else None
    value = assignment.child_by_field_name("right")
    if bound is None or bound.kind != "bound" or target is None or value is None:
        return
    target_text = syntax.text(target)
    count = f"{syntax.text(bound.subject)} * sizeof {target_text}[0]"
    if target_text == variable or ctree.has_side_effects(target):
        return
    if ctree.is_zero(value):
        suggestion = (
            f"This loop zeroes `{target_text}` element by element: "
            f"`memset({target_text}, 0, {count});` says so in one line."
        )
    else:
        source = _element(value, variable)
        if source is None or not _same_element_type(context, target, source):
            return
        suggestion = (
            f"This loop copies `{syntax.text(source)}` into `{target_text}` element by element: "
            f"`memcpy({target_text}, {syntax.text(source)}, {count});` says so in one line "
            "(use memmove when the two can overlap)."
        )
    context.report(RULE_ID, ADVICE, node, f"{suggestion} {NOT_PROVEN}")
