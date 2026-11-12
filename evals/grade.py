"""Checks an eval run independently of the agent's own snapshot.

    uv run python evals/grade.py <eval id> <edited file>

It selects the same regions in the eval's original file, then runs the guard and
the verify checks on the edited file and prints what passed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "readable-c" / "scripts"))

from readablec import guard, includes, regions  # noqa: E402  the path is set above
from readablec.analysis import Analysis  # noqa: E402
from readablec.issues import ERROR, REVIEW  # noqa: E402
from readablec.verify import compare, names  # noqa: E402


def main() -> int:
    eval_id, edited_path = int(sys.argv[1]), Path(sys.argv[2])
    specs = json.loads((ROOT / "evals" / "evals.json").read_text(encoding="utf-8"))["evals"]
    spec = next(item for item in specs if item["id"] == eval_id)
    original_path = ROOT / spec["files"][0]
    original = original_path.read_bytes()
    current = edited_path.read_bytes()
    old = Analysis(original, original_path)
    selection = spec["selection"]
    line_ranges = [
        tuple(int(part) for part in text.split("-")) for text in selection.get("lines", [])
    ]
    selected = regions.resolve(
        old.source,
        old.root,
        old.functions,
        function_names=selection.get("function", []),
        line_ranges=line_ranges,
    ).regions
    print(f"eval {eval_id} ({spec['name']}): regions {[region.label for region in selected]}")
    result = guard.check(original, selected, current)
    print(f"guard: {'passed' if result.ok else 'FAILED'}")
    for issue in result.issues:
        print(f"  {issue.severity}: {issue.message}")
    if result.spans is None:
        return 1
    new = Analysis(current, edited_path)
    old_spans = [(region.start, region.end) for region in selected]
    known = includes.known_names(edited_path, new.tokens)
    frozen = names.frozen_entries(old, selected)
    issues = [
        *names.parse_issues(old, selected, new, result.spans),
        *names.dialect_issues(old, new, result.spans),
        *names.unresolved_names(old, new, result.spans, known),
        *names.scope_issues(old, old_spans, new, result.spans),
        *names.frozen_issues(new, result.spans, frozen),
        *names.stale_comment_issues(old, old_spans, new, result.spans),
    ]
    tiers, review = compare.compare(old, old_spans, new, result.spans)
    errors = [issue for issue in issues if issue.severity == ERROR]
    print(f"errors: {len(errors)}")
    for issue in errors:
        print(f"  line {issue.line}: {issue.message}")
    for item in tiers:
        print(f"tier: {item.name}: {item.tier} ({item.summary})")
    reviews = [issue for issue in issues + review if issue.severity == REVIEW]
    print(f"review items: {len(reviews)}")
    for issue in reviews:
        print(f"  {issue.message}")
    return 1 if errors or not result.ok else 0


if __name__ == "__main__":
    sys.exit(main())
