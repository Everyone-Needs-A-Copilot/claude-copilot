# {{PRODUCT_NAME}} — SOUL

> **The decision instrument. When in doubt, consult this file.**
> This is not a vision statement or a mission poster. It is the tool you use to
> decide whether a proposed feature *belongs* in this product — by staying true
> to its purpose.
>
> **How to use it:** Run any feature, request, or "wouldn't it be cool if…"
> through **Section 5: Feature Filter**. Pass the gates in order. If a feature
> can't survive the filter in under a minute, the answer is **no**.
>
> **It is living.** This file is DRAFTED early (right after the service-design
> phase, so it can act as a north star for everything that follows) and
> RATIFIED later (after the design challenge brief, when the hard calls are
> concrete). It changes only when real evidence says the product changed — and
> every change is logged in **Section 10: Evolution**.
>
> For deeper context, this file sits on top of `docs/00-overview/00-vision.md` —
> the vision explains *what* the product is; the soul decides *what is allowed
> to exist in it*.

> **STATUS: DRAFT / RATIFIED — vX.X.**
<!-- TODO: While drafting (after Phase 2), mark this DRAFT v0.1. When ratified with the
     owner (after Phase 5), mark RATIFIED v1.0 and add the date. See Section 10. -->

<!--
USING THIS TEMPLATE
===================
- This file lives at the PROJECT ROOT as `SOUL.md` — not inside docs/. It is a
  living, root-level artifact you consult whenever a feature decision comes up.
- Fill each section by interview, one question at a time. The full facilitation
  guide — interview questions per section, synthesis rules, and the Define-Done
  bar — is in the new-product skill's `references/soul-file.md`. Read it before facilitating.
- Every italic line under a heading states what the section is FOR and the test
  it must pass. Delete the italics once the section is real if you like; keep
  the discipline.
- Mark anything you couldn't determine yet with `<!-- TODO: ... -->`.
- Default to the FULL 10-section structure below. A genuinely simple product may scale sections down (e.g. 3 principles instead of 5, no priority-order conflict table) — but never drop the Feature Filter or the IS / IS-NOT table. Those two are the instrument. -->

---

## 1. The Job

*What this section is for: the struggling moment this product exists to resolve, in the user's own words. Test it must pass: a stranger reading only this section understands who is hurting and why, with no feature talk.*

<!-- TODO: Write the core job in Jobs-to-be-Done form. Pull from docs/02-service-design/30-jtbd.md
     if it exists. Keep the user's language. -->

**When** [situation the user is in], **they want to** [motivation — what they're trying to do], **so they can** [the deeper outcome they're really after].

**The struggling moment:**
<!-- TODO: Describe the specific, felt moment of friction this product eliminates.
     One vivid paragraph. The trade-off the user is forced to make today. -->

**Who this serves:**

<!-- TODO: List the people in the job — not just the buyer/primary user, but everyone
     whose experience the product changes. Pull from the personas in the journey maps. -->

| User | What they need |
|------|---------------|
| **[Primary user]** (primary) | |
| **[Secondary party]** | |
| **[The user over time]** | |

---

## 2. The Essence

*What this section is for: the one-line soul of the product, and a hard boundary of what it is and is not. Test it must pass: the IS / IS-NOT table is specific enough that two people would sort the same borderline feature the same way.*

**Soul statement:**
<!-- TODO: One sentence. What this product fundamentally does and for whom — the thing
     that would remain if everything else were stripped away. Not a tagline; a decision. -->

**The deeper aim:**
<!-- TODO: The outcome beneath the outcome. If the product works, what becomes true in
     the user's life or work that is bigger than the immediate task? -->

**As a person, this product would be:**
<!-- TODO: Describe the product as a character — the kind of person it is when it shows up.
     This anchors voice (Section 7) and reveals the soul faster than abstractions. -->

**Would NOT be:**
<!-- TODO: The opposite character — the version of this product you are deliberately
     refusing to build. Naming the anti-character sharpens the real one. -->

<!-- TODO: Fill the IS / IS-NOT table. Each row is a real, tempting confusion — the thing
     people will assume this product is. The right-hand column is the adjacent product it
     is NOT. This table does more decision-making than any other part of this file. -->

| It IS | It IS NOT |
|-------|-----------|
| | |
| | |
| | |

**Key boundary — read this twice:**
<!-- TODO: State the single most-confused boundary in plain language — the place where
     this product looks like a neighbour but behaves differently, and the condition under
     which a borderline capability is allowed. This is the line people will push on. -->

---

## 3. Design Principles

*What this section is for: 3–5 named principles that actively reject features. Test each must pass: it produces a concrete **rejection** (a feature it kills), not a sentiment everyone already agrees with. If a principle offends no one, it is decoration — cut it.*

<!-- TODO: Write 3–5 principles. Each MUST have all three parts below. The Rejection line
     is the load-bearing one: if you can't name something the principle refuses, the
     principle isn't real yet. See soul-file.md for the interview that surfaces these
     ("Tell me a feature a competitor has that you'd refuse to build — why?"). -->

### Principle 1: [Name it memorably]
**Meaning:** <!-- TODO: What this principle commits the product to. One or two sentences. -->
**Rejection:** <!-- TODO: "We reject ___." Name the specific feature/behaviour this kills. -->
**Test:** <!-- TODO: A question you can ask of any feature in one breath, with a clear pass/fail. -->

### Principle 2: [Name it memorably]
**Meaning:** **Rejection:** **Test:**

### Principle 3: [Name it memorably]
**Meaning:** **Rejection:** **Test:**

<!-- TODO: Add Principle 4 and 5 only if they earn their place. More is not better. -->

### When Principles Conflict
*Settle the priority order in advance, so a live argument doesn't have to.*

<!-- TODO: When two principles point in opposite directions on a real feature, which wins?
     State the order. Mark which principles are load-bearing and which yield. This is a
     Founding Decision (Section 9) — fill it at ratification if not before. -->

Priority order: **[Principle] > [Principle] > [Principle] > …**

---

## 4. Anti-Patterns

*What this section is for: 3–5 named failure modes — the specific ways this product could rot into something worse. Test each must pass: it has a **name** you'd actually say out loud in a meeting, and **early-warning phrases** that let you catch the drift before it ships.*

<!-- TODO: Name each failure mode like a character or a trap ("The Closer," "The Spreadsheet
     With Feelings"). For each: the seductive drift (it always starts as a reasonable idea),
     why it kills the product, the phrases that signal it's happening, and the line you won't
     cross. Seed these from the regression triggers / non-goals in the vision and scope docs. -->

### [The Named Failure Mode]
**Drift:** <!-- TODO: The plausible, tempting version of the bad idea — how it sneaks in. -->
**Why it kills us:** <!-- TODO: What essential thing the product loses if this wins. -->
**Early warning:** <!-- TODO: The exact words/requests that signal this drift. List them. -->
**Line in the sand:** <!-- TODO: The non-negotiable counter-commitment. -->

### [The Named Failure Mode]
**Drift:** **Why it kills us:** **Early warning:** **Line in the sand:**

### [The Named Failure Mode]
**Drift:** **Why it kills us:** **Early warning:** **Line in the sand:**

<!-- TODO: Add a 4th and 5th anti-pattern only if they name a genuinely distinct trap. -->

---

## 5. Feature Filter

*What this section is for: the actual instrument. Sequential gates plus a growing table of real verdicts. Test it must pass: a person who has never seen this product can run a proposed feature through it and reach the same in/out verdict you would — in under a minute.*

<!-- TODO: Write 2–4 gates. Order them cheapest-to-evaluate first so most bad ideas die
     fast. The last gate should always be the Anti-Pattern check. Each gate is a single
     question with an explicit "if no / if yes → stop" rule. -->

Use these gates **in order**. A feature must pass **all** of them.

### Gate 1: [Name] Test
> "[The question.]"

<!-- TODO: State what a failure means and the action. e.g. "If it only moves data → it
     belongs in a different product. Stop." -->

### Gate 2: [Name] Test
> "[The question.]"

<!-- TODO: e.g. "If it doesn't touch the struggling moment → may be useful, not essential.
     Deprioritise." -->

### Gate 3: Principle Test
> "Does it survive every principle in Section 3?"

One violation → redesign or reject.

### Gate 4: Anti-Pattern Test
> "Does building this drift toward any named anti-pattern in Section 4?"

If yes → reject, or redesign until it doesn't.

### Case Law (In / Out)

*Real verdicts, recorded as you make them. This table is how the filter gets smarter and how future arguments get settled by precedent. Seed it at ratification with decisions already made in earlier phases; grow it forever after.*

<!-- TODO: Each row is a real feature you said yes or no to, the gate that decided it, and
     the one-line reason. Include borderline calls — those teach the most. The strongest
     "IN" rows are features where holding the line IS the product's soul. -->

| Feature | Verdict | Gate | Reasoning |
|---------|---------|------|-----------|
| | **IN** | | |
| | **IN** | | |
| | **OUT** | | |
| | **OUT** | | |

---

## 6. Quality Bar

*What this section is for: the line between "functional" and "done" for this product. Test it must pass: each item is checkable — someone could look at the product and say yes or no, not "sort of."*

**The standard:**
<!-- TODO: One sentence naming the bar this product holds itself to. What does "done,"
     not just "working," mean here? -->

**Non-negotiables:**
<!-- TODO: The checklist every release must pass. Each item concrete and verifiable.
     Pull from the moments-that-matter A+ states and the design principles. -->

- [ ]
- [ ]
- [ ]

**Taste test:**
<!-- TODO: The aesthetic / felt-quality test that can't be reduced to a checkbox but
     still discriminates. "If you have to explain what a screen is for, the design failed."
     Match the product's own design direction (docs/04-experience-design). -->

**Quality failure modes:**

| Failure | Symptom |
|---------|---------|
| | |
| | |

---

## 7. Voice & Tone

*What this section is for: how the product speaks, as a constraint not a suggestion. Test it must pass: the We Say / We Don't Say pairs are specific enough that someone could rewrite a real string correctly from them.*

**Character:**
<!-- TODO: Describe the product's voice as a person (tie back to "As a person…" in Section 2).
     Direct? Warm? Playful? Spare? Name what it never sounds like. -->

**Language rules:**
<!-- TODO: Pairs of real phrasings. Left = on-voice. Right = the tempting, off-voice version
     (jargon, hype, salesiness, whatever this product refuses). Make them concrete strings,
     not categories. Pull from docs/04-experience-design/70-copy-voice.md if it exists. -->

| We Say | We Don't Say |
|--------|--------------|
| | |
| | |
| | |

**Tone shifts:**
<!-- TODO: How the voice flexes by context — empty states, errors, success, sensitive moments.
     One row per context that matters. -->

| Context | Tone |
|---------|------|
| | |
| | |

---

## 8. Success Signals

*What this section is for: how you know you're keeping — or losing — the soul, from outside the building. Test it must pass: positive signals are quotes you'd be thrilled to overhear; drift signals are early enough to act on, not autopsies.*

**Positive signals (we're on track):**
<!-- TODO: Real things users (and the people they affect) would say if the product is being
     true to itself. Write them as overheard quotes, not metrics. -->

- "…"
- "…"
- "…"

**Drift signals (we're losing the soul):**
<!-- TODO: Early observable symptoms that the product is rotting toward an anti-pattern.
     Each paired with what it means. These should fire BEFORE damage is done. -->

| Signal | What it means |
|--------|---------------|
| | |
| | |

**Recovery questions:**
<!-- TODO: 2–3 questions to ask when a drift signal fires, to get back to true. -->

1. 2.

---

## 9. Founding Decisions

*What this section is for: the calls that are settled, so they never have to be re-litigated. Test it must pass: each entry resolves a real tension (often an anti-pattern or a principle conflict) and is dated.*

<!-- TODO: List the decisions this whole instrument rests on — the ones the owner has
     ratified and that future-you is not allowed to casually reopen. Each should reference
     the principle, anti-pattern, or boundary it settles. Fill these at the RATIFY pass.
     This section replaces the open-questions scaffolding once the soul is locked. -->

The settled calls this instrument is built on. Ratified with the owner <!-- TODO: DATE -->.

1. **[Decision].** <!-- TODO: What was decided and what it resolves. -->
2. **[Decision].**
3. **[Priority order is settled:** [Principle] > [Principle] > … ] <!-- if applicable -->
4. **[The anti-patterns are named and kept:** [names]. ]

---

## 10. Evolution

*What this section is for: proof this is a living instrument, not a poster. Test it must pass: the changelog shows real dates, versions, and the reason each change was made.*

This file changes only when:
- Real user outcomes shift what the product is for
- We learn something durable that contradicts a current principle or boundary
- The product's place in its ecosystem changes (another product takes over a job)

When updated, add the rationale to the changelog below.

### Changelog

<!-- TODO: Record every version. At minimum: a DRAFT entry (after Phase 2) and a RATIFIED
     v1.0 entry (after Phase 5). Newest first. -->

| Date | Version | Change & rationale |
|------|---------|--------------------|
| | v1.0 | Ratified with the owner. <!-- TODO: what got settled at ratification --> |
| | v0.1 | Drafted as root-level decision instrument. Synthesized from vision, scope, JTBD, journeys, and moments-that-matter. |
