"""Rules about expressions, declarations, comments, layout and function size."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .. import conventions, ctree, lexer, syntax
from ..findings import ADVICE, RULE, Finding
from .engine import RuleContext, on, on_function, on_lines

if TYPE_CHECKING:
    from tree_sitter import Node

MAX_FUNCTION_LINES = 60
MAX_NESTING = 3
MAX_PARAMETERS = 5
EXEMPT_NUMBERS = {"0", "1", "2", "-1", "0.0", "1.0", "0x0", "0x00", "00"}
MAGIC_EXEMPT_CONTEXTS = {
    "enumerator",
    "initializer_list",
    "array_declarator",
    "preproc_def",
    "sizeof_expression",
    "field_declaration",
}
CODE_LINE = re.compile(
    r"(?:[;{}]\s*$)|^\s*(?:if|for|while|return|else|switch|case)\b|^\s*#\s*(?:if|define|include)"
)


@on("number_literal")
def magic_number(node: Node, context: RuleContext) -> None:
    spelling = syntax.text(node).rstrip("uUlLfF").lower()
    if spelling in EXEMPT_NUMBERS or syntax.enclosing(node, MAGIC_EXEMPT_CONTEXTS) is not None:
        return
    parent = node.parent
    while parent is not None and parent.type == "parenthesized_expression":
        parent = parent.parent
    is_shift_count = (
        parent is not None
        and parent.type == "binary_expression"
        and ctree.operator(parent) in ctree.SHIFTS
        and parent.child_by_field_name("right") is not None
        and parent.child_by_field_name("right").end_byte >= node.end_byte
    )
    declaration = syntax.enclosing(node, {"declaration"})
    names_a_constant = declaration is not None and any(
        syntax.text(child) == "const"
        for child in declaration.children
        if child.type == "type_qualifier"
    )
    if is_shift_count or names_a_constant:
        return
    context.report(
        "magic-number",
        ADVICE,
        node,
        f"Name `{syntax.text(node)}` unless it explains itself. In a region, `enum {{ NAME = "
        f"{syntax.text(node)} }};` inside the function keeps the type int; use it only when the "
        "literal was an int (no suffix, at most 32767).",
    )


@on("expression_statement")
def side_effects(node: Node, context: RuleContext) -> None:
    expressions = syntax.named_children(node)
    if not expressions:
        return
    expression = syntax.unwrap_parentheses(expressions[0])
    if _is_copy_idiom(expression):
        return
    changes = [
        child
        for child in syntax.walk(expression)
        if child.type in ("assignment_expression", "update_expression")
    ]
    if len(changes) < 2:  # noqa: PLR2004  one change per statement is the goal
        return
    context.report(
        "side-effects",
        ADVICE,
        node,
        f"This statement makes {len(changes)} changes. Split it into one statement per change, "
        "in the order the code performs them.",
    )


def _is_copy_idiom(expression: Node) -> bool:
    """`*dst++ = *src++;`, the classic copy step."""
    if expression.type != "assignment_expression" or ctree.operator(expression) != "=":
        return False
    sides = [expression.child_by_field_name("left"), expression.child_by_field_name("right")]
    return all(side is not None and _is_post_increment_dereference(side) for side in sides)


def _is_post_increment_dereference(node: Node) -> bool:
    current = syntax.unwrap_parentheses(node)
    if current.type != "pointer_expression" or ctree.operator(current) != "*":
        return False
    argument = current.child_by_field_name("argument")
    return argument is not None and argument.type == "update_expression"


@on("cast_expression")
def stacked_casts(node: Node, context: RuleContext) -> None:
    value = node.child_by_field_name("value")
    if value is not None and syntax.unwrap_parentheses(value).type == "cast_expression":
        context.report(
            "stacked-casts",
            ADVICE,
            node,
            "Two casts in a row. Keep both only when the middle type matters, as in "
            "`(int)(unsigned char)c`, which avoids sign extension, and say why in a comment.",
        )


@on("declaration")
def multiple_declarators(node: Node, context: RuleContext) -> None:
    in_function = syntax.enclosing(node, {"compound_statement"}) is not None
    in_for_header = node.parent is not None and node.parent.type == "for_statement"
    declarators = node.children_by_field_name("declarator")
    if in_function and not in_for_header and len(declarators) > 1:
        context.report(
            "multiple-declarators",
            ADVICE,
            node,
            "This declares several variables at once. One declaration per line is easier to read "
            "and to change.",
        )


@on_function
def function_size(node: Node, context: RuleContext) -> None:
    span = context.function
    if span is None:
        return
    owns_header = any(start <= span.definition_start < end for start, end in context.spans)
    if not owns_header:
        return
    name = node.child_by_field_name("declarator") or node
    lines = syntax.end_line(node) - syntax.start_line(node) + 1
    parameters = len(syntax.parameter_nodes(node))
    nesting = max_nesting(node.child_by_field_name("body"))
    problems = []
    if lines > MAX_FUNCTION_LINES:
        problems.append(f"{lines} lines (over {MAX_FUNCTION_LINES})")
    if nesting > MAX_NESTING:
        problems.append(f"nesting depth {nesting} (over {MAX_NESTING})")
    if parameters > MAX_PARAMETERS:
        problems.append(f"{parameters} parameters (over {MAX_PARAMETERS})")
    if problems:
        context.report(
            "function-size",
            ADVICE,
            name,
            f"`{span.name}` has {', '.join(problems)}. Extract parts with a responsibility of their "
            "own into static helpers, and flatten nesting with early returns.",
        )


NESTING_TYPES = {
    "if_statement",
    "for_statement",
    "while_statement",
    "do_statement",
    "switch_statement",
}


def max_nesting(body: Node | None) -> int:
    """How deeply if, for, while, do and switch nest; an else-if chain counts once."""
    if body is None:
        return 0
    deepest = 0
    stack: list[tuple[Node, int]] = [(body, 0)]
    while stack:
        node, depth = stack.pop()
        is_else_if = (
            node.type == "if_statement"
            and node.parent is not None
            and node.parent.type == "else_clause"
        )
        if node.type in NESTING_TYPES and not is_else_if:
            depth += 1
            deepest = max(deepest, depth)
        stack.extend((child, depth) for child in node.children)
    return deepest


@on_lines
def indent_style(context: RuleContext) -> None:
    style = context.conventions.indent_char
    if style not in ("tabs", "spaces"):
        return
    source = context.analysis.source
    lines = [
        line
        for line in conventions.code_line_starts(source, context.analysis.tokens)
        if any(start <= source.line_start(line) < end for start, end in context.spans)
    ]
    starts = [source.line_start(line) for line in lines]
    contexts = lexer.contexts_at(source.data, context.analysis.tokens, starts)
    for line, line_context in zip(lines, contexts, strict=True):
        # A line that continues a parameter list or a call is aligned, not
        # indented: files indented with tabs often align such lines with spaces.
        is_continuation = line_context.parens > 0 or line_context.brackets > 0
        content = source.line_bytes(line)
        indent = conventions.leading_whitespace(content)
        if is_continuation or not content.strip() or not indent:
            continue
        wrong = indent.startswith(b" ") if style == "tabs" else b"\t" in indent
        if wrong:
            expected = "tabs" if style == "tabs" else "spaces"
            context.findings.append(
                _line_finding(
                    context,
                    line,
                    "indent-style",
                    RULE,
                    f"The file indents with {expected}; this line does not.",
                )
            )


@on_lines
def commented_out_code(context: RuleContext) -> None:
    source = context.analysis.source
    for token in context.analysis.tokens:
        is_comment_in_span = token.kind == lexer.COMMENT and any(
            start <= token.start < end for start, end in context.spans
        )
        if not is_comment_in_span:
            continue
        lines = [line for line in _comment_lines(token.text) if line.strip()]
        code_lines = [line for line in lines if CODE_LINE.search(line)]
        if code_lines and len(code_lines) * 2 >= len(lines):
            context.findings.append(
                _line_finding(
                    context,
                    source.line_of(token.start),
                    "commented-out-code",
                    ADVICE,
                    "This comment looks like disabled code. Delete it (version control keeps "
                    "history), or rewrite it as an explanation if it documents something.",
                )
            )


def _comment_lines(text: bytes) -> list[str]:
    body = text.decode("utf-8", "replace")
    body = body[2:-2] if body.startswith("/*") else body[2:]
    return [line.strip().lstrip("*").strip() for line in body.splitlines()]


def _line_finding(
    context: RuleContext, line: int, rule: str, severity: str, message: str
) -> Finding:
    function = next(
        (
            span.name
            for span in context.analysis.functions
            if span.first_line <= line <= span.last_line
        ),
        None,
    )
    snippet = context.analysis.source.line_bytes(line).decode("utf-8", "replace").strip()
    return Finding(rule, severity, line, 1, message, function, snippet[:120])
