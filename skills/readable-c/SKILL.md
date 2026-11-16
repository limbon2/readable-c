---
name: readable-c
description: >-
  Refactor C code (not C++) into readable code without changing what it does, for a whole file or
  for part of one: chosen functions, or a line range inside a function, with every byte outside
  the selection kept as it was. A bundled tool checks the work without a compiler: it proves that
  nothing outside the selection changed, and that mechanical refactors (renames, braces, else after
  return, named conditions, named constants) keep behavior. Use it whenever someone asks to clean
  up, untangle, simplify, rename, de-nest, restructure or make readable any C code, legacy C, a
  long or deeply nested C function, cryptic names or magic numbers, or points at C functions or
  line numbers to tidy, even when they never say "refactor".
metadata:
  version: "0.4.0"
---

# Readable C

Turn C code into code that a reviewer can read, debug and change, without changing what it does. The work happens in regions: the functions or lines the user chose. Everything outside them stays byte for byte as it was, including line endings and legacy encodings.

Readable code is the deliverable, and behavior is the constraint. When the two conflict, keep the behavior and say what you left.

## The tool

`scripts/readable_c.py` in this skill's folder does the checking. Find the absolute path of the folder that holds this `SKILL.md`, and run from the project:

```
uv run <skill-folder>/scripts/readable_c.py <command> <file> [options]
```

`uv run` installs the tool's pinned dependencies (tree-sitter, its C grammar and clang-format) on first use and writes nothing into the project. Without uv, see [references/tool.md](references/tool.md#running-without-uv). Every command takes `--json`. Exit code 0 means clean, 1 means findings or errors, 2 means a usage or environment problem.

| Command | Use it to |
| --- | --- |
| `doctor FILE [--std STANDARD]` | find the configured C standard and the file's conventions |
| `outline FILE [--findings]` | list functions and declarations with line numbers, without reading the whole file |
| `start FILE --function NAME` / `--lines A-B` / `--all` | select regions and snapshot the file; prints the regions, what they depend on and the baseline findings |
| `verify FILE [--diff] [--final]` | prove that nothing outside the regions changed and check that behavior was kept |
| `check FILE` | list the readability findings left in the regions |
| `format FILE` | apply the project's `.clang-format` inside the regions only |
| `reader FILE` | print the current regions, their diff, and the C standard for a fresh subagent |
| `repair FILE [--encoding ENC]` | undo line-ending or encoding damage that an edit tool did outside the regions |
| `restore FILE` | put the original text back into the regions |
| `finish FILE` | forget the snapshot when the work is done; it waits for a `verify --final` of the file as it is |

## Workflow

1. Run `doctor FILE`. Note the target C standard and its source, the line endings, the encoding and the boolean type. Standards can differ by file. Use `--std` with `doctor` and `start` when you can confirm the target for this file across supported builds. When the target is unknown, use the original file's tracked features. See [Dialect](references/hazards.md#dialect).
2. Settle the scope. Use the functions or lines the user named. For a whole file, run `outline` and take one function at a time, or `start --all` when file-scope changes (statics, constants) are wanted. If the request is unclear, ask which functions or lines.
3. Run `start` with that scope and read what it prints: the region text, the declarations and macros it uses (flagged macros hide a `return` or `goto`, or evaluate an argument twice), the frozen names, the conventions and the baseline findings.
4. Before the first edit, read [references/rules.md](references/rules.md) and [references/hazards.md](references/hazards.md). Check the project's coding guidance and nearby declarations for comment conventions. Use Doxygen throughout the documentation in scope where the project or task calls for it.
5. Refactor in small steps, in this order: names, control flow, conditions and expressions, constants, extracting helpers, then comments for whatever is still not obvious. After each step run `verify`. Fix every error it reports before the next step.
6. Run `check`. Fix each rule finding, or keep a one-line reason for the report. A finding marked new came from your edit: fix it.
7. If the project has a `.clang-format`, run `format`, then `verify` again.
8. Do the reader pass (below). It is required.
9. Run `verify --final` and write the report (below) from its output. Then run `finish`. If the file or target C standard changes, run the final check again and update the report. To undo the change, run `restore`, then `finish`.

### The reader pass

Give a fresh reader the current regions, their diff against the snapshot, and the known project C standard. Ask it to find what the new code leaves unexplained and which older practices the refactor introduced.

- **If your harness can start a subagent, you must use one.** Give it this task with the paths filled in: `Run uv run <skill-folder>/scripts/readable_c.py reader <file> and do what it says.` If it cannot run commands, give it the complete `reader FILE` output. Include any explicit documentation format request and its scope, or a short project rule or example with its source. Keep the brief independent of your notes and conversation.
- Only when your harness has no way to start a subagent, read the `reader FILE` output yourself as if you had never seen the code, answer it, and say so in the report.
- The reader answers with three lists:
  - **A, the code could say it.** Each item comes with the answer the reader worked out from the code. Check that answer against the code, then write it down where the reader needed it: a name, a comment, a named constant, a contract comment or a simpler shape. Write down surprising behavior too ("`retries` stops at 255 and never wraps"), even when you keep it. A comment that does not match the code gets rewritten to say what the code does, even when it was there before you.
  - **B, only outside knowledge answers it.** Answer it with a comment only from a source you can read here, such as a header in the project or the library's documentation, and name the source when it is not obvious. Otherwise add it to "Open questions". Never write a guess into a comment to make a question go away. Questions of why and whether a behavior is intended belong here; keep the behavior.
  - **C, practices introduced by the refactor.** Check each finding against the diff and the project's supported C standard and conventions. Fix older constructs and comment format mismatches when the replacement fits the selected regions and preserves behavior and compatibility. Give a reason in the report for each finding you leave.
- After any fix, check the changed lines' indentation, run `format` if the project has a `.clang-format`, then run `verify` and give a fresh reader the updated brief. Finish when the final round returns an empty list A and you have resolved or explained every item in C. Run at most three rounds. If you edit after the last round, report that those edits had no fresh reader.

If `verify` says text outside the regions changed at the byte level only (CRLF became LF, or legacy bytes were re-encoded), your edit tool rewrote the file: run `repair`. If it says real text outside the regions changed, undo that edit; never work around the guard.

## What to change

The rules come from one idea: the reader should not have to work anything out that a name or a shape could tell them. [references/rules.md](references/rules.md) has a before-and-after example and a safe fix for each.

- `cryptic-name`: locals and parameters say what they hold (`remaining_bytes`, not `n2`). Loop counters `i`, `j`, `k` are fine.
- `named-conditions`: each part of an `&&`/`||` condition is a name, a member, or a call with plain arguments. Name the parts, or name the whole condition when a later part is only safe after an earlier one.
- `else-after-return`, `lonely-if`, `duplicate-branches`, `missing-braces`, `misleading-indentation`: flat, braced, honest control flow. Prefer early returns to deep nesting. A branch-by-branch translation (of a `?:`, say) is a first step: when two neighboring branches do the same thing, join their conditions with `||`.
- `nested-ternary`, `unneeded-ternary`, `assignment-in-condition`, `mixed-operators`, `side-effects`: one idea per expression, with the grouping visible.
- Declare and initialize new locals together near first use where the target allows it. In C99 or later, put a loop-only counter and its initializer in the `for` header when that preserves scope and evaluation.
- `magic-number`: name values that do not explain themselves. Use a type-matched `const` for ordinary value reads. Reserve enums for alternatives of one kind, such as states or result codes. See [Constants](references/rules.md#constants) for contexts that require compile-time values.
- `function-size`: a function over 60 lines or nested deeper than 3 levels gets its parts with a responsibility of their own extracted into static helpers. Do not add layers, wrappers or abstractions with a single use.
- `function-contract`: every function in a region that is longer than 10 lines starts with a short comment: what it does, what it returns (and on failure), who frees what it allocates or takes.
- `needs-comment`: C that made sense to its author still stops a reader at allocations (who owns the block, why that size), bit operations (what the bits mean), casts that read memory as another type, raw `memcpy`/`memmove` offsets, bounds and offsets added up from literals (`2 * n + 1 < rem`, `pos += 36`: which fields, which sizes), and calls into third-party or system APIs (what they return on failure, who owns what they return). Add a short comment at each such place, or a name that makes it unnecessary. Write only what the code, its headers or the library's documentation show; when you cannot establish a meaning, do not guess: list it under "Open questions" in the report. Comments explain why and what things mean, never what the code does step by step; delete comments that repeat the code and commented-out code. When you rename something, update the comments that use the old name: `verify` lists the ones you missed.
- `hand-written-library`: a loop that only measures a string or fills or copies an array is a call to `strnlen`, `strlen`, `strcspn`, `memset` or `memcpy`; `check` suggests one only when it is exact.
- `indent-style` and the conventions: match both the file's indentation characters and the nesting level of nearby statements.
- Preserve project macros and types where their semantics or an interface require them. Follow the configured standard and project guidance for new internal code. Expanding a project macro by hand needs a reason in the report.

Advice findings (`magic-number`, `side-effects`, `hand-written-library`, `many-parameters`, `goto`, `param-reassign`, `stacked-casts`, `multiple-declarators`, `commented-out-code`, `boolean-literal`) are judgment calls; act on them when the result reads better. Every other finding is a rule: fix it, or give its reason in the report.

In a file that is not UTF-8, new comments with non-ASCII text need converting: `verify` reports them and `repair --encoding <codec>` converts the new lines.

## Keep the behavior

The tool sees a lot, but not types, macros from unseen headers, or every `#if` configuration. [references/hazards.md](references/hazards.md) explains each of these:

- A guard such as `p != NULL && p->len > 0` must stay one expression or one named value. Separate variables would evaluate `p->len` when `p` is NULL.
- A named value gets the exact type of its expression. Watch integer promotions, signedness and width.
- Never duplicate, drop or reorder a side effect, and never move a call to a later or conditional position.
- `x == TRUE` and `c ? 1 : 0` only fold when the value is known to be 0 or 1.
- An array parameter is a pointer inside a helper: `sizeof` changes.
- A macro that hides `return` or `goto` cannot move into a helper. A macro that evaluates its argument twice must not get a new argument with side effects.
- Code under `#if` must stay right for every configuration, not only the one you can see.
- Keep `static`, `volatile`, `errno` handling, switch fallthrough, and what `break` and `continue` leave.

## Region discipline

- Change only the regions. Extracted helpers go in the helper slot, the empty region right before the function that `start` reports for a line range, or inside a function region before the function.
- Keep frozen names: names that code outside the regions uses keep their name, type and declaration. `verify` checks them.
- Add no `#include` and no `#if`, `#undef` or `#pragma`. A new `#define` needs a reason in the report.
- Use C features supported by the configured standard and the headers and declarations already available to the region. If the standard is unknown, `verify` uses the original file's tracked features as a conservative fallback.
- Changes outside the regions (renaming a global, a header, a prototype) go into the report as proposals.

The details are in [references/regions.md](references/regions.md).

## How `verify` decides

For each function in a region `verify` reports a tier:

- Tier 0: the tokens are the same; only comments and layout changed.
- Tier 1: the normalized syntax trees are the same, which proves the behavior is the same. These reach tier 1:
  - renames, braces, else after return, `else { if }`;
  - neighboring branches with the same body joined with `||`, and `!` pushed through `&&` and `||`;
  - nested `if`s merged with `&&`, and a loop body flattened with `if (...) continue;`;
  - named conditions and named enum constants;
  - `x != 0`, `c ? 1 : 0`, `x += 1` and `x = x + 1`;
  - an assignment moved out of an `if` condition;
  - a `?:` written as `if`/`else` (with the tests in their original order);
  - a `for` loop written as a `while` loop.
- Tier 2: the code was restructured (extracted helpers, reordered tests, removed gotos). `verify` lists what changed in calls, literals, writes and jumps. Explain each item in the report, or undo the step.

Errors always block: new syntax errors, dialect violations, names that resolve nowhere, a new local that hides an outer name, a changed frozen name. When a function only reaches tier 2, prefer smaller steps that reach tier 1 one at a time. A rewrite that reads better but reorders tests (`if (t > 5000) ... if (t > 1000) ...` in place of `t > 1000 ? (t > 5000 ? 2 : 1) : 0`) is tier 2: explain why the order does not matter.

## When the tool cannot run

If neither uv nor Python 3.10 to 3.14 is available, follow the rules and hazards by hand, keep the edit inside the regions, and say plainly in the report that no checks ran. Never describe an unchecked change as verified. Use the fallback brief in [references/reader.md](references/reader.md) for the reader pass.

## Report

End with this report, filled in from `verify --final`. Say "not run" with a reason for anything that did not run; never claim a check that did not pass.

```
## Refactor of <file>
Regions: <functions or lines>
Changes:
- <rule or reason>: <what changed, where>
Verification:
- C standard: <standard and source | unknown, original file features used>
- Guard (nothing outside the regions changed): passed | failed
- Errors from verify: <none | list>
- Equivalence: <function>: tier <0|1|2> (...)
- Review items explained: <item>: <why it is right>
- Formatting: applied with <.clang-format> | not run: <reason>
- Compilation and tests: not run (the tool works without a build)
Comments added: <line>: <what it explains> | none
Reader pass: <subagent | by myself: the harness has no subagents>, <N> rounds; list A in the last round: <empty | N left, why>
- A <line>: <reader's question> -> <what changed>
- B <line>: <reader's question> -> <comment from <source> | open question>
- C <line>: <new practice or comment format finding> -> <what changed | reason for keeping it>
Findings left: <rule at line>: <reason> | none
Open questions: <meanings you could not establish, for the user to answer> | none
Proposed changes outside the regions: <list> | none
```
