"""verify rejects writes to const variables, and only to variables that are const themselves."""

from conftest import analyse
from readablec.verify import names


def const_errors(before: str, after: str) -> list[str]:
    old, new = analyse(before), analyse(after)
    issues = names.scope_issues(old, [(0, len(old.data))], new, [(0, len(new.data))])
    return [issue.message for issue in issues if "declared const" in issue.message]


def function(statements: str) -> str:
    return f"void f(const char *text, int count)\n{{\n{statements}\n}}\n"


def test_a_pointer_to_const_data_can_change():
    # Real code: `const rdpMcs *mcs; mcs = context->rdp->mcs;`
    code = function("    const char *cursor;\n    cursor = text;\n    cursor++;")
    assert const_errors(function(""), code) == []


def test_taking_the_address_of_a_const_is_not_a_write():
    code = function("    const int limit = 4;\n    count = *(&limit);")
    assert const_errors(function(""), code) == []


def test_assigning_a_const_variable_is_an_error():
    plain = function("    const int limit = 4;\n    limit = count;")
    pointer = function("    char *const cursor = 0;\n    cursor = 0;")
    pointer_to_const_pointer = function("    char *const *list = 0;\n    list = 0;")
    assert len(const_errors(function(""), plain)) == 1
    assert len(const_errors(function(""), pointer)) == 1
    assert const_errors(function(""), pointer_to_const_pointer) == []


def test_an_error_the_original_already_had_is_not_new():
    code = function("    const int limit = 4;\n    limit = count;")
    assert const_errors(code, code) == []
