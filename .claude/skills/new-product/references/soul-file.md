# Soul File Reference

How to facilitate the creation of a product's **soul file** (`SOUL.md`) — the per-product decision instrument that decides whether a feature belongs in the product by staying true to its purpose.

This is the companion to the template at `assets/templates/SOUL.md`. Read both before facilitating. For retrofitting a soul onto an existing project that already has docs or code, use `references/soul-retrofit.md` instead.

---

## What the Soul File Is (and Isn't)

The soul file is a **decision instrument**, not a vision statement. Its single job: let a human — or an AI agent — decide, in under a minute, whether a proposed feature belongs in this product.

| It IS | It IS NOT |
|-------|-----------|
| A filter that produces in/out verdicts | A mission poster or brand manifesto |
| Made of testable principles and named traps | A list of aspirational adjectives |
| Living — drafted, ratified, versioned | A one-time deliverable signed off and shelved |
| A root-level artifact (`SOUL.md`) | A doc buried in `docs/` |

The gold-standard reference for structure and voice is Convoco's `SOUL.md`. Study how every principle carries a *rejection test*, every anti-pattern is a *named* failure mode with early-warning phrases, and the Feature Filter has sequential gates plus a case-law table of real verdicts.

---

## Where It Sits in the Flow: Draft Early, Refine Late

The soul file is created in **two passes**, not one. This is deliberate: the soul must exist early enough to steer the work, but the hardest calls can only be made once the work is concrete.

```
Phase 1: Discovery
Phase 2: Research & Service Design
  └── DESIGN FOUNDATION CHECKPOINT
        ▼
   ░░ SOUL — DRAFT PASS (v0.1) ░░   ← draft SOUL.md now; it guides Phases 3–5
        ▼
Phase 3: Requirements
Phase 4: Experience Design
Phase 5: Design Challenge (brief)
        ▼
   ░░ SOUL — RATIFY PASS (v1.0) ░░  ← lock it before the prototype is built
        ▼
   └── DESIGN COMPLETE CHECKPOINT
Phase 6: Prototype
```

### DRAFT pass — after Phase 2

**Why here:** Vision, scope, JTBD, journeys, and moments-that-matter now exist. That's enough raw material to state what the product *is* and what it refuses to be — so the soul can act as a north star while requirements, UX, UI, and the brief are written. Every later document should be checkable against the draft soul.

**What this pass fills (as much as the evidence supports):**
- **Section 1 (The Job)** — lift from `docs/02-service-design/30-jtbd.md` and the journey maps.
- **Section 2 (The Essence)** — soul statement, deeper aim, and a first IS / IS-NOT table from the vision's non-goals and "what this is NOT."
- **Section 3 (Design Principles)** — the principles, each with a rejection test.
- **Section 4 (Anti-Patterns)** — named failure modes, seeded from the vision's regression triggers and the scope doc's non-goals.
- **Section 5 (Feature Filter)** — the gates. Leave the case-law table mostly empty; seed only verdicts already obviously decided.
- **Sections 6–8** — first-draft quality bar, voice, and success signals (these get sharper after Phase 4).

Mark the status line **DRAFT v0.1** and add the v0.1 changelog row. Leave **Section 9 (Founding Decisions)** as open questions for now.

### RATIFY pass — after Phase 5

**Why here:** The design challenge brief is done. The hard trade-offs are no longer hypothetical — you've made real calls about what's in the prototype and what isn't. Now the case law and founding decisions can be filled concretely.

**What this pass does:**
- **Section 5 case-law table** — populate it with the real in/out verdicts made across Phases 3–5. Borderline calls are the most valuable rows.
- **Section 9 (Founding Decisions)** — convert the open questions into settled, dated calls. Resolve every principle conflict (the priority order) and every anti-pattern boundary.
- **Re-test Sections 3 & 4** — after building the brief, does any principle lack a real rejection? Does any anti-pattern not match a real temptation you faced? Fix them.
- **Sections 6–8** — tighten the quality bar against the moments-that-matter A+ states and the voice against `docs/04-experience-design/70-copy-voice.md`.

Walk the owner through the whole file, get explicit agreement, mark the status **RATIFIED v1.0** with the date, and add the v1.0 changelog row. The soul is now the working decision instrument.

---

## Facilitation Technique

Use the same one-question-at-a-time technique as the rest of the process (see `facilitation-process.md`): ask one question, wait for the full answer, probe with "why" and "what does that look like," name what you heard, use the owner's own words in synthesis. The soul file lives or dies on specificity — a vague soul is no soul.

Three sections are notoriously hard to get right. The owner will reach for platitudes; your job is to push past them:

- **Design Principles** must produce a *rejection test*, not a value everyone shares.
- **Anti-Patterns** must *name* the failure mode, not gesture at "bad versions."
- **Feature Filter case law** must come from *real* decisions, not invented examples.

The probing questions below are tuned to break those three open.

---

## Interview Questions by Section

Ask these conversationally, adapting to what earlier documents already answered. Skip anything the vision or service-design docs already settled — reference it and go deeper instead of re-asking.

### Section 1 — The Job
- "Take me to the exact moment someone needs this. Where are they, what just happened, what are they dreading?"
- "What's the trade-off they're forced to make today, before this product exists?"
- "Besides the main user, whose experience does this product change? Who's on the other side of it?"
- *Synthesis:* state the job in JTBD form ("When… they want to… so they can…"), pulling the JTBD doc forward.

### Section 2 — The Essence
- "In one sentence: what does this product fundamentally do, that nothing else does for this person?"
- "Beneath the obvious outcome — what bigger thing becomes true in their life if this works?"
- "If this product were a person walking into the room, who are they? How do they behave?"
- "Now the opposite — what kind of product are you deliberately refusing to build? Who's the version of this you'd be ashamed of?"
- "People will assume this is basically a [adjacent product]. What is it that you are NOT?" — *ask this several times to fill the IS / IS-NOT table; each confusion is a row.*
- *Probe for the key boundary:* "Where does this product look most like a competitor but behave completely differently? Under what condition is that borderline thing allowed?"

### Section 3 — Design Principles (get a rejection test, not a platitude)
- "Tell me a feature a competitor has that you would **refuse** to build — even if users asked for it. Why?" → *the refusal is the seed of a principle.*
- "What's a decision you'd make that a reasonable, profit-minded person would call stupid? Why is it right for this product?"
- "Finish this: 'We reject ___.' Give me three." → *each becomes a principle's Rejection line.*
- For each candidate principle: "Give me a feature this principle KILLS. If it doesn't kill anything, it's decoration — what's the real one underneath it?"
- "Hand me this principle as a one-breath question I can ask of any feature, with a clear pass or fail." → *that's the Test line.*
- *Conflict:* "Name two of your principles that could point in opposite directions on a real feature. When they fight, which wins?" → *seeds the priority order and a Founding Decision.*

### Section 4 — Anti-Patterns (name the failure mode)
- "Imagine this product five years from now, ruined — still running, but it's become something you hate. What did it turn into?"
- "What's the *reasonable-sounding* feature request that would start that rot? It always begins as a good idea."
- "Give that failure mode a name you'd actually say in a meeting." → *e.g. 'The Closer,' 'The Spreadsheet With Feelings.'*
- "What exact words or requests would tip you off that it's happening?" → *the Early-warning phrases.*
- "What's the line you will not cross to prevent it?" → *the Line in the sand.*
- *Seed from prior docs:* mine the vision's "Warning Signs / Regression Triggers" and the scope doc's non-goals — those are anti-patterns waiting to be named.

### Section 5 — Feature Filter
- "What's the very first question you'd ask of ANY feature idea — the one that kills most bad ideas fastest?" → *Gate 1.*
- "What's the next cheapest question that filters out 'useful but not essential'?" → *Gate 2.*
- *Build the case law from real history:* "Walk me through the last few features you said yes to — and the ones you said no to. For each: which gate decided it, and why?"
- "Tell me a feature you were genuinely torn on. Which way did it go, and what tipped it?" → *borderline rows teach the most.*
- *At ratification:* re-walk every in/out call made across Phases 3–5 and record it as case law.

### Section 6 — Quality Bar
- "What's the difference between this product *working* and this product being *done*? Give me the checklist a release has to pass."
- "What's a quality test you can't reduce to a checkbox but you'd still catch instantly?" → *the Taste test.*
- "When quality slips here, what does the symptom look like?" → *the failure-modes table.*

### Section 7 — Voice & Tone
- "How does this product talk? If it were the person from Section 2, what's its voice?"
- "Give me a real sentence this product would say — and the tempting, off-voice version of the same sentence." → *each pair is a We Say / We Don't Say row.*
- "Where does the tone need to shift — errors, empty states, sensitive moments?"

### Section 8 — Success Signals
- "What would you be thrilled to overhear a user say? Their exact words." → *positive signals.*
- "What's the earliest sign — observable from outside — that you're drifting toward one of your anti-patterns?" → *drift signals; these must fire early, not in the autopsy.*
- "When that sign fires, what question gets you back to true?" → *recovery questions.*

### Section 9 — Founding Decisions (ratify pass)
- "Of everything we've discussed, which calls are now SETTLED — the ones future-you isn't allowed to casually reopen?"
- "For each: what tension does it resolve?" — *tie each to a principle, an anti-pattern, or a boundary.*
- "Confirm the priority order when principles conflict." — *record it; date it.*

---

## Synthesis Rules (specific to the soul file)

1. **Use the owner's own words.** A principle in the owner's voice beats a polished one in yours. Soul files die when they sound like a consultant wrote them.
2. **Every principle MUST carry a concrete rejection test.** If you can't name a feature the principle kills, the principle is decoration. Do not write it — push the owner for the real one underneath.
3. **Name every anti-pattern memorably.** A failure mode with a name ("The Megaphone") gets caught in conversation; an abstract warning doesn't. If it has no name, it isn't done.
4. **Seed the case-law table from real decisions.** Mine Phases 1–5 for in/out calls already made — the non-goals, regression triggers, scope cuts, and brief trade-offs are case law waiting to be recorded. Don't invent example features.
5. **Make the IS / IS-NOT table do work.** Each row should settle a real, tempting confusion — the adjacent product people will assume this is. Vague rows ("good, not bad") are useless.
6. **Keep the instrument crisp even though the process is warm.** Facilitate gently; write tersely. The filter has to be usable under time pressure by someone who didn't sit in the interview.
7. **Don't invent to fill a section.** If a section can't be earned from evidence yet, leave the `<!-- TODO -->` and surface it at the ratify pass.

---

## Define Done — Soul File Quality Bar

The soul file is done (RATIFIED) when **all** of these are true:

- [ ] **Section 1** states the struggling moment in the user's own words, with everyone the job touches.
- [ ] **Section 2** has a one-sentence soul statement and an IS / IS-NOT table where every row settles a real confusion.
- [ ] **Section 3**: every principle has a Meaning, a concrete **Rejection** (a feature it kills), and a one-breath **Test**. No platitudes.
- [ ] **Section 4**: every anti-pattern is **named**, with early-warning phrases and a line in the sand.
- [ ] **Section 5**: the Feature Filter is usable by a stranger in **under a minute**, and the case-law table holds real in/out verdicts (including at least one borderline call).
- [ ] **Section 6** non-negotiables are each checkable (yes/no, not "sort of").
- [ ] **Section 7** We Say / We Don't Say pairs are concrete strings, not categories.
- [ ] **Section 8** drift signals fire early enough to act on.
- [ ] **Section 9** Founding Decisions are settled and **dated**, including the priority order when principles conflict.
- [ ] **Section 10** changelog shows the DRAFT (v0.1) and RATIFIED (v1.0) entries with dates and rationale.
- [ ] The file lives at the **project root** as `SOUL.md`, and the status line reads **RATIFIED v1.0**.

If a simple product scaled sections down, that's fine — but the Feature Filter and the IS / IS-NOT table are never optional. They are the instrument.

---

**Related:** [Soul template](../assets/templates/SOUL.md) | [Soul retrofit skill](soul-retrofit.md) | [Facilitation process](facilitation-process.md) | [Document sequence](document-sequence.md)
