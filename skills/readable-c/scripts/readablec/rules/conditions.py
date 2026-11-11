"""Rules about conditions and the operators inside them."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import ctree, syntax
from ..findings import ADVICE, RULE
from .engine import RuleContext, on

if TYPE_CHECKING:
    from tree_sitter import Node


# named-conditions: Mannie's rule (scripts/eslint/named-conditions.mjs), ported to C.
#
# A condition that joins raw expressions with && or || makes the reader work out
# every part to learn what is checked. Named parts say it directly:
#
#     bool is_in_range = index < count;
#     if (is_in_range && is_table_row) { ... }
#
# A part counts as named when it is a variable, a member path (`cfg->enabled`),
# a call of a named function with plain arguments (`is_empty(list)`), a literal,
# or the negation of one of these. Initializers are not checked, because
# `bool is_valid = a && b;` already names the whole condition; that is also how
# to keep a guard such as `p != NULL && p->len > 0` intact.


def _named_condition_message(context: RuleContext, is_loop: bool) -> str:
    boolean = context.conventions.boolean_type.split(" ")[0]
    if is_loop:
        return (
            "Name this part of the loop condition. A loop evaluates its condition again on "
            "every pass, so a variable set before the loop would go stale: move the check into "
            "a static function such as `is_at_end(...)`, or leave it and say why in the report."
        )
    return (
        f"Name this part of the condition (`{boolean} is_in_range = index < count;`) and "
        "combine the names. If the part is only safe after an earlier part (a NULL or bounds "
        "check), name the whole condition as one value or move it into a static function: "
        "separate variables would evaluate it even when the guard fails."
    )


def _check_condition(
    context: RuleContext, condition: Node, *, severity: str, is_loop: bool, only_conditions: bool
) -> None:
    root = syntax.unwrap_parentheses(condition)
    while ctree.is_negation(root):
        argument = root.child_by_field_name("argument")
        if argument is None:
            return
        root = syntax.unwrap_parentheses(argument)
    if not ctree.is_composition(root):
        return
    parts = ctree.condition_parts(root)
    if only_conditions and not _looks_like_condition(parts):
        return
    message = _named_condition_message(context, is_loop)
    for part in parts:
        if not ctree.is_named(part):
            context.report("named-conditions", severity, part, message)


def _looks_like_condition(parts: list[Node]) -> bool:
    """A returned && or || is a condition when one of its parts compares or negates."""
    for part in parts:
        is_comparison = (
            part.type == "binary_expression" and ctree.operator(part) in ctree.COMPARISONS
        )
        if is_comparison or ctree.is_negation(part):
            return True
    return False


def _statement_severity(context: RuleContext) -> str:
    # Naming a part needs a declaration in the middle of a block, which a file
    # without C99 declarations cannot take; there it is a judgment call.
    return RULE if context.conventions.allows_mixed_declarations else ADVICE


@on("if_statement")
def named_conditions_in_if(node: Node, context: RuleContext) -> None:
    condition = node.child_by_field_name("condition")
    if condition is not None:
        _check_condition(
            context,
            condition,
            severity=_statement_severity(context),
            is_loop=False,
            only_conditions=False,
        )


@on("while_statement", "do_statement", "for_statement")
def named_conditions_in_loop(node: Node, context: RuleContext) -> None:
    condition = node.child_by_field_name("condition")
    if condition is not None:
        _check_condition(context, condition, severity=ADVICE, is_loop=True, only_conditions=False)


@on("conditional_expression")
def named_conditions_in_choice(node: Node, context: RuleContext) -> None:
    condition = node.child_by_field_name("condition")
    if condition is not None:
        _check_condition(
            context,
            condition,
            severity=_statement_severity(context),
            is_loop=False,
            only_conditions=False,
        )


@on("return_statement")
def named_conditions_in_return(node: Node, context: RuleContext) -> None:
    values = syntax.named_children(node)
    if values:
        _check_condition(
            context,
            values[0],
            severity=_statement_severity(context),
            is_loop=False,
            only_conditions=True,
        )


@on("conditional_expression")
def nested_ternary(node: Node, context: RuleContext) -> None:
    for field in ("condition", "consequence", "alternative"):
        part = node.child_by_field_name(field)
        if part is not None and syntax.unwrap_parentheses(part).type == "conditional_expression":
            context.report(
                "nested-ternary",
                RULE,
                node,
                "This `?:` holds another `?:`. Rewrite it with if/else, or name the inner choice "
                "in a variable first.",
            )
            return


@on("conditional_expression")
def unneeded_ternary(node: Node, context: RuleContext) -> None:
    condition = node.child_by_field_name("condition")
    consequence = node.child_by_field_name("consequence")
    alternative = node.child_by_field_name("alternative")
    if condition is None or consequence is None or alternative is None:
        return
    if syntax.text(consequence) == syntax.text(alternative):
        context.report(
            "unneeded-ternary",
            RULE,
            node,
            "Both branches of this `?:` are the same. Keep the value and drop the choice, but keep "
            "the condition as a statement if it has side effects.",
        )
        return
    pair = (_truth_value(consequence), _truth_value(alternative))
    if pair not in ((1, 0), (0, 1)):
        return
    uses_macros = any(syntax.text(part) in ("TRUE", "FALSE") for part in (consequence, alternative))
    shown = syntax.text(syntax.unwrap_parentheses(condition))
    if ctree.is_boolean_valued(condition):
        replacement = shown if pair == (1, 0) else f"!({shown})"
    else:
        replacement = f"({shown}) != 0" if pair == (1, 0) else f"({shown}) == 0"
    if uses_macros:
        context.report(
            "unneeded-ternary",
            ADVICE,
            node,
            f"This `?:` turns a condition into TRUE or FALSE. If TRUE is 1 and FALSE is 0, write "
            f"`{replacement}`; check the macros before changing it.",
        )
        return
    context.report(
        "unneeded-ternary",
        RULE,
        node,
        f"This `?:` only turns a condition into 1 or 0. Write `{replacement}`, which has the "
        "same value.",
    )


def _truth_value(node: Node) -> int | None:
    current = syntax.unwrap_parentheses(node)
    spelling = syntax.text(current)
    if current.type in ("true", "false"):
        return 1 if current.type == "true" else 0
    if current.type == "number_literal" and spelling in ("0", "1"):
        return int(spelling)
    return None


@on("if_statement", "while_statement", "do_statement", "for_statement", "conditional_expression")
def assignment_in_condition(node: Node, context: RuleContext) -> None:
    condition = node.child_by_field_name("condition")
    if condition is None:
        return
    for part in ctree.condition_parts(condition):
        if part.type == "assignment_expression":
            context.report(
                "assignment-in-condition",
                RULE,
                part,
                "This condition assigns. Assign in a statement before it and test the variable, "
                "for example `count = read_items(list); if (count != 0)`. Comparing the assignment, "
                "as in `while ((c = getchar()) != EOF)`, is a known idiom and is allowed.",
            )


@on("binary_expression")
def mixed_operators(node: Node, context: RuleContext) -> None:
    outer = ctree.operator(node)
    for side in ("left", "right"):
        operand = node.child_by_field_name(side)
        if operand is None or operand.type != "binary_expression":
            continue
        inner = ctree.operator(operand)
        if not _needs_parentheses(outer, inner):
            continue
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None or right is None:
            return
        left_text, right_text = syntax.text(left), syntax.text(right)
        if side == "left":
            left_text = f"({left_text})"
        else:
            right_text = f"({right_text})"
        context.report(
            "mixed-operators",
            RULE,
            node,
            f"`{syntax.text(node)}` groups as `{left_text} {outer} {right_text}`. Add those "
            "parentheses so the grouping is visible. If that grouping is not what the author "
            "meant, keep the behavior and report it as a suspected bug.",
        )
        return


def _needs_parentheses(outer: str, inner: str) -> bool:
    if outer == inner:
        return False
    if outer in ctree.BITWISE:
        return inner in ctree.COMPARISONS | ctree.ARITHMETIC | ctree.SHIFTS | ctree.BITWISE
    if outer in ctree.SHIFTS:
        return inner in ctree.ARITHMETIC
    return outer in ctree.LOGICAL and inner in ctree.LOGICAL


@on("binary_expression")
def boolean_literal(node: Node, context: RuleContext) -> None:
    if ctree.operator(node) not in ("==", "!="):
        return
    for side in ("left", "right"):
        operand = node.child_by_field_name(side)
        if operand is not None and syntax.unwrap_parentheses(operand).type in ("true", "false"):
            context.report(
                "boolean-literal",
                ADVICE,
                node,
                "Comparing with TRUE or FALSE: `x == TRUE` is false when x is 2. Write `x` or "
                "`!x` only when x is known to hold 0 or 1 (a comparison result or a bool).",
            )
            return
