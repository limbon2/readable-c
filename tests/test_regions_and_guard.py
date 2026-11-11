import pytest
from conftest import FIXTURES, analyse
from readablec import guard, regions
from readablec.issues import ERROR

CODE = (
    "#include <stdio.h>\n"
    "\n"
    "/* Counts positive values. */\n"
    "static int count_positive(const int *values, int length)\n"
    "{\n"
    "    int index;\n"
    "    int total = 0;\n"
    "    for (index = 0; index < length; index++) {\n"
    "        if (values[index] > 0)\n"
    "            total++;\n"
    "    }\n"
    "    return total;\n"
    "}\n"
    "\n"
    "int main(void)\n"
    "{\n"
    "    return count_positive(0, 0);\n"
    "}\n"
)


def resolve(code: str, **request) -> list[regions.Region]:
    analysis = analyse(code)
    return regions.resolve(analysis.source, analysis.root, analysis.functions, **request).regions


def test_function_region_includes_the_comment_above():
    [region] = resolve(CODE, function_names=["count_positive"])
    data = CODE.encode()
    assert data[region.start : region.end].startswith(b"/* Counts positive values. */")
    assert data[region.start : region.end].endswith(b"}\n")


def test_unknown_function_suggests_close_names():
    with pytest.raises(regions.RegionError, match="count_positive"):
        resolve(CODE, function_names=["count_positiv"])


def test_line_range_snaps_to_whole_statements_and_adds_a_slot():
    slot, lines = resolve(CODE, line_ranges=[(9, 9)])
    assert slot.is_slot
    assert slot.start == CODE.encode().index(b"/* Counts")
    text = CODE.encode()[lines.start : lines.end].decode()
    assert text.startswith("        if (values[index] > 0)")
    assert text.endswith("total++;\n")


def test_range_across_functions_grows_to_whole_items():
    [region] = resolve(CODE, line_ranges=[(12, 16)])
    text = CODE.encode()[region.start : region.end].decode()
    assert "count_positive" in text
    assert text.rstrip().endswith("}")


def test_regions_only_white_space_apart_merge():
    merged = resolve(CODE, function_names=["count_positive", "main"])
    assert len(merged) == 1


def test_text_scan_finds_functions_tree_sitter_cannot_parse():
    code = "void h(void) {\n#ifdef FOO\n  if (a) {\n#else\n  if (b) {\n#endif\n    x = 1;\n  }\n}\n"
    [region] = resolve(code, function_names=["h"])
    assert code.encode()[region.start : region.end] == code.encode()


def edit(code: str, old: str, new: str) -> bytes:
    assert old in code
    return code.replace(old, new).encode()


def guard_check(code: str, current: bytes, **request) -> guard.GuardResult:
    return guard.check(code.encode(), resolve(code, **request), current)


def test_guard_accepts_edits_inside_the_region():
    current = edit(CODE, "            total++;", "        {\n            total++;\n        }")
    result = guard_check(CODE, current, function_names=["count_positive"])
    assert result.ok


def test_guard_rejects_an_edit_outside_and_names_the_line():
    current = edit(CODE, "return count_positive(0, 0);", "return count_positive(0, 1);")
    result = guard_check(CODE, current, function_names=["count_positive"])
    assert not result.ok
    assert "original line 17" in result.issues[0].message


def test_guard_rejects_a_comment_left_open_in_the_region():
    current = edit(CODE, "    return total;\n", "    return total; /* open\n")
    result = guard_check(CODE, current, function_names=["count_positive"])
    assert not result.ok
    assert "inside a comment" in result.issues[0].message


def test_guard_rejects_an_extra_brace_in_a_line_range():
    current = edit(CODE, "            total++;", "            total++; }")
    result = guard_check(CODE, current, line_ranges=[(9, 10)])
    assert not result.ok
    assert "brace depth" in result.issues[0].message


def test_guard_accepts_a_helper_in_the_slot():
    helper = "static int is_positive(int value)\n{\n    return value > 0;\n}\n\n"
    current = edit(CODE, "/* Counts positive values. */", helper + "/* Counts positive values. */")
    current = current.replace(b"if (values[index] > 0)", b"if (is_positive(values[index]))")
    result = guard_check(CODE, current, line_ranges=[(9, 10)])
    assert result.ok


def test_guard_rejects_added_includes_and_reviews_new_constant_macros():
    with_include = edit(CODE, "    int index;\n", "#include <string.h>\n    int index;\n")
    result = guard_check(CODE, with_include, function_names=["count_positive"])
    assert any(issue.check == "directives" and issue.severity == ERROR for issue in result.issues)
    with_macro = edit(CODE, "    int index;\n", "#define LIMIT 5\n    int index;\n")
    result = guard_check(CODE, with_macro, function_names=["count_positive"])
    assert result.ok
    assert [issue.severity for issue in result.issues] == ["review"]


def test_guard_rejects_a_new_macro_whose_name_frozen_code_uses():
    with_macro = edit(CODE, "    int index;\n", "#define main other\n    int index;\n")
    result = guard_check(CODE, with_macro, function_names=["count_positive"])
    assert not result.ok


def test_guard_reports_ambiguous_boundaries():
    code = "int a;\nint b;\nint c;\nint b;\nint d;\n"
    analysis = analyse(code)
    data = code.encode()
    first = regions.Region(0, data.index(b"int b"), "lines", "first")
    second = regions.Region(data.index(b"int c"), data.index(b"int c") + 7, "lines", "second")
    current = b"int b;\nint b;\nint c;\nint b;\nint d;\n"
    assert analysis.source.line_count == 5
    result = guard.check(data, [first, second], current)
    assert not result.ok


def legacy() -> bytes:
    return (FIXTURES / "legacy.c").read_bytes()


def legacy_regions() -> list[regions.Region]:
    analysis = analyse(legacy())
    return regions.resolve(
        analysis.source, analysis.root, analysis.functions, function_names=["is_stable"]
    ).regions


def test_crlf_turned_into_lf_is_diagnosed_and_repaired():
    original = legacy()
    edited = original.replace(b"int d = a - b;", b"int difference = a - b;").replace(
        b"SQR(d)", b"SQR(difference)"
    )
    damaged = edited.replace(b"\r\n", b"\n")
    result = guard.check(original, legacy_regions(), damaged)
    assert not result.ok
    assert "line endings went from CRLF to LF" in result.issues[0].message
    assert guard.repair(original, legacy_regions(), damaged, None) == edited


def test_reencoded_legacy_bytes_are_repaired_from_the_snapshot():
    original = legacy()
    edited = original.replace(b"int d = a - b;", b"int difference = a - b;").replace(
        b"SQR(d)", b"SQR(difference)"
    )
    damaged = edited.decode("cp1251").encode("utf-8")
    assert guard.repair(original, legacy_regions(), damaged, None) == edited


def test_repair_needs_an_encoding_for_new_non_ascii_lines():
    original = legacy()
    comment = "    /* разность */\r\n".encode("cp1251")
    edited = original.replace(b"    int d = a - b;\r\n", b"    int d = a - b;\r\n" + comment)
    damaged = edited.decode("cp1251").encode("utf-8")
    with pytest.raises(guard.RepairError, match="--encoding"):
        guard.repair(original, legacy_regions(), damaged, None)
    assert guard.repair(original, legacy_regions(), damaged, "cp1251") == edited


def test_restore_puts_the_original_region_back():
    original = CODE.encode()
    selected = resolve(CODE, function_names=["count_positive"])
    current = edit(CODE, "int total = 0;", "int sum = 0;")
    result = guard.check(original, selected, current)
    assert result.spans is not None
    assert guard.restore(original, selected, current, result.spans) == original
