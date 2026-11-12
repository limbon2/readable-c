"""needs-comment: places a reader cannot understand from the code alone.

Code that makes sense to its author can still stop a reader: an allocation whose
size or owner is not obvious, a shift by a literal into a literal mask, a cast
that reads memory as another type, a call into a library the file does not
define. A comment next to such code answers the question the reader would ask.
The rule reports these places when no comment sits on the same lines or on the
two lines above. It is a rule, so inside a region every such place gets a comment,
a name that explains it, or a reason in the report.

The same rules require a one-line contract above every function in a region that
is longer than a few lines (function-contract), so a reader learns what it does,
what it returns and who frees what before reading its body.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import ctree, stdlib, syntax
from ..findings import RULE
from .engine import RuleContext, on, on_function

if TYPE_CHECKING:
    from tree_sitter import Node

RULE_ID = "needs-comment"
LINES_ABOVE = 2

ALWAYS_EXPLAINED = {"realloc", "reallocarray"}
ALLOCATORS = {
    "malloc",
    "calloc",
    "realloc",
    "reallocarray",
    "aligned_alloc",
    "memalign",
    "strdup",
    "strndup",
    "alloca",
    "_alloca",
}
RAW_MEMORY = {"memcpy", "memmove", "memset", "memcmp", "strncpy", "strncat"}
SIZE_ARITHMETIC = {"+", "-", "*", "/", "%", "<<", ">>"}
BIT_ASSIGNMENTS = {"&=", "|=", "^=", "<<=", ">>="}
STATEMENT_TYPES = {
    "expression_statement",
    "declaration",
    "return_statement",
    "if_statement",
    "while_statement",
    "do_statement",
    "for_statement",
    "switch_statement",
    "case_statement",
}
NAMED_ELSEWHERE = {"enumerator", "preproc_def", "sizeof_expression"}


def _statement_of(node: Node) -> Node:
    current = node
    while current.parent is not None and current.type not in STATEMENT_TYPES:
        current = current.parent
    return current


def _is_explained(context: RuleContext, node: Node) -> bool:
    """True when a comment ends on the lines of the code, or on the two lines above its statement."""
    first = syntax.start_line(_statement_of(node)) - LINES_ABOVE
    last = syntax.end_line(node)
    return any(start <= last and end >= first for start, end in context.comment_lines)


def _report_once(context: RuleContext, node: Node, message: str) -> None:
    statement = _statement_of(node)
    is_new = context.first_time(RULE_ID, statement.start_byte, statement.end_byte)
    if is_new and not _is_explained(context, node):
        context.report(RULE_ID, RULE, node, message)


def _callee(node: Node) -> str:
    function = node.child_by_field_name("function")
    if function is None or function.type != "identifier":
        return ""
    return syntax.text(function)


def _arguments(node: Node) -> list[Node]:
    arguments = node.child_by_field_name("arguments")
    return syntax.named_children(arguments) if arguments is not None else []


def _has_arithmetic(node: Node) -> bool:
    for child in syntax.walk(node):
        if child.type == "binary_expression" and ctree.operator(child) in SIZE_ARITHMETIC:
            return True
    return False


def _leaves_the_function(call: Node) -> bool:
    """True when the allocated block is returned or stored where it outlives the function."""
    child, parent = call, call.parent
    while parent is not None and parent.type in ("parenthesized_expression", "cast_expression"):
        child, parent = parent, parent.parent
    if parent is None:
        return False
    if parent.type == "return_statement":
        return True
    if parent.type != "assignment_expression" or parent.child_by_field_name("right") != child:
        return False
    target = parent.child_by_field_name("left")
    stored = syntax.unwrap_parentheses(target) if target is not None else None
    return stored is not None and stored.type in (
        "field_expression",
        "pointer_expression",
        "subscript_expression",
    )


@on("call_expression")
def memory_needs_comment(node: Node, context: RuleContext) -> None:
    name = _callee(node)
    if name in ALLOCATORS:
        sized = any(_has_arithmetic(argument) for argument in _arguments(node))
        if name in ALWAYS_EXPLAINED or sized or _leaves_the_function(node):
            failure = (
                " Say what happens when it fails: realloc leaves the old block allocated."
                if name in ALWAYS_EXPLAINED
                else ""
            )
            _report_once(
                context,
                node,
                f"Say who owns the memory from `{name}`, who frees it, and why its size is what it "
                f"is, for example `/* +1 for the terminating NUL; the caller frees it */`.{failure}",
            )
    elif name in RAW_MEMORY and any(_has_arithmetic(argument) for argument in _arguments(node)):
        _report_once(
            context,
            node,
            f"Say what this `{name}` copies, moves or compares, and why the offsets and sizes are "
            "right, for example `/* drop the frame just handled: header and body */`.",
        )


def _literal_inside(node: Node) -> bool:
    for child in syntax.walk(node):
        is_number = child.type == "number_literal" and syntax.text(child) not in (
            "0",
            "0x0",
            "0x00",
        )
        if is_number:
            return True
    return False


def _bits_message() -> str:
    return (
        "Say what these bits mean: the field, the encoding or the trick, for example "
        "`/* bits 4-7 of the status byte: the channel number */` or `/* 16-bit little-endian */`. "
        "A named mask or shift (`enum { CHANNEL_SHIFT = 4 };`) can replace the comment."
    )


@on("binary_expression")
def bits_need_comment(node: Node, context: RuleContext) -> None:
    is_bitwise = ctree.operator(node) in ctree.BITWISE | ctree.SHIFTS
    if not is_bitwise or syntax.enclosing(node, NAMED_ELSEWHERE) is not None:
        return
    if _literal_inside(node):
        _report_once(context, node, _bits_message())


@on("assignment_expression")
def bit_assignment_needs_comment(node: Node, context: RuleContext) -> None:
    value = node.child_by_field_name("right")
    is_bit_assignment = ctree.operator(node) in BIT_ASSIGNMENTS
    if is_bit_assignment and value is not None and _literal_inside(value):
        _report_once(context, node, _bits_message())


OFFSET_ARITHMETIC = {"+", "-", "*", "/"}
MIN_UNEXPLAINED_LITERAL = 2


def _literal_value(node: Node) -> int | None:
    current = syntax.unwrap_parentheses(node)
    if current.type != "number_literal":
        return None
    spelling = syntax.text(current).rstrip("uUlL")
    try:
        return int(spelling, 16 if spelling.lower().startswith("0x") else 10)
    except ValueError:
        return None


def _literal_arithmetic(node: Node) -> bool:
    """True when the expression adds, subtracts, multiplies or divides by a literal of 2 or
    more: `2 * len + 1`, `pos + 4`. Adding or subtracting 1 reads as obvious and is left alone."""
    for child in syntax.walk(node):
        is_arithmetic = (
            child.type == "binary_expression" and ctree.operator(child) in OFFSET_ARITHMETIC
        )
        if not is_arithmetic:
            continue
        for side in ("left", "right"):
            operand = child.child_by_field_name(side)
            value = _literal_value(operand) if operand is not None else None
            if value is not None and value >= MIN_UNEXPLAINED_LITERAL:
                return True
    return False


def _bounds_message() -> str:
    return (
        "Say what this bound or offset is made of, which fields it adds up and their sizes, or "
        "build it from named sizes such as `pos + ENTRY_HEADER_LEN` or `sizeof(WCHAR)`, so a "
        "reader does not have to work out the numbers."
    )


@on("binary_expression")
def bound_needs_comment(node: Node, context: RuleContext) -> None:
    is_comparison = ctree.operator(node) in ctree.COMPARISONS
    if not is_comparison or syntax.enclosing(node, NAMED_ELSEWHERE) is not None:
        return
    operands = [node.child_by_field_name(side) for side in ("left", "right")]
    if any(operand is not None and _literal_arithmetic(operand) for operand in operands):
        _report_once(context, node, _bounds_message())


@on("subscript_expression")
def index_needs_comment(node: Node, context: RuleContext) -> None:
    index = node.child_by_field_name("index")
    if index is not None and _literal_arithmetic(index):
        _report_once(context, node, _bounds_message())


@on("assignment_expression")
def offset_needs_comment(node: Node, context: RuleContext) -> None:
    """A position advanced by a literal: `pos += 36`, `pos = pos + 4 + len * 2 + 2`."""
    target = node.child_by_field_name("left")
    value = node.child_by_field_name("right")
    if target is None or value is None:
        return
    operator = ctree.operator(node)
    steps_by_literal = operator in ("+=", "-=") and (
        (_literal_value(value) or 0) >= MIN_UNEXPLAINED_LITERAL or _literal_arithmetic(value)
    )
    target_text = syntax.text(syntax.unwrap_parentheses(target))
    advances_itself = (
        operator == "="
        and _literal_arithmetic(value)
        and any(syntax.text(child) == target_text for child in syntax.walk(value))
    )
    if steps_by_literal or advances_itself:
        _report_once(context, node, _bounds_message())


CONTRACT_MIN_LINES = 10


@on_function
def function_contract(node: Node, context: RuleContext) -> None:
    span = context.function
    if span is None:
        return
    owns_header = any(start <= span.definition_start < end for start, end in context.spans)
    lines = syntax.end_line(node) - syntax.start_line(node) + 1
    has_comment_above = span.first_line < context.analysis.source.line_of(span.definition_start)
    if not owns_header or has_comment_above or lines <= CONTRACT_MIN_LINES:
        return
    declarator = node.child_by_field_name("declarator")
    return_type = node.child_by_field_name("type")
    returns_nothing = (
        return_type is not None
        and syntax.text(return_type) == "void"
        and declarator is not None
        and declarator.type == "function_declarator"
    )
    result = (
        "what it changes" if returns_nothing else "what it returns (and what it returns on failure)"
    )
    context.report(
        "function-contract",
        RULE,
        declarator or node,
        f"Add a short comment above `{span.name}`: what it does, {result}, and who frees memory "
        "it allocates or takes. Write only what the code shows, and say nothing that does not "
        "apply.",
    )


def _is_pointer_cast(node: Node | None) -> bool:
    if node is None:
        return False
    current = syntax.unwrap_parentheses(node)
    if current.type != "cast_expression":
        return False
    type_node = current.child_by_field_name("type")
    return type_node is not None and "*" in syntax.text(type_node)


@on("pointer_expression", "field_expression", "subscript_expression")
def reinterpretation_needs_comment(node: Node, context: RuleContext) -> None:
    is_dereference = node.type != "pointer_expression" or ctree.operator(node) == "*"
    is_arrow = node.type != "field_expression" or ctree.operator(node) == "->"
    reads_through_cast = (
        is_dereference and is_arrow and _is_pointer_cast(node.child_by_field_name("argument"))
    )
    if reads_through_cast:
        _report_once(
            context,
            node,
            "This reads memory as another type. Say what the bytes at this address are and what "
            "the cast assumes about layout, byte order and alignment.",
        )


@on("call_expression")
def library_call_needs_comment(node: Node, context: RuleContext) -> None:
    name = _callee(node)
    function = context.function.node if context.function else None
    if not name or function is None:
        return
    known = context.known_names
    is_standard = name in stdlib.STANDARD_NAMES or name in stdlib.ALWAYS_KNOWN
    from_elsewhere = (
        not is_standard
        and name not in context.analysis.file_scope_names
        and name not in known.names
        and context.analysis.scope(function).symbol_of(node.child_by_field_name("function")) is None
    )
    if not from_elsewhere or not known.unknown_system_headers:
        return
    if not context.first_time(
        RULE_ID, "call", context.function.name if context.function else "", name
    ):
        return
    headers = ", ".join(f"<{header}>" for header in known.unknown_system_headers)
    if not _is_explained(context, node):
        context.report(
            RULE_ID,
            RULE,
            node,
            f"`{name}` comes from outside this file, probably from {headers}. Unless its name says "
            "it all, say what it does here: what it returns on failure, who owns what it returns, "
            "its units. Take that from the library's header or documentation, not from a guess.",
        )
