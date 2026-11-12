# Changelog

All notable changes to readable-c are recorded here. The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.4.0] - 2026-11-12

### Added

- The reader pass: once the code is done, a fresh subagent that has never seen it reads it and lists the questions it would have to ask the author, in two lists: what the code could say, with the answer the reader worked out, and what only outside knowledge answers, including why the code does what it does. The agent writes every answer of the first kind down as a name, a comment or a named constant, and repeats the pass with a new subagent until a reader of the final code has none, up to three rounds. `verify --final` reports an error until a round has seen the final code or three rounds have run. A question of the second kind gets a comment from a source the agent can read, or goes to the report as an open question. The pass is required, and the skill must use a subagent when the harness can start one. The new `reader` command prints the brief for it: the current region code and the declarations it uses, never the original or the agent's notes. `references/reader.md` describes the pass and holds the brief for when the tool cannot run.
- `needs-comment` reports bounds and offsets built from literal arithmetic, such as `2 * n + 1 < rem`, `buf[pos + 4]`, `pos += 36` and `pos = pos + 4 + n * 2 + 2`, when no comment says which fields add up to the number.
- The `function-contract` rule asks for a comment above every function in a region that is longer than 10 lines: what it does, what it returns and on failure, who frees what.
- The `hand-written-library` advice points at loops that only measure a string, or fill or copy an array, and suggests `strlen`, `strnlen`, `strcspn`, their `wcs` forms, `memset` or `memcpy`. It suggests a call only when the call does exactly what the loop does.

### Changed

- `needs-comment` is a rule instead of advice, and so are the length and nesting parts of `function-size`. A model that treated them as optional left allocations, bit tricks, offsets and long functions unexplained. More than 5 parameters stays advice, under the new name `many-parameters`, because a region task cannot change a signature that other code calls.
- `finish` refuses while the file holds changes that no `verify --final` has checked. In a test run, a model edited comments after its final check and reported "0 rule findings" for a file that had 3. `finish --force` skips the check.
- `start` and `reader` also show the types that the shown declarations use, such as `struct item` for `static struct item items[MAX_ITEMS];`.

### Fixed

- `verify` reported `const char *p; p = text;` as an assignment to a const variable, an error, although only the characters are const and the pointer may change. It fired on unchanged legacy code and told agents to fix code that compiles. Only variables that are const themselves count now (`const int n`, `char *const p`), taking the address of a const no longer counts as a write, and an error the original already had is not reported as new.

## [0.3.0] - 2026-11-12

### Added

- The `duplicate-branches` rule reports an `else if` that runs the same code as the branch before it.
- Tier 1 proves joining such neighboring branches with `||`, joining consecutive `if`s whose identical bodies always leave (`if (!a) return -1; if (!b) return -1;`), and pushing `!` through `&&` and `||`. A named condition for the joined test is proven too.
- The `nested-ternary` guidance treats a branch-by-branch translation as a first step and shows how to join and name the result.

### Changed

- Before, `verify` proved a literal translation of a nested `?:` that kept two identical branches, but treated the cleaner merged form as restructuring. A model that followed the skill closely kept the duplicate. Both forms are tier 1 now, and `check` reports the duplicate.

## [0.2.0] - 2026-11-12

### Added

- The `needs-comment` advice rule points at code a reader cannot follow alone when no comment explains it: allocations with a computed size or an owner outside the function, `realloc`, raw memory copies with computed offsets, bit operations with literal masks and shifts, reads through pointer casts, and calls into third-party or system APIs. Standard library functions never count as third-party calls, even when the file gets their headers through another library's headers.
- Guidance for explanatory comments: what to say for each kind of place, comments taken only from the code, headers and documentation, and open questions in the report for meanings that cannot be established. The report template has "Comments added" and "Open questions".
- `verify` reports old comments that still mention a local or parameter the function no longer declares, which is what a rename leaves behind when it misses a comment.
- `verify` reports new lines with UTF-8 text in a file that is not UTF-8, and `repair --encoding` converts them while the guard passes.

### Fixed

- `indent-style` no longer reports continuation lines of a parameter list or a call that are aligned with spaces in a file indented with tabs. It treated that common style as wrong and pushed agents to re-indent such lines.

### Security

- Snapshots live in a per-user folder created readable by its owner only. The tool refuses a state folder that is a link or that another user owns, writes snapshots without following a link planted at their names, and refuses a snapshot that belongs to another file. Before, on a shared temp folder such as Linux's /tmp, another local user could make `start` overwrite a file through a planted link, or make `restore --whole-file` write a planted snapshot into a source file.

## [0.1.0] - 2026-11-11

### Added

- The `readable-c` skill: a workflow for refactoring hand-written C into readable code, one region of a file at a time, with the rules, behavior hazards and region model as references.
- The `readable_c.py` tool with the commands `doctor`, `outline`, `start`, `check`, `verify`, `format`, `repair`, `restore` and `finish`.
- Regions by function name, line range or whole file. A line range inside a function snaps to whole statements and gets a helper slot for extracted functions.
- A guard that proves nothing outside the regions changed, in bytes and in meaning, and keeps CRLF line endings and legacy encodings such as CP1251. `repair` undoes line-ending and encoding damage from edit tools.
- Readability rules, including a C port of Mannie's `named-conditions` rule, with baseline findings recorded at `start`.
- Build-free verification: dialect, unresolved names, shadowing and frozen names as errors, and three equivalence tiers per function (tokens, normalized syntax tree, inventory of calls, literals, writes and jumps). Tier 1 proves renames, braces, else after return, merged `if`s, loops flattened with `continue`, named conditions and constants, `?:` written as `if`/`else`, `for` written as `while`, and compound assignments.
- Evals: three refactoring tasks on legacy C fixtures and a grader that rechecks an agent's result against the original file.
- Region-only formatting with the project's `.clang-format`.
- A Claude Code plugin and marketplace, Codex metadata, and installation through the `skills` CLI.
