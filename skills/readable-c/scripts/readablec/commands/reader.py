"""`reader`: a brief for a first-time reader of the regions as they are now.

The agent that refactored the code cannot see what it left unexplained: it knows what
every name means and why every number is there. The reader pass hands the code to a
fresh agent that knows none of that. The brief holds only the current text of the
regions and the declarations it uses, never the original code or the agent's notes,
and asks for the questions a newcomer would have to ask the author, sorted into what the
code could say (the agent must fix those) and what only outside knowledge answers.

Each brief records a digest of the text it showed, so `verify --final` can tell whether
the code the report describes went through the pass.
"""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Sequence
from pathlib import Path

from .. import includes, state
from ..context import span_context
from .common import EXIT_CLEAN, Output, numbered_lines, open_session
from .review import guard_failed

Span = tuple[int, int]

BRIEF = """\
You are a C developer reading this code for the first time. You know C and its standard
library well. You do not know this project, its libraries, its file formats or its
protocols, and you cannot ask the author.

Read the code below and list the questions you would have to ask the author, or look up
elsewhere, before you could change this code safely. Sort them into two lists:

A. The code could say it. You found the answer in the code below, but only by working
   it out, because nothing tells you directly:
   - what a name holds or does, when the name does not say it;
   - where a number, size, offset or bound comes from;
   - what a step computes that you had to trace by hand (a loop, a cast, bit arithmetic);
   - what a function does, returns or owns, when you had to read its body to find out;
   - a comment that does not match what the code does.
   Give the answer you worked out for each one. If you cannot, it belongs in B.
B. Only outside knowledge answers it: what a library call does or returns, what a
   protocol or file format says, why the code does what it does, whether a behavior is
   intended, who calls this code.

When the code does something surprising, put what it does in A, with your answer, and
the question of why in B.

Do not ask about what the C standard defines or what the code already says plainly. Do
not suggest fixes, rewrite code or comment on style: questions only. Use only what is
below; do not open other files.

Reply in this form, one question per line, with the questions that cost you the most
time first. Write "none" under a list that has no questions.

A. The code could say it
1. <line>: <question> -> <the answer you worked out>
B. Only outside knowledge answers it
1. <line>: <question>"""


def region_digest(current: bytes, spans: Sequence[Span]) -> str:
    """Names the text of the regions, so a brief can be matched to the code it showed."""
    digest = hashlib.sha256()
    for start, end in spans:
        digest.update(current[start:end])
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def reader(path: Path, as_json: bool) -> int:
    output = Output(as_json)
    session = open_session(path)
    if session.result.spans is None:
        return guard_failed(output, path, session)
    analysis = session.current_analysis()
    spans = [span for span in session.spans if span[0] < span[1]]
    digest = region_digest(session.current, spans)
    snapshot = session.snapshot
    if digest not in snapshot.reader_briefs:
        state.save(
            dataclasses.replace(
                snapshot, path=path, reader_briefs=[*snapshot.reader_briefs, digest]
            )
        )
        round_number = len(snapshot.reader_briefs) + 1
    else:
        round_number = snapshot.reader_briefs.index(digest) + 1

    lines = [BRIEF]
    encoding = analysis.conventions.encoding.name
    for start, end in spans:
        first = analysis.source.line_of(start)
        last = analysis.source.line_of(end - 1)
        lines.extend(["", f"== Code: lines {first}-{last} of {path.name}"])
        lines.extend(numbered_lines(analysis.source, start, end, encoding))
    context = span_context(analysis, spans, includes.known_names(path, analysis.tokens))
    lines.extend(["", "== Declarations from the same file that this code uses"])
    for name, kind, text in context.declarations:
        lines.append(
            f"- {kind} `{name}`: {text}" if "\n" not in text else f"- {kind} `{name}`:\n{text}"
        )
    if not context.declarations:
        lines.append("(none)")
    grouped: dict[str, list[str]] = {}
    for name, header in context.from_headers.items():
        grouped.setdefault(header, []).append(name)
    if grouped or context.unknown:
        lines.extend(["", "== Names declared in headers (not shown)"])
        lines.extend(
            f"- {header}: {', '.join(sorted(names))}" for header, names in sorted(grouped.items())
        )
        if context.unknown:
            lines.append(f"- in headers this brief does not show: {', '.join(context.unknown)}")

    for line in lines:
        output.line(line)
    output.json({"round": round_number, "digest": digest, "brief": "\n".join(lines)})
    return EXIT_CLEAN
