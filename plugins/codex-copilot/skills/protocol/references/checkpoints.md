# Checkpoints

## When to checkpoint

Checkpoint when the user should confirm direction before more work happens.

Typical checkpoint points:

- after service design
- after UX design
- after UI design
- after technical planning for large work

## What to include

Lead with the recommendation. Use this shape when the user must make a real decision:

```text
[One headline sentence: what is now true, not what was investigated.]
Recommendation: [what you would do and why, in one sentence.]
[Design-flow checkpoint only: “Approve to continue?” Otherwise a one-sentence question, only if the choice is irreversible, outward or budget-affecting.]

Task: TASK-xxx | WP: WP-xxx
```

- State the recommendation first. If every option is reversible within current authorization, take the recommendation and report it instead of asking.
- Design-flow checkpoints (after service, UX and UI design, and PRD or design approval) keep explicit approval: ask one approval sentence and wait.
- Offer a short list of outcome-stated options only when the choice is irreversible, outward or budget-affecting. Never print generic standing options such as change, back, skip, or show the work product.
- Put Task/WP metadata on one trailing line, never before the outcome.
- If there is no real decision, state the outcome and proceed without options or an approval question.
- Include soul, architecture, design-fidelity, QA, or next-step context only when it changes the decision.
- Keep evidence, findings, and file traces in the work product unless one is necessary to understand the decision.

## Done block and example first

Before substantial work, post the five-line done block and wait for one word from the owner:

```text
Done means: [the outcome the owner will see]
Proven by: [the check that shows it]
Not in scope: [what this will not touch]
Assumptions: [at most three, each with how it is checked]
First example: [the one populated instance built first]
```

The confirmed block becomes the task contract: `tc task contract <id> --from-done-block <file>`. When the work builds a collection, workflow family, integration or asset family, build one populated first example with real content (one journey; one narrative section; one item through the real path; one record plus one exception; one device and an observed action), show it, apply the correction, then expand.

When subagents are requested, run at most three concurrently unless the done block says otherwise, close each when its piece is done, and run one QA pass per batch.

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
