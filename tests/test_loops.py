"""hand-written-library suggests a standard call only when the call does what the loop does."""

import pytest
from conftest import findings

PARAMETERS = (
    "char *name, char *p, const unsigned char *bytes, int *table, int *dst, int *src, "
    "short *small, const wchar_t *wide, const WCHAR *w"
)


def suggestion(statements: str) -> str | None:
    code = (
        f"void f({PARAMETERS})\n{{\n    size_t len, cap = 4, i, n = 3;\n    int total = 0;\n"
        f"    {statements}\n}}\n"
    )
    found = findings(code, "hand-written-library")
    assert all(finding.severity == "advice" for finding in found)
    return found[0].message if found else None


@pytest.mark.parametrize(
    ("statements", "call"),
    [
        (
            "len = 0;\n    while (len < cap && name[len] != 0) {\n        len++;\n    }",
            "len = strnlen(name, cap);",
        ),
        ("for (len = 0; len < cap && name[len]; len++)\n        ;", "len = strnlen(name, cap);"),
        (
            "n = 0;\n    while (n < cap && bytes[n] != 0) n++;",
            "n = strnlen((const char *)bytes, cap);",
        ),
        ("i = 0;\n    while (name[i] != '\\0') i++;", "i = strlen(name);"),
        ("while (*p) p++;", "p += strlen(p);"),
        ("i = 0;\n    while (name[i] && name[i] != '/') i++;", 'i = strcspn(name, "/");'),
        ("while (*p != '\\0' && *p != '/') p++;", 'p += strcspn(p, "/");'),
        ("i = 0;\n    while (wide[i]) i++;", "i = wcslen(wide);"),
        ("for (i = 0; i < n; i++) table[i] = 0;", "memset(table, 0, n * sizeof table[0]);"),
        (
            "for (i = 0; i < n; i++) {\n        dst[i] = src[i];\n    }",
            "memcpy(dst, src, n * sizeof dst[0]);",
        ),
    ],
)
def test_suggests_the_exact_call(statements, call):
    message = suggestion(statements)
    assert message is not None
    assert f"`{call}`" in message


def test_strnlen_comes_with_a_portability_note():
    message = suggestion("len = 0;\n    while (len < cap && name[len] != 0) len++;")
    assert message is not None
    assert "POSIX" in message


@pytest.mark.parametrize(
    "statements",
    [
        # WCHAR is a 16-bit integer outside Windows, so wcslen would be wrong there.
        "i = 0;\n    while (w[i]) i++;",
        # The counter does not visibly start at 0.
        "while (len < cap && name[len] != 0) len++;",
        # memchr returns NULL where the loop stops at the bound.
        "i = 0;\n    while (i < n && name[i] != ':') i++;",
        # `<=` scans one element more than the bound.
        "for (i = 0; i <= n; i++) table[i] = 0;",
        # Different element types: memcpy would copy bytes, the loop converts.
        "for (i = 0; i < n; i++) table[i] = small[i];",
        # The loop does more than step the counter.
        "i = 0;\n    while (i < n && name[i] != 0) { total += name[i]; i++; }",
        "for (i = 0; i < n; i++) total += src[i];",
        "for (i = 1; i < n; i++) table[i] = 0;",
    ],
)
def test_stays_quiet_when_no_call_is_exact(statements):
    assert suggestion(statements) is None
