# Session Flow, Phase Transitions, and Prototype Output

## Getting started

When the user starts a new session, check their state:

1. Does `docs/TODO-DESIGN-PACKAGE.md` exist in their project? If not, this is a new product or existing work: follow `setup-and-resume.md`. Directories such as `docs/01-architecture/` or `docs/40-initiatives/` belong to the project's own framework scaffolding, not to the design package, so do not treat their presence as previous design work.
2. If `docs/TODO-DESIGN-PACKAGE.md` exists, read it to find where they left off.
3. Is there an active document marked IN PROGRESS? Resume from the session break point.

If uncertain, ask: "Is this a new product or are you continuing previous work?"

## Session management

- Primary resume point: `docs/TODO-DESIGN-PACKAGE.md`.
- When pausing mid-document: synthesize what has been discussed, mark the document IN PROGRESS, and add `<!-- SESSION BREAK: Completed through Round [X]. Resume at Round [Y]. -->`.
- When resuming: read the tracker, find the first NOT STARTED or IN PROGRESS document, and brief the user on where they are before asking anything.
- Specialists, task tracking and memory depend on the runtime; see `runtime.md`.

## Phase transitions

After each phase completes, brief the user on what comes next before starting:

| Transition | What to Say |
|------------|------------|
| Phase 1 → 2 | "Vision is set. Now we research, starting with a self-interview about who your users are." |
| Phase 2 → soul DRAFT | "Service design is done. Before requirements, we'll distill the product's soul: a decision instrument that captures what this product is and refuses to be, and a filter every future feature has to pass." |
| Phase 2 → 3 | "Soul is drafted. Now we turn those insights into requirements, and we'll check every decision against the soul as we go." |
| Phase 3 → 4 | "Requirements done. Now experience design: UX, UI, and voice." |
| Phase 4 → 5 | "Experience design done. Last step before prototype: the design challenge brief." |
| Phase 5 → soul RATIFY | "Brief is approved. Now we ratify the soul, locking the feature filter and founding decisions with the real calls we've made across every phase." |
| Phase 5 → 6 | "Soul is ratified. Time to create your prototype. What format do you want?" |

## Prototype output

After Phase 5, the user chooses their output format. Details and prerequisites are in `prototype-outputs.md`.

## Requests to honor at any point

| The user says... | Do this |
|------------------|---------|
| "Let's pause here and save progress" | Synthesize what has been discussed into the current document, mark it IN PROGRESS, add the SESSION BREAK marker, update the tracker, and tell the user how to resume (run the skill again in this folder, or say "Check docs/TODO-DESIGN-PACKAGE.md for where I left off"). |
| "I want to start over" | Archive the current `docs/` with the Path 2 archive command in `setup-and-resume.md` so nothing is lost, verify the archive, then ask the user to confirm before clearing everything in `docs/` except `_archive/`, and restart from Path 1. Leave a root `SOUL.md` in place unless the user asks to archive it too. |
| "I'm stuck" or an unfamiliar error | Name the exact state (current document, round and tracker status), explain in plain words, and offer the next step. |

## Tips to share with first-time users

- Answer in your own words; natural language gives the best synthesis.
- Saying "I don't know" is useful: it is captured as an open question and the process keeps moving.
- You can pause at any time and resume later in a new session.
- Each phase builds on the last; skipping is allowed, but staying with the sequence gives richer results.
- Earlier answers can be revisited when something changes.
