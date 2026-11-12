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
  version: "0.2.0"
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
| `doctor FILE` | learn the file's conventions and what the tool can do here |
| `outline FILE [--findings]` | list functions and declarations with line numbers, without reading the whole file |
| `start FILE --function NAME` / `--lines A-B` / `--all` | select regions and snapshot the file; prints the regions, what they depend on and the baseline findings |
| `verify FILE [--diff] [--final]` | prove that nothing outside the regions changed and check that behavior was kept |
| `check FILE` | list the readability findings left in the regions |
| `format FILE` | apply the project's `.clang-format` inside the regions only |
| `repair FILE [--encoding ENC]` | undo line-ending or encoding damage that an edit tool did outside the regions |
| `restore FILE` | put the original text back into the regions |
| `finish FILE` | forget the snapshot when the work is done |

## Workflow

1. Run `doctor FILE` once per project. Note the line endings, the encoding, the dialect (C89 or C99) and the boolean type: new code must match them.
2. Settle the scope. Use the functions or lines the user named. For a whole file, run `outline` and take one function at a time, or `start --all` when file-scope changes (statics, constants) are wanted. If the request is unclear, ask which functions or lines.
3. Run `start` with that scope and read what it prints: the region text, the declarations and macros it uses (flagged macros hide a `return` or `goto`, or evaluate an argument twice), the frozen names, the conventions and the baseline findings.
4. Before the first edit, read [references/rules.md](references/rules.md) and [references/hazards.md](references/hazards.md).
5. Refactor in small steps, in this order: names, control flow, conditions and expressions, constants, extracting helpers, then comments for whatever is still not obvious. After each step run `verify`. Fix every error it reports before the next step.
6. Run `check`. Fix each rule finding, or keep a one-line reason for the report. A finding marked new came from your edit: fix it.
7. If the project has a `.clang-format`, run `format`, then `verify` again.
8. Run `verify --final`, write the report (below), and run `finish`. If the user wants the change undone, run `restore` instead.

If `verify` says text outside the regions changed at the byte level only (CRLF became LF, or legacy bytes were re-encoded), your edit tool rewrote the file: run `repair`. If it says real text outside the regions changed, undo that edit; never work around the guard.

## What to change

The rules come from one idea: the reader should not have to work anything out that a name or a shape could tell them. [references/rules.md](references/rules.md) has a before-and-after example and a safe fix for each.

- `cryptic-name`: locals and parameters say what they hold (`remaining_bytes`, not `n2`). Loop counters `i`, `j`, `k` are fine.
- `named-conditions`: each part of an `&&`/`||` condition is a name, a member, or a call with plain arguments. Name the parts, or name the whole condition when a later part is only safe after an earlier one.
- `else-after-return`, `lonely-if`, `missing-braces`, `misleading-indentation`: flat, braced, honest control flow. Prefer early returns to deep nesting.
- `nested-ternary`, `unneeded-ternary`, `assignment-in-condition`, `mixed-operators`, `side-effects`: one idea per expression, with the grouping visible.
- `magic-number`: name values that do not explain themselves.
- `function-size`: extract parts with a responsibility of their own into static helpers. Do not add layers, wrappers or abstractions with a single use.
- `needs-comment`: C that made sense to its author still stops a reader at allocations (who owns the block, why that size), bit operations (what the bits mean), casts that read memory as another type, raw `memcpy`/`memmove` offsets, and calls into third-party or system APIs (what they return on failure, who owns what they return). Add a short comment at each such place. Write only what the code, its headers or the library's documentation show; when you cannot establish a meaning, do not guess: list it under "Open questions" in the report. Comments explain why and what things mean, never what the code does step by step; delete comments that repeat the code and commented-out code. When you rename something, update the comments that use the old name: `verify` lists the ones you missed.
- `indent-style` and the conventions: new code looks like the code around it.
- Keep using the project's own macros and idioms, such as an error-handling macro like `CHECK`, logging macros and asserts. They are the code base's conventions, so expanding one by hand needs a reason in the report.

Advice findings (`needs-comment`, `magic-number`, `goto`, `param-reassign`, `stacked-casts`, `multiple-declarators`, `commented-out-code`, `boolean-literal`, `function-size`) are judgment calls; act on them when the result reads better.

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
- Add no `#include` and no `#if`, `#undef` or `#pragma`. A new `#define` needs a reason in the report; prefer `enum { NAME = 5 };` inside the function.
- Use only C the file already uses. `verify` rejects `//` comments, declarations after statements, `bool` and other C99 forms in a file that has none.
- Changes outside the regions (renaming a global, a header, a prototype) go into the report as proposals.

The details are in [references/regions.md](references/regions.md).

## How `verify` decides

For each function in a region `verify` reports a tier:

- Tier 0: the tokens are the same; only comments and layout changed.
- Tier 1: the normalized syntax trees are the same, which proves the behavior is the same. These reach tier 1:
  - renames, braces, else after return, `else { if }`;
  - nested `if`s merged with `&&`, and a loop body flattened with `if (...) continue;`;
  - named conditions and named enum constants;
  - `x != 0`, `c ? 1 : 0`, `x += 1` and `x = x + 1`;
  - an assignment moved out of an `if` condition;
  - a `?:` written as `if`/`else` (with the tests in their original order);
  - a `for` loop written as a `while` loop.
- Tier 2: the code was restructured (extracted helpers, reordered tests, removed gotos). `verify` lists what changed in calls, literals, writes and jumps. Explain each item in the report, or undo the step.

Errors always block: new syntax errors, constructs the file does not use, names that resolve nowhere, a new local that hides an outer name, a changed frozen name. When a function only reaches tier 2, prefer smaller steps that reach tier 1 one at a time. A rewrite that reads better but reorders tests (`if (t > 5000) ... if (t > 1000) ...` in place of `t > 1000 ? (t > 5000 ? 2 : 1) : 0`) is tier 2: explain why the order does not matter.

## When the tool cannot run

If neither uv nor Python 3.10 to 3.14 is available, follow the rules and hazards by hand, keep the edit inside the regions, and say plainly in the report that no checks ran. Never describe an unchecked change as verified.

## Report

End with this report, filled in from `verify --final`. Say "not run" with a reason for anything that did not run; never claim a check that did not pass.

```
## Refactor of <file>
Regions: <functions or lines>
Changes:
- <rule or reason>: <what changed, where>
Verification:
- Guard (nothing outside the regions changed): passed | failed
- Errors from verify: <none | list>
- Equivalence: <function>: tier <0|1|2> (...)
- Review items explained: <item>: <why it is right>
- Formatting: applied with <.clang-format> | not run: <reason>
- Compilation and tests: not run (the tool works without a build)
Comments added: <line>: <what it explains> | none
Findings left: <rule at line>: <reason> | none
Open questions: <meanings you could not establish, for the user to answer> | none
Proposed changes outside the regions: <list> | none
```
