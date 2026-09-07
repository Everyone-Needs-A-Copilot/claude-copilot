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

## When not to checkpoint

Do not overuse checkpoints on:

- small bug fixes
- tightly scoped technical tasks
- explicit user requests to proceed straight through
