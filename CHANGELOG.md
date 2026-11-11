# Changelog

All notable changes to readable-c are recorded here. The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- The `needs-comment` advice rule points at code a reader cannot follow alone when no comment explains it: allocations with a computed size or an owner outside the function, `realloc`, raw memory copies with computed offsets, bit operations with literal masks and shifts, reads through pointer casts, and calls into third-party or system APIs.
- Guidance for explanatory comments: what to say for each kind of place, comments taken only from the code, headers and documentation, and open questions in the report for meanings that cannot be established. The report template has "Comments added" and "Open questions".
- `verify` reports new lines with UTF-8 text in a file that is not UTF-8, and `repair --encoding` converts them while the guard passes.

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
