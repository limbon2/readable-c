# readable-c

An agent skill that refactors hand-written C (not C++) into readable code without changing what it does. It works on a whole file, or on part of one, such as some functions or a line range inside a long function, and keeps every byte outside that part as it was. A bundled tool checks the result without a compiler, so it works on projects that cannot be built where the agent runs.

The skill gives the agent:

- a workflow: select regions, edit in small steps, verify after each step, report;
- readability rules for C, each with a safe fix ([rules](skills/readable-c/references/rules.md));
- the C pitfalls that change behavior during a refactor ([hazards](skills/readable-c/references/hazards.md));
- `readable_c.py`, which proves that nothing outside the regions changed (CRLF line endings and CP1251 comments included), proves that mechanical refactors keep behavior, and lists what restructuring changed so the agent can explain it.

## Requirements

- [uv](https://docs.astral.sh/uv/), or Python 3.10 to 3.14 with pip. uv installs the tool's pinned dependencies (tree-sitter, tree-sitter-c, clang-format) on first use, which needs internet access once. See [running without uv](skills/readable-c/references/tool.md#running-without-uv) for pip and offline installs.
- An agent that reads skills: Claude Code, or Codex.
- No compiler. A `.clang-format` in the project is used when present.

## Installation

Put this repository where the other machine can reach it: push it to your Git host, or copy the folder. Then pick one way.

With the [skills CLI](https://github.com/vercel-labs/skills), for Claude Code and Codex, for every project:

```bash
npx skills add <owner>/readable-c --skill readable-c --agent claude-code codex --global --copy
```

`<owner>/readable-c` can also be a path to a local copy. `--copy` copies the files; without it the CLI creates symlinks, which on Windows need extra rights. Leave out `--global` to install into the current project only. The skill answers to `/readable-c`.

As a Claude Code plugin:

```text
/plugin marketplace add <owner>/readable-c
/plugin install readable-c@readable-c
```

The plugin's skill answers to `/readable-c:readable-c`.

By hand: copy `skills/readable-c/` to `~/.claude/skills/readable-c/` (Claude Code) or `~/.agents/skills/readable-c/` (Codex), or into a project's `.claude/skills/` or `.agents/skills/`.

Check the installation from any C project:

```bash
uv run ~/.claude/skills/readable-c/scripts/readable_c.py doctor path/to/file.c
```

## Usage

Ask in plain words, and name the part of the file:

```text
Make parse_record in src/records.c readable. Don't touch anything else in the file.
Lines 140-195 of net/packet.c, inside handle_packet, are a mess. Clean up just that part.
Untangle load_config and apply_config in config.c.
```

The agent selects the regions with `start`, edits in small steps, runs `verify` after each step and `check` for the findings left, and ends with a report: what changed, what was proven, what it could not prove and why, and the changes it proposes outside the regions.

For each function, `verify` reports a tier:

| Tier | Meaning |
| --- | --- |
| 0 | Same tokens: only comments and layout changed. |
| 1 | Same normalized syntax tree: renames, braces, else after return, named conditions, named constants and similar refactors, proven to keep behavior. |
| 2 | Restructured: the tool lists the calls, literals, writes and jumps that changed, and the agent explains them. |

## Where the rules come from

The rules and the verification discipline come from the Mannie project's `AGENTS.md` and its lint setup, rewritten for C and for code the agent did not write:

| Mannie | readable-c |
| --- | --- |
| "Readable source code" in `AGENTS.md` | [rules.md](skills/readable-c/references/rules.md) |
| The formatter is the authority (`task fmt`) | `format`, with the project's `.clang-format`, inside the regions only |
| ESLint `no-nested-ternary`, `no-else-return`, `no-lonely-if`, `curly`, `no-unneeded-ternary`, `no-param-reassign` | `nested-ternary`, `else-after-return`, `lonely-if`, `missing-braces`, `unneeded-ternary`, `param-reassign` |
| The custom ESLint rule `mannie/named-conditions` and its tests | `named-conditions`, with the same test cases in C |
| Clippy's size lints | `function-size` |
| "Comments explain what the code cannot" | `needs-comment`, which points at allocations, bit operations, memory casts and library calls without a comment, and the guidance for comments that are true |
| Narrow suppressions that state a reason | no markers in the user's code; every finding left gets a reason in the report |
| "Improve the code you touch, do not reformat unrelated files" | regions and the guard |
| "Never claim a check passed unless it ran" | the report template |

## Development

This repository holds the skill (`skills/readable-c/`), its tests and evals. [AGENTS.md](AGENTS.md) has the rules for working on it.

```bash
task ci
```

runs ruff, the format check, the package validator and the tests. Without Task: `uv run ruff check .`, `uv run ruff format --check .`, `uv run python tools/validate_package.py` and `uv run pytest`.

## Versions

- **0.2.0** (2026-11-12): comments for code that is hard to follow (`needs-comment`), stale-comment and encoding checks in `verify`, private snapshot folders, and an `indent-style` fix.
- **0.1.0** (2026-11-11): first version. See [CHANGELOG.md](CHANGELOG.md).
