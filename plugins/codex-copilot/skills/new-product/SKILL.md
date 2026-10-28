---
name: new-product
description: Facilitates zero-to-one product definition from an empty folder. Use when the user runs /new-product or $new-product, or says they want to start a new product, create a design package, or work through vision, JTBD, journey maps, requirements, UX, UI, copy and voice, a design challenge brief and a prototype. Sets up docs/ and SOUL.md in the current directory, runs a six-phase facilitated interview, and resumes from docs/TODO-DESIGN-PACKAGE.md. Not for designing a feature inside an existing product (use the protocol workflow).
---

# New Product

Skill version: 1.0.0

Guide the user through a facilitated conversation that produces a complete product design package in the current directory: the documents that define what the product is, who it is for, how it looks and feels, and what the prototype should be. You ask structured questions, the user answers in their own words, and you synthesize the answers into documents. Each template carries its own facilitation guide as an HTML comment.

Throughout this skill, `<skill-dir>` is the directory that contains this SKILL.md. Templates live in `<skill-dir>/assets/templates/` and reference guides live in `<skill-dir>/references/`. The skill itself is stateless: all progress lives in the user's project (`docs/`, `docs/TODO-DESIGN-PACKAGE.md`, root `SOUL.md`).

## Reference Documents

Read these as the matching step comes up, not all at once.

| Document | Path | What It Provides |
|----------|------|-----------------|
| Setup and resume | `<skill-dir>/references/setup-and-resume.md` | Detecting new, resume or existing-docs state; copying templates; placeholder replacement; migration mapping for existing work |
| Facilitation rules | `<skill-dir>/references/facilitation-rules.md` | Your role, conversation technique, synthesis rules, how to talk about effort |
| Facilitation process | `<skill-dir>/references/facilitation-process.md` | Detailed conversation technique, adaptation, synthesis, session management, phase transitions |
| Document sequence | `<skill-dir>/references/document-sequence.md` | The full structure across six phases with prerequisites and checkpoint checks |
| Session flow | `<skill-dir>/references/session-flow.md` | Session start, pausing and resuming, phase transition messages |
| Soul file | `<skill-dir>/references/soul-file.md` | Per-section interview questions, synthesis rules and the Define-Done bar for SOUL.md |
| Soul retrofit | `<skill-dir>/references/soul-retrofit.md` | Creating SOUL.md for a project that already has documentation or code |
| Prototype outputs | `<skill-dir>/references/prototype-outputs.md` | Phase 6 choices, prerequisites to check, hand-off to build workflows |
| Runtime | `<skill-dir>/references/runtime.md` | How specialists, task tracking and memory map onto the runtime you are in |

## The Six Phases

| Phase | Focus | Output |
|-------|-------|--------|
| 1: Discovery | Vision, scope, metrics | 3 documents in `docs/00-overview/` |
| 2: Research and Service Design | Interviews, JTBD, journey maps, moments that matter, service blueprint | `docs/01-research/` and `docs/02-service-design/` |
| After Phase 2: Soul DRAFT | IS/IS-NOT, design principles, anti-patterns, Feature Filter | `SOUL.md` at the project root (DRAFT v0.1), the north star for Phases 3 to 5 |
| 3: Requirements | User stories, use cases, acceptance criteria | `docs/03-requirements/` |
| 4: Experience Design | UX design, UI design, copy and voice | `docs/04-experience-design/` |
| 5: Design Challenge | Creative brief | `docs/05-design-challenge/00-brief.md` |
| After Phase 5: Soul RATIFY | Case law, founding decisions, principle priority order | `SOUL.md` updated to RATIFIED v1.0 before the prototype |
| 6: Prototype | Figma, design spec, Storybook or Next.js, the user's choice | `docs/06-prototype/` plus the chosen output |

## What the Skill Creates

After setup in an empty folder, the project directory holds the template package, the tracker and (once Phase 2 is done) the soul file:

```text
SOUL.md                          # created after Phase 2 (DRAFT), ratified after Phase 5
docs/
  README.md
  TODO-DESIGN-PACKAGE.md         # tracker and resume point
  00-overview/                   # vision, scope, metrics
  01-research/                   # interviews, JTBD, journeys, moments
  02-service-design/             # service blueprint
  03-requirements/               # stories, use cases, acceptance criteria
  04-experience-design/          # UX, UI, copy and voice
  05-design-challenge/           # creative brief
  06-prototype/                  # guide for the chosen output
```

## Core Pattern

Every facilitated document follows the same loop: read the facilitation comment, ask one round of questions, probe, synthesize in the user's words, read it back, update the tracker. GOOD: "So what I'm hearing is the pain starts when the handoff is unclear. Here is what I wrote; does it feel right?" BAD: "Please list your top five features."

## Anti-Patterns

Facilitation failure modes to avoid:

- **Question dumping**: asking several questions at once. Ask one, then listen.
- **Form filling**: treating the template as a questionnaire. Follow the user's energy and use the comment as a guide.
- **Sanitizing**: rewriting answers into formal documentation language. Keep the user's words, numbers and anecdotes.
- **Inventing**: filling a section the user never spoke to. Mark it `<!-- TODO: ... -->` and capture it as an unknown.
- **Batch synthesis**: writing everything at the end. Fill sections as you go and read each back.
- **Telling, not asking**: deciding what to build. Reflect what you heard and ask what it changes for the user.
- **Skipping checkpoints**: starting Phase 3 without the soul DRAFT, or the prototype without an approved brief.
- **Time estimates**: describing effort in hours or weeks. Use phase, priority and complexity.

## Define Done

- [ ] Template package copied into `docs/` (and `SOUL.md` kept out of `docs/`)
- [ ] `docs/README.md` and the tracker carry the product name and description
- [ ] Phase 1 documents completed (vision, scope, metrics)
- [ ] At least one interview artifact completed
- [ ] Phase 2 documents completed (JTBD, journeys, moments, blueprint)
- [ ] Design Foundation Checkpoint passes
- [ ] `SOUL.md` DRAFTED at the project root before Phase 3 begins
- [ ] Phase 3 documents completed (user stories, use cases, acceptance criteria)
- [ ] Phase 4 documents completed (UX, UI, copy and voice)
- [ ] Design challenge brief completed and approved by the user
- [ ] `SOUL.md` RATIFIED at the project root before the prototype
- [ ] `docs/TODO-DESIGN-PACKAGE.md` status matches actual document state
- [ ] Design Complete Checkpoint passes
- [ ] Prototype output created in the chosen format

## Instructions

### Step 1: Detect State and Set Up

Work in the current directory; it is the project directory. Read `references/setup-and-resume.md` and follow the path that matches what is on disk:

- `docs/TODO-DESIGN-PACKAGE.md` exists: resume. Read the tracker, brief the user on where they left off, and continue at the first `NOT STARTED` or `IN PROGRESS` document.
- No tracker and no `docs/` content (an empty folder): new product. Ask for the product name and a one-line description, then copy the template package into `docs/`.
- No tracker but `docs/` already holds design material: existing work. Archive it to `docs/_archive/<date>-pre-template/`, overlay the templates, then migrate the archived content into the new structure.

If you are unsure which applies, ask: "Is this a new product, or are you continuing previous work?"

Check the runtime and optional tooling once per session with `references/runtime.md`. Missing tooling never blocks the process; you facilitate single-handed.

### Step 2: Conduct the Facilitation

Read `references/facilitation-rules.md` and `references/facilitation-process.md`, and follow the document order in `references/document-sequence.md`. `docs/TODO-DESIGN-PACKAGE.md` is the operational resume point. For each facilitated document:

1. Read the HTML comment at the top of the document; it holds the facilitation guide with structured question rounds.
2. Ask the questions one round at a time, one question at a time.
3. Listen and probe; follow-up questions are more valuable than the scripted ones.
4. Synthesize the user's answers into the document sections using their own language, and read the section back for confirmation.
5. Update the tracker status when the document is done.

### Step 3: Design Foundation Checkpoint and Soul DRAFT

After Phases 1 and 2, verify the Design Foundation Checkpoint in the tracker: vision, scope and metrics exist; at least one completed interview artifact exists; journeys, JTBD and moments that matter exist. If anything is missing, say what, and ask whether to create it now or proceed with the risks listed. Then facilitate the soul DRAFT pass with `references/soul-file.md`, creating `SOUL.md` at the project root from `<skill-dir>/assets/templates/SOUL.md`.

### Step 4: Phases 3 to 5

Continue through requirements, experience design and the design challenge brief, checking each document against the draft soul as it is written. Do not start the prototype until the user approves the brief.

### Step 5: Soul RATIFY and Design Complete Checkpoint

Once the brief is approved, facilitate the soul RATIFY pass with `references/soul-file.md`. Then verify the Design Complete Checkpoint in the tracker: all design documents complete, brief reviewed and approved, creative direction agreed.

### Step 6: Create the Prototype

Read `references/prototype-outputs.md`. Help the user choose one of four outputs, check its prerequisites, read the matching guide in `docs/06-prototype/`, and build it from everything documented in Phases 1 to 5.

## Quality Checklist

- [ ] Every completed document uses the user's own language, not generic template text
- [ ] The forces map uses the Moments Framework (Push, Pull, Anxiety, Habit)
- [ ] JTBD uses the canonical format: "When [situation], I want to [motivation], so I can [outcome]"
- [ ] Journey maps include struggling moments with severity ratings
- [ ] User stories include priority (P0/P1/P2) and dependencies
- [ ] Acceptance criteria are testable (Given/When/Then)
- [ ] The tracker status matches actual document completion
- [ ] Both checkpoints reflect the current pass or fail state
- [ ] No effort is described in time; use phases, priority and complexity
