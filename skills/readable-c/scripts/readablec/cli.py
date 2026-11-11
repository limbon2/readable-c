"""The command line: `readable_c.py <command> FILE [options]`."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .commands import edit, inspect, review, start
from .commands.common import EXIT_USAGE, CommandError, configure_console
from .syntax import MissingDependencyError

DESCRIPTION = """\
Refactor C into readable code, one region of a file at a time.

Workflow: doctor FILE, then start FILE --function NAME (or --lines A-B), edit,
verify FILE after each step, check FILE for the findings left, format FILE,
verify FILE --final, finish FILE. restore FILE undoes the regions; repair FILE
fixes line endings or encoding that an edit tool changed outside the regions.
"""

_LINE_RANGE = re.compile(r"^(\d+)(?:-(\d+))?$")


def _line_range(text: str) -> tuple[int, int]:
    match = _LINE_RANGE.match(text.strip())
    if match is None:
        raise argparse.ArgumentTypeError(f"expected A-B or A, got {text!r}")
    first = int(match.group(1))
    last = int(match.group(2) or first)
    if last < first:
        raise argparse.ArgumentTypeError(f"the range {text!r} ends before it starts")
    return first, last


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="readable_c.py",
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"readable-c {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    def command(name: str, help_text: str, takes_file: bool = True) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=help_text, description=help_text)
        if takes_file:
            sub.add_argument("file", type=Path, help="the C file")
        sub.add_argument("--json", action="store_true", help="print JSON instead of text")
        return sub

    doctor = command(
        "doctor", "show the tools available and the conventions of a file", takes_file=False
    )
    doctor.add_argument("file", type=Path, nargs="?", help="a C file to describe")

    outline = command("outline", "list the functions and declarations of a file with their lines")
    outline.add_argument(
        "--findings", action="store_true", help="count the findings of each function"
    )

    begin = command("start", "select regions and snapshot the file before editing")
    begin.add_argument(
        "--function",
        action="append",
        default=[],
        metavar="NAME",
        help="a function to refactor (repeatable)",
    )
    begin.add_argument(
        "--lines",
        action="append",
        default=[],
        type=_line_range,
        metavar="A-B",
        help="a line range to refactor (repeatable)",
    )
    begin.add_argument("--all", action="store_true", help="make the whole file one region")
    begin.add_argument(
        "--replace", action="store_true", help="drop a snapshot in progress and start over"
    )
    begin.add_argument(
        "--include",
        action="append",
        default=[],
        type=Path,
        metavar="DIR",
        help="a folder to search for headers",
    )
    begin.add_argument("--quiet", action="store_true", help="do not print the region text")

    command("check", "list the readability findings inside the regions")

    verify = command(
        "verify", "check that nothing outside the regions changed and that behavior was kept"
    )
    verify.add_argument("--diff", action="store_true", help="show a diff of every region")
    verify.add_argument(
        "--final", action="store_true", help="also print the data the final report needs"
    )
    verify.add_argument(
        "--include",
        action="append",
        default=[],
        type=Path,
        metavar="DIR",
        help="a folder to search for headers",
    )

    command("format", "apply the project's .clang-format inside the regions only")

    repair = command(
        "repair", "restore frozen bytes after an edit tool changed line endings or encoding"
    )
    repair.add_argument(
        "--encoding", help="the encoding for changed non-ASCII lines, such as cp1251"
    )

    restore = command("restore", "put the original text back into the regions")
    restore.add_argument(
        "--whole-file", action="store_true", help="write back the whole file as it was at start"
    )

    command("finish", "forget the snapshot once the refactor is done")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    configure_console()
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 20000))
    arguments = _parser().parse_args(argv)
    try:
        return _dispatch(arguments)
    except CommandError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE
    except MissingDependencyError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE


def _dispatch(arguments: argparse.Namespace) -> int:  # noqa: PLR0911  one return per command
    name = arguments.command
    as_json = arguments.json
    if name == "doctor":
        return inspect.doctor(arguments.file, as_json)
    if name == "outline":
        return inspect.outline(arguments.file, arguments.findings, as_json)
    if name == "start":
        return start.start(
            arguments.file,
            function_names=arguments.function,
            line_ranges=arguments.lines,
            whole_file=arguments.all,
            replace=arguments.replace,
            include_dirs=arguments.include,
            quiet=arguments.quiet,
            as_json=as_json,
        )
    if name == "check":
        return review.check(arguments.file, as_json)
    if name == "verify":
        return review.verify(
            arguments.file, arguments.include, arguments.diff, arguments.final, as_json
        )
    if name == "format":
        return edit.format_regions(arguments.file, as_json)
    if name == "repair":
        return edit.repair(arguments.file, arguments.encoding, as_json)
    if name == "restore":
        return edit.restore(arguments.file, arguments.whole_file, as_json)
    return edit.finish(arguments.file, as_json)
