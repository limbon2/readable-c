# Behavior hazards in C refactors

A readability refactor must not change what the program does. These are the ways a reasonable-looking edit changes behavior in C. `verify` catches some of them (each section says which); the rest need care.

Contents: [Evaluation](#evaluation) · [Types](#types) · [Macros](#macros) · [Helpers](#helpers) · [Control flow](#control-flow) · [Preprocessor](#preprocessor) · [Names and scope](#names-and-scope) · [Dialect](#dialect) · [Things that are not yours to change](#things-that-are-not-yours-to-change)

## Evaluation

- Short-circuit guards. In `a && b` and `a || b`, `b` runs only when needed. `p != NULL && p->len > 0` protects `p->len`; naming `p->len > 0` in its own variable reads it unconditionally. Name the whole condition, or extract a static function. `verify` refuses to prove such a split (tier 2).
- Order of side effects. Moving a call into a condition, out of a condition, before or after another call, or into a variable that is computed earlier, can change the order in which effects happen. Keep every call at the same point in the evaluation, and never call a function twice where it ran once.
- Unsequenced expressions. `a[i] = i++` and `f(i++, i)` are undefined behavior. Do not "fix" them silently; report them as suspected bugs.
- `volatile` reads. Each read of a volatile object is an effect. Do not merge, duplicate or move them.
- `errno`. Any library call may change `errno`. Read it before the next call, as the original does.

## Types

- A named value takes the type of its expression after the usual conversions. `unsigned char` operands promote to `int`; `a + b` of two `uint16_t` is an `int`. Declaring the variable narrower truncates; declaring it wider can change later arithmetic. When unsure, use the type of the widest operand, and keep signedness.
- Comparing signed and unsigned values converts the signed one. Changing a type in a comparison can flip its result for negative values.
- Literal types depend on the value and the suffix: `40000` is `long` where `int` is 16 bits, and `0xFFFF` may be `unsigned`. Replace a literal by an enum constant (always `int`) only for a plain int literal up to 32767.
- `bool` and `_Bool` store 0 or 1; `BOOL` is usually `int` and stores anything. `flag ? 1 : 0` and `flag != 0` normalize; `flag` alone does not.
- `char` may be signed or unsigned depending on the compiler. Keep casts such as `(unsigned char)c` before `ctype.h` calls.

## Macros

- A macro that hides `return`, `goto`, `break` or `continue` jumps relative to where it is used. Code that uses it cannot move into a helper: the `goto` label would not exist there, and the `return` would leave the helper instead of the caller. `start` flags these macros.
- A function-like macro that uses its parameter twice evaluates its argument twice. `SQR(i++)` increments twice. Do not pass it a new expression with side effects, and do not replace a named value by an expression in its argument. `start` flags these too.
- Macro arguments are text. Parentheses inside them matter, which is why `verify` keeps them there.
- `assert` and other stringifying macros print their argument's text. A rename inside one changes the message, which is normally fine; mention it.
- A macro defined inside a function body is visible only from its `#define` on. A helper placed before the function cannot use it. `start` warns about these.

## Helpers

- An array parameter is a pointer: `sizeof(buffer)` in a helper gives the pointer size. Pass the length explicitly.
- `static` locals keep their value between calls. Moving one into a helper keeps that; copying it into two helpers splits it.
- Variadic code (`va_start`, `va_arg`) cannot move into a helper without passing a `va_list`.
- `setjmp` and `longjmp`, and locals changed between them, must stay where they are.
- A helper that returns early must give the caller what the caller needs to stop as well; check every path.
- Large local arrays moved into a helper still use stack, once per call.

## Control flow

- `break` inside a `switch` leaves the switch, not the loop around it. Restructuring a switch inside a loop can change what a `break` or `continue` leaves.
- Switch fallthrough. A `case` without `break` runs the next case. Keep it, and add a comment such as `/* falls through */` when it is on purpose.
- `continue` in a `do ... while` jumps to the condition, and in a `for` to the update step. Converting between loop kinds changes that.
- Cleanup gotos release resources in a set order. Keep the order, and keep every path that reached the label reaching it.
- Unbraced bodies follow the parser, not the indentation. Brace what the parser sees (see `misleading-indentation`).

## Preprocessor

- Code under `#if`, `#ifdef` and `#else` must stay right for every configuration, including the ones you cannot compile here. A name that exists only in one branch cannot be used outside it.
- Do not move code across `#if` boundaries, and do not add or remove directives; `verify` rejects added and removed includes and conditionals.
- Tree-sitter cannot parse `#if` blocks that open braces in each branch. Rules and the tier 1 check skip that code, and `verify` falls back to comparing tokens. Edit such code with extra care, and say in the report that it was not proven.

## Names and scope

- A new local that has the same name as a global, or as a local of an enclosing block, hides it. Code below that meant the outer one now reads the new one. `verify` reports this as an error.
- Moving a declaration out of a block widens its scope; moving it in narrows it. Code after a line range may use a local declared inside the range; such locals are frozen and must stay declared at the same block level with the same type.
- Two declarations of the same name in one block do not compile. `verify` reports this.
- A `const` local that is assigned later does not compile. `verify` reports this.

## Dialect

Without a compiler, using only the C the file already uses is the main protection against an edit that does not compile. `verify` rejects these when the original file never uses them:

- `//` comments;
- declarations after statements in a block, and declarations in a `for` header;
- `bool`, `true`, `false` and `_Bool`;
- `inline`, `restrict`, `long long`, `_Static_assert`, `__func__`;
- designated initializers and compound literals.

Names from headers that the file does not include are not available either. `verify` reports a new name that it cannot resolve.

## Things that are not yours to change

In a region task, these stay as they are, and changes to them go into the report as proposals:

- the signature of a non-static function, and anything a header declares;
- struct, union and enum layouts, and global variables;
- macro names and bodies used outside the regions;
- `#include` lines and other directives;
- the file's encoding, line endings and final newline.
