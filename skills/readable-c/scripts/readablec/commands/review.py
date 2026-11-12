"""`check` and `verify`: the findings that remain, and proof that behavior was kept."""

from __future__ import annotations

import dataclasses
import difflib
from collections.abc import Sequence
from pathlib import Path

from .. import guard, includes, state
from ..findings import RULE, Finding, mark_new
from ..issues import ERROR, REVIEW, Issue
from ..rules import run_rules
from ..verify import compare, names
from .common import (
    EXIT_CLEAN,
    EXIT_FINDINGS,
    Output,
    Session,
    display_path,
    open_session,
    print_finding,
    print_issue,
)


def guard_failed(output: Output, path: Path, session: Session) -> int:
    output.section("Guard: failed")
    for issue in session.result.issues:
        print_issue(output, path, issue)
    output.json({"guard": "failed", "issues": [issue.to_json() for issue in session.result.issues]})
    return EXIT_FINDINGS


def _current_findings(
    session: Session,
) -> tuple[list[tuple[Finding, bool]], list[tuple[int, int, str]]]:
    analysis = session.current_analysis()
    frozen_names = {str(entry["name"]) for entry in session.snapshot.frozen}
    report = run_rules(analysis, session.spans, frozen_names)
    baseline = [Finding.from_json(item) for item in session.snapshot.baseline]
    return mark_new(report.findings, baseline), report.unchecked


def check(path: Path, as_json: bool) -> int:
    output = Output(as_json)
    session = open_session(path)
    if session.result.spans is None:
        return guard_failed(output, path, session)
    findings, unchecked = _current_findings(session)
    rules = [(finding, is_new) for finding, is_new in findings if finding.severity == RULE]
    advice = [(finding, is_new) for finding, is_new in findings if finding.severity != RULE]
    output.section(f"Rule findings: {len(rules)} ({sum(1 for _, is_new in rules if is_new)} new)")
    for finding, is_new in sorted(rules, key=lambda pair: not pair[1]):
        print_finding(output, path, finding, is_new)
    output.section(f"Advice: {len(advice)}")
    for finding, is_new in advice:
        print_finding(output, path, finding, is_new)
    for first, last, reason in unchecked:
        output.line(f"{display_path(path)}:{first}: not checked (lines {first}-{last}): {reason}")
    if rules:
        output.line()
        output.line(
            "Fix each rule finding, or give its reason in the report. New findings came from the "
            "edit: fix those."
        )
    output.json(
        {
            "rule_findings": [dict(finding.to_json(), new=is_new) for finding, is_new in rules],
            "advice": [dict(finding.to_json(), new=is_new) for finding, is_new in advice],
            "unchecked": unchecked,
        }
    )
    return EXIT_FINDINGS if rules else EXIT_CLEAN


def verify(
    path: Path, include_dirs: Sequence[Path], show_diff: bool, final: bool, as_json: bool
) -> int:
    output = Output(as_json)
    session = open_session(path)
    if session.result.spans is None:
        return guard_failed(output, path, session)
    old = session.original_analysis()
    new = session.current_analysis()
    old_spans = [(region.start, region.end) for region in session.regions]
    new_spans = session.spans
    known = includes.known_names(path, new.tokens, include_dirs)
    issues: list[Issue] = list(session.result.issues)
    issues.extend(
        guard.foreign_text_issues(
            session.snapshot.original, session.regions, session.current, new_spans
        )
    )
    issues.extend(names.parse_issues(old, session.regions, new, new_spans))
    issues.extend(names.dialect_issues(old, new, new_spans))
    issues.extend(names.unresolved_names(old, new, new_spans, known))
    issues.extend(names.scope_issues(old, old_spans, new, new_spans))
    issues.extend(names.frozen_issues(new, new_spans, session.snapshot.frozen))
    issues.extend(names.stale_comment_issues(old, old_spans, new, new_spans))
    results, equivalence_issues = compare.compare(old, old_spans, new, new_spans)
    issues.extend(equivalence_issues)
    reader_issue = reader_gate_issue(session) if final else None
    if reader_issue is not None:
        issues.append(reader_issue)
    findings, unchecked = _current_findings(session)
    errors = [issue for issue in issues if issue.severity == ERROR]
    review_items = [issue for issue in issues if issue.severity == REVIEW]

    output.section("Guard: passed (nothing outside the regions changed)")
    output.section(f"Errors: {len(errors)}")
    for issue in errors:
        print_issue(output, path, issue)
    output.section("Equivalence by function")
    for result in results:
        tier = "-" if result.tier is None else f"tier {result.tier}"
        where = f" (line {result.line})" if result.line else ""
        output.line(f"- {result.name}: {tier}: {result.summary}{where}")
    output.section(f"Review items: {len(review_items)} (explain each in the report)")
    for issue in review_items:
        print_issue(output, path, issue)
    rule_count = sum(1 for finding, _ in findings if finding.severity == RULE)
    new_rule_count = sum(1 for finding, is_new in findings if finding.severity == RULE and is_new)
    advice_count = len(findings) - rule_count
    output.section("Findings")
    output.line(
        f"{rule_count} rule findings ({new_rule_count} new), {advice_count} advice "
        f"(baseline had {len(session.snapshot.baseline)} findings). Run `check` for details."
    )
    for first, last, reason in unchecked:
        output.line(f"not checked: lines {first}-{last}: {reason}")
    if show_diff:
        _print_diff(output, session)
    if final:
        state.save(
            dataclasses.replace(
                session.snapshot, path=path, final_digest=state.file_digest(session.current)
            )
        )
        _print_report_data(
            output,
            path,
            session,
            results=results,
            errors=errors,
            review_items=review_items,
            rule_count=rule_count,
        )
    output.json(
        {
            "guard": "passed",
            "errors": [issue.to_json() for issue in errors],
            "review": [issue.to_json() for issue in review_items],
            "functions": [result.to_json() for result in results],
            "rule_findings": rule_count,
            "new_rule_findings": new_rule_count,
            "advice": advice_count,
            "unchecked": unchecked,
            "reader": reader_status(session),
        }
    )
    return EXIT_FINDINGS if errors else EXIT_CLEAN


def _print_diff(output: Output, session: Session) -> None:
    old = session.original_analysis()
    encoding = old.conventions.encoding.name
    for region, (start, end) in zip(session.regions, session.spans, strict=True):
        before = session.snapshot.original[region.start : region.end].decode(
            encoding, "backslashreplace"
        )
        after = session.current[start:end].decode(encoding, "backslashreplace")
        output.section(f"Diff of {region.label}")
        first_line = (
            old.source.line_of(region.start) if region.start < len(session.snapshot.original) else 1
        )
        diff = difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"original (from line {first_line})",
            tofile="current",
            lineterm="",
        )
        for line in diff:
            output.line(line)


def _print_report_data(
    output: Output,
    path: Path,
    session: Session,
    *,
    results: list[compare.FunctionResult],
    errors: list[Issue],
    review_items: list[Issue],
    rule_count: int,
) -> None:
    output.section("Data for the report")
    output.line(f"File: {display_path(path)}")
    output.line("Regions: " + "; ".join(region.label for region in session.regions))
    output.line(f"Guard: passed. Errors: {len(errors)}. Review items: {len(review_items)}.")
    proven = [result.name for result in results if result.tier in (0, 1)]
    unproven = [result.name for result in results if result.tier not in (0, 1)]
    output.line(f"Proven equivalent (tier 0 or 1): {', '.join(proven) or 'none'}")
    output.line(f"Not proven (tier 2, explain): {', '.join(unproven) or 'none'}")
    output.line(f"Rule findings left: {rule_count} (give a reason for each)")
    output.line(f"Reader pass: {reader_status(session)}")
    output.line("Not run: compilation and tests (this tool works without a build).")


MAX_READER_ROUNDS = 3


def _current_digest(session: Session) -> str:
    from .reader import region_digest  # noqa: PLC0415  reader imports this module

    spans = [span for span in session.spans if span[0] < span[1]]
    return region_digest(session.current, spans)


def reader_status(session: Session) -> str:
    """Whether a reader brief showed the code as it is now, and in which round."""
    briefs = session.snapshot.reader_briefs
    digest = _current_digest(session)
    if digest in briefs:
        return f"round {briefs.index(digest) + 1} showed the current code ({len(briefs)} briefs in all)"
    if len(briefs) >= MAX_READER_ROUNDS:
        return (
            f"the code changed after the last of {len(briefs)} rounds: say in the report that no "
            "round checked the last changes"
        )
    if briefs:
        return (
            f"the code changed after the last of {len(briefs)} briefs: run `reader` again and give it "
            "to a fresh subagent"
        )
    return "not run: run `reader` and give it to a fresh subagent (required, see SKILL.md)"


def reader_gate_issue(session: Session) -> Issue | None:
    """The final check needs a reader round that saw the final code, unless three rounds ran."""
    briefs = session.snapshot.reader_briefs
    if _current_digest(session) in briefs or len(briefs) >= MAX_READER_ROUNDS:
        return None
    if briefs:
        message = (
            f"The code changed after the last reader round ({len(briefs)} so far). Run `reader` "
            "again and give it to a new subagent: the pass is done when a round that sees the "
            f"final code returns an empty list A, or after {MAX_READER_ROUNDS} rounds."
        )
    else:
        message = (
            "The reader pass has not run. Run `reader` and give it to a fresh subagent, as "
            "SKILL.md describes; the final check needs it."
        )
    return Issue("reader", ERROR, message, None)
