# The reader pass

The agent that refactored a region knows what every name means and why every number is there, so it cannot see what the code leaves unexplained. The reader pass gives the code to an agent that knows none of that and collects the questions it would have to ask the author, sorted by who can answer them:

- **A, the code could say it**: the reader found the answer in the code, but only by working it out, and says what it worked out. These are the agent's to write down, and the pass is done when a fresh reader of the final code has none.
- **B, only outside knowledge answers it**: what a library does, what a protocol says, why the code does what it does, whether a behavior is intended. The agent answers these only from a source it can read, or lists them as open questions.

A surprising behavior splits in two: what the code does goes into A (the code can say it, so the next reader does not have to work it out again), and why it does it goes into B.

## Running it

`reader FILE` prints the brief: the instructions below, then the current text of the regions with line numbers, then the declarations from the same file that the code uses (and the types those declarations use), then the names that come from headers. It never shows the original code or the findings.

Give the brief to a fresh subagent, as SKILL.md describes. The simplest task is one line, so nothing of yours slips in:

```
Run uv run <skill-folder>/scripts/readable_c.py reader <file> and do what it says.
```

Each brief records a digest of the region text it showed. `verify --final` reports an error until a brief has shown the final code or three rounds have run.

## Rounds

1. Start a subagent with the brief and collect its two lists.
2. Write down every answer in list A, and run `verify`.
3. Answer each question in list B from a source you can read, with a comment, or add it to "Open questions" in the report.
4. If the code changed, start a new subagent for the next round: one that saw the old version remembers it.

The pass is done when a round that saw the final code returns an empty list A. Stop after three rounds at most; if the third round still had A questions, write them down and say in the report that no round checked those changes. List every question and what became of it in the report.

## Answering list A

Each A item comes with the reader's answer. Check it against the code first: readers misread too. Then put it where the reader needed it:

- A name the reader had to work out: rename, so the name says what the reader worked out.
- A number, size, offset or bound: name it (`enum { RECORD_HEADER_LEN = 6 };`) or say in a comment which fields add up to it.
- A step the reader traced by hand: say what it computes in a comment, or extract it into a helper whose name says it.
- A function whose purpose or ownership the reader worked out: write its contract comment.
- A surprising behavior: say what the code does in a comment, and keep the behavior. Whether it is intended is a B question.
- A comment that does not match the code: rewrite it to say what the code does, even when the comment was there before you. When the comment states an intent the code does not carry out, keep the code, correct the comment, and add the mismatch to "Open questions": it may be a bug.

## Answering list B

- A library call: take what it does, returns and allocates from the library's header or documentation in the project, and say in the comment where it comes from when that is not obvious. Never take it from the call's name alone.
- A protocol or file format fact: take it from the specification or from the project's own definitions (field structs, named constants). Without a source, it is an open question.
- Why the code does something, whether a behavior is intended, who calls the code: only someone who knows the project can answer; it is an open question. Keep the behavior.
- A comment that states something the code does not show needs its source named, or "assumes" when the code relies on it without checking it.

## The brief

When the tool cannot run, give the subagent this text, followed by the code of the regions with their line numbers and the declarations they use:

```
You are a C developer reading this code for the first time. You know C and its standard
library well. You do not know this project, its libraries, its file formats or its
protocols, and you cannot ask the author.

Read the code below and list the questions you would have to ask the author, or look up
elsewhere, before you could change this code safely. Sort them into two lists:

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

Do not ask about what the C standard defines or what the code already says plainly. Do
not suggest fixes, rewrite code or comment on style: questions only. Use only what is
below; do not open other files.

Reply in this form, one question per line, with the questions that cost you the most
time first. Write "none" under a list that has no questions.

A. The code could say it
1. <line>: <question> -> <the answer you worked out>
B. Only outside knowledge answers it
1. <line>: <question>
```
