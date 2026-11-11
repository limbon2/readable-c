"""The commands end to end, on copies of the fixtures."""

import json

from conftest import FIXTURES


def test_doctor_describes_the_file(run_cli, fixture_copy):
    path = fixture_copy("legacy.c")
    result = run_cli("doctor", str(path))
    assert result.code == 0
    assert "line endings: CRLF" in result.out
    assert "looks like cp1251" in result.out
    assert "boolean type: BOOL" in result.out


def test_outline_lists_functions_with_their_lines(run_cli, fixture_copy):
    path = fixture_copy("inventory.c")
    result = run_cli("outline", str(path), "--json")
    items = json.loads(result.out)["items"]
    functions = {
        item["name"]: (item["first_line"], item["last_line"])
        for item in items
        if item["kind"] == "function"
    }
    assert functions["add_item"] == (42, 59)


def test_a_full_refactor_session(run_cli, fixture_copy):
    path = fixture_copy("inventory.c")
    started = run_cli("start", str(path), "--function", "cnt", "--json")
    assert started.code == 0
    baseline = json.loads(started.out)["baseline"]
    assert any(finding["rule"] == "cryptic-name" for finding in baseline)

    unchanged = run_cli("verify", str(path))
    assert unchanged.code == 0
    assert "tier 0" in unchanged.out

    text = path.read_text()
    path.write_text(
        text.replace(
            "static int cnt(int lo, int hi)\n{\n    int i, c = 0;\n    for (i = 0; i < n_items; i++) {\n"
            "        if (items[i].qty >= lo && items[i].qty <= hi)\n            c++;\n    }\n    return c;\n}",
            "static int cnt(int lowest, int highest)\n{\n    int index;\n    int count = 0;\n"
            "    for (index = 0; index < n_items; index++) {\n"
            "        int is_in_range = items[index].qty >= lowest && items[index].qty <= highest;\n"
            "        if (is_in_range) {\n            count++;\n        }\n    }\n    return count;\n}",
        ),
        newline="",
    )
    verified = run_cli("verify", str(path), "--json")
    report = json.loads(verified.out)
    assert verified.code == 0, verified.out
    assert report["functions"][0]["tier"] == 1
    assert report["errors"] == []

    checked = run_cli("check", str(path), "--json")
    assert json.loads(checked.out)["rule_findings"] == []

    assert run_cli("finish", str(path)).code == 0
    assert "No refactor in progress" in run_cli("verify", str(path)).err


def test_frozen_function_name_must_stay(run_cli, fixture_copy):
    path = fixture_copy("inventory.c")
    run_cli("start", str(path), "--function", "find_item")
    text = path.read_text()
    path.write_text(
        text.replace("int find_item(const char *nm)", "int lookup_item(const char *nm)"), newline=""
    )
    result = run_cli("verify", str(path))
    assert result.code == 1
    assert "`find_item` (function) is used outside the regions" in result.out


def test_dialect_and_unresolved_names_are_errors(run_cli, fixture_copy):
    path = fixture_copy("inventory.c")
    run_cli("start", str(path), "--function", "cnt")
    text = path.read_text()
    path.write_text(
        text.replace("    return c;\n}", "    // done\n    return c + totl;\n}", 1), newline=""
    )
    result = run_cli("verify", str(path))
    assert result.code == 1
    assert "`//` comments" in result.out
    assert "`totl` is not declared" in result.out


def test_start_twice_needs_replace(run_cli, fixture_copy):
    path = fixture_copy("inventory.c")
    assert run_cli("start", str(path), "--function", "cnt").code == 0
    second = run_cli("start", str(path), "--function", "report")
    assert second.code == 2
    assert "already in progress" in second.err
    assert run_cli("start", str(path), "--function", "report", "--replace").code == 0


def test_repair_after_line_endings_and_encoding_changed(run_cli, fixture_copy):
    path = fixture_copy("legacy.c")
    original = path.read_bytes()
    run_cli("start", str(path), "--function", "is_stable")
    edited = original.replace(b"int d = a - b;", b"int difference = a - b;").replace(
        b"SQR(d)", b"SQR(difference)"
    )
    path.write_bytes(edited.decode("cp1251").encode("utf-8").replace(b"\r\n", b"\n"))
    failed = run_cli("verify", str(path))
    assert failed.code == 1
    assert "Run `repair`" in failed.out
    assert run_cli("repair", str(path)).code == 0
    assert path.read_bytes() == edited
    assert run_cli("verify", str(path)).code == 0


def test_utf8_comments_in_a_cp1251_file_are_caught_and_converted(run_cli, fixture_copy):
    path = fixture_copy("legacy.c")
    original = path.read_bytes()
    run_cli("start", str(path), "--function", "is_stable")
    comment = "    /* разность двух показаний */\r\n"
    anchor = b"    int d = a - b;\r\n"
    path.write_bytes(original.replace(anchor, comment.encode("utf-8") + anchor))
    verified = run_cli("verify", str(path))
    assert verified.code == 1
    assert "Run `repair --encoding cp1251`" in verified.out
    assert run_cli("repair", str(path)).code == 2
    assert run_cli("repair", str(path), "--encoding", "cp1251").code == 0
    assert path.read_bytes() == original.replace(anchor, comment.encode("cp1251") + anchor)
    assert run_cli("verify", str(path)).code == 0


def test_restore_returns_the_regions(run_cli, fixture_copy):
    path = fixture_copy("inventory.c")
    original = path.read_bytes()
    run_cli("start", str(path), "--function", "report")
    path.write_bytes(original.replace(b"int i, tot = 0;", b"int i, total = 0;"))
    assert run_cli("restore", str(path)).code == 0
    assert path.read_bytes() == original


def test_format_touches_only_the_regions(run_cli, fixture_copy, tmp_path):
    (tmp_path / ".clang-format").write_text("BasedOnStyle: LLVM\nIndentWidth: 4\n")
    path = fixture_copy("inventory.c")
    original = path.read_bytes()
    messy_outside = original.replace(b"static int n_items;", b"static   int   n_items;")
    messy_inside = messy_outside.replace(b"    return c;\n}", b"    return   c ;\n}")
    path.write_bytes(messy_outside)
    run_cli("start", str(path), "--function", "cnt")
    path.write_bytes(messy_inside)
    result = run_cli("format", str(path))
    assert result.code == 0, result.out
    formatted = path.read_bytes()
    assert b"static   int   n_items;" in formatted
    assert b"    return c;\n}" in formatted


def test_format_skips_without_a_project_style(run_cli, fixture_copy):
    path = fixture_copy("inventory.c")
    run_cli("start", str(path), "--function", "cnt")
    result = run_cli("format", str(path))
    assert result.code == 0
    assert "no .clang-format" in result.out


def test_line_range_with_a_helper_in_the_slot(run_cli, fixture_copy):
    path = fixture_copy("inventory.c")
    started = run_cli("start", str(path), "--lines", "66-73", "--json")
    regions = json.loads(started.out)["regions"]
    assert [region["kind"] for region in regions] == ["slot", "lines"]
    text = path.read_text()
    helper = "static int is_flagged(const struct item *entry)\n{\n    return (entry->flags & 1) == 1;\n}\n\n"
    text = text.replace("int report(FILE *out)", helper + "int report(FILE *out)")
    path.write_text(text, newline="")
    result = run_cli("verify", str(path))
    assert "is_flagged: tier 2: new function" in result.out


def test_fixtures_keep_their_bytes():
    legacy = (FIXTURES / "legacy.c").read_bytes()
    assert b"\r\n" in legacy
    assert "Комментарии".encode("cp1251") in legacy
