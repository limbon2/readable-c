"""The commands end to end, on copies of the fixtures."""

import json

from conftest import FIXTURES
from readablec.commands.reader import BRIEF


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

    assert run_cli("reader", str(path)).code == 0
    assert run_cli("verify", str(path), "--final").code == 0
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


def test_reader_brief_shows_the_current_regions_and_is_tracked(run_cli, fixture_copy):
    path = fixture_copy("inventory.c")
    assert run_cli("start", str(path), "--function", "cnt", "--quiet").code == 0
    not_yet = json.loads(run_cli("verify", str(path), "--json").out)["reader"]
    assert not_yet.startswith("not run")

    text = path.read_text()
    path.write_text(
        text.replace("int lo, int hi", "int lowest, int hi").replace("qty >= lo", "qty >= lowest"),
        newline="",
    )
    brief = run_cli("reader", str(path))
    assert brief.code == 0
    assert brief.out.startswith("You are a C developer reading this code for the first time.")
    assert "static int cnt(int lowest, int hi)" in brief.out
    assert "int lo," not in brief.out, "the brief must not show the original code"
    assert "- struct `item`:" in brief.out, "the type behind `items` is shown too"
    assert "find_item" not in brief.out, "code outside the regions stays out"
    current = json.loads(run_cli("verify", str(path), "--json").out)["reader"]
    assert current.startswith("round 1 showed the current code")

    path.write_text(
        path.read_text().replace("int hi)", "int highest)").replace("<= hi", "<= highest"),
        newline="",
    )
    changed = json.loads(run_cli("verify", str(path), "--json").out)["reader"]
    assert changed.startswith("the code changed after the last of 1 briefs")
    second = json.loads(run_cli("reader", str(path), "--json").out)
    assert second["round"] == 2
    assert (
        "Reader pass: round 2 showed the current code"
        in run_cli("verify", str(path), "--final").out
    )


def test_reader_guide_holds_the_same_brief_as_the_tool():
    guide = (
        FIXTURES.parent.parent / "skills" / "readable-c" / "references" / "reader.md"
    ).read_text(encoding="utf-8")
    assert BRIEF in guide


def test_reader_brief_sorts_questions_into_two_lists():
    assert "A. The code could say it" in BRIEF
    assert "B. Only outside knowledge answers it" in BRIEF
    assert "a comment that does not match what the code does" in BRIEF


def test_final_verify_needs_a_reader_round_on_the_final_code(run_cli, fixture_copy):
    path = fixture_copy("inventory.c")
    assert run_cli("start", str(path), "--function", "cnt", "--quiet").code == 0
    assert run_cli("verify", str(path)).code == 0, "only the final check needs the reader pass"
    missing = run_cli("verify", str(path), "--final", "--json")
    assert missing.code == 1
    assert "The reader pass has not run" in json.loads(missing.out)["errors"][0]["message"]

    assert run_cli("reader", str(path)).code == 0
    assert run_cli("verify", str(path), "--final").code == 0

    def rename(old: str, new: str) -> None:
        text = path.read_text()
        text = text.replace(f"int {old},", f"int {new},").replace(f">= {old} &&", f">= {new} &&")
        path.write_text(text, newline="")

    for old, new in (("lo", "low"), ("low", "lower")):
        rename(old, new)
        stale = run_cli("verify", str(path), "--final", "--json")
        assert stale.code == 1
        assert (
            "changed after the last reader round" in json.loads(stale.out)["errors"][0]["message"]
        )
        assert run_cli("reader", str(path)).code == 0

    rename("lower", "lowest")
    after_three = run_cli("verify", str(path), "--final")
    assert after_three.code == 0, "after three rounds the report says what no round checked"
    assert "no round checked the last changes" in after_three.out


def test_finish_waits_for_a_final_check_of_the_file_as_it_is(run_cli, fixture_copy):
    path = fixture_copy("inventory.c")
    assert run_cli("start", str(path), "--function", "cnt", "--quiet").code == 0
    edited = path.read_text().replace(SPLIT_DECLARATION[0], SPLIT_DECLARATION[1])
    path.write_text(edited, newline="")

    unchecked = run_cli("finish", str(path))
    assert unchecked.code == 1
    assert "`verify --final` has not run" in unchecked.out

    run_cli("verify", str(path), "--final")
    path.write_text(edited.replace("/* Counts", "/* Counts all"), newline="")
    changed = run_cli("finish", str(path))
    assert changed.code == 1
    assert "changed after the last `verify --final`" in changed.out

    run_cli("verify", str(path), "--final")
    assert run_cli("finish", str(path)).code == 0
    assert "No refactor in progress" in run_cli("verify", str(path)).err


def test_finish_after_restore_or_with_force(run_cli, fixture_copy):
    path = fixture_copy("inventory.c")
    assert run_cli("start", str(path), "--function", "cnt", "--quiet").code == 0
    path.write_text(path.read_text().replace(*SPLIT_DECLARATION), newline="")
    assert run_cli("restore", str(path)).code == 0
    assert run_cli("finish", str(path)).code == 0, "nothing is left to check after restore"

    assert run_cli("start", str(path), "--function", "cnt", "--quiet").code == 0
    path.write_text(path.read_text().replace(*SPLIT_DECLARATION), newline="")
    assert run_cli("finish", str(path), "--force").code == 0


SPLIT_DECLARATION = ("int i, c = 0;", "int i;\n    int c = 0;")
