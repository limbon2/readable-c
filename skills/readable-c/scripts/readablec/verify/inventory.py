"""Tier 2: what restructured code does, counted, so the agent can account for differences.

The inventory counts canonical forms, so renames and named constants do not show
up as differences; names are only used to show an item. A difference is not a bug
by itself: moving a call into a helper keeps it, while dropping a duplicate call
removes one. The agent explains each difference in the report.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .canonical import Canonical

SPECIAL_CALLS = {
    "va_start",
    "va_arg",
    "va_end",
    "va_copy",
    "setjmp",
    "longjmp",
    "assert",
    "exit",
    "abort",
}
SPECIAL_NAMES = {"__LINE__", "__FILE__", "__func__", "__FUNCTION__", "errno"}
JUMP_KINDS = {
    "return": "return",
    "break_statement": "break",
    "continue_statement": "continue",
    "goto": "goto",
}
CATEGORIES = ("calls to", "literal", "writes to", "jump", "static local", "special")


@dataclass
class Inventory:
    counts: dict[str, Counter[str]] = field(
        default_factory=lambda: {name: Counter() for name in CATEGORIES}
    )
    shown: dict[str, str] = field(default_factory=dict)

    def add(self, category: str, identity: object, display: str) -> None:
        item = repr(identity)
        self.counts[category][item] += 1
        self.shown.setdefault(item, display)


def collect(forms: list[tuple[Canonical, dict[int, str]]]) -> Inventory:
    """Count over canonical forms, each with the names of its own function's variables."""
    inventory = Inventory()
    for form, names in forms:
        _walk(form, inventory, names)
    return inventory


def _walk(form: object, inventory: Inventory, names: dict[int, str]) -> None:  # noqa: C901  one branch per counted kind
    if not isinstance(form, tuple) or not form:
        return
    head = form[0]
    if head == "call":
        callee = render(form[1], names)
        inventory.add("calls to", form[1], callee)
        if callee in SPECIAL_CALLS:
            inventory.add("special", callee, callee)
    elif head in ("num", "lit"):
        inventory.add("literal", form[1], str(form[1]))
    elif head == "id" and form[1] in SPECIAL_NAMES:
        inventory.add("special", form[1], str(form[1]))
    elif head in ("increment", "decrement"):
        _note_write(form[1], inventory, names)
    elif head == "update":
        _note_write(form[3], inventory, names)
    elif head == "assignment_expression" and len(form) >= 4:  # noqa: PLR2004  (type, left, operator, right)
        _note_write(form[1], inventory, names)
    elif head in JUMP_KINDS:
        inventory.add("jump", JUMP_KINDS[head], JUMP_KINDS[head])
    elif head == "decl" and "static" in form[1]:
        inventory.add(
            "static local", (form[2], form[4]), f"static {form[2]} = {render(form[4], names)}"
        )
    for part in form[1:]:
        if isinstance(part, tuple):
            _walk_part(part, inventory, names)


def _walk_part(part: tuple, inventory: Inventory, names: dict[int, str]) -> None:
    is_sequence = bool(part) and isinstance(part[0], tuple)
    if is_sequence:
        for item in part:
            _walk(item, inventory, names)
    else:
        _walk(part, inventory, names)


def _note_write(target: object, inventory: Inventory, names: dict[int, str]) -> None:
    is_local_variable = isinstance(target, tuple) and bool(target) and target[0] == "L"
    if not is_local_variable:
        inventory.add("writes to", target, render(target, names))


def differences(before: Inventory, after: Inventory) -> list[str]:
    """Readable lines for every count that changed."""
    lines = []
    for category in CATEGORIES:
        old, new = before.counts[category], after.counts[category]
        for item in sorted(set(old) | set(new)):
            if old[item] != new[item]:
                shown = after.shown.get(item) or before.shown.get(item, item)
                lines.append(f"{category} `{shown}`: {old[item]} before, {new[item]} after")
    return lines


def render(form: object, names: dict[int, str]) -> str:  # noqa: PLR0911  one return per shape
    """C-like text for a canonical expression, for messages."""
    if not isinstance(form, tuple) or not form:
        return str(form)
    head = form[0]
    if head == "L":
        return names.get(int(form[1]), f"local#{form[1]}")
    if head in ("id", "num", "lit"):
        return str(form[1])
    if head == "field":
        return f"{render(form[1], names)}{form[2]}{form[3]}"
    if head == "binary":
        return f"{render(form[2], names)} {form[1]} {render(form[3], names)}"
    if head == "not":
        return f"!{render(form[1], names)}"
    if head == "call":
        arguments = ", ".join(render(argument, names) for argument in form[2])
        return f"{render(form[1], names)}({arguments})"
    if head == "()":
        return f"({render(form[1], names)})" if len(form) > 1 else "()"
    if head == "pointer_expression" and len(form) > 2:  # noqa: PLR2004  (type, operator, operand)
        return f"{form[1]}{render(form[2], names)}"
    if head == "subscript_expression" and len(form) >= 3:  # noqa: PLR2004  (type, array, index)
        return f"{render(form[1], names)}[{render(form[2], names)}]"
    return repr(form)
