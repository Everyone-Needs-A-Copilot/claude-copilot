# Soul Retrofit

Retrofits a soul file (SOUL.md) onto an EXISTING project or product that already has documentation and/or a codebase. Analyzes existing docs and the code surface to draft as much of the soul as the evidence supports, identifies what only the owner knows, interviews to close those gaps, and writes a ratified SOUL.md to the target project root.

## Overview

This skill creates a **soul file** for a product that already exists. Unlike the new-project flow (which interviews from a blank page across two passes — see `soul-file.md`), a retrofit starts from evidence: the project's docs and its code already encode most of what the product *is*. The work is to mine that evidence into a draft, find the gaps only the owner can fill, and close them with the minimum number of questions.

**Point it at any repo.** The owner names a target project; you read its real files and produce `SOUL.md` at that project's root.

### Read these first
- `assets/templates/SOUL.md` — the 10-section structure you will fill. **Do not restate it here; fill it.**
- `soul-file.md` — the per-section interview questions, synthesis rules, and Define-Done bar. The retrofit interview (Step 3) draws from the same question bank; this skill only adds *which* questions to ask given what analysis already answered.

### Define Done
- [ ] Target project's docs and code surveyed; evidence captured
- [ ] Draft soul produced, with inferred content clearly marked
- [ ] Gap list produced — exactly which sections/fields evidence could not determine
- [ ] Owner interviewed to close gaps (one question at a time)
- [ ] `SOUL.md` written to the **target project root**, ratified with a date and a v1.0 changelog entry
- [ ] Meets the soul-file Define-Done bar in `soul-file.md` (every principle testable, every anti-pattern named, Feature Filter usable in under a minute, IS / IS-NOT populated)

---

## The Flow

```
STEP 1  Analyze   → read docs + survey code → DRAFT soul (mark inferences)
STEP 2  Gap-find  → list what evidence could NOT determine (owner-only knowledge)
STEP 3  Interview → ask the MINIMUM questions to close the gaps, one at a time
STEP 4  Synthesize→ write SOUL.md to target root, ratified, v1.0 changelog
```

The balance between Steps 1 and 3 depends on how rich the project's docs are (see "Calibrating to Doc Richness" at the end).

---

## STEP 1 — Analyze

Goal: extract a draft soul from what already exists. Read for evidence of each of the 10 sections; infer what you reasonably can; **mark every inference** so the owner can confirm or correct it.

### Read the documentation
Look for, in roughly this priority:
- `README.md` (root and `docs/`) — the product's own pitch of what it is
- Any vision / PRD / strategy doc, `docs/`, `CLAUDE.md` or `AGENTS.md`, `ECOSYSTEM` entry
- Roadmaps, changelogs, and issue templates — these reveal what's been said yes/no to
- Marketing copy or landing pages in-repo — reveals voice and positioning

### Survey the codebase
Documentation says what the product *intends*; code says what it *does*. Reconcile both.
- **Entry points** — `package.json` scripts, `main`/`bin`, route files, CLI commands, MCP tool definitions. These reveal the real feature surface.
- **Feature surface** — top-level modules/directories, command names, API endpoints, exported tools. What can a user actually *do*?
- **Naming** — the words the code uses for its core entities are the product's real vocabulary (feeds Section 7 voice and the IS / IS-NOT table).
- **What's conspicuously absent** — a relationship tool with no "send email" feature is telling you a boundary. Absences are evidence of anti-patterns the team already avoids.

```bash
# Orient fast in the target repo (replace <target>):
ls -la <target>
cat <target>/README.md 2>/dev/null
ls <target>/docs 2>/dev/null
cat <target>/package.json 2>/dev/null   # scripts, bin, description
# Map the feature surface:
ls <target>/src <target>/app <target>/lib 2>/dev/null
```

### Draft the soul
Fill `assets/templates/SOUL.md` as far as the evidence supports. For each inferred item, mark it so it's unmistakably a guess to confirm:

```
**Soul statement:** <!-- INFERRED from README + CLI commands; CONFIRM -->
[your best synthesis]
```

Expect to get furthest on the **evidence-rich** sections and stall on the **owner-only** ones:

| Usually inferable from evidence | Usually owner-only (gaps) |
|---|---|
| §1 The Job (from README / use cases) | §3 the *rejection* test behind each principle |
| §2 soul statement, feature surface, half the IS/IS-NOT | §4 Anti-Patterns (the *named* failure modes) |
| §3 candidate principles (the values) | §2 the IS-NOT boundaries the owner refuses |
| §5 the gates (from how features cluster) | §5 the priority order when principles conflict |
| §6 visible quality conventions | §9 Founding Decisions |
| §7 voice (from existing copy) | §8 what counts as drift for *this* owner |

---

## STEP 2 — Identify Gaps

Produce an explicit list of what analysis could **not** determine. Be precise — this list becomes the interview agenda, and a short, sharp gap list is the whole point of retrofitting (don't re-ask what the code already told you).

For each gap, name the section, the missing field, and why evidence can't supply it. The gaps are almost always the things only the founder knows:

- **Anti-patterns** — code shows what the product *does*, never the tempting-but-wrong futures the owner is steering away from.
- **The IS-NOT boundaries** — what the product deliberately refuses, especially when it would be easy and profitable to add.
- **Principle rejection tests** — the values are visible; the *line each value draws* (the feature it kills) usually isn't.
- **Priority order** — which principle wins when two collide.
- **Founding Decisions** — the settled calls and their rationale.
- **Drift signals** — what *this owner* would count as losing the soul.

Present the gap list to the owner before interviewing: "Here's the draft I pulled from your docs and code. Here's exactly what I couldn't determine without you — [N] things. Let's close them."

---

## STEP 3 — Interview

Close the gaps with the **minimum** set of questions, one at a time, warm-facilitator style (`facilitation-process.md`). Do not re-interview what Step 1 already answered — confirm those quickly ("I read this as X — right?") and spend the conversation on the gaps.

Use the full per-section question bank in `soul-file.md`. Below is the **prioritized gap-closing subset** — the questions that close owner-only gaps, in the order that gives the most leverage:

### Priority 1 — Anti-Patterns (§4) and the rejections behind principles (§3)
*These are the highest-value gaps and the hardest to infer.*
- "Picture this product in five years, ruined — still running but you hate what it became. What did it turn into?" → names anti-patterns.
- "What's the reasonable-sounding feature request that would start that rot?" → the drift.
- "Give that failure mode a name you'd say out loud." → the name.
- "Tell me a feature a competitor has that you'd **refuse** to build — why?" → the rejection test behind a principle.
- "Finish this three times: 'We reject ___.'"

### Priority 2 — IS-NOT boundaries (§2)
- "People assume this is basically a [adjacent product the code resembles]. What is it that you're NOT?" — ask per confusion; each fills an IS / IS-NOT row.
- "What would be easy and profitable to add that you refuse to? Why?"

### Priority 3 — Conflict order and Founding Decisions (§3, §9)
- "Name two principles that could point opposite ways on a real feature. When they fight, which wins?"
- "Which calls about this product are SETTLED — the ones you don't want reopened? What tension does each resolve?"

### Priority 4 — Drift signals and confirmations (§8, and confirming inferred §1/§2/§5/§7)
- "What's the earliest outside sign you'd be drifting toward one of those failure modes?"
- Confirm the inferred items: read each back, get a yes or a correction.

Seed the **case-law table (§5)** during the interview by walking real history: "Walk me through the last few features you said yes to — and no to. Which gate decided each, and why?" Borderline calls make the best rows.

---

## STEP 4 — Synthesize & Write

1. Merge inferred (confirmed) content with interview answers into the full `assets/templates/SOUL.md` structure. Remove the `INFERRED / CONFIRM` markers once
   confirmed; keep `<!-- TODO -->` on anything still genuinely open.
2. Apply the soul-file **synthesis rules** from `soul-file.md`: owner's own words; every principle carries a concrete rejection test; every anti-pattern named; case law from real decisions; IS / IS-NOT rows that settle real confusions.
3. Verify against the **Define Done** bar in `soul-file.md`. If the Feature Filter isn't usable in under a minute, or a principle has no rejection, it's not done — go back to Step 3 for that gap.
4. Write `SOUL.md` to the **target project root** (not inside its `docs/`).
5. Ratify with the owner: walk the whole file, get explicit agreement, set the status line to **RATIFIED v1.0** with today's date, and add the changelog row:

   ```
   | <date> | v1.0 | Retrofitted soul. Drafted from existing docs + code survey; gaps closed with the owner and ratified. |
   ```

---

## Calibrating to Doc Richness

The retrofit shifts weight between analysis and interview depending on what exists:

| Project state | Approach |
|---|---|
| **Rich docs** (vision/PRD, design docs, mature README) | Lean hard on Step 1. Draft most sections from evidence. Interview only to close the owner-only gaps (anti-patterns, IS-NOT, priority order, founding decisions) and to confirm inferences. Short conversation. |
| **Thin docs** (sparse README, code only) | Code survey still yields the feature surface, vocabulary, and boundaries-by-absence — but the *why* is missing. Interview-heavy: this looks close to the new-project flow in `soul-file.md`. Use that flow's full question bank, informed by what the code already revealed. |
| **No docs, early code** | Treat as near-greenfield. Run essentially the new-project DRAFT pass, using the code only to ground vocabulary and the feature surface. Expect to interview most sections. |

In all cases the output is identical: a ratified `SOUL.md` at the project root that passes the Define-Done bar.

---

**Related:** [Soul template](../assets/templates/SOUL.md) | [Soul file reference](soul-file.md) | [Facilitation process](facilitation-process.md)
