"""The reader gets the region diff and compatible C standard for its practice review."""

import json
from dataclasses import replace

from readablec import state
from readablec.commands.reader import region_digest


def test_reader_needs_a_fresh_brief_when_the_configured_standard_changes(run_cli, tmp_path):
    source = tmp_path / "count.c"
    source.write_text("int count(void) { return 1; }\n", encoding="utf-8")
    compile_database = tmp_path / "compile_commands.json"

    def configure(flag):
        compile_database.write_text(
            json.dumps(
                [
                    {
                        "directory": str(tmp_path),
                        "file": source.name,
                        "arguments": ["cc", flag, "-c", source.name],
                    }
                ]
            ),
            encoding="utf-8",
        )

    configure("-std=c99")
    assert run_cli("start", str(source), "--all", "--quiet").code == 0
    first = json.loads(run_cli("reader", str(source), "--json").out)
    assert "== Configured C standard\nC99 (" in first["brief"]
    assert first["brief"].endswith("== Changes from the snapshot (selected regions only)\n(none)")
    assert run_cli("verify", str(source), "--final").code == 0

    configure("-std=c17")
    stale = run_cli("verify", str(source), "--final")
    assert stale.code == 1
    assert "No reader brief used the current instructions and C standard" in stale.out
    current = json.loads(run_cli("reader", str(source), "--json").out)
    assert "== Configured C standard\nC17 (" in current["brief"]
    assert current["digest"] != first["digest"]
    assert current["round"] == 1
    assert run_cli("verify", str(source), "--final").code == 0


def test_pre_practice_review_briefs_do_not_count_as_rounds(run_cli, tmp_path):
    source = tmp_path / "count.c"
    code = b"int count(void) { return 1; }\n"
    source.write_bytes(code)
    assert run_cli("start", str(source), "--all", "--quiet").code == 0
    old_rounds = [
        region_digest(code.replace(b"1", value), [(0, len(code))]) for value in (b"1", b"2", b"3")
    ]
    state.save(replace(state.load(source), reader_briefs=old_rounds))

    assert run_cli("verify", str(source), "--final").code == 1
    first = json.loads(run_cli("reader", str(source), "--json").out)
    assert first["round"] == 1
    assert run_cli("verify", str(source), "--final").code == 0


def test_reader_diff_limits_original_text_to_regions_and_includes_helper_slots(run_cli, tmp_path):
    source = tmp_path / "sum.c"
    original = (
        "int untouched(void) { return 42; }\r\n"
        "\r\n"
        "int sum(int count)\r\n"
        "{\r\n"
        "    count += 2; /* outside the selection */\r\n"
        "    return count + 3; /* Комментарий */\r\n"
        "}\r\n"
    ).encode("cp1251")
    source.write_bytes(original)
    assert run_cli("start", str(source), "--lines", "6-6", "--quiet").code == 0

    helper = b"static int add_three(int value) { return value + 3; }\r\n\r\n"
    changed = original.replace(b"int sum(", helper + b"int sum(")
    changed = changed.replace(original.splitlines()[5], b"    return add_three(count);")
    source.write_bytes(changed)
    brief = run_cli("reader", str(source))

    assert brief.code == 0
    assert "== Configured C standard\nUnknown." in brief.out
    assert "untouched" not in brief.out
    assert "outside the selection" not in brief.out
    assert "+static int add_three(int value)" in brief.out
    assert "-    return count + 3; /* Комментарий */" in brief.out
    assert "+    return add_three(count);" in brief.out
    assert "--- original (from line 6)\n+++ current (from line 8)" in brief.out
    assert source.read_bytes() == changed


def test_reader_diff_shows_removed_documentation_tags(run_cli, tmp_path):
    source = tmp_path / "count.c"
    definition = "int increment(int count) { return count + 1; }\n"
    source.write_text(
        "/**\n * @param count The current count.\n * @return The updated count.\n */\n"
        + definition,
        encoding="utf-8",
    )
    assert run_cli("start", str(source), "--function", "increment", "--quiet").code == 0
    source.write_text("/* Return the updated count. */\n" + definition, encoding="utf-8")

    brief = run_cli("reader", str(source))
    assert brief.code == 0
    current_code, diff = brief.out.split("== Changes from the snapshot")
    assert "@param count" not in current_code
    assert "- * @param count The current count." in diff
    assert "- * @return The updated count." in diff
    assert "+/* Return the updated count. */" in diff
