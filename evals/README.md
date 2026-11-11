# Evals

End-to-end checks of the skill: an agent gets a realistic request and the skill, and a grader checks what it did to the file.

| Eval | Request | What it exercises |
| --- | --- | --- |
| 1 `whole-function` | make `report` in `inventory.c` readable | nesting, a nested `?:`, an operator-precedence trap |
| 2 `line-range` | clean up lines 47-74 of `netio.c` | a range inside a long function, the helper slot, a C89 file |
| 3 `two-functions-crlf-cp1251` | untangle `read_weight` and `is_stable` in `legacy.c` | CRLF line endings, CP1251 comments, a K&R function, a macro that hides a `goto`, `BOOL` |

`evals.json` holds the prompts, the region each request means, and the assertions. The inputs in `files/` keep their exact bytes (see `.gitattributes`).

## Running an eval

1. Copy the input into a workspace: `evals/workspaces/eval-<id>/` (ignored by git).
2. Give a fresh agent this prompt, with the paths filled in:

   ```text
   You are a coding agent working in a C project located at <workspace> (treat that folder as
   the project root; work only inside it and do not commit anything).

   A skill named `readable-c` is installed for you at <skill-folder>. Before doing anything else,
   read <skill-folder>/SKILL.md and follow it; its tool runs as
   `uv run <skill-folder>/scripts/readable_c.py <command> <file>`.

   The user's request: "<prompt from evals.json>"

   When you are done, reply with the final report that the skill asks for.
   ```

3. Grade the result against the original, independently of the agent's own snapshot:

   ```bash
   uv run python evals/grade.py <id> evals/workspaces/eval-<id>/<file>
   ```

   The grader prints the guard result, the errors, the tier of each function and the review items. Then read the agent's report against the assertions in `evals.json`: every review item and every finding left needs an explanation that holds up.

## Results of 0.1.0 (2026-11-11)

All three runs passed the guard with no errors and explained every review item.

| Eval | Tiers | Notes |
| --- | --- | --- |
| 1 | `report`: 2 | The refactor reordered the level tests, so it stays tier 2; the same refactor with the original test order now proves at tier 1. The agent folded `1 == 1`, which keeps the meaning. |
| 2 | `handle_packet`, two new helpers: 2 | Extracted `read_le16` and `consume_bytes` into the slot and split a variable that did two jobs; every inventory change explained correctly. |
| 3 | `is_stable`: 1, `read_weight`: 2 | CRLF and CP1251 bytes kept exactly. The agent expanded the `CHECK` macro by hand; the skill now asks agents to keep project macros. |
