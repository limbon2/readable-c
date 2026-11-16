"""`reader`: a brief for a first-time reader of the regions as they are now.

The agent that refactored the code cannot see what it left unexplained: it knows what
every name means and why every number is there. The reader pass hands the code to a
fresh agent that knows none of that. It asks what the current code leaves
unexplained, then shows the region diff so the reader can flag older practices
and comment format mismatches introduced by the refactor.

Each brief records a digest tied to the region text and configured standard it showed.
"""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Sequence
from pathlib import Path

from .. import includes, state
from ..context import span_context
from .common import EXIT_CLEAN, Output, Session, numbered_lines, open_session, region_diffs
from .review import guard_failed

Span = tuple[int, int]

BRIEF = """\
You are a C developer reading this code for the first time. You know C and its standard
library well. You do not know this project, its libraries, its file formats or its
protocols, and you cannot ask the author.

Read the current code and its declarations first. List the questions you would have
to ask the author, or look up elsewhere, before you could change this code safely:

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

For A and B, ask questions about the current code. Skip what the C standard defines
and what the code already says plainly.

Then compare the region diff to the current code.

C. Older practices and comment format mismatches introduced by the refactor.
   Look for a newly adopted older construct, idiom or API with a clearer, supported
   replacement. Give the current line, what the diff shows was introduced, a
   replacement, and the evidence that the configured standard or project conventions
   support it. Consider scope, evaluation, types, API contracts and portability.
   For function docs, flag a new comment that departs from a project rule or a
   comparable documented function, or an edit that drops documentation tags
   that still apply. Ask under B if compatibility, equivalence or the expected comment
   format depends on missing project information.
   Flag new uses, including reuse of an existing idiom in a new place. Skip uses
   that were only moved, renamed or reformatted, and choices justified by the
   project's conventions or compatibility requirements.

Review only the supplied material. Leave code changes to the refactoring agent.
Reply in this form, one item per line. Put the questions that cost you the most
time first and write "none" under an empty list.

A. The code could say it
1. <line>: <question> -> <the answer you worked out>
B. Only outside knowledge answers it
1. <line>: <question>
C. Older practices and comment format mismatches introduced by the refactor
1. <current line>: <new use or format mismatch> -> <replacement and project evidence>"""


def region_digest(current: bytes, spans: Sequence[Span]) -> str:
    """Names the text of the regions, so a brief can be matched to the code it showed."""
    digest = hashlib.sha256()
    for start, end in spans:
        digest.update(current[start:end])
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def reader_rounds(session: Session) -> tuple[list[str], str]:
    """The earlier briefs for this review and standard, and the digest of this round."""
    standard = session.configured_standard
    context = f"{BRIEF}\0{standard.name}\0{standard.source}" if standard else BRIEF
    context_digest = hashlib.sha256(context.encode("utf-8", "surrogatepass")).hexdigest()[:16]
    # Briefs from before the practice review lack this prefix and need a fresh round.
    prefix = f"reader:{context_digest}:"
    briefs = [brief for brief in session.snapshot.reader_briefs if brief.startswith(prefix)]
    spans = [span for span in session.spans if span[0] < span[1]]
    return briefs, prefix + region_digest(session.current, spans)


def reader(path: Path, as_json: bool) -> int:
    output = Output(as_json)
    session = open_session(path)
    if session.result.spans is None:
        return guard_failed(output, path, session)
    analysis = session.current_analysis()
    spans = [span for span in session.spans if span[0] < span[1]]
    briefs, digest = reader_rounds(session)
    snapshot = session.snapshot
    if digest not in briefs:
        state.save(
            dataclasses.replace(
                snapshot, path=path, reader_briefs=[*snapshot.reader_briefs, digest]
            )
        )
        round_number = len(briefs) + 1
    else:
        round_number = briefs.index(digest) + 1

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

    lines.extend(_practice_review_lines(session))
    for line in lines:
        output.line(line)
    output.json({"round": round_number, "digest": digest, "brief": "\n".join(lines)})
    return EXIT_CLEAN


def _practice_review_lines(session: Session) -> list[str]:
    lines = ["", "== Configured C standard"]
    standard = session.configured_standard
    if standard is None:
        lines.append(
            "Unknown. File syntax alone cannot establish compatibility with a replacement."
        )
    else:
        lines.append(f"{standard.name} ({standard.source})")
    lines.extend(["", "== Changes from the snapshot (selected regions only)"])
    changed = [(region, diff) for region, diff in region_diffs(session) if diff]
    for region, diff in changed:
        lines.extend(["", f"== Diff of {region.label}", *diff])
    if not changed:
        lines.append("(none)")
    return lines
