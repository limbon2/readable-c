"""Configured standards come from applicable build evidence."""

import json
from pathlib import Path

import pytest
from conftest import analyse
from readablec import standard
from readablec.verify import names


def write_database(folder: Path, entries: list[dict[str, object]]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "compile_commands.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


def test_compile_database_uses_matching_file_and_last_flag(tmp_path):
    source = tmp_path / "source" / "code with spaces.c"
    source.parent.mkdir()
    source.touch()
    root = tmp_path / "out" / "build" / "release"
    database = write_database(
        root,
        [
            {"directory": ".", "file": "../../../other.c", "arguments": ["cc", "-std=c90"]},
            {
                "directory": ".",
                "file": "../../../source/code with spaces.c",
                "command": 'clang -std=c90 "-DSAMPLE=-std=c99 in a macro" '
                '-std=gnu17 -c "../../../source/code with spaces.c"',
            },
        ],
    )
    assert standard.detect(source) == standard.CStandard(2017, str(database))


def test_database_uses_oldest_explicit_standard(tmp_path):
    source = tmp_path / "code.c"
    source.touch()
    database = write_database(
        tmp_path,
        [
            {"directory": ".", "file": str(source), "arguments": ["cl", "/std:c17"]},
            {"directory": ".", "file": "code.c", "arguments": ["cc", "-std=c99"]},
        ],
    )
    assert standard.detect(source) == standard.CStandard(
        1999, f"{database} (oldest matching edition)"
    )


def test_matching_default_command_can_use_literal_cmake_setting(tmp_path):
    source = tmp_path / "src" / "code.c"
    source.parent.mkdir()
    source.touch()
    config = tmp_path / "CMakeLists.txt"
    config.write_text(
        "# set(CMAKE_C_STANDARD 90)\n"
        "project(example C)\n"
        'SET(CMAKE_C_STANDARD "17")\n'
        "set(CMAKE_C_STANDARD_REQUIRED ON)\n"
        "add_executable(example src/code.c)\n",
        encoding="utf-8",
    )
    write_database(
        tmp_path / "cmake-build-debug",
        [{"directory": "..", "file": "src/code.c", "arguments": ["cc", "src/code.c"]}],
    )
    assert standard.detect(source) == standard.CStandard(2017, f"{config} (requested default)")
    assert standard.detect(source.with_suffix(".h")) is None


@pytest.mark.parametrize("unknown", ["/std:clatest", "@compiler-flags.rsp"])
def test_unknown_matching_command_prevents_cmake_guess(tmp_path, unknown):
    source = tmp_path / "code.c"
    source.touch()
    (tmp_path / "CMakeLists.txt").write_text("set(CMAKE_C_STANDARD 17)\n", encoding="utf-8")
    write_database(
        tmp_path,
        [{"directory": ".", "file": "code.c", "arguments": ["cc", "-std=c17", unknown]}],
    )
    assert standard.detect(source) is None


@pytest.mark.parametrize(
    "text",
    [
        "if(BUILD_MODERN)\n  set(CMAKE_C_STANDARD 17)\nendif()",
        "block()\n  set(CMAKE_C_STANDARD 17)\nendblock()",
        "message(\n  set(CMAKE_C_STANDARD 17)\n)",
        "add_executable(example code.c)\nset(CMAKE_C_STANDARD 17)",
        "set(CMAKE_C_STANDARD 17)\nset_property(TARGET example PROPERTY C_STANDARD 90)",
        'set(CMAKE_C_STANDARD 17)\ntarget_compile_options(example PRIVATE "-std=c90")',
        "set(CMAKE_C_STANDARD ${BUILD_STANDARD})",
        "set(cmake_c_standard 17)",
        "#[[\nset(CMAKE_C_STANDARD 17)\n]]",
        'message("guessing a C standard:\nset(CMAKE_C_STANDARD 17)\n")',
    ],
)
def test_cmake_declines_ambiguous_or_inapplicable_source_settings(tmp_path, text):
    source = tmp_path / "code.c"
    source.touch()
    (tmp_path / "CMakeLists.txt").write_text(text, encoding="utf-8")
    assert standard.detect(source) is None


def test_configured_standard_allows_first_use_in_partial_block():
    before = analyse("int f(int n) {\n    if (!n) return 0;\n    return n;\n}\n")
    after = analyse(
        "int f(int n) {\n    if (!n) return 0;\n    int result = n;\n    return result;\n}\n"
    )
    spans = [(after.data.index(b"int result"), after.data.index(b"}"))]
    assert names.dialect_issues(before, after, spans, standard.CStandard(2017, "test")) == []
    [issue] = names.dialect_issues(before, after, spans, standard.CStandard(1990, "test"))
    assert issue.line == 3
    assert "declarations after statements" in issue.message
    [fallback] = names.dialect_issues(before, after, spans)
    assert fallback.line == 3


def test_c90_rejects_an_edit_that_makes_a_frozen_declaration_mixed():
    before = analyse(
        "int f(void) {\n    int first = 1;\n    int second = 2;\n    return first + second;\n}\n"
    )
    after = analyse(
        "int f(void) {\n    int first;\n    first = 1;\n    int second = 2;\n    return first + second;\n}\n"
    )
    spans = [(after.data.index(b"int first;"), after.data.index(b"int second"))]
    [issue] = names.dialect_issues(before, after, spans, standard.CStandard(1990, "test"))
    assert issue.line == 3


def test_configured_standard_grandfathers_existing_extensions():
    before = analyse("int f(void) {\n    // inherited compiler extension\n    return 0;\n}\n")
    after = analyse("int f(void) {\n    // rewritten comment\n    return 0;\n}\n")
    target = standard.CStandard(1990, "test")
    assert names.dialect_issues(before, after, [(0, len(after.data))], target) == []
    extended = analyse(after.data + b"// New comment is another use.\n")
    spans = [(len(after.data), len(extended.data))]
    [issue] = names.dialect_issues(before, extended, spans, target)
    assert issue.line == 5
    assert issue.severity == "error"


@pytest.mark.parametrize(
    ("prefix", "reported"),
    [
        ("", ["bool", "true"]),
        ("#include <stdbool.h>\n", []),
        ("typedef int bool;\nenum { true = 1 };\n", []),
    ],
)
def test_c17_boolean_aliases_require_visible_definitions(prefix, reported):
    before = analyse(prefix + "int f(void) { return 1; }\n")
    after = analyse(prefix + "int f(void) { bool count = true; return count; }\n")
    spans = [(0, len(after.data))]
    issues = names.dialect_issues(before, after, spans, standard.CStandard(2017, "test"))
    assert [issue.message.split("`")[1] for issue in issues] == reported
    assert names.dialect_issues(before, after, spans, standard.CStandard(2023, "test")) == []


def test_c17_uses_a_boolean_definition_from_an_included_project_header(tmp_path):
    source = tmp_path / "code.c"
    (tmp_path / "flags.h").write_text("typedef int bool;\n#define false 0\n", encoding="utf-8")
    before = '#include "flags.h"\nint f(void) { return 0; }\n'
    after = '#include "flags.h"\nint f(void) { bool flag = false; return flag; }\n'
    original = analyse(before)
    new = analyse(after)
    new.source.path = source
    assert (
        names.dialect_issues(original, new, [(0, len(new.data))], standard.CStandard(2017, "test"))
        == []
    )


def test_configured_c23_construct_is_rejected_for_c17():
    before = analyse("void *f(void) { return 0; }\n")
    after = analyse("void *f(void) { return nullptr; }\n")
    spans = [(0, len(after.data))]
    [issue] = names.dialect_issues(before, after, spans, standard.CStandard(2017, "test"))
    assert "`nullptr`" in issue.message
    assert "C23" in issue.message
    assert names.dialect_issues(before, after, spans, standard.CStandard(2023, "test")) == []
