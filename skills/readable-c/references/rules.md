# Readability rules for C

Each rule has an ID that `check` reports. A rule finding is fixed, or kept with a one-line reason in the report. An advice finding is a judgment call. Every fix below keeps behavior; where a tempting fix would not, the section says so.

Contents: [Names](#names) · [Conditions](#conditions) · [Control flow](#control-flow) · [Expressions](#expressions) · [Constants](#constants) · [Functions and helpers](#functions-and-helpers) · [Project conventions](#project-conventions) · [Comments](#comments) · [Layout](#layout) · [Order of work](#order-of-work)

## Names

### cryptic-name (rule)

Locals and parameters of one or two characters, and placeholders such as `tmp`, `temp`, `buf2` or `p1`, make the reader trace every use to learn what the value is.

```c
/* before */
int add_item(const char *nm, int q)
{
    struct item *p;
    ...
/* after */
int add_item(const char *item_name, int quantity)
{
    struct item *new_item;
```

- Exempt: `i`, `j`, `k`, `n`, `x`, `y`, `z`, `c`, `ch`, `fd`, `fp`, `id`, `ok`, `rc`, `dx`, `dy`, `dz`.
- A name says what the value holds or counts: `bytes_left`, `first_free_slot`, `is_open`. A boolean reads as a question: `is_`, `has_`, `can_`.
- Follow the file's naming style that `doctor` reports (snake_case, camelCase).
- Renaming a local or a parameter is safe inside the region. Parameter names in a definition do not affect callers. `verify` proves the rename (tier 1) and catches a new name that hides another declaration.
- A name used outside the region (a static function, a global) is frozen. Propose its rename in the report instead.

### param-reassign (advice)

```c
/* before */
while (len > 0) { ...; len--; }
/* after */
size_t remaining = len;
while (remaining > 0) { ...; remaining--; }
```

After the change, `len` still means what the caller passed, which helps the code below it.

## Conditions

### named-conditions (rule in `if`, `?:` and `return`; advice in loops and in files without C99 declarations)

Ported from Mannie's ESLint rule. A part of an `&&`/`||` condition counts as named when it is a variable, a member path (`cfg->enabled`, `rows[i]`), a literal, a call of a named function with plain arguments (`is_empty(list)`, `strcmp(a, b)`), or the negation of one of these. Comparisons, arithmetic and calls with computed arguments get a name first.

```c
/* before */
if (count > 0 && is_visible) { ... }
/* after */
bool has_items = count > 0;      /* use the file's boolean type: bool, BOOL or int */
if (has_items && is_visible) { ... }
```

A part that is only safe after an earlier part must not become a separate variable: the variable would be computed even when the guard fails.

```c
/* before */
if (p != NULL && p->len > 0) { ... }
/* wrong: reads p->len when p is NULL */
int has_p = p != NULL;
int has_data = p->len > 0;
/* right: one named value */
int has_data = p != NULL && p->len > 0;
if (has_data) { ... }
/* or a static function */
static int has_data(const struct packet *p) { return p != NULL && p->len > 0; }
```

- An initializer is never checked: `int is_valid = a && b;` already names the whole condition.
- Loops evaluate their condition on every pass, so a variable set before the loop would go stale. Use a static function such as `is_at_end(...)`, or leave the condition and say why.
- In a file without declarations after statements (C89), a new variable must go at the start of the block, which moves where it is evaluated. There, prefer a static function, or leave the condition.
- `verify` proves the change (tier 1) when the named value is used once, right after its declaration, and moving it cannot fault or reorder side effects.

### nested-ternary (rule)

```c
/* before */
level = total > 5000 ? 2 : total > 1000 ? 1 : 0;
/* after */
if (total > 5000) {
    level = 2;
} else if (total > 1000) {
    level = 1;
} else {
    level = 0;
}
```

Keep the tests in the order the `?:` evaluates them, and `verify` proves the rewrite (tier 1). Reordering them, for example to test the largest value first, is a restructuring (tier 2): say why the order does not matter.

### unneeded-ternary (rule)

A `?:` that only produces 1 or 0 hides a condition. The fix must keep the value:

| Before | After | Why |
| --- | --- | --- |
| `a > b ? 1 : 0` | `a > b` | a comparison is already 0 or 1 |
| `flags & MASK ? 1 : 0` | `(flags & MASK) != 0` | `flags & MASK` can be any value |
| `a > b ? 0 : 1` | `!(a > b)` or `a <= b` | |
| `ok ? TRUE : FALSE` | (advice) | only when TRUE is 1 and FALSE is 0; check the macros |

When both branches are the same, keep the value and drop the choice. Keep the condition as a statement if it has side effects.

### assignment-in-condition (rule)

```c
/* before */
if ((idx = find_item(name)) >= 0) {
/* after */
idx = find_item(name);
if (idx >= 0) {
```

- The bare form `if (x = y)` is flagged; so is an assignment that is a part of `&&`/`||`.
- `while ((c = getchar()) != EOF)` is a known idiom and is allowed. Rewriting it needs the call in two places, which is worse.
- `verify` proves the move out of an `if` or `switch` condition (tier 1) when the assignment is the first thing the condition evaluates.

### mixed-operators (rule)

```c
/* before: groups as flags & (1 == 1) */
if (items[i].flags & 1 == 1)
/* after: the parentheses show what the code does now */
if (items[i].flags & (1 == 1))
```

Add the parentheses that match the current grouping, never the ones the author probably meant. If the grouping looks like a bug, keep it and report it as a suspected bug: fixing it changes behavior, which a refactor must not do.

Flagged: `&`, `|`, `^` mixed with comparisons, arithmetic, shifts or each other; shifts mixed with arithmetic; `&&` mixed with `||`.

### boolean-literal (advice)

`x == TRUE` is false when `x` is 2. Rewrite it as `x` only when `x` holds 0 or 1 (a comparison result or a `bool`). The tool cannot see the type, so the decision is yours.

## Control flow

### else-after-return (rule)

```c
/* before */
if (idx >= 0) {
    items[idx].qty += quantity;
    return idx;
} else {
    if (n_items >= MAX_ITEMS)
        return -1;
    ...
}
/* after */
if (idx >= 0) {
    items[idx].qty += quantity;
    return idx;
}
if (n_items >= MAX_ITEMS) {
    return -1;
}
...
```

Also after `break`, `continue` and `goto`. Moving the else body out one level widens the scope of its declarations; rename any that would clash with names after it. `verify` proves the change (tier 1).

### lonely-if (rule)

`else { if (x) { ... } }` becomes `else if (x) { ... }`.

### Flattening loops and nested ifs

Deep nesting in a loop body usually flattens with a guard at its top:

```c
/* before */
for (i = 0; i < n_items; i++) {
    if (items[i].flags & 1) {
        if (items[i].qty > 0) {
            report_item(&items[i]);
        }
    }
}
/* after */
for (i = 0; i < n_items; i++) {
    int is_reported = (items[i].flags & 1) != 0 && items[i].qty > 0;
    if (!is_reported) {
        continue;
    }
    report_item(&items[i]);
}
```

Two nested `if`s without `else` are one `if` with `&&`. `verify` proves both rewrites (tier 1), and a `for` loop rewritten as a `while` loop, as long as the `continue` skips exactly what the nested version skipped.

### missing-braces (rule)

Every body of `if`, `else`, `for`, `while` and `do` gets braces. Brace exactly the statement the parser sees as the body:

```c
/* before */
if (a)
    b = 1;
    c = 2;     /* runs every time, whatever the indentation says */
/* after */
if (a) {
    b = 1;
}
c = 2;
```

A lone `;` as a body becomes `{}`, with a comment if the empty body is on purpose.

### misleading-indentation (rule)

The statement after an unbraced body is indented as if it belonged to it, or sits on the same line. Brace the real body, give the next statement its real indentation, and report a suspected bug. Never move the statement into the body.

### goto (advice)

A forward `goto` to cleanup code at the end of the function is a C idiom; keep it. A backward `goto` is a loop in disguise: a `while` or `for` with the same exit conditions reads better, but it is a restructuring (tier 2), so take it as its own step and explain it.

## Expressions

### side-effects (advice)

One change per statement:

```c
/* before */
total = count++ * size;
/* after */
total = count * size;
count++;
```

Keep the order in which the original performs its changes. `*dst++ = *src++;` is the classic copy step and is exempt.

### stacked-casts (advice)

`(int)(unsigned char)c` is right when the middle cast prevents sign extension; say so in a comment. Remove casts only when the types say they do nothing, which the tool cannot check.

### multiple-declarators (advice)

`int i, total = 0;` becomes two declarations. `verify` treats both forms as the same.

## Constants

### magic-number (advice)

```c
/* before */
strncpy(entry->name, name, 31);
/* after, inside the function */
enum { LAST_NAME_INDEX = 31 };
strncpy(entry->name, name, LAST_NAME_INDEX);
```

- In a region, define the constant inside the function (`enum { NAME = 31 };`) or in the helper slot. A new `#define` needs a reason in the report, and `verify` rejects one whose name the rest of the file uses.
- An enum constant has the type `int`. Replace a literal with it only when the literal was a plain `int` (no `u`, `l` or `f` suffix, at most 32767). Otherwise use the file's constant style with the same type, such as `static const unsigned long`.
- Exempt: 0, 1, 2, -1, shift counts, array sizes, initializer tables and values that already name themselves.
- `verify` proves a literal replaced by an enum constant or an object-like macro that the file defines once (tier 1).

## Functions and helpers

### function-size (advice)

Over 60 lines, nesting deeper than 3, or more than 5 parameters. Flatten nesting with early returns first. Then extract parts that have a responsibility of their own into static helpers:

- Name a helper for what it answers or does: `find_free_slot`, `is_valid_header`.
- Put it in the helper slot before the function (for a line range) or before the function inside a function region. Make it `static`.
- Pass what it needs as parameters. An array parameter becomes a pointer, so `sizeof` inside the helper changes; pass the length.
- Code that uses a macro hiding `return` or `goto` stays in the caller.
- Extracting is a restructuring (tier 2): `verify` lists the calls and writes that moved; explain them.

Do not extract a helper that is used once and has no meaning of its own, do not add wrapper layers, and do not generalize for cases the code does not have.

## Project conventions

Keep using the project's own macros and idioms: error-handling macros such as `CHECK(x)`, logging and tracing macros, assertion macros, and the project's typedefs (`BOOL`, `u8`). They are how the rest of the code base reads. Expanding one by hand, or replacing it with your own pattern, makes the region the odd one out; when it really reads better, say why in the report and propose the change for the whole code base instead.

## Comments

A comment answers the question a reader would stop at, which the code cannot answer itself. C has many such places: memory that changes hands, bits packed into a word, bytes read as another type, calls into libraries with conventions of their own. Write a short comment at each of them, and nowhere else.

### needs-comment (advice)

`check` points at these places when no comment sits on the same lines or on the two lines above:

| Kind | Flagged when | The comment says |
| --- | --- | --- |
| allocation | `realloc` always; `malloc`, `calloc`, `strdup` and the like when the size is computed or the block is returned or stored in a structure | who owns the block and who frees it; why the size is what it is; for `realloc`, what happens when it fails |
| raw memory | `memcpy`, `memmove`, `memset`, `memcmp`, `strncpy`, `strncat` with computed offsets or sizes | what is copied or moved, and why the offsets and sizes are right |
| bits | shifts and masks with literal numbers, and `&=`, `\|=`, `^=`, `<<=`, `>>=` with literals | what the bits mean: the field, the encoding or the trick |
| reinterpreted memory | reading through a pointer cast: `*(T *)p`, `((T *)p)->x`, `((T *)p)[i]` | what the bytes are, and what the cast assumes about layout, byte order and alignment |
| library calls | calls into a non-standard system or third-party header the file includes (`<windows.h>`, `<openssl/ssl.h>`) | what the call does here: its result on failure, who owns what it returns, its units |

```c
buf = malloc(len + 1);  /* +1 for the terminating NUL; the caller frees buf */

/* bits 4-7 of the status byte hold the channel number */
channel = (status >> 4) & 0x0F;

length = frame[1] | (frame[2] << 8);  /* 16-bit little-endian length field */

/* CRC-16/MODBUS: 0xA001 is the polynomial 0x8005 with its bits reversed */
crc = (crc & 1) ? (crc >> 1) ^ 0xA001 : crc >> 1;

/* Drop the frame just handled: its header and body. */
memmove(link->buf, link->buf + HDR_LEN + body_len, link->len - HDR_LEN - body_len);

/* Wait up to 500 ms; WAIT_TIMEOUT means the worker has not finished. */
if (WaitForSingleObject(worker, 500) == WAIT_TIMEOUT) {
```

A name often says it better than a comment: `enum { CHANNEL_SHIFT = 4, CHANNEL_MASK = 0x0F };` inside the function (see `magic-number`). A comment changes no token and a named enum constant is proven by tier 1, so neither puts behavior at risk.

### Only true comments

A wrong comment is worse than none, because the reader trusts it. Write only what the code, the file, its headers or the library's documentation show:

- Take the meaning of a bit, a field or an offset from how the code uses it: where it is set, what it is compared with, the names of the macros and fields around it. `start` lists the declarations and macros the region uses, and `outline` shows where else the file has them.
- Take what a library call does from its declaration and documentation (the header in the project, the vendor's documentation), never from its name alone.
- When the meaning cannot be established, do not guess and do not write a vague comment. Leave the code as it is and put the question under "Open questions" in the report, for example "What does bit 0 of `item.flags` mean?".
- Say "assumes" when the code relies on something it never checks: `/* assumes a little-endian host */`.

### Placement and style

- Put a comment above the line or block it explains, or at the end of a short line. One line is usually enough.
- Say why, or what something means. Never narrate what the code does step by step: `i++; /* increment i */` repeats the code, so delete such comments.
- Use the file's comment style (`/* */` in a file without `//` comments) and the language of its other comments.
- In a file that is not UTF-8 (`doctor` shows the encoding, for example cp1251), new non-ASCII text needs converting: `verify` reports it, and `repair --encoding cp1251` converts the new lines. Plain ASCII avoids the step.
- Keep comments that carry information, such as license headers, author notes and the reasons for workarounds. Rewrite a comment that the refactor made wrong: after a rename, `verify` points at old comments that still use the old name, such as a header comment that says `cb->server` once the parameter is `slot`.
- `commented-out-code` (advice): delete disabled code, because version control keeps it. Ask first when the project has no version control.

## Layout

- `indent-style` (rule): new lines use the file's indentation (tabs or spaces, and the width `doctor` reports).
- Match the brace placement, spacing and line length of the code around the region.
- With a project `.clang-format`, run `format`; it touches the regions only.

## Order of work

Work in small steps and run `verify` after each, so that each step reaches tier 0 or 1 on its own:

1. Names.
2. Control flow: early returns, else after return, braces.
3. Conditions and expressions.
4. Constants.
5. Helpers (tier 2: explain them).
6. Comments for what is still not obvious (`needs-comment`), and open questions for what you could not establish.
