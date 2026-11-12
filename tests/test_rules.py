"""Every rule fires on what it targets and stays quiet on the accepted forms."""

import pytest
from conftest import analyse, findings
from readablec.rules import run_rules

C99_PRELUDE = "void prelude(void) { f(); int c99 = 0; }\n"


def body(statements: str) -> str:
    return f"void f(int a, int b)\n{{\n{statements}\n}}\n"


def count(code: str, rule: str) -> int:
    return len(findings(code, rule))


# named-conditions: the cases of Mannie's ESLint rule, translated to C.

NAMED_CONDITIONS_VALID = [
    "if (is_ready && has_items) {}",
    "if (index < count) {}",
    "if (!is_ready || options.enabled) {}",
    "if (user->is_admin && list_contains(list, id)) {}",
    "if (starts_with(lines[index], '|') && is_open) {}",
    "if (!(is_ready && has_items)) {}",
    "if (at(items, -1) && is_array(value)) {}",
    "while (is_table_row_at(index)) {}",
    'label = is_ready && has_items ? "ready" : "waiting";',
    "int is_table_row = index < count && starts_with(trim(lines[index]), '|');",
]

NAMED_CONDITIONS_INVALID = [
    ("while (index < count && starts_with(trim(lines[index]), '|')) {}", 2),
    ("if (count > 0 && is_visible) {}", 1),
    ('label = count > 0 && is_visible ? "a" : "b";', 1),
    ("if (!(first == second || is_ready)) {}", 1),
    ("if (is_ready && check(first + second)) {}", 1),
    ("for (i = 0; i < count && !done; i += 1) {}", 1),
    ("do {} while (is_ready || any_done(items, count + 1));", 1),
]


@pytest.mark.parametrize("statement", NAMED_CONDITIONS_VALID)
def test_named_conditions_accepts_named_parts(statement):
    assert count(body(statement), "named-conditions") == 0


@pytest.mark.parametrize(("statement", "expected"), NAMED_CONDITIONS_INVALID)
def test_named_conditions_reports_each_unnamed_part(statement, expected):
    assert count(body(statement), "named-conditions") == expected


def test_named_conditions_in_returns_only_when_it_compares():
    picks_a_value = "int f(int key) { return cache_get(key) || load(key, depth + 1); }"
    compares = "int f(const char *line) { return line != NULL && starts_with(trim(line), '|'); }"
    assert count(picks_a_value, "named-conditions") == 0
    assert count(compares, "named-conditions") == 2


def test_named_conditions_severity_follows_the_dialect():
    statement = "if (count > 0 && is_visible) {}"
    [c89] = findings(body(statement), "named-conditions")
    [c99] = findings(C99_PRELUDE + body(statement), "named-conditions")
    [loop] = findings(C99_PRELUDE + body("while (count > 0 && is_visible) {}"), "named-conditions")
    assert (c89.severity, c99.severity, loop.severity) == ("advice", "rule", "advice")


def test_nested_ternary():
    assert count(body("x = a ? b ? 1 : 2 : 3;"), "nested-ternary") == 1
    assert count(body("x = a ? 1 : 2;"), "nested-ternary") == 0


def test_unneeded_ternary_suggests_a_value_preserving_rewrite():
    [relational] = findings(body("x = a > b ? 1 : 0;"), "unneeded-ternary")
    [plain] = findings(body("x = a ? 1 : 0;"), "unneeded-ternary")
    assert "`a > b`" in relational.message
    assert "`(a) != 0`" in plain.message
    assert count(body("x = a ? 2 : 0;"), "unneeded-ternary") == 0


def test_unneeded_ternary_with_macros_is_advice():
    [finding] = findings(body("x = a ? TRUE : FALSE;"), "unneeded-ternary")
    assert finding.severity == "advice"


def test_else_after_return_break_continue_and_goto():
    assert count(body("if (a) { return; } else { b = 1; }"), "else-after-return") == 1
    assert count(body("while (a) { if (b) break; else a--; }"), "else-after-return") == 1
    assert count(body("if (a) { b = 1; } else { b = 2; }"), "else-after-return") == 0


def test_duplicate_branches():
    repeated = "if (a) {\n    b = a;\n} else if (b < 32) {\n    b = a;\n} else {\n    b = 32;\n}"
    unbraced = "if (a) b = a; else if (b < 32) { b = a; /* fits */ } else b = 32;"
    different = "if (a) { b = a; } else if (b < 32) { b = 1; } else { b = 32; }"
    separate_guards = "if (!a) return; if (!b) return;"
    assert [finding.snippet for finding in findings(body(repeated), "duplicate-branches")] == [
        "(b < 32)"
    ]
    assert count(body(unbraced), "duplicate-branches") == 1
    assert count(body(different), "duplicate-branches") == 0
    assert count(body(separate_guards), "duplicate-branches") == 0


def test_lonely_if():
    assert count(body("if (a) { b = 1; } else { if (b) { a = 1; } }"), "lonely-if") == 1
    assert count(body("if (a) { b = 1; } else if (b) { a = 1; }"), "lonely-if") == 0


def test_missing_braces():
    assert count(body("if (a) b = 1;"), "missing-braces") == 1
    assert count(body("if (a) { b = 1; } else b = 2;"), "missing-braces") == 1
    assert count(body("while (a) ;"), "missing-braces") == 1
    assert count(body("if (a) { b = 1; } else if (b) { a = 2; }"), "missing-braces") == 0


def test_assignment_in_condition_allows_the_compared_idiom():
    assert count(body("if (a = b) {}"), "assignment-in-condition") == 1
    assert count(body("if (a && (b = next())) {}"), "assignment-in-condition") == 1
    assert count(body("while ((c = getchar()) != EOF) {}"), "assignment-in-condition") == 0


def test_mixed_operators_shows_the_current_grouping():
    [finding] = findings(body("if (a & b == 1) {}"), "mixed-operators")
    assert "`a & (b == 1)`" in finding.message
    assert count(body("x = a << b + 1;"), "mixed-operators") == 1
    assert count(body("if (a && b || c) {}"), "mixed-operators") == 1
    assert count(body("x = (a & b) == 1;"), "mixed-operators") == 0
    assert count(body("x = a + b * c;"), "mixed-operators") == 0


def test_misleading_indentation():
    misleading = body("    if (a)\n        b = 1;\n        a = 2;")
    honest = body("    if (a)\n        b = 1;\n    a = 2;")
    same_line = body("    if (a) b = 1; a = 2;")
    assert count(misleading, "misleading-indentation") == 1
    assert count(honest, "misleading-indentation") == 0
    assert count(same_line, "misleading-indentation") == 1


def test_cryptic_names_spare_conventional_ones():
    code = "int f(int nm, int i)\n{\n    int tmp2 = 0;\n    int count = 0;\n    for (int k = 0; k < 2; k++) {}\n    return nm + i + tmp2 + count;\n}\n"
    names = sorted(finding.snippet for finding in findings(code, "cryptic-name"))
    assert names == ["nm", "tmp2"]


def test_indent_style_follows_the_file():
    code = "void f(void)\n{\n    a = 1;\n    b = 2;\n    c = 3;\n    d = 4;\n\te = 5;\n}\n"
    [finding] = findings(code, "indent-style")
    assert finding.line == 7
    assert findings("void f(void)\n{\n    a = 1;\n\tb = 2;\n}\n", "indent-style") == []


def test_indent_style_leaves_aligned_continuation_lines_alone():
    tabbed = "\n".join(f"\tvalue{index} = {index};" for index in range(6))
    code = (
        "static int\nparse(const char *data,\n    size_t size)\n{\n"
        f"{tabbed}\n\tcall(data,\n\t    size);\n    stray = 1;\n}}\n"
    )
    assert [finding.snippet for finding in findings(code, "indent-style")] == ["stray = 1;"]


def test_magic_numbers_and_their_exemptions():
    code = body("x = a * 60;\nb = a << 4;\nint table[] = {3, 5, 7};\nreturn_code = -1;")
    assert [finding.snippet for finding in findings(code, "magic-number")] == ["60"]


def test_side_effects_spare_the_copy_idiom():
    assert count(body("a = b++;"), "side-effects") == 1
    assert count(body("*dst++ = *src++;"), "side-effects") == 0


def test_goto_allows_forward_jumps_to_cleanup():
    cleanup = "int f(int a)\n{\n    if (a) goto out;\n    a = 2;\nout:\n    return a;\n}\n"
    backward = "int f(int a)\n{\nagain:\n    a--;\n    if (a) goto again;\n    return a;\n}\n"
    assert count(cleanup, "goto") == 0
    assert count(backward, "goto") == 1


def test_param_reassign_and_stacked_casts_and_declarators():
    assert count("int f(int len) { len--; return len; }", "param-reassign") == 1
    assert count(body("x = (int)(unsigned char)a;"), "stacked-casts") == 1
    assert count(body("int c, d;"), "multiple-declarators") == 1


def test_commented_out_code():
    assert count(body("/* x = 1;\n   y = 2; */\na = 1;"), "commented-out-code") == 1
    assert count(body("/* The scale reports grams. */\na = 1;"), "commented-out-code") == 0


def test_function_size():
    long_body = "\n".join(f"    a = {index};" for index in range(70))
    [finding] = findings(body(long_body), "function-size")
    assert finding.severity == "rule"
    assert count(body("a = 1;"), "function-size") == 0
    nested = "if (a) { if (b) { while (a) { if (b) { a = 1; } } } }"
    assert "nesting depth 4" in findings(body(nested), "function-size")[0].message


def test_many_parameters_is_advice_on_its_own():
    code = "void f(int a, int b, int c, int d, int e, int g)\n{\n    a = 1;\n}\n"
    assert count(code, "function-size") == 0
    [finding] = findings(code, "many-parameters")
    assert finding.severity == "advice"


def test_code_inside_parse_errors_is_reported_as_not_checked():
    code = "void h(void) {\n#ifdef FOO\n  if (a) {\n#else\n  if (b) {\n#endif\n    x = 1;\n  }\n}\n"
    analysis = analyse(code)
    report = run_rules(analysis, [(0, len(analysis.data))])
    assert report.findings == []
    assert report.unchecked
