# Regions, the guard and frozen names

A region is the part of a file a refactor may change. Everything else is frozen: it must stay byte for byte the same, and it must still mean the same.

## Choosing regions

| Request | `start` option | Region |
| --- | --- | --- |
| "Clean up `parse_record`" | `--function parse_record` | the whole definition and the comments directly above it |
| "Lines 120 to 160 are a mess" | `--lines 120-160` | those lines, grown to whole statements, plus a helper slot |
| "These two functions" | `--function a --function b` | two regions (one if only blank lines separate them) |
| "This whole file" | `--all` | the whole file; file-scope changes are allowed |

- A line range inside one function grows outward to whole statements, comment blocks and `#if` groups. `start` says when it grew.
- A line range that crosses functions or top-level declarations grows to cover them whole.
- A function defined in several `#if` branches is selected in every branch.
- A function that tree-sitter cannot parse (K&R with implicit `int`, `WINAPI`-style macros, `#if` branches that each open a brace) is still found by a text scan. Its region works, but rules and the tier 1 check skip it.
- For a whole file, prefer one function at a time: each step is smaller and easier to prove.

## The helper slot

A line range inside a function gets an empty second region just before that function: the helper slot. Extracted static helpers go there, and nowhere else outside the range.

```c
/* helper slot: new static functions go here */
/* Counts positive values. */
static int count_positive(const int *values, int length)
{
    ...
    /* lines 9-10: the selected range */
    ...
}
```

The slot sits above the comment attached to the function. A helper in the slot cannot see macros defined inside the function body; `start` lists any.

## What the guard checks

`verify`, `check`, `format` and `restore` all start with the guard.

1. The frozen text is unchanged. The original is split into frozen segments and regions; the current file must contain every frozen segment, in order, with only region text between them. The guard searches from both ends, so it notices when the regions' boundaries are ambiguous.
2. The frozen text still means the same. At the start of each frozen segment, the lexer must be in the same state as before: not inside a comment, string or continued line, at the same depth of braces, parentheses and brackets, and inside the same `#if` groups. A region that leaves a `/*` open, adds a `}`, or ends with a backslash fails here.
3. Directives in regions are unchanged. Adding or removing an `#include`, `#if`, `#undef` or `#pragma` is an error. A new object-like `#define` is a review item, unless its name is used outside the regions, which is an error. A new function-like macro is an error: write a static function.

When the guard fails, it names the first changed line outside the regions and how to fix it.

## Line endings and encodings

The tool reads and writes bytes. It never re-encodes frozen text, so CRLF line endings, a BOM, a missing final newline and comments in legacy code pages such as CP1251 survive.

Edit tools are less careful. Some rewrite the whole file with LF line endings or as UTF-8. The guard reports such damage as a byte-level change, and `repair` fixes it:

- frozen bytes come back from the snapshot;
- region text gets the file's line ending;
- in a file that was re-encoded, unchanged region lines get their original bytes back, and changed lines with non-ASCII text are encoded with `--encoding` (for example `repair --encoding cp1251`; `doctor` shows its guess).

Keep non-ASCII comments in a legacy file untouched where you can.

## Frozen names

`start` lists what the code outside the regions needs from inside them:

- File-scope names defined in a region and used outside it, such as a static function called elsewhere, or a global. Their name and declaration must stay; parameter names may change.
- Locals declared in a line range and used after it in the same function. They must stay declared at the same block level, with the same type.
- Labels in a range that a `goto` outside it jumps to.

`verify` reports each one that is missing or changed as an error.

## Snapshots

`start` stores the original file and the regions in a private folder under the OS temp folder (`READABLE_C_STATE_DIR` overrides it), never in the project. One refactor per file runs at a time: `start` refuses a second one unless `--replace`, which drops the old snapshot and starts from the file as it is now.

- `restore` puts the original region text back and keeps everything else as it is now. If the guard cannot find the regions, `restore --whole-file` writes back the whole file as it was at `start`, which also drops any other edits made since.
- `finish` deletes the snapshot.

## Proposals outside the regions

Some improvements need changes outside the regions: a better name for a global, a fixed prototype, a new header include, a constant shared by several functions. Do not make them. List them in the report under "Proposed changes outside the regions", with where and why.
