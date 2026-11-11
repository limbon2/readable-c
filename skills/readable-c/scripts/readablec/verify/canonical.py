"""Tier 1: a canonical form of a function that ignores the readability refactors.

Two versions of a function with equal canonical forms behave the same. The form
drops what those refactors change and what cannot change behavior:

- comments, layout and redundant parentheses (kept inside call arguments,
  which may belong to a macro, and inside `sizeof`);
- the names of locals, parameters and labels: a variable becomes its order of
  first appearance and its type, so a rename matches, a changed type does not,
  and a rename that captures another name binds differently and does not match;
- where a local is declared: `int x = E;` reads as the statement `x = E;`;
- braces around a single statement, `else` after a branch that always leaves,
  `else { if }`, nested `if`s without `else` (one `if` with `&&`), and plain
  nested blocks;
- in a loop body, `if (c) { ...; continue; } rest` (an `if` with `else`);
- a `for` loop without its own `continue` (a `while` loop);
- `return c ? a : b;` and `x = c ? a : b;` (an `if` with `else`);
- `E != 0`, `E == 0`, `!!E`, `c ? 1 : 0`, comparison order, and comparisons of
  two integer literals;
- `x++`, `++x` and `x += 1` used as statements;
- an assignment at the head of an `if` condition, `if ((x = f()) > 0)`, moved
  into the statement before it;
- a named value used once, inlined where that cannot change evaluation (see
  `_can_inline`), and constants the file defines with a literal value.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import ctree, lexer, syntax
from ..scopes import FunctionScope, NodeKey, Symbol, key

if TYPE_CHECKING:
    from tree_sitter import Node

    from ..analysis import Analysis

Canonical = tuple

# Operator spellings that the generic form keeps, because they change meaning.
OPERATOR_TOKENS = {
    "+", "-", "*", "/", "%", "&", "|", "^", "~", "!", "<<", ">>", "&&", "||", "==", "!=", "<",
    "<=", ">", ">=", "=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>=", "++",
    "--", "->", ".", "?", ":", ",", "...",
}  # fmt: skip
FLIPPED = {">": "<", ">=": "<="}
MAX_SAFE_ENUM_VALUE = 32767
SIGN_AND_NUMBER = 2


def constant_values(analysis: Analysis) -> dict[str, Canonical]:
    """Names the file defines exactly once as a literal: `#define N 5`, `enum { N = 5 }`."""
    seen: dict[str, list[Canonical | None]] = {}
    for token in analysis.tokens:
        macro = lexer.macro_definition(token)
        if macro is not None and not macro.is_function_like:
            seen.setdefault(macro.name.decode("utf-8", "surrogateescape"), []).append(
                _literal_body(macro.body)
            )
    for node in syntax.walk(analysis.root):
        if node.type != "enumerator":
            continue
        name = node.child_by_field_name("name")
        if name is not None:
            seen.setdefault(syntax.text(name), []).append(
                _safe_enum_value(node.child_by_field_name("value"))
            )
    return {
        name: values[0]
        for name, values in seen.items()
        if len(values) == 1 and values[0] is not None
    }


def _literal_body(body: bytes) -> Canonical | None:
    text = body.decode("utf-8", "surrogateescape").strip()
    while text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    tokens = lexer.tokenize(text.encode("utf-8", "surrogateescape"))
    is_negative_number = (
        len(tokens) == SIGN_AND_NUMBER and tokens[0].text == b"-" and tokens[1].kind == lexer.NUMBER
    )
    if is_negative_number:
        return ("num", "-" + tokens[1].text.decode())
    if len(tokens) == 1 and tokens[0].kind in (lexer.NUMBER, lexer.CHAR, lexer.STRING):
        kind = "num" if tokens[0].kind == lexer.NUMBER else "lit"
        return (kind, tokens[0].text.decode("utf-8", "surrogateescape"))
    return None


def _safe_enum_value(value: Node | None) -> Canonical | None:
    """An enum constant equals its literal only for a plain int literal that fits every int."""
    if value is None or value.type != "number_literal":
        return None
    spelling = syntax.text(value)
    try:
        number = int(spelling, 0)
    except ValueError:
        return None
    if 0 <= number <= MAX_SAFE_ENUM_VALUE:
        return ("num", spelling)
    return None


class Canonicalizer:
    def __init__(self, analysis: Analysis, function: Node, constants: dict[str, Canonical]) -> None:
        self.analysis = analysis
        self.function = function
        self.scope: FunctionScope = analysis.scope(function)
        self.constants = constants
        self.inlined = _inlinable(self.scope)
        self.ordinals: dict[int, int] = {}
        self.ordinal_names: dict[int, str] = {}
        self.hoisted: dict[NodeKey, Node] = {}

    def canonical_function(self) -> Canonical:
        parameters = tuple(
            self.variable(symbol) for symbol in self.scope.symbols if symbol.kind == "parameter"
        )
        body = self.function.child_by_field_name("body")
        return ("function", parameters, self.block(body) if body is not None else None)

    def variable(self, symbol: Symbol) -> Canonical:
        if id(symbol) not in self.ordinals:
            ordinal = len(self.ordinals)
            self.ordinals[id(symbol)] = ordinal
            self.ordinal_names[ordinal] = symbol.name
        return ("L", self.ordinals[id(symbol)], _without_const(symbol.type_text))

    # Statements

    def block(self, node: Node) -> Canonical:
        return ("block", tuple(self.statements(syntax.named_children(node))))

    def statements(self, nodes: list[Node]) -> list[Canonical]:
        result: list[Canonical] = []
        for node in nodes:
            self._append(result, node)
        return result

    def _append(self, result: list[Canonical], node: Node) -> None:  # noqa: PLR0911  one return per statement kind
        if node.type == "comment":
            return
        if node.type == "declaration":
            result.extend(self.declaration(node))
            return
        if node.type == "enum_specifier" and self._enum_is_substituted(node):
            return
        if node.type == "compound_statement":
            result.extend(self.statements(syntax.named_children(node)))
            return
        if node.type == "expression_statement":
            result.extend(self.expression_statement(node))
            return
        if node.type in ("if_statement", "switch_statement"):
            self._hoist_leading_assignment(result, node)
        if node.type == "return_statement":
            values = syntax.named_children(node)
            result.extend(self._returned(values[0]) if values else [("return", None)])
            return
        if node.type == "for_statement":
            result.extend(self._for_loop(node))
            return
        is_else_after_jump = (
            node.type == "if_statement"
            and node.child_by_field_name("alternative") is not None
            and ctree.always_jumps(node.child_by_field_name("consequence"))
        )
        if is_else_after_jump:
            condition = node.child_by_field_name("condition")
            consequence = node.child_by_field_name("consequence")
            result.append(_if(self.condition(condition), self.body(consequence), None))
            alternative = ctree.else_statement(node)
            if alternative is not None:
                self._append(result, alternative)
            return
        result.append(self.statement(node))

    def _enum_is_substituted(self, node: Node) -> bool:
        """A local `enum { N = 5 };` whose every constant reads as its literal adds nothing."""
        body = node.child_by_field_name("body")
        if body is None or node.child_by_field_name("name") is not None:
            return False
        enumerators = [child for child in body.named_children if child.type == "enumerator"]
        return bool(enumerators) and all(
            _safe_enum_value(enumerator.child_by_field_name("value")) is not None
            for enumerator in enumerators
        )

    def _hoist_leading_assignment(self, result: list[Canonical], node: Node) -> None:
        """`if ((x = f()) > 0)` is `x = f(); if (x > 0)`: the assignment runs first either way."""
        condition = node.child_by_field_name("condition")
        assignment = _leading_assignment(condition) if condition is not None else None
        if assignment is None:
            return
        target = assignment.child_by_field_name("left")
        if target is None:
            return
        result.append(("expr", self.expression(assignment)))
        self.hoisted[key(assignment)] = target

    def body(self, node: Node | None) -> Canonical | None:
        if node is None:
            return None
        return _as_body(self.statements([node]))

    def loop_body(self, node: Node | None) -> Canonical | None:
        if node is None:
            return None
        return _as_body(self._fold_continues(self.statements([node])))

    def _fold_continues(self, items: list[Canonical]) -> list[Canonical]:
        """At the top of a loop body, `if (c) { x; continue; } rest` is `if (c) { x } else { rest }`."""
        for index, item in enumerate(items):
            is_guard = item[0] == "if" and item[3] is None and _ends_with_continue(item[2])
            if is_guard:
                rest = self._fold_continues(items[index + 1 :])
                guarded = _if(item[1], _without_final_continue(item[2]), _as_body(rest))
                return [*items[:index], guarded]
        return items

    def _returned(self, value: Node) -> list[Canonical]:
        """`return c ? a : b;` is `if (c) return a; return b;`."""
        choice = _choice_parts(value)
        if choice is None:
            return [("return", self.expression(value))]
        condition, consequence, alternative = choice
        return [
            _if(self.condition(condition), _as_body(self._returned(consequence)), None),
            *self._returned(alternative),
        ]

    def _assigned(self, target: Canonical | None, value: Node) -> Canonical:
        """`x = c ? a : b;` is `if (c) x = a; else x = b;`."""
        choice = _choice_parts(value)
        if choice is None:
            return ("expr", ("assignment_expression", target, "=", self.expression(value)))
        condition, consequence, alternative = choice
        return _if(
            self.condition(condition),
            self._assigned(target, consequence),
            self._assigned(target, alternative),
        )

    def _for_loop(self, node: Node) -> list[Canonical]:
        """`for (init; test; step) body` is `init; while (test) { body step }` once the body
        has no `continue` of its own, which would skip the step. Continue guards are folded
        first, so a loop flattened with `continue` still reads as the nested original."""
        initializer = node.child_by_field_name("initializer")
        condition = node.child_by_field_name("condition")
        update = node.child_by_field_name("update")
        items: list[Canonical] = []
        if initializer is not None and initializer.type == "declaration":
            items.extend(self.declaration(initializer))
        elif initializer is not None:
            items.extend(("expr", effect) for effect in self.effects(initializer))
        body = node.child_by_field_name("body")
        body_items = self._fold_continues(self.statements([body])) if body is not None else []
        steps = [("expr", effect) for effect in self.effects(update)] if update is not None else []
        test = self.condition(condition) if condition is not None else ("num", "1")
        if _has_own_continue(body_items):
            items.append(("for", test, tuple(steps), _as_body(body_items)))
        else:
            items.append(("while", test, _as_body(body_items + steps)))
        return items

    def statement(self, node: Node) -> Canonical:  # noqa: PLR0911  one branch per statement kind
        kind = node.type
        if kind == "if_statement":
            alternative = ctree.else_statement(node)
            return _if(
                self.condition(node.child_by_field_name("condition")),
                self.body(node.child_by_field_name("consequence")),
                self.body(alternative) if alternative is not None else None,
            )
        if kind == "while_statement":
            return (
                "while",
                self.condition(node.child_by_field_name("condition")),
                self.loop_body(node.child_by_field_name("body")),
            )
        if kind == "do_statement":
            return (
                "do",
                self.loop_body(node.child_by_field_name("body")),
                self.condition(node.child_by_field_name("condition")),
            )
        if kind in ("break_statement", "continue_statement"):
            return (kind,)
        if kind == "goto_statement":
            return ("goto", self.label(node.child_by_field_name("label")))
        if kind == "labeled_statement":
            label = node.child_by_field_name("label")
            rest = [child for child in syntax.named_children(node) if child != label]
            return ("label", self.label(label), tuple(self.statements(rest)))
        if kind == "switch_statement":
            body = node.child_by_field_name("body")
            return (
                "switch",
                self.expression(node.child_by_field_name("condition")),
                self.block(body) if body else None,
            )
        if kind == "case_statement":
            value = node.child_by_field_name("value")
            rest = [child for child in syntax.named_children(node) if child != value]
            return (
                "case",
                self.expression(value) if value is not None else "default",
                tuple(self.statements(rest)),
            )
        return self.generic(node)

    def expression_statement(self, node: Node) -> list[Canonical]:
        values = syntax.named_children(node)
        if not values:
            return []
        expression = syntax.unwrap_parentheses(values[0])
        is_assigned_choice = (
            expression.type == "assignment_expression"
            and ctree.operator(expression) == "="
            and _choice_parts(expression.child_by_field_name("right")) is not None
            and ctree.is_path(expression.child_by_field_name("left"))
        )
        if is_assigned_choice:
            target = self.expression(expression.child_by_field_name("left"))
            return [self._assigned(target, expression.child_by_field_name("right"))]
        return [("expr", effect) for effect in self.effects(values[0])]

    def effects(self, node: Node) -> list[Canonical]:
        """An expression whose value is discarded: comma parts become separate steps."""
        current = syntax.unwrap_parentheses(node)
        if current.type == "comma_expression":
            left = current.child_by_field_name("left")
            right = current.child_by_field_name("right")
            return (
                [*self.effects(left), *self.effects(right)]
                if left and right
                else [self.expression(current)]
            )
        target = _plain_target(current)
        if target is not None and current.type == "update_expression":
            operator = "+" if ctree.operator(current) == "++" else "-"
            return [self._expanded(target, operator, ("num", "1"))]
        is_compound = (
            current.type == "assignment_expression" and ctree.operator(current) in COMPOUND
        )
        if target is not None and is_compound:
            operator = ctree.operator(current)[:-1]
            value = self.expression(current.child_by_field_name("right"))
            return [self._expanded(target, operator, value)]
        return [self.expression(current)]

    def _expanded(self, target: Node, operator: str, value: Canonical | None) -> Canonical:
        """`x++`, `x += 1` and `x = x + 1` as one form: valid when evaluating `x` has no effects."""
        place = self.expression(target)
        return ("assignment_expression", place, "=", ("binary", operator, place, value))

    def declaration(self, node: Node) -> list[Canonical]:
        """Locals become assignments; static locals, arrays and others stay declarations."""
        storage = tuple(
            sorted(
                syntax.text(child)
                for child in node.children
                if child.type == "storage_class_specifier" and syntax.text(child) != "register"
            )
        )
        result: list[Canonical] = []
        for declarator in node.children_by_field_name("declarator"):
            inner, value = declarator, None
            if declarator.type == "init_declarator":
                inner = declarator.child_by_field_name("declarator")
                value = declarator.child_by_field_name("value")
            name = syntax.declared_name(inner)
            symbol = self.scope.symbol_of(name) if name is not None else None
            if symbol is not None and symbol in self.inlined:
                continue
            is_plain_local = (
                symbol is not None
                and symbol.kind == "local"
                and "[" not in symbol.type_text
                and (value is None or value.type != "initializer_list")
            )
            if is_plain_local:
                assert symbol is not None, "checked above"
                if value is not None:
                    result.append(self._assigned(self.variable(symbol), value))
                continue
            if symbol is not None and symbol.is_variable:
                identity: Canonical = self.variable(symbol)
            else:
                identity = ("id", syntax.text(name) if name is not None else "")
            type_text = (
                symbol.type_text if symbol is not None else " ".join(syntax.text(node).split())
            )
            result.append(
                (
                    "decl",
                    storage,
                    _without_const(type_text),
                    identity,
                    self.expression(value) if value is not None else None,
                )
            )
        return result

    # Expressions

    def condition(self, node: Node | None) -> Canonical | None:  # noqa: PLR0911  one return per kind of test
        """An expression in a boolean context, where only zero or non-zero matters."""
        if node is None:
            return None
        current = syntax.unwrap_parentheses(node)
        if key(current) in self.hoisted:
            return self.condition(self.hoisted[key(current)])
        if current.type == "identifier":
            symbol = self.scope.symbol_of(current)
            if symbol is not None and symbol in self.inlined and symbol.value is not None:
                return self.condition(symbol.value)
        if current.type == "binary_expression":
            operator = ctree.operator(current)
            left = current.child_by_field_name("left")
            right = current.child_by_field_name("right")
            if left is not None and right is not None and operator in ("!=", "=="):
                other = right if ctree.is_zero(left) else left if ctree.is_zero(right) else None
                if other is not None:
                    tested = self.condition(other)
                    return tested if operator == "!=" else _negate(tested)
        if ctree.is_negation(current):
            return _negate(self.condition(current.child_by_field_name("argument")))
        value = self.expression(current)
        if value is not None and value[0] == "bool":
            return value[1]
        return value

    def truth(self, node: Node | None) -> Canonical | None:
        """The 0-or-1 value of a condition, as `E != 0` gives it."""
        if node is None:
            return None
        if ctree.is_boolean_valued(node):
            return self.expression(node)
        return ("bool", self.condition(node))

    def expression(self, node: Node | None, in_arguments: bool = False) -> Canonical | None:  # noqa: PLR0911, PLR0912, C901  one branch per expression kind
        if node is None:
            return None
        if key(node) in self.hoisted:
            return self.expression(self.hoisted[key(node)], in_arguments)
        kind = node.type
        if kind == "parenthesized_expression":
            inner = syntax.named_children(node)
            if not inner:
                return ("()",)
            value = self.expression(inner[0], in_arguments)
            return ("()", value) if in_arguments else value
        if kind == "identifier":
            return self.identifier(node)
        if kind == "number_literal":
            return ("num", syntax.text(node))
        if kind in ("string_literal", "concatenated_string"):
            return ("lit", _string_content(node))
        if kind in ("char_literal", "true", "false", "null"):
            return ("lit", syntax.text(node))
        if kind == "binary_expression":
            return self.binary(node, in_arguments)
        if ctree.is_negation(node):
            argument = node.child_by_field_name("argument")
            inner = syntax.unwrap_parentheses(argument) if argument is not None else None
            if inner is not None and ctree.is_negation(inner):
                return self.truth(inner.child_by_field_name("argument"))
            return _negate(self.condition(argument))
        if kind == "conditional_expression":
            return self.choice(node, in_arguments)
        if kind == "call_expression":
            arguments = node.child_by_field_name("arguments")
            values = syntax.named_children(arguments) if arguments is not None else []
            return (
                "call",
                self.expression(node.child_by_field_name("function")),
                tuple(self.expression(value, in_arguments=True) for value in values),
            )
        if kind == "field_expression":
            field = node.child_by_field_name("field")
            return (
                "field",
                self.expression(node.child_by_field_name("argument"), in_arguments),
                ctree.operator(node),
                syntax.text(field) if field is not None else "",
            )
        if kind == "update_expression":
            argument = node.child_by_field_name("argument")
            is_prefix = argument is not None and node.start_byte < argument.start_byte
            return (
                "update",
                ctree.operator(node),
                is_prefix,
                self.expression(argument, in_arguments),
            )
        if kind == "cast_expression":
            type_node = node.child_by_field_name("type")
            type_text = " ".join(syntax.text(type_node).split()) if type_node is not None else ""
            return (
                "cast",
                type_text,
                self.expression(node.child_by_field_name("value"), in_arguments),
            )
        if kind == "sizeof_expression":
            return self.sizeof(node)
        return self.generic(node, in_arguments)

    def choice(self, node: Node, in_arguments: bool) -> Canonical | None:
        condition = node.child_by_field_name("condition")
        consequence = node.child_by_field_name("consequence")
        alternative = node.child_by_field_name("alternative")
        pair = (_truth_literal(consequence), _truth_literal(alternative))
        if pair == (1, 0):
            return self.truth(condition)
        if pair == (0, 1):
            return _negate(self.condition(condition))
        return (
            "?:",
            self.condition(condition),
            self.expression(consequence, in_arguments),
            self.expression(alternative, in_arguments),
        )

    def binary(self, node: Node, in_arguments: bool) -> Canonical | None:
        operator = ctree.operator(node)
        left_node = node.child_by_field_name("left")
        right_node = node.child_by_field_name("right")
        if operator in ctree.LOGICAL:
            return _logic(operator, [self.condition(left_node), self.condition(right_node)])
        if operator in ("!=", "==") and left_node is not None and right_node is not None:
            other = (
                right_node
                if ctree.is_zero(left_node)
                else left_node
                if ctree.is_zero(right_node)
                else None
            )
            if other is not None:
                return self.truth(other) if operator == "!=" else _negate(self.condition(other))
        left = self.expression(left_node, in_arguments)
        right = self.expression(right_node, in_arguments)
        folded = _folded_comparison(operator, left, right)
        if folded is not None:
            return folded
        if operator in FLIPPED:
            return ("binary", FLIPPED[operator], right, left)
        if operator in ("==", "!="):
            first, second = sorted((left, right), key=repr)
            return ("binary", operator, first, second)
        return ("binary", operator, left, right)

    def sizeof(self, node: Node) -> Canonical:
        value = node.child_by_field_name("value")
        if value is not None:
            return ("sizeof", self.expression(value, in_arguments=True))
        type_node = node.child_by_field_name("type")
        return (
            "sizeof-type",
            " ".join(syntax.text(type_node).split()) if type_node is not None else "",
        )

    def identifier(self, node: Node) -> Canonical | None:
        symbol = self.scope.symbol_of(node)
        if symbol is None:
            name = syntax.text(node)
            return self.constants.get(name, ("id", name))
        if symbol in self.inlined and symbol.value is not None:
            return self.expression(symbol.value)
        if symbol.kind == "enum-constant":
            constant = _safe_enum_value(symbol.value)
            return constant if constant is not None else ("id", symbol.name)
        if symbol.is_variable:
            return self.variable(symbol)
        return ("id", symbol.name)

    def label(self, node: Node | None) -> Canonical:
        if node is None:
            return ("label?",)
        symbol = self.scope.labels.get(syntax.text(node))
        return ("B", symbol.index) if symbol is not None else ("label?", syntax.text(node))

    def generic(self, node: Node, in_arguments: bool = False) -> Canonical:
        parts: list[object] = [node.type]
        for child in node.children:
            if child.type == "comment":
                continue
            if child.is_named:
                parts.append(self.expression(child, in_arguments))
            elif child.type in OPERATOR_TOKENS:
                parts.append(child.type)
        if node.child_count == 0:
            parts.append(syntax.text(node))
        return tuple(parts)


def _negate(value: Canonical | None) -> Canonical:
    if value is not None and len(value) == 2 and value[0] == "not":  # noqa: PLR2004  ("not", operand)
        return value[1]
    if value is not None and len(value) == 2 and value[0] == "bool":  # noqa: PLR2004  ("bool", operand)
        return ("not", value[1])
    return ("not", value)


COMPOUND = {"+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="}


def _plain_target(expression: Node) -> Node | None:
    """The variable or member that `++`, `--` or a compound assignment changes, when
    evaluating it has no effects, so that `x op= e` reads the same as `x = x op e`."""
    if expression.type == "update_expression":
        target = expression.child_by_field_name("argument")
    elif expression.type == "assignment_expression":
        target = expression.child_by_field_name("left")
    else:
        return None
    if target is None or not ctree.is_path(target):
        return None
    return syntax.unwrap_parentheses(target)


def _as_body(items: list[Canonical]) -> Canonical:
    if len(items) == 1 and items[0][0] != "decl":
        return items[0]
    return ("block", tuple(items))


def _is_empty(body: Canonical | None) -> bool:
    return body == ("block", ())


def _if(
    condition: Canonical | None, consequence: Canonical | None, alternative: Canonical | None
) -> Canonical:
    """An `if` in normal form: no empty branch before an `else`, no `if` nested in an `if`
    without `else`."""
    if alternative is not None and _is_empty(consequence):
        return _if(_negate(condition), alternative, None)
    nests_plain_if = (
        alternative is None
        and consequence is not None
        and consequence[0] == "if"
        and consequence[3] is None
    )
    if nests_plain_if:
        assert consequence is not None, "checked above"
        return ("if", _logic("&&", [condition, consequence[1]]), consequence[2], None)
    return ("if", condition, consequence, alternative)


def _logic(operator: str, operands: list[Canonical | None]) -> Canonical:
    """`a && b && c` in one flat form, however it is grouped."""
    flat: list[Canonical | None] = []
    for operand in operands:
        is_same_chain = operand is not None and operand[0] == "logic" and operand[1] == operator
        if is_same_chain:
            assert operand is not None, "checked above"
            flat.extend(operand[2])
        else:
            flat.append(operand)
    return ("logic", operator, tuple(flat))


def _ends_with_continue(body: Canonical | None) -> bool:
    if body == ("continue_statement",):
        return True
    is_block = body is not None and body[0] == "block" and bool(body[1])
    return is_block and body[1][-1] == ("continue_statement",)


def _without_final_continue(body: Canonical | None) -> Canonical:
    if body is None or body == ("continue_statement",):
        return ("block", ())
    return _as_body(list(body[1][:-1]))


def _has_own_continue(forms: list[Canonical]) -> bool:
    """True when a `continue` in the canonical statements belongs to the loop that holds them."""
    stack: list[object] = list(forms)
    while stack:
        form = stack.pop()
        if not isinstance(form, tuple) or not form:
            continue
        if form == ("continue_statement",):
            return True
        if form[0] in ("while", "for", "do"):
            continue
        stack.extend(part for part in form if isinstance(part, tuple))
    return False


def _choice_parts(node: Node | None) -> tuple[Node, Node, Node] | None:
    """(condition, consequence, alternative) of a `?:` that an `if` can replace."""
    if node is None:
        return None
    current = syntax.unwrap_parentheses(node)
    if current.type != "conditional_expression":
        return None
    condition = current.child_by_field_name("condition")
    consequence = current.child_by_field_name("consequence")
    alternative = current.child_by_field_name("alternative")
    if condition is None or consequence is None or alternative is None:
        return None
    is_truth_pair = (_truth_literal(consequence), _truth_literal(alternative)) in ((1, 0), (0, 1))
    writes = any(
        child.type in ("assignment_expression", "update_expression")
        for child in syntax.walk(current)
    )
    if is_truth_pair or writes:
        return None
    return condition, consequence, alternative


def _folded_comparison(
    operator: str, left: Canonical | None, right: Canonical | None
) -> Canonical | None:
    """`1 == 1` is `1`: a comparison of two integer literals has a known value."""
    if operator not in ctree.COMPARISONS:
        return None
    values = [_integer_value(side) for side in (left, right)]
    if values[0] is None or values[1] is None:
        return None
    outcomes = {
        "==": values[0] == values[1],
        "!=": values[0] != values[1],
        "<": values[0] < values[1],
        "<=": values[0] <= values[1],
        ">": values[0] > values[1],
        ">=": values[0] >= values[1],
    }
    return ("num", "1" if outcomes[operator] else "0")


def _integer_value(form: Canonical | None) -> int | None:
    if form is None or form[0] != "num":
        return None
    spelling = str(form[1]).rstrip("uUlL")
    try:
        if spelling.startswith(("0x", "0X")):
            return int(spelling, 16)
        if len(spelling) > 1 and spelling.startswith("0"):
            return int(spelling, 8)
        return int(spelling)
    except ValueError:
        return None


def _truth_literal(node: Node | None) -> int | None:
    if node is None:
        return None
    current = syntax.unwrap_parentheses(node)
    spelling = syntax.text(current)
    if current.type in ("true", "false") and spelling in ("true", "false"):
        return 1 if spelling == "true" else 0
    if current.type == "number_literal" and spelling in ("0", "1"):
        return int(spelling)
    return None


def _leading_assignment(condition: Node) -> Node | None:  # noqa: PLR0911  each exit is one case of the rule
    """The assignment that a condition evaluates before anything else, if any."""
    current = syntax.unwrap_parentheses(condition)
    if current.type == "assignment_expression":
        target = current.child_by_field_name("left")
        is_simple_target = (
            target is not None and syntax.unwrap_parentheses(target).type == "identifier"
        )
        return current if ctree.operator(current) == "=" and is_simple_target else None
    if ctree.is_negation(current):
        argument = current.child_by_field_name("argument")
        return _leading_assignment(argument) if argument is not None else None
    if current.type != "binary_expression":
        return None
    left = current.child_by_field_name("left")
    right = current.child_by_field_name("right")
    if left is None or right is None:
        return None
    candidate = _leading_assignment(left)
    if candidate is None:
        return None
    if ctree.operator(current) in ctree.LOGICAL:
        return candidate
    target = candidate.child_by_field_name("left")
    target_name = syntax.text(syntax.unwrap_parentheses(target)) if target is not None else ""
    reads_target = any(
        node.type == "identifier" and syntax.text(node) == target_name
        for node in syntax.walk(right)
    )
    # Other operators do not order their operands, so the right side must not
    # depend on the assignment or have effects of its own.
    if reads_target or ctree.has_side_effects(right):
        return None
    return candidate


def _without_const(type_text: str) -> str:
    words = [word for word in type_text.replace("*", " * ").split() if word != "const"]
    return " ".join(words)


def _string_content(node: Node) -> str:
    if node.type == "concatenated_string":
        parts = [child for child in node.named_children if child.type == "string_literal"]
        prefixes = {syntax.text(part).split('"', 1)[0] for part in parts}
        if len(prefixes) == 1:
            return prefixes.pop() + '"' + "".join(_string_body(part) for part in parts) + '"'
    return syntax.text(node)


def _string_body(node: Node) -> str:
    spelling = syntax.text(node)
    return spelling[spelling.index('"') + 1 : -1]


def _inlinable(scope: FunctionScope) -> set[Symbol]:
    """Locals that only name a value: inlining them cannot change what the code does."""
    return {symbol for symbol in scope.symbols if _can_inline(scope, symbol)}


def _can_inline(scope: FunctionScope, symbol: Symbol) -> bool:  # noqa: PLR0911  each early exit is one condition of the proof
    """`bool is_ready = count > 0; if (is_ready && ...)` reads the same as the inlined form when
    the local is used once, in the statement that follows its declaration (or after other
    effect-free declarations), never changed, keeps the value (a 0-or-1 initializer, or a bool
    tested only for truth), and is either evaluated at the same point, first and unconditionally,
    or has no side effects and cannot fault."""
    if symbol.kind != "local" or symbol.value is None or "volatile" in symbol.qualifiers:
        return False
    if (
        "*" in symbol.type_text
        or "[" in symbol.type_text
        or symbol.value.type == "initializer_list"
    ):
        return False
    uses = scope.uses_of(symbol)
    if len(uses) != 1 or scope.is_modified(symbol):
        return False
    use = uses[0]
    if len(symbol.statement.children_by_field_name("declarator")) != 1:
        return False
    target = _following_statement(symbol.statement, use)
    if target is None:
        return False
    position = _use_position(target, use)
    if position is None:
        return False
    is_conditional, follows_effects, is_boolean_context = position
    keeps_value = ctree.is_boolean_valued(symbol.value) or (
        _is_bool_type(symbol.type_text) and is_boolean_context
    )
    can_move = not is_conditional or not (
        ctree.has_side_effects(symbol.value) or ctree.can_trap(symbol.value)
    )
    return keeps_value and not follows_effects and can_move


def _is_bool_type(type_text: str) -> bool:
    return _without_const(type_text) in ("bool", "_Bool")


def _following_statement(declaration: Node, use: Node) -> Node | None:
    """The statement holding `use`, when only effect-free declarations stand between."""
    sibling = declaration.next_named_sibling
    while sibling is not None:
        if sibling.type == "comment":
            sibling = sibling.next_named_sibling
            continue
        if sibling.start_byte <= use.start_byte < sibling.end_byte:
            accepted = (
                "if_statement",
                "return_statement",
                "expression_statement",
                "declaration",
                "switch_statement",
            )
            return sibling if sibling.type in accepted else None
        is_quiet_declaration = sibling.type == "declaration" and not ctree.has_side_effects(sibling)
        if not is_quiet_declaration:
            return None
        sibling = sibling.next_named_sibling
    return None


def _use_position(statement: Node, use: Node) -> tuple[bool, bool, bool] | None:
    """(evaluated conditionally, after a side effect, in a boolean context), or None when the use
    is not in the statement's head, the part that runs once before anything else."""
    head = _statement_head(statement, use)
    if head is None:
        return None
    is_conditional = False
    follows_effects = False
    child = use
    parent = use.parent
    while child != head and parent is not None:
        if parent.type == "binary_expression" and ctree.operator(parent) in ctree.LOGICAL:
            left = parent.child_by_field_name("left")
            if left is not None and child != left:
                is_conditional = True
                follows_effects = follows_effects or ctree.has_side_effects(left)
        elif parent.type == "conditional_expression":
            condition = parent.child_by_field_name("condition")
            if condition is not None and child != condition:
                is_conditional = True
                follows_effects = follows_effects or ctree.has_side_effects(condition)
        elif parent.type == "comma_expression":
            left = parent.child_by_field_name("left")
            if left is not None and child != left:
                follows_effects = follows_effects or ctree.has_side_effects(left)
        elif parent.type != "parenthesized_expression":
            siblings = [node for node in parent.named_children if node != child]
            follows_effects = follows_effects or any(
                ctree.has_side_effects(node) for node in siblings
            )
        child, parent = parent, parent.parent
    return is_conditional, follows_effects, _is_boolean_context(use, statement)


def _statement_head(statement: Node, use: Node) -> Node | None:
    if statement.type in ("if_statement", "switch_statement"):
        head = statement.child_by_field_name("condition")
    elif statement.type in ("return_statement", "expression_statement"):
        values = syntax.named_children(statement)
        head = values[0] if values else None
    else:
        head = statement
    if head is None or not head.start_byte <= use.start_byte < head.end_byte:
        return None
    return head


def _is_boolean_context(use: Node, statement: Node) -> bool:
    child = use
    parent = use.parent
    while parent is not None and parent.type == "parenthesized_expression":
        is_if_condition = (
            statement.type == "if_statement"
            and parent == statement.child_by_field_name("condition")
        )
        if is_if_condition:
            return True
        child, parent = parent, parent.parent
    if parent is None:
        return False
    if parent.type == "binary_expression":
        return ctree.operator(parent) in ctree.LOGICAL
    if parent.type == "conditional_expression":
        return parent.child_by_field_name("condition") == child
    return ctree.is_negation(parent)
