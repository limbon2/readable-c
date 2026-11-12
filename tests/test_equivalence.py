"""The tiers: what `verify` proves equal, and the near misses it must not."""

import pytest
from conftest import review_items, tier

ORIGINAL = """
int count;
int f(const int *values, int n)
{
    int i, c = 0;
    for (i = 0; i < n; i++) {
        if (values[i] > 0 && values[i] < 100)
            c++;
    }
    return c;
}
"""


def test_comment_and_layout_changes_are_tier_0():
    after = ORIGINAL.replace("int i, c = 0;", "int i, c = 0; /* running total */")
    assert tier(ORIGINAL, after) == 0


PROVEN = {
    "renames": ORIGINAL.replace("int i, c = 0;", "int index, total = 0;")
    .replace("for (i = 0; i < n; i++)", "for (index = 0; index < n; index++)")
    .replace("values[i]", "values[index]")
    .replace("c++;", "total++;")
    .replace("return c;", "return total;")
    .replace("int n)", "int length)")
    .replace("i < n;", "i < length;")
    .replace("index < n;", "index < length;"),
    "braces": ORIGINAL.replace("            c++;", "        {\n            c++;\n        }"),
    "named condition": ORIGINAL.replace(
        "        if (values[i] > 0 && values[i] < 100)\n            c++;",
        "        int is_in_range = values[i] > 0 && values[i] < 100;\n        if (is_in_range) {\n            c++;\n        }",
    ),
    "enum constant": ORIGINAL.replace(
        "    int i, c = 0;", "    enum { LIMIT = 100 };\n    int i, c = 0;"
    ).replace("values[i] < 100", "values[i] < LIMIT"),
    "flipped comparison": ORIGINAL.replace("values[i] > 0", "0 < values[i]"),
    "increment spelling": ORIGINAL.replace("i++)", "i += 1)"),
    "declaration split": ORIGINAL.replace("int i, c = 0;", "int i;\n    int c;\n    c = 0;"),
}


@pytest.mark.parametrize("change", sorted(PROVEN))
def test_mechanical_refactors_are_tier_1(change):
    assert tier(ORIGINAL, PROVEN[change]) == 1


def test_else_after_return_and_lonely_if_are_tier_1():
    before = "int f(int a)\n{\n    if (a < 0) {\n        return -1;\n    } else {\n        if (a == 0) {\n            return 0;\n        }\n    }\n    return 1;\n}\n"
    after = "int f(int a)\n{\n    if (a < 0) {\n        return -1;\n    }\n    if (a == 0) {\n        return 0;\n    }\n    return 1;\n}\n"
    assert tier(before, after) == 1
    lonely = "int f(int a)\n{\n    if (a) { return 1; } else { if (a + 1) { a = 2; } }\n    return a;\n}\n"
    else_if = (
        "int f(int a)\n{\n    if (a) { return 1; } else if (a + 1) { a = 2; }\n    return a;\n}\n"
    )
    assert tier(lonely, else_if) == 1


def test_zero_tests_and_boolean_values_are_tier_1():
    before = "int f(int *p, int n)\n{\n    if (p != NULL && n != 0) return n > 3 ? 1 : 0;\n    return !!n;\n}\n"
    after = "int f(int *p, int n)\n{\n    if (p && n) return n > 3;\n    return n != 0;\n}\n"
    assert tier(before, after) == 1


def test_assignment_moved_out_of_a_condition_is_tier_1():
    before = "int f(void)\n{\n    int x;\n    if ((x = next()) >= 0) {\n        return x;\n    }\n    return -1;\n}\n"
    after = "int f(void)\n{\n    int x;\n    x = next();\n    if (x >= 0) {\n        return x;\n    }\n    return -1;\n}\n"
    assert tier(before, after) == 1


def test_infinite_loop_spellings_are_tier_1():
    before = "void f(void)\n{\n    for (;;) { step(); }\n}\n"
    after = "void f(void)\n{\n    while (1) {\n        step();\n    }\n}\n"
    assert tier(before, after) == 1


NOT_PROVEN = {
    "changed operator": ORIGINAL.replace("values[i] > 0", "values[i] >= 0"),
    "changed literal": ORIGINAL.replace("< 100", "< 101"),
    "dropped statement": ORIGINAL.replace("            c++;\n", "            ;\n"),
    "named guard split": "int f(const int *p)\n{\n    int has_p = p != NULL;\n    int is_positive = *p > 0;\n    if (has_p && is_positive) return 1;\n    return 0;\n}\n",
}


@pytest.mark.parametrize("change", sorted(NOT_PROVEN))
def test_behavior_changes_are_not_proven(change):
    before = ORIGINAL
    if change == "named guard split":
        before = (
            "int f(const int *p)\n{\n    if (p != NULL && *p > 0) return 1;\n    return 0;\n}\n"
        )
    assert tier(before, NOT_PROVEN[change]) == 2


LOOP = """
int f(const struct item *items, int count)
{
    int i, total = 0;
    for (i = 0; i < count; i++) {
        if (items[i].flags & 1 == 1) {
            if (items[i].qty > 0) {
                total = total + items[i].qty;
            }
        }
    }
    return total;
}
"""


def test_continue_guards_merged_ifs_and_folded_literals_are_tier_1():
    flattened = LOOP.replace(
        "        if (items[i].flags & 1 == 1) {\n            if (items[i].qty > 0) {\n"
        "                total = total + items[i].qty;\n            }\n        }\n",
        "        int is_counted = (items[i].flags & 1) != 0 && items[i].qty > 0;\n"
        "        if (!is_counted) {\n            continue;\n        }\n        total = total + items[i].qty;\n",
    )
    assert tier(LOOP, flattened) == 1


def test_a_continue_guard_that_skips_too_much_is_not_tier_1():
    wrong = LOOP.replace(
        "        if (items[i].flags & 1 == 1) {\n            if (items[i].qty > 0) {\n"
        "                total = total + items[i].qty;\n            }\n        }\n",
        "        if (items[i].qty > 0) {\n            continue;\n        }\n        total = total + items[i].qty;\n",
    )
    assert tier(LOOP, wrong) == 2


def test_for_loops_without_continue_read_as_while_loops():
    before = "int f(const char *s)\n{\n    int k;\n    for (k = 0; s[k] != 0; k++)\n        ;\n    return k;\n}\n"
    after = "int f(const char *s)\n{\n    int k;\n    k = 0;\n    while (s[k] != 0) {\n        k++;\n    }\n    return k;\n}\n"
    assert tier(before, after) == 1
    with_continue = "int f(int n)\n{\n    int k, t = 0;\n    for (k = 0; k < n; k++) {\n        if (k == 3) continue;\n        t++;\n    }\n    return t;\n}\n"
    naive = "int f(int n)\n{\n    int k, t = 0;\n    k = 0;\n    while (k < n) {\n        if (k == 3) continue;\n        t++;\n        k++;\n    }\n    return t;\n}\n"
    assert tier(with_continue, naive) == 2


def test_choices_written_as_if_else_are_tier_1():
    returned = "int f(int t)\n{\n    return t > 1000 ? (t > 5000 ? 2 : 1) : 0;\n}\n"
    as_ifs = "int f(int t)\n{\n    if (t > 1000) {\n        if (t > 5000) {\n            return 2;\n        }\n        return 1;\n    }\n    return 0;\n}\n"
    assert tier(returned, as_ifs) == 1
    assigned = "int f(int a)\n{\n    int x = a > 0 ? 5 : 6;\n    return x;\n}\n"
    as_if_else = "int f(int a)\n{\n    int x;\n    if (a > 0) {\n        x = 5;\n    } else {\n        x = 6;\n    }\n    return x;\n}\n"
    assert tier(assigned, as_if_else) == 1
    swapped = as_if_else.replace("x = 5;", "x = 7;")
    assert tier(assigned, swapped) == 2


CAP = "unsigned long f(int long_format, unsigned long rem)\n{{\n    unsigned long cap;\n{body}    return cap;\n}}\n"
CAP_ORIGINAL = CAP.format(body="    cap = long_format ? rem : (rem < 32 ? rem : 32);\n")
CAP_VERSIONS = {
    "literal chain": "    if (long_format) {\n        cap = rem;\n    } else if (rem < 32) {\n        cap = rem;\n    } else {\n        cap = 32;\n    }\n",
    "merged": "    if (long_format || rem < 32) {\n        cap = rem;\n    } else {\n        cap = 32;\n    }\n",
    "named": "    int fits = long_format || rem < 32;\n    if (fits) {\n        cap = rem;\n    } else {\n        cap = 32;\n    }\n",
    "named choice": "    int fits = long_format || rem < 32;\n    cap = fits ? rem : 32;\n",
}


@pytest.mark.parametrize("version", sorted(CAP_VERSIONS))
def test_branches_with_the_same_body_merge_with_or(version):
    assert tier(CAP_ORIGINAL, CAP.format(body=CAP_VERSIONS[version])) == 1


def test_only_adjacent_branches_merge():
    before = "int f(int a, int b, int c)\n{\n    int x = 0;\n    if (a) x = 1; else if (b) x = 2; else if (c) x = 1;\n    return x;\n}\n"
    reordered = "int f(int a, int b, int c)\n{\n    int x = 0;\n    if (a || c) x = 1; else if (b) x = 2;\n    return x;\n}\n"
    assert tier(before, reordered) == 2
    different = before.replace("else if (c) x = 1;", "else x = 3;")
    merged_wrongly = "int f(int a, int b, int c)\n{\n    int x = 0;\n    if (a || b) x = 1; else x = 3;\n    return x;\n}\n"
    assert tier(different, merged_wrongly) == 2


def test_repeated_guards_and_de_morgan_are_tier_1():
    guards = "int f(const char *a, const char *b)\n{\n    if (!a) return -1;\n    if (!b) return -1;\n    return 0;\n}\n"
    joined = (
        "int f(const char *a, const char *b)\n{\n    if (!a || !b) return -1;\n    return 0;\n}\n"
    )
    negated = (
        "int f(const char *a, const char *b)\n{\n    if (!(a && b)) return -1;\n    return 0;\n}\n"
    )
    assert tier(guards, joined) == 1
    assert tier(guards, negated) == 1


def test_compound_assignments_read_as_their_expansion():
    before = "void f(int *total, int n)\n{\n    int sum = 0;\n    sum = sum + n;\n    sum = sum * 2;\n    *total = sum;\n}\n"
    after = "void f(int *total, int n)\n{\n    int sum = 0;\n    sum += n;\n    sum *= 2;\n    *total = sum;\n}\n"
    assert tier(before, after) == 1


def test_compound_assignments_with_effects_in_the_target_are_not_expanded():
    before = "void f(int *a, int i)\n{\n    a[i++] += 2;\n}\n"
    after = "void f(int *a, int i)\n{\n    a[i++] = a[i++] + 2;\n}\n"
    assert tier(before, after) == 2


def test_named_parts_are_tier_1_only_when_moving_them_cannot_fault():
    before = "int f(int n, const int *p)\n{\n    if (n > 0 && n < 100) return 1;\n    if (n > 0 && p[n] < 100) return 2;\n    return 0;\n}\n"
    pure = before.replace(
        "    if (n > 0 && n < 100) return 1;",
        "    int is_positive = n > 0;\n    int is_small = n < 100;\n    if (is_positive && is_small) return 1;",
    )
    assert tier(before, pure) == 1
    reads_memory = before.replace(
        "    if (n > 0 && p[n] < 100) return 2;",
        "    int is_positive = n > 0;\n    int is_small = p[n] < 100;\n    if (is_positive && is_small) return 2;",
    )
    assert tier(before, reads_memory) == 2


def test_rename_capturing_a_global_is_not_tier_1():
    before = "int count;\nint f(int n)\n{\n    int c = n;\n    return c + count;\n}\n"
    after = "int count;\nint f(int n)\n{\n    int count = n;\n    return count + count;\n}\n"
    assert tier(before, after) == 2


def test_side_effects_are_not_moved_into_a_condition():
    before = "int f(void)\n{\n    if (first() && second()) return 1;\n    return 0;\n}\n"
    after = "int f(void)\n{\n    int a = first();\n    int b = second();\n    if (a && b) return 1;\n    return 0;\n}\n"
    assert tier(before, after) == 2


def test_inventory_names_a_dropped_call_and_a_changed_literal():
    before = "void f(int n)\n{\n    log_value(n);\n    store(n, 5);\n}\n"
    after = "void f(int n)\n{\n    store(n, 6);\n}\n"
    items = " | ".join(review_items(before, after))
    assert "calls to `log_value`: 1 before, 0 after" in items
    assert "literal `5`: 1 before, 0 after" in items


def test_inventory_ignores_renames():
    before = "void f(struct item *p)\n{\n    p->qty = 0;\n    p->name[0] = 1;\n}\n"
    after = "void f(struct item *entry)\n{\n    entry->name[0] = 1;\n    entry->qty = 0;\n}\n"
    assert review_items(before, after) == []
