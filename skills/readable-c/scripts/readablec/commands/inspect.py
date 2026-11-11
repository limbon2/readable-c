"""`doctor` and `outline`: what the tool can do here, and what a file holds."""

from __future__ import annotations

import importlib.metadata
import platform
import shutil
from pathlib import Path

from .. import formatting, includes, state, syntax
from ..analysis import Analysis
from ..rules import run_rules
from ..rules.style import max_nesting
from .common import EXIT_CLEAN, Output, display_path, read_file

OUTLINE_KINDS = {"prototype", "variable", "typedef", "struct", "union", "enum", "macro"}


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def doctor(path: Path | None, as_json: bool) -> int:
    output = Output(as_json)
    tools = {
        "python": platform.python_version(),
        "tree-sitter": _package_version("tree-sitter"),
        "tree-sitter-c": _package_version("tree-sitter-c"),
        "clang-format": formatting.version(),
        "uv": shutil.which("uv"),
        "state folder": str(state.state_dir()),
    }
    output.section("Tools")
    for name, value in tools.items():
        output.line(f"{name}: {value or 'not available'}")
    report: dict[str, object] = {"tools": tools}
    if path is not None:
        report["file"] = _describe_file(output, path)
    output.json(report)
    return EXIT_CLEAN


def _describe_file(output: Output, path: Path) -> dict[str, object]:
    analysis = Analysis(read_file(path), path)
    conventions = analysis.conventions
    errors = syntax.error_nodes(analysis.root)
    error_lines = sorted({syntax.start_line(node) for node in errors})
    unparsed = [function.name for function in analysis.functions if not function.is_parsed]
    config = formatting.find_config(path)
    known = includes.known_names(path, analysis.tokens)
    output.section(f"File {display_path(path)}")
    output.line(f"{analysis.source.line_count} lines, {len(analysis.functions)} functions")
    for line in conventions.describe():
        output.line(line)
    if error_lines:
        shown = ", ".join(map(str, error_lines[:10]))
        output.line(f"parse: {len(errors)} problems (lines {shown}); rules skip that code")
    else:
        output.line("parse: no problems")
    if unparsed:
        output.line(f"found by the text scan only: {', '.join(unparsed)}")
    output.line(f"formatter: {config if config else 'no .clang-format; `format` will skip'}")
    if known.missing_headers:
        output.line(f"headers the tool cannot find: {', '.join(known.missing_headers)}")
    if known.unknown_system_headers:
        output.line(f"system headers it does not know: {', '.join(known.unknown_system_headers)}")
    return {
        "path": str(path),
        "lines": analysis.source.line_count,
        "functions": len(analysis.functions),
        "conventions": conventions.describe(),
        "parse_problem_lines": error_lines,
        "clang_format_config": str(config) if config else None,
        "missing_headers": known.missing_headers,
    }


def outline(path: Path, with_findings: bool, as_json: bool) -> int:
    output = Output(as_json)
    analysis = Analysis(read_file(path), path)
    items: list[dict[str, object]] = []
    for function in analysis.functions:
        node = function.node
        details = {
            "lines": function.last_line - function.first_line + 1,
            "parameters": len(syntax.parameter_nodes(node)) if node is not None else None,
            "nesting": max_nesting(node.child_by_field_name("body")) if node is not None else None,
        }
        if with_findings:
            report = run_rules(analysis, [(function.start, function.end)])
            details["rule_findings"] = sum(
                1 for finding in report.findings if finding.severity == "rule"
            )
            details["advice"] = sum(
                1 for finding in report.findings if finding.severity == "advice"
            )
        items.append(
            {
                "kind": "function" if function.is_parsed else "function (text scan)",
                "name": function.name,
                "first_line": function.first_line,
                "last_line": function.last_line,
                **details,
            }
        )
    for declaration in analysis.declarations.all:
        if declaration.kind not in OUTLINE_KINDS:
            continue
        first = analysis.source.line_of(declaration.start)
        last = analysis.source.line_of(max(declaration.start, declaration.end - 1))
        items.append(
            {
                "kind": declaration.kind,
                "name": declaration.name,
                "first_line": first,
                "last_line": last,
            }
        )
    items.sort(key=lambda item: (int(str(item["first_line"])), str(item["kind"])))
    output.line(
        f"{display_path(path)}: {analysis.source.line_count} lines, {len(analysis.functions)} functions"
    )
    for item in items:
        output.line(_outline_line(item))
    output.json({"path": str(path), "items": items})
    return EXIT_CLEAN


def _outline_line(item: dict[str, object]) -> str:
    first, last = item["first_line"], item["last_line"]
    lines = f"L{first}" if first == last else f"L{first}-{last}"
    text = f"  {lines:<14} {item['kind']:<22} {item['name']}"
    if str(item["kind"]).startswith("function"):
        facts = [f"{item['lines']} lines"]
        if item.get("nesting") is not None:
            facts.append(f"nesting {item['nesting']}")
        if item.get("parameters") is not None:
            facts.append(f"{item['parameters']} params")
        if "rule_findings" in item:
            facts.append(f"{item['rule_findings']} rule / {item['advice']} advice findings")
        text += "  (" + ", ".join(facts) + ")"
    return text
