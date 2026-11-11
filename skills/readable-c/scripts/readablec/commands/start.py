"""`start`: select the regions, snapshot the file, and show what the regions depend on."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from .. import includes, regions, state
from ..analysis import Analysis
from ..context import RegionContext, region_context
from ..rules import run_rules
from ..verify.names import frozen_entries
from .common import (
    EXIT_CLEAN,
    CommandError,
    Output,
    display_path,
    numbered_lines,
    print_finding,
    read_file,
)


def start(  # noqa: PLR0913  the command's options
    path: Path,
    *,
    function_names: Sequence[str],
    line_ranges: Sequence[tuple[int, int]],
    whole_file: bool,
    replace: bool,
    include_dirs: Sequence[Path],
    quiet: bool,
    as_json: bool,
) -> int:
    output = Output(as_json)
    if state.exists(path) and not replace:
        existing = state.load(path)
        shown = "; ".join(region.label for region in existing.regions)
        raise CommandError(
            f"A refactor of {display_path(path)} is already in progress ({shown}). Finish it with "
            "`finish`, undo it with `restore`, or pass --replace to start over from the file as it is now."
        )
    data = read_file(path)
    analysis = Analysis(data, path)
    try:
        resolution = regions.resolve(
            analysis.source,
            analysis.root,
            analysis.functions,
            function_names=function_names,
            line_ranges=line_ranges,
            whole_file=whole_file,
        )
    except regions.RegionError as error:
        raise CommandError(str(error)) from error
    selected = resolution.regions
    frozen = frozen_entries(analysis, selected)
    spans = [(region.start, region.end) for region in selected]
    frozen_names = {str(entry["name"]) for entry in frozen}
    baseline = run_rules(analysis, spans, frozen_names)
    known = includes.known_names(path, analysis.tokens, include_dirs)
    context = region_context(analysis, selected, known)
    snapshot = state.Snapshot(
        path=path,
        original=data,
        regions=selected,
        baseline=[finding.to_json() for finding in baseline.findings],
        frozen=frozen,
        notes=resolution.notes,
    )
    state.save(snapshot)

    output.section(f"Regions of {display_path(path)}")
    for region in selected:
        output.line(f"- {regions.describe(analysis.source, region)}")
    for note in resolution.notes:
        output.line(f"  note: {note}")
    if not quiet:
        encoding = analysis.conventions.encoding.name
        for region in selected:
            if region.is_slot:
                continue
            output.section(region.label)
            for line in numbered_lines(analysis.source, region.start, region.end, encoding):
                output.line(line)
    _print_context(output, context, frozen)
    output.section("Conventions of this file (write new code the same way)")
    for line in analysis.conventions.describe():
        output.line(f"- {line}")
    output.section(f"Baseline findings ({len(baseline.findings)})")
    for finding in baseline.findings:
        print_finding(output, path, finding)
    for first, last, reason in baseline.unchecked:
        output.line(f"{display_path(path)}:{first}: not checked (lines {first}-{last}): {reason}")
    output.section("Next")
    output.line(
        "Read references/rules.md and references/hazards.md, then edit in small steps and run "
        "`verify` after each step. Run `check` for the findings that remain."
    )
    output.json(
        {
            "path": str(path),
            "regions": [region.to_json() for region in selected],
            "notes": resolution.notes,
            "frozen": frozen,
            "baseline": [finding.to_json() for finding in baseline.findings],
            "unchecked": baseline.unchecked,
            "context": {
                "declarations": context.declarations,
                "macro_warnings": context.macro_warnings,
                "from_headers": context.from_headers,
                "unknown": context.unknown,
                "define_warnings": context.define_warnings,
            },
            "conventions": analysis.conventions.describe(),
        }
    )
    return EXIT_CLEAN


def _print_context(output: Output, context: RegionContext, frozen: list[dict[str, object]]) -> None:
    output.section("Declarations from this file that the regions use")
    if not context.declarations:
        output.line("(none)")
    for name, kind, text in context.declarations:
        output.line(
            f"- {kind} `{name}`: {text}" if "\n" not in text else f"- {kind} `{name}`:\n{text}"
        )
    for warning in context.macro_warnings + context.define_warnings:
        output.line(f"! {warning}")
    if context.from_headers:
        output.section("Names from headers")
        grouped: dict[str, list[str]] = {}
        for name, header in context.from_headers.items():
            grouped.setdefault(header, []).append(name)
        for header, names in sorted(grouped.items()):
            output.line(f"- {header}: {', '.join(sorted(names))}")
    if context.unknown:
        output.line(f"- declared somewhere the tool cannot see: {', '.join(context.unknown)}")
    output.section("Frozen names (code outside the regions depends on them)")
    if not frozen:
        output.line("(none)")
    for entry in frozen:
        if entry["scope"] == "file":
            output.line(
                f"- {entry['kind']} `{entry['name']}`: keep the name and `{entry['signature']}`"
            )
        elif entry["scope"] == "local":
            output.line(
                f"- local `{entry['name']}` in {entry['function']}: keep it declared at the same block "
                f"level with type `{entry['type']}`"
            )
        else:
            output.line(
                f"- label `{entry['name']}` in {entry['function']}: a goto outside the region uses it"
            )
