# Surfacing unknowns

**The rule.** Every design-stage agent — `sd`, `uxd`, `uids`, `ind`, `cco`, `ta`, `cw` — emits an `Unknowns:` line in its Output Format. `Unknowns: none` is permitted and is a claim the agent owns. Omitting the line is not: the SubagentStop hook records the omission to `.claude/hooks/state/asking.json` and names it in the session transcript.

An unknown that would change the work escalates instead of being noted. The escalation block is already exempt from every token budget in each agent's Runtime Precedence section, alongside promise markers, QA `ARTIFACT:` lines and Task/WP identifiers:

```
QUESTION: [the one thing that changes the answer]
OPTIONS: [A — consequence] | [B — consequence]
CONTEXT: [why this cannot be resolved from what you were given]
```

One question, not a checklist. Each option carries its consequence so the reader can decide without a second round trip. `CONTEXT:` is what makes it a question rather than a request to be told what to do — it states what the agent already ruled out.

## Why this is mandatory rather than available

The mechanism predates this rule. Fourteen agent files exempt a `QUESTION:/OPTIONS:/CONTEXT:` block from their token budget, and every one of them mentions it *only* in that exception clause. Nothing ever asked for one, so nothing ever produced one. It was a right the specialists held and never exercised.

What that cost, measured. A brief for a drywall bid-estimating tool carried a real contradiction: "Level 4 finish throughout" against "Garage included" — a garage is not finished to Level 4, and which one governs changes the labour estimate materially. Both arms received the identical brief, and a sealed answer sheet would release the resolution to any arm that actually asked.

- The arm with **no framework at all** asked, earned three sealed clarification answers, and priced 25 fewer labour hours.
- The arm running the **full design chain**, with enforcement verified as registered, earned **zero**. It asked nothing and priced a guess.

The chain had resolved internally what should have been a conversation. For a framework whose stated purpose is experience-first, design-led software, that is the wrong trade in the one place it claims to be strongest.

## Resolving an ambiguity silently is a defect

It reads as efficiency and is the opposite. Inferring an answer where the brief is genuinely undecided converts the user's decision into the agent's hidden assumption and buries it inside a deliverable, where it surfaces later as rework — the exact outcome this framework exists to reduce. Guessing is only acceptable when the guess is stated as one.

A specialist's competence includes knowing what it cannot know. An agent that never reports an unknown is not demonstrating confidence; it is declining to distinguish what it was told from what it decided.

## What is checkable, and what is not

`Unknowns:` presence is mechanical: the hook classifies each design-stage return as `unknowns`, `question`, `declared-none`, or `absent`, and only `absent` produces a message. Nothing here judges whether the unknown raised was the *right* one — that remains a matter of judgement, and no hook should pretend otherwise.

"Questions raised before building" is therefore a proxy, not a score. It is the closest thing the benchmark found to a measurable signal of product judgement, and it is worth counting for exactly that reason and no further.

## Cost

The seven `Unknowns:` lines add 441 bytes to the agent corpus. That tripped FF9's absolute ceiling, which is the mechanism working as designed — the ceiling has zero headroom precisely so that growth is a reviewed decision. The baseline was raised by the measured amount with this document as the stated reason.

The rationale deliberately lives here rather than in `_shared/output-contract.md`. That canonical block is duplicated byte-for-byte into every agent file, so a paragraph added there costs its length seventeen times over in always-loaded context. The enforcement belongs in the agents; the argument for it belongs in the docs.

## Related

- `.claude/agents/_shared/output-contract.md` — the canonical Output Contract block
- `.claude/hooks/subagent-stop.sh` — `record_design_unknowns()`
- `.claude/context-budget-baseline-v5.13.5.json` — FF9 ceilings and the reason each was raised
