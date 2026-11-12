# The readable_c.py tool

Contents: [Running it](#running-it) · [Running without uv](#running-without-uv) · [Commands](#commands) · [Output](#output) · [Verification in detail](#verification-in-detail) · [Troubleshooting](#troubleshooting)

## Running it

```
uv run <skill-folder>/scripts/readable_c.py <command> <file> [options]
```

`<skill-folder>` is the folder that holds `SKILL.md`. The script's header (PEP 723) pins its dependencies:

| Package | Version | Used for |
| --- | --- | --- |
| tree-sitter | 0.25 or 0.26 | parsing |
| tree-sitter-c | 0.24.2 | the C grammar |
| clang-format | 23.1.5 | `format` |

uv installs them into its own cache on first use and needs internet access once. They support Python 3.10 to 3.14; uv picks or downloads a matching Python, so a machine with only Python 3.15 still works through uv.

The tool writes snapshots to a private folder of its own, `<temp>/readable-c-<user>/` (`READABLE_C_STATE_DIR` overrides it), and writes to the source file only in `format`, `repair` and `restore`. The folder is created readable by its owner only; the tool refuses a state folder that is a link or that another user owns, and it refuses a snapshot that does not belong to the file it is used for.

## Running without uv

With Python 3.10 to 3.14:

```
python -m venv .readable-c-venv
.readable-c-venv/bin/pip install --only-binary :all: "tree-sitter>=0.25,<0.27" tree-sitter-c==0.24.2 clang-format==23.1.5
.readable-c-venv/bin/python <skill-folder>/scripts/readable_c.py doctor
```

On Windows the folder is `.readable-c-venv\Scripts\`. Create the virtual environment outside the project, or add it to the project's ignore file.

Offline machines: on a machine with internet, run `pip download --only-binary :all: --python-version 3.12 --platform <platform> "tree-sitter>=0.25,<0.27" tree-sitter-c==0.24.2 clang-format==23.1.5 -d wheels`, carry the `wheels` folder over, and install with `pip install --no-index --find-links wheels ...`.

## Commands

### doctor [FILE]

Shows Python, the package versions, clang-format and the state folder. With a file, also its line endings, encoding (with a guess for legacy code pages), indentation, brace placement, dialect, boolean type, naming styles, constant style, parse problems, `.clang-format`, and the headers the tool cannot find.

### outline FILE [--findings]

Lists functions, prototypes, globals, types and macros with their lines. Functions show their length, nesting depth and parameter count, and with `--findings` the number of rule and advice findings, which helps pick what to refactor first. Functions that only the text scan found are marked.

### start FILE (--function NAME | --lines A-B)... | --all

Options: `--replace` drops a snapshot in progress; `--include DIR` (repeatable) adds a folder to search for headers; `--quiet` leaves out the region text.

Prints:

- the regions (and how line ranges grew);
- the region text with line numbers;
- the declarations from the same file that the regions use, with warnings for macros that hide a jump or evaluate an argument twice, and for `#define`s inside the function above a line range;
- the names that come from headers, and the ones the tool cannot place;
- the frozen names;
- the conventions;
- the baseline findings, and code that is not checked because it does not parse.

### check FILE

Lists the rule findings (new ones first; "new" means the edit introduced it) and the advice in the current regions, and the lines that were not checked. Exits 1 while rule findings remain.

### verify FILE [--diff] [--final] [--include DIR]

Runs the guard, then:

| Check | Severity |
| --- | --- |
| new syntax errors in the regions | error |
| new lines that hold UTF-8 text in a file that is not UTF-8 (fix with `repair --encoding`) | error |
| C constructs the original file never uses (dialect) | error |
| names that resolve nowhere (likely a typo or a missed rename) | error, or review when some headers could not be read |
| a new local that hides an outer name; a name declared twice in one block; a `const` local that is assigned; a `goto` without its label | error |
| frozen names missing or changed | error |
| an old comment that still mentions a local or parameter the function no longer declares (a missed rename) | review |
| an object-like `#define` added or removed | review |
| tier 2 inventory differences | review |
| with `--final`: no reader round has seen the final code, and fewer than three rounds ran | error |

Then it prints the equivalence tier of each function and a summary of the findings. `--diff` adds a unified diff of each region; `--final` adds the data for the report, including whether a reader brief showed the code as it is now. Exits 1 when there is an error.

### format FILE

Needs a `.clang-format` (or `_clang-format`) in the file's folder or above. The tool formats the whole file in memory with the project's style, with the options that change tokens turned off (`InsertBraces`, `RemoveParentheses`, `RemoveSemicolon`, `QualifierAlignment`, `SortIncludes`, `ReflowComments`, `IntegerLiteralSeparator`), applies only the replacements inside the regions, and refuses the result if any token changed. Without a `.clang-format` it does nothing and says so.

### reader FILE

Prints the brief for the reader pass: instructions for a first-time reader, the current text of the regions with line numbers, the declarations from the same file that the code uses (and the types those declarations use), and the names that come from headers. It leaves out the original code and the findings. Give the output to a fresh subagent; see [reader.md](reader.md). Each brief records a digest of the region text, which `verify --final` compares with the code as it is now.

### repair FILE [--encoding CODEC]

For a guard failure caused by line endings, BOM, trailing white space, the final newline or encoding. When the guard passes, it converts new region lines that hold UTF-8 text in a file that is not UTF-8, such as a new comment in a CP1251 file; that needs `--encoding`. See [regions.md](regions.md#line-endings-and-encodings).

### restore FILE [--whole-file]

Puts the original text back into the regions. `--whole-file` writes back the whole file as it was at `start`.

### finish FILE [--force]

Deletes the snapshot. It refuses (exit 1) while the file holds changes that no `verify --final` has checked: when `verify --final` never ran, or the file changed after the last one, even in a comment. The report is written from `verify --final`, so a later edit can make it wrong. A file that `restore` put back passes. `--force` deletes the snapshot without the check; use it only when the user asks to stop.

## Output

Findings and issues use compiler-style lines that editors can follow:

```
inventory.c:46:9: rule (new): [assignment-in-condition] This condition assigns. ...
inventory.c:51: error: [names] `totl` is not declared in the region, ...
```

`--json` prints one JSON document per command instead. Exit codes: 0 clean, 1 findings or errors, 2 usage or environment problem (message on stderr).

## Verification in detail

`verify` compares the original and the current version of every function that touches a region.

- Tier 0 compares tokens without comments and white space.
- Tier 1 compares canonical syntax trees. The canonical form:
  - replaces each local and parameter by its order of first use and its type, so renames match and captures do not;
  - drops comments, layout, redundant parentheses (except inside call arguments and `sizeof`), braces around single statements, plain nested blocks, `else` after a branch that always leaves, and `else { if }`;
  - joins an `else if` whose body repeats the branch before it, and consecutive `if`s whose identical bodies always leave, into one condition with `||`; pushes `!` through `&&` and `||`;
  - merges nested `if`s without `else` into one `if` with `&&`, and flattens `&&` and `||` chains;
  - in a loop body, reads `if (c) { x; continue; } rest` as `if (c) { x } else { rest }`;
  - reads a `for` loop whose body has no `continue` of its own as `init; while (test) { body step }`;
  - reads `return c ? a : b;` and `x = c ? a : b;` as an `if` with `else`;
  - reads `int x = E;` as `x = E;` and drops declarations without a value;
  - normalizes `E != 0`, `E == 0`, `!E`, `!!E`, `NULL`, `c ? 1 : 0`, `c ? 0 : 1`, the order of comparisons, and comparisons of two integer literals (`1 == 1` is `1`);
  - reads `x++`, `++x`, `x += 1` and `x = x + 1` as the same statement when evaluating `x` has no effects;
  - moves an assignment at the head of an `if` or `switch` condition into a statement before it;
  - inlines a local that names a value, when it is used once in the next statement and moving it cannot fault or reorder effects;
  - replaces enum constants (plain int literals up to 32767) and object-like macros that the file defines once by their literal.
- Tier 2 counts, in canonical form, the calls, literals, writes to non-local memory, jumps, static locals and special names (`va_*`, `setjmp`, `assert`, `errno`, `__LINE__`) of the functions that did not reach tier 0 or 1, and reports every count that changed.

Functions that do not parse cleanly can reach tier 0, never tier 1.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `error: The tool needs the Python packages tree-sitter...` | Run through `uv run`, or install the pinned packages (see above). |
| pip tries to build tree-sitter from source | Python is 3.15 or newer: use uv, or Python 3.10 to 3.14. |
| uv fails in the Codex sandbox | Allow network access for the first run, or set `UV_CACHE_DIR` to a folder inside the temp folder, which the sandbox lets the tool write. |
| `No refactor in progress` | Run `start` first; snapshots live in the temp folder and may be cleared on reboot. |
| `already in progress` | `finish` or `restore` the old refactor, or `start --replace`. |
| The guard fails after every edit, citing line endings | The edit tool converts the file. Run `repair` after each edit, or edit with a tool that keeps line endings. |
| A name from a header shows as unresolved | Pass the header's folder with `--include DIR`. |
