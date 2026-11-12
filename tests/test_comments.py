"""needs-comment points at code a reader cannot follow alone, and stays quiet once it is explained."""

from conftest import findings


def needs_comment(code: str) -> list[str]:
    return [finding.snippet for finding in findings(code, "needs-comment")]


def body(statements: str, prelude: str = "") -> str:
    return f"{prelude}void f(char *s, struct node *n, int count, unsigned char *buf)\n{{\n{statements}\n}}\n"


def test_realloc_always_needs_a_comment():
    assert needs_comment(body("    s = realloc(s, 64);")) == ["realloc(s, 64)"]


def test_allocations_need_one_when_the_size_or_the_owner_is_not_obvious():
    assert needs_comment(body("    s = malloc(count + 1);")) == ["malloc(count + 1)"]
    assert needs_comment(body("    n->name = malloc(sizeof *n);")) == ["malloc(sizeof *n)"]
    assert needs_comment("char *dup(void)\n{\n    return malloc(16);\n}\n") == ["malloc(16)"]
    assert needs_comment(body("    n = malloc(sizeof *n);")) == []


def test_raw_memory_with_computed_offsets_needs_a_comment():
    assert needs_comment(body("    memmove(buf, buf + count, 64 - count);")) == [
        "memmove(buf, buf + count, 64 - count)"
    ]
    assert needs_comment(body("    memcpy(buf, s, sizeof *n);")) == []


def test_literal_bit_operations_need_a_comment_once_per_statement():
    assert needs_comment(body("    count = (buf[0] >> 4) & 0x0F;")) == ["(buf[0] >> 4) & 0x0F"]
    assert needs_comment(body("    count |= 0x80;")) == ["count |= 0x80"]
    named = "enum { CHANNEL_SHIFT = 4, CHANNEL_MASK = 0x0F };\n"
    assert needs_comment(body("    count = (buf[0] >> CHANNEL_SHIFT) & CHANNEL_MASK;", named)) == []


def test_reading_memory_through_a_cast_needs_a_comment():
    assert needs_comment(body("    count = *(int *)(buf + 4);")) == ["*(int *)(buf + 4)"]
    assert needs_comment(body("    count = ((struct node *)buf)->size;")) == [
        "((struct node *)buf)->size"
    ]
    assert needs_comment(body("    count = (int)buf[0];")) == []


def test_a_comment_on_the_line_or_just_above_explains_it():
    above = "    /* bits 4-7: the channel number */\n    count = (buf[0] >> 4) & 0x0F;"
    trailing = "    count = (buf[0] >> 4) & 0x0F;  /* the channel number */"
    too_far = "    /* the channel number */\n\n\n    count = (buf[0] >> 4) & 0x0F;"
    assert needs_comment(body(above)) == []
    assert needs_comment(body(trailing)) == []
    assert len(needs_comment(body(too_far))) == 1


def test_calls_into_a_system_library_need_a_comment_once_per_function():
    code = (
        "#include <windows.h>\n#include <string.h>\n"
        "int f(void *worker)\n{\n"
        "    if (WaitForSingleObject(worker, 500) == WAIT_TIMEOUT) return 1;\n"
        "    WaitForSingleObject(worker, 10);\n"
        '    return (int)strlen("x");\n}\n'
    )
    [finding] = findings(code, "needs-comment")
    assert (
        "`WaitForSingleObject` comes from outside this file, probably from <windows.h>"
        in finding.message
    )


def test_standard_functions_from_other_headers_are_not_library_calls():
    # The file gets <string.h> and <stdlib.h> only through WinPR, as real code often does.
    code = (
        "#include <winpr/string.h>\n"
        "int f(const WCHAR *wide, const char *text, size_t len)\n{\n"
        "    char *copy = malloc(len + 1);\n"
        "    memcpy(copy, text, len);\n"
        "    if (strcmp(copy, text) == 0) free(copy);\n"
        "    return ConvertFromUnicode(CP_UTF8, 0, wide, 16, &copy, 0, NULL, NULL);\n}\n"
    )
    assert needs_comment(code) == [
        "malloc(len + 1)",
        "ConvertFromUnicode(CP_UTF8, 0, wide, 16, &copy, 0, NULL, NULL)",
    ]


def test_calls_are_not_flagged_without_a_library_header():
    code = '#include <string.h>\n#include "local.h"\nint f(void)\n{\n    return helper(1) + (int)strlen("x");\n}\n'
    assert needs_comment(code) == []


def test_needs_comment_is_a_rule():
    [finding] = findings(body("    s = realloc(s, 64);"), "needs-comment")
    assert finding.severity == "rule"


def test_bounds_and_offsets_built_from_literals_need_a_comment():
    assert needs_comment(body("    if (2 * count + 1 < 64) return;")) == ["2 * count + 1 < 64"]
    assert needs_comment(body("    s[0] = buf[count + 2];")) == ["buf[count + 2]"]
    assert needs_comment(body("    count += 36;")) == ["count += 36"]
    assert needs_comment(body("    count = count + 4 + count * 2 + 2;")) == [
        "count = count + 4 + count * 2 + 2"
    ]


def test_bounds_with_names_small_steps_or_a_comment_are_fine():
    named = "enum { HEADER_LEN = 8 };\n"
    assert needs_comment(body("    if (count + HEADER_LEN < 64) return;", named)) == []
    assert needs_comment(body("    if (count + 1 < 64) return;")) == []
    assert needs_comment(body("    count += 1;")) == []
    assert needs_comment(body("    count = buf[count - 1];")) == []
    explained = "    /* the 4-byte id, then the name */\n    count += 36;"
    assert needs_comment(body(explained)) == []


def test_a_long_function_needs_a_contract_comment_above_it():
    statements = "\n".join(f"    count = count + {index};" for index in range(12))
    code = body(statements)
    [finding] = findings(code, "function-contract")
    assert finding.severity == "rule"
    assert "`f`" in finding.message
    assert findings("/* Adds up the counts. */\n" + code, "function-contract") == []
    assert findings(body("    count = 1;"), "function-contract") == []


def test_the_contract_of_a_void_function_does_not_ask_for_a_result():
    statements = "\n".join(f"    count = count + {index};" for index in range(12))
    [void_finding] = findings(body(statements), "function-contract")
    assert "what it returns" not in void_finding.message
    returning = f"int g(int count)\n{{\n{statements}\n    return count;\n}}\n"
    [int_finding] = findings(returning, "function-contract")
    assert "what it returns" in int_finding.message
