"""Rules about the shape of control flow: else after a jump, braces, indentation, goto."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import ctree, syntax
from ..findings import ADVICE, RULE
from .engine import RuleContext, on

if TYPE_CHECKING:
    from tree_sitter import Node


@on("if_statement")
def else_after_return(node: Node, context: RuleContext) -> None:
    clause = node.child_by_field_name("alternative")
    if clause is None or not ctree.always_jumps(node.child_by_field_name("consequence")):
        return
    context.report(
        "else-after-return",
        RULE,
        clause,
        "The branch before this `else` always leaves (return, break, continue or goto). Drop "
        "the `else` and move its body out one level. Rename any of its declarations that would "
        "clash with names after it.",
    )


@on("else_clause")
def lonely_if(node: Node, context: RuleContext) -> None:
    statements = syntax.named_children(node)
    if len(statements) != 1 or statements[0].type != "compound_statement":
        return
    inner = syntax.named_children(statements[0])
    if len(inner) == 1 and inner[0].type == "if_statement":
        context.report(
            "lonely-if",
            RULE,
            node,
            "This `else` block holds only an `if`. Write `else if` and drop one level of braces.",
        )


def _bodies(node: Node) -> list[Node]:
    if node.type == "if_statement":
        bodies = [node.child_by_field_name("consequence")]
        alternative = ctree.else_statement(node)
        if alternative is not None and alternative.type != "if_statement":
            bodies.append(alternative)
        return [body for body in bodies if body is not None]
    body = node.child_by_field_name("body")
    return [body] if body is not None else []


@on("if_statement", "while_statement", "for_statement", "do_statement")
def missing_braces(node: Node, context: RuleContext) -> None:
    for body in _bodies(node):
        if body.type == "compound_statement":
            continue
        is_empty = body.type == "expression_statement" and not syntax.named_children(body)
        message = (
            "This body is a lone `;`, which is easy to misread. Write `{}`, with a comment if the "
            "empty body is on purpose."
            if is_empty
            else "Add braces around this body. Brace exactly the statement the parser sees as the "
            "body, whatever the indentation suggests."
        )
        context.report("missing-braces", RULE, body, message)


@on("if_statement", "while_statement", "for_statement")
def misleading_indentation(node: Node, context: RuleContext) -> None:
    body = _last_unbraced_body(node)
    following = node.next_named_sibling
    while following is not None and following.type == "comment":
        following = following.next_named_sibling
    if body is None or following is None:
        return
    data = context.analysis.data
    source = context.analysis.source
    same_line = syntax.end_line(body) == syntax.start_line(following)
    guard_indent = ctree.indentation_of_line(data, source.line_start(syntax.start_line(node)))
    body_indent = ctree.indentation_of_line(data, source.line_start(syntax.start_line(body)))
    next_indent = ctree.indentation_of_line(data, source.line_start(syntax.start_line(following)))
    body_on_own_line = syntax.start_line(body) > syntax.start_line(node)
    indents = (guard_indent, body_indent, next_indent)
    mixes_tabs_and_spaces = any(b"\t" in indent for indent in indents) and any(
        b" " in indent for indent in indents
    )
    looks_inside = (
        body_on_own_line and next_indent == body_indent and len(body_indent) > len(guard_indent)
    )
    if mixes_tabs_and_spaces and not same_line:
        return
    if same_line or looks_inside:
        context.report(
            "misleading-indentation",
            RULE,
            following,
            f"This statement looks like part of the body on line {syntax.start_line(body)}, but it "
            "runs whatever the condition is. Brace only what the parser sees (the first statement), "
            "keep the behavior, and report it as a suspected bug.",
        )


def _last_unbraced_body(node: Node) -> Node | None:
    if node.type == "if_statement":
        alternative = ctree.else_statement(node)
        body = alternative if alternative is not None else node.child_by_field_name("consequence")
    else:
        body = node.child_by_field_name("body")
    if body is None or body.type in ("compound_statement", "if_statement"):
        return None
    return body


@on("goto_statement")
def goto(node: Node, context: RuleContext) -> None:
    label = node.child_by_field_name("label")
    function = context.function.node if context.function else None
    if label is None or function is None:
        return
    target = context.analysis.scope(function).labels.get(syntax.text(label))
    if target is None:
        return
    statement = target.statement
    body = function.child_by_field_name("body")
    is_backward = statement.start_byte < node.start_byte
    is_top_level = statement.parent == body
    if is_backward:
        message = (
            "This `goto` jumps backward, which is a loop in disguise. Consider a `while` or `for` "
            "loop with the same exit conditions."
        )
    elif not is_top_level:
        message = (
            "This `goto` jumps into a nested block. Restructure it, or explain it in a comment."
        )
    else:
        return
    context.report("goto", ADVICE, node, message)
