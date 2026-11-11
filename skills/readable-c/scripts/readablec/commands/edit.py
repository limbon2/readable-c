"""Commands that write the file: `format`, `repair` and `restore`; and `finish`."""

from __future__ import annotations

from pathlib import Path

from .. import formatting, guard, state
from .common import (
    EXIT_CLEAN,
    EXIT_FINDINGS,
    CommandError,
    Output,
    Session,
    display_path,
    open_session,
    print_issue,
    write_file,
)


def format_regions(path: Path, as_json: bool) -> int:
    output = Output(as_json)
    session = open_session(path)
    if session.result.spans is None:
        raise CommandError(
            "The guard fails, so the regions cannot be found. Run `verify` to see why."
        )
    try:
        result = formatting.format_regions(path, session.current, session.spans)
    except formatting.FormatError as error:
        output.line(f"format: skipped: {error}")
        output.json({"formatted": False, "reason": str(error)})
        return EXIT_CLEAN
    if result.data != session.current:
        write_file(path, result.data)
    after = guard.check(session.snapshot.original, session.regions, result.data)
    output.line(
        f"format: applied {result.applied} changes inside the regions with {display_path(result.config)}; "
        f"ignored {result.skipped} outside them."
    )
    output.line("guard: " + ("passed" if after.ok else "failed"))
    for issue in after.issues:
        print_issue(output, path, issue)
    output.json(
        {"formatted": True, "applied": result.applied, "ignored": result.skipped, "guard": after.ok}
    )
    return EXIT_CLEAN if after.ok else EXIT_FINDINGS


def repair(path: Path, encoding: str | None, as_json: bool) -> int:
    output = Output(as_json)
    session = open_session(path)
    if session.result.spans is not None:
        return _convert_new_text(output, path, session, encoding)
    try:
        repaired = guard.repair(
            session.snapshot.original, session.regions, session.current, encoding
        )
    except guard.RepairError as error:
        raise CommandError(str(error)) from error
    write_file(path, repaired)
    after = guard.check(session.snapshot.original, session.regions, repaired)
    output.line("repair: restored the frozen bytes and converted the regions to the file's format.")
    output.line("guard: " + ("passed" if after.ok else "failed"))
    for issue in after.issues:
        print_issue(output, path, issue)
    output.json({"repaired": True, "guard": after.ok})
    return EXIT_CLEAN if after.ok else EXIT_FINDINGS


def _convert_new_text(output: Output, path: Path, session: Session, encoding: str | None) -> int:
    """With the frozen text intact, the only repair left is new UTF-8 text in a legacy file."""
    original, regions, spans = session.snapshot.original, session.regions, session.spans
    foreign = guard.foreign_text_issues(original, regions, session.current, spans)
    if not foreign:
        output.line("repair: nothing to repair; the frozen text is intact.")
        output.json({"repaired": False})
        return EXIT_CLEAN
    if encoding is None:
        raise CommandError(
            f"{len(foreign)} new line(s) hold UTF-8 text in a file that is not UTF-8. Run "
            "`repair --encoding <codec>` with the file's encoding (`verify` and `doctor` show a guess)."
        )
    try:
        converted = guard.convert_new_text(original, regions, session.current, spans, encoding)
    except guard.RepairError as error:
        raise CommandError(str(error)) from error
    write_file(path, converted)
    output.line(f"repair: converted {len(foreign)} new line(s) to {encoding}.")
    output.json({"repaired": True, "converted_lines": len(foreign), "encoding": encoding})
    return EXIT_CLEAN


def restore(path: Path, whole_file: bool, as_json: bool) -> int:
    output = Output(as_json)
    session = open_session(path)
    if whole_file:
        write_file(path, session.snapshot.original)
        output.line("restore: wrote the file back exactly as it was at `start`.")
        output.json({"restored": "whole file"})
        return EXIT_CLEAN
    if session.result.spans is None:
        raise CommandError(
            "Text outside the regions changed too, so the regions cannot be found. Run `repair` if "
            "only line endings or encoding changed, or `restore --whole-file` to return the whole "
            "file to its state at `start` (this also drops any other edits made since then)."
        )
    restored = guard.restore(
        session.snapshot.original, session.regions, session.current, session.spans
    )
    write_file(path, restored)
    output.line(
        f"restore: put back the original text of {len(session.regions)} region(s); the snapshot is kept."
    )
    output.json({"restored": "regions"})
    return EXIT_CLEAN


def finish(path: Path, as_json: bool) -> int:
    output = Output(as_json)
    removed = state.delete(path)
    output.line("finish: the snapshot is removed." if removed else "finish: there was no snapshot.")
    output.json({"removed": removed})
    return EXIT_CLEAN
