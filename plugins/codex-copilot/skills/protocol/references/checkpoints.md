# Checkpoints

## When to checkpoint

Checkpoint when the user should confirm direction before more work happens.

Typical checkpoint points:

- after service design
- after UX design
- after UI design
- after technical planning for large work

## What to include

Use this shape when the user must make a real decision:

```text
[One headline sentence: what is now true, not what was investigated.]
[At most 2–3 more sentences, only when the decision is unintelligible without them.]

1. [Decision-specific option, stated as the outcome it produces.]
2. [Decision-specific option.]
3. [Decision-specific option, only when real.]

Which one?

Task: TASK-xxx | WP: WP-xxx
```

- Put 2–3 numbered, decision-specific options immediately before a question of at most 4 words, normally “Which one?”
- Do not print generic standing options such as change, back, skip, or show the work product.
- Put Task/WP metadata on one trailing line, never before the outcome.
- If there is no real decision, state the outcome and proceed without options or an approval question.
- Include soul, architecture, design-fidelity, QA, or next-step context only when it changes the decision.
- Keep evidence, findings, and file traces in the work product unless one is necessary to understand the decision.

## Approval and decision requests

Design-flow checkpoints (after service, UX and UI design, and PRD or design approval) require explicit user approval; there is no auto-proceed there. Everywhere else, when there is no real decision, state the outcome and proceed.

Every request that needs the owner's input, whether from a checkpoint or from a `tc` refusal, carries one line `DECISION NEEDED: <concrete decision>` (for example `DECISION NEEDED: $4 over Convoco budget for 30 more API calls`). This is the only form such a request takes; money beyond the project budget is the only case that also needs a verbatim owner quote.

When the user requests changes at a checkpoint, revise with their feedback as a constraint and present the checkpoint again. If revisions stop converging, say so and offer a fresh start (the no-progress rule, not a fixed iteration count).

Runaway protection is enforced in code by `tc execution` (a hard ceiling per task that halts and reports), not by counting continuations in instructions.

## When not to checkpoint

Do not overuse checkpoints on:

- small bug fixes
- tightly scoped technical tasks
- explicit user requests to proceed straight through
