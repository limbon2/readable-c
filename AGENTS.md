# AGENTS.md

Instructions for coding agents working on this repository, and for the people who review their work. `CLAUDE.md` only imports this file.

## Project

- What: `readable-c` is an agent skill that refactors hand-written C (not C++) into readable code without changing behavior. It works on whole files or on parts of a file, such as some functions or a line range inside a function, and keeps every byte outside the selected regions unchanged. It needs no compiler: a Python tool built on tree-sitter checks the result.
- Origin: the rules and the verification discipline come from the Mannie project's `AGENTS.md`, its ESLint and Clippy settings and its custom `named-conditions` rule. [README](README.md#where-the-rules-come-from) maps each one.
- What gets installed is `skills/readable-c/`. Everything else (tests, evals, tooling) stays in the repository.

## Layout

| Path | Contents |
| --- | --- |
| `skills/readable-c/SKILL.md` | The workflow an agent follows. Keep it under 300 lines and move detail to `references/`. |
| `skills/readable-c/references/` | Rules, behavior hazards, the region model and the tool reference, which agents read on demand. |
| `skills/readable-c/scripts/readable_c.py` | The CLI entry. Its PEP 723 header pins the dependencies that `uv run` installs. |
| `skills/readable-c/scripts/readablec/` | The tool's package: source and lexer, syntax, regions and the guard, rules, verification, formatting, commands. |
| `skills/readable-c/agents/openai.yaml` | Codex metadata. |
| `.claude-plugin/` | The Claude Code plugin and its marketplace. |
| `tests/` | pytest tests and C fixtures. Fixtures keep their bytes (`-text` in `.gitattributes`). |
| `evals/` | End-to-end prompts and fixtures for agents using the skill. |
| `tools/validate_package.py` | Checks the skill's metadata and that the versions agree. |

## Rules for the code

- The tool's own Python follows the rules the skill teaches: descriptive names, straightforward control flow, named parts in compound conditions, no nested conditional expressions, one side effect per expression, and comments that explain what the code cannot. Ruff enforces what it can (`pyproject.toml`).
- Suppressions are narrow and state their reason: `# noqa: RULE  reason`. Ruff reports a suppression that no longer suppresses anything (`RUF100`).
- The tool handles source files as bytes. Tree-sitter offsets are bytes, and a legacy file may hold bytes that are not UTF-8. Decode only for display.
- A check that cannot run says so; it never reports success. Code inside tree-sitter ERROR nodes is reported as not checked.
- Every rule has a test that it fires and a test that it stays quiet on the accepted forms. Every guard and verification path has a test that it passes and a test that it fails.
- Keep the dependency pins in `scripts/readable_c.py` and in `pyproject.toml`'s `dev` group equal.

## Writing

Documentation, `SKILL.md`, references and messages that the tool prints use plain, specific English:

- no em dashes or en dashes as connectors;
- no "not X but Y" framing;
- no closing lines that repeat the paragraph;
- no bold label on every list item;
- no inflated words such as "crucial", "robust", "seamless" or "pivotal".

Messages say what was found and what to do about it.

## Commands

[Task](https://taskfile.dev) runs them, and each one is a plain `uv run` command (see `Taskfile.yml`):

- `task fmt` fixes and formats the Python code with ruff;
- `task lint` runs ruff, checks the formatting and validates the package files;
- `task test` runs pytest;
- `task ci` runs everything above and must pass before a change is done.

The skill's tool runs as `uv run skills/readable-c/scripts/readable_c.py <command>`.

## Versioning

One version covers the skill (`SKILL.md` metadata), the plugin (`.claude-plugin/plugin.json`) and `CHANGELOG.md`, and `tools/validate_package.py` checks that they agree. `CHANGELOG.md` follows Keep a Changelog.
