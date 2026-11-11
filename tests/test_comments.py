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


def test_calls_are_not_flagged_without_a_library_header():
    code = '#include <string.h>\n#include "local.h"\nint f(void)\n{\n    return helper(1) + (int)strlen("x");\n}\n'
    assert needs_comment(code) == []
