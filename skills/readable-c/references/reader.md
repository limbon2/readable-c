# The reader pass

The agent that refactored a region knows what every name means and why every number is there, so it cannot see what the code leaves unexplained. A fresh reader asks what it would need to know to change the code safely and checks the diff for older practices and comment format mismatches the refactor introduced.

- **A, the code could say it**: the reader found the answer in the code, but only by working it out, and says what it worked out. These are the agent's to write down, and the pass is done when a fresh reader of the final code has none.
- **B, only outside knowledge answers it**: what a library does, what a protocol says, why the code does what it does, whether a behavior is intended. The agent answers these only from a source it can read, or lists them as open questions.
- **C, older practices and comment format mismatches**: the reader points to a new use or comment format mismatch and gives a replacement with evidence that it fits the project.

A surprising behavior splits in two: what the code does goes into A (the code can say it, so the next reader does not have to work it out again), and why it does it goes into B.

## Running it

`reader FILE` prints the instructions below, the current regions with line numbers, the declarations they use, and the names from headers. It then shows the configured C standard and its source when known, followed by a diff of the selected regions against the snapshot. The diff headers give the starting file line for each side, and hunk lines are relative to those starts.

Give the brief to a fresh subagent, as SKILL.md describes. The simplest task is one line, so nothing of yours slips in:

```
Run uv run <skill-folder>/scripts/readable_c.py reader <file> and do what it says.
```

If an applicable rule for documentation comments or a nearby example is outside the brief, give the reader the exact rule or example and its source. Use the project's own wording or code so the reader can make an independent assessment.

Each brief records a digest tied to the region text and configured standard. `verify --final` reports an error until a brief has shown the final code or three rounds have run with the current standard and reader instructions.

## Rounds

1. Start a subagent with the brief and collect its three lists.
2. Write down every answer in list A.
3. Answer each question in list B from a source you can read, with a comment, or add it to "Open questions" in the report.
4. Check each item in list C and fix it or give a specific reason in the report.
5. If the code changed, run `verify` and start a new subagent for the next round. A reader who saw the old version remembers it.

The pass is done when a round that saw the final code returns an empty list A and every item in list C has been addressed. Stop after three rounds. Address the last round's feedback and say in the report if code changed after it. List each question and finding and what became of it.

## Answering list A

Each A item comes with the reader's answer. Check it against the code first: readers misread too. Then put it where the reader needed it:

- A name the reader had to work out: rename, so the name says what the reader worked out.
- A number, size, offset or bound: use a [typed constant](rules.md#constants) or say in a comment which fields add up to it.
- A step the reader traced by hand: say what it computes in a comment, or extract it into a helper whose name says it.
- A function whose purpose or ownership the reader worked out: write its contract comment.
- A surprising behavior: say what the code does in a comment, and keep the behavior. Whether it is intended is a B question.
- A comment that does not match the code: rewrite it to say what the code does, even when the comment was there before you. When the comment states an intent the code does not carry out, keep the code, correct the comment, and add the mismatch to "Open questions": it may be a bug.

## Answering list B

- A library call: take what it does, returns and allocates from the library's header or documentation in the project, and say in the comment where it comes from when that is not obvious. Never take it from the call's name alone.
- A protocol or file format fact: take it from the specification or from the project's own definitions (field structs, named constants). Without a source, it is an open question.
- Why the code does something, whether a behavior is intended, who calls the code: only someone who knows the project can answer; it is an open question. Keep the behavior.
- A comment that states something the code does not show needs its source named, or "assumes" when the code relies on it without checking it.

## Answering list C

Check the diff and the project's supported targets. For example, a new loop counter can be declared in the `for` header where the configured standard supports it and the counter is used only by the loop. Check that moving its declaration preserves when the initializer is evaluated and what its name refers to.

Make the change only when it fits the project, stays in the regions and preserves behavior. Run `verify` after each edit. Keep the current code and record the reason when the project uses a required API or type, a change would affect callers or evaluation, or compatibility cannot be established. Raising the required C standard, changing a public interface or altering observable behavior goes beyond this pass.

Check the relevant project guidance or comparable documentation. If the task asks for a documentation conversion, give the reader the requested format and scope. Check function contracts, callbacks and other documentation in those regions, including inherited comments. Keep relevant tags and update renamed parameters in them.

## The brief

When the tool cannot run, give the subagent this text, the current regions with line numbers and used declarations, the configured standard and its source if known, and the region diff against the original. If the original is unavailable, say so. The reader can still answer A and B and report that it could not check C.

```
You are a C developer reading this code for the first time. You know C and its standard
library well. You do not know this project, its libraries, its file formats or its
protocols, and you cannot ask the author.

Read the current code and its declarations first. List the questions you would have
to ask the author, or look up elsewhere, before you could change this code safely:

A. The code could say it. You found the answer in the code below, but only by working
   it out, because nothing tells you directly:
   - what a name holds or does, when the name does not say it;
   - where a number, size, offset or bound comes from;
   - what a step computes that you had to trace by hand (a loop, a cast, bit arithmetic);
   - what a function does, returns or owns, when you had to read its body to find out;
   - a comment that does not match what the code does.
   Give the answer you worked out for each one. If you cannot, it belongs in B.
B. Only outside knowledge answers it: what a library call does or returns, what a
   protocol or file format says, why the code does what it does, whether a behavior is
   intended, who calls this code.

When the code does something surprising, put what it does in A, with your answer, and
the question of why in B.

For A and B, ask questions about the current code. Skip what the C standard defines
and what the code already says plainly.

Then compare the region diff to the current code.

C. Older practices and comment format mismatches introduced by the refactor.
   Look for a newly adopted older construct, idiom or API with a clearer, supported
   replacement. Give the current line, what the diff shows was introduced, a
   replacement, and the evidence that the configured standard or project conventions
   support it. Consider scope, evaluation, types, API contracts and portability.
   Check new enums used solely to name sizes, limits, shifts or other independent
   constants. Flag them when a typed constant or another project-approved form
   preserves the type and any requirement for an integer constant expression.
   Flag new declarations separated from initialization, including loop-only counters,
   when combining them preserves scope and evaluation under the configured standard.
   Check indentation on changed lines against other statements in the same block.
   For documentation, including callback contracts, flag a new or edited comment
   that departs from the format in a project rule or a comparable documented function,
   or drops tags that still apply. If the task requests a documentation conversion,
   check every documentation comment in its selected regions, including comments
   absent from the diff. Ask under B if compatibility, equivalence or comment format
   depends on missing project information.
   Flag new uses, including reuse of an existing idiom in a new place. Skip uses
   that were only moved, renamed or reformatted, and choices justified by the
   project's conventions or compatibility requirements.

Review only the supplied material. Leave code changes to the refactoring agent.
Reply in this form, one item per line. Put the questions that cost you the most
time first and write "none" under an empty list.

A. The code could say it
1. <line>: <question> -> <the answer you worked out>
B. Only outside knowledge answers it
1. <line>: <question>
C. Older practices and comment format mismatches introduced by the refactor
1. <current line>: <new use or format mismatch> -> <replacement and project evidence>
```
