# Claude Copilot — SOUL

> **The decision instrument. When in doubt, consult this file.**
> This is not a vision statement or a mission poster. It is the tool you use to
> decide whether a proposed feature *belongs* in this product — by staying true
> to its purpose.
>
> **How to use it:** Run any feature, request, or "wouldn't it be cool if…"
> through **Section 5: Feature Filter**. Pass the gates in order. If a feature
> can't survive the filter in under a minute, the answer is **no**.
>
> **It is living.** It changes only when real evidence says the product changed —
> and every change is logged in **Section 10: Evolution**.

> **STATUS: DRAFT v0.1 — retrofit from documentation; pending owner ratification.** (2026-06-28)
<!-- This was retrofitted from the repo's README, CLAUDE.md, philosophy doc, overview
     card, VERSION.json, and the hooks/agents surface. Inferences are marked
     `<!-- INFERRED FROM DOCS; CONFIRM -->`. Owner-only calls are marked
     `<!-- TODO: owner -->` and must be ratified, not guessed. -->

---

## 1. The Job

*The struggling moment this product exists to resolve, in the user's own words.*

**When** a developer works with Claude Code across many sessions on real, complex software,
**they want to** keep their decisions, process, and context from evaporating every time a session ends — without burning their token budget rebuilding it,
**so they can** do disciplined, resumable, inspectable work instead of starting from zero every morning.

**The struggling moment:**
<!-- INFERRED FROM DOCS (philosophy.md, README "The Problem"); CONFIRM -->
You open Claude Code and it has forgotten everything — your project, your decisions, your context. You explain it again. Tokens burn before any work happens. The advice you get is generic, the process is ad-hoc, and there are no quality gates. Worse: even when you *do* set up a disciplined process, it doesn't get followed — a diagnostic of 15 real sessions found 94% of work stayed in the main session despite a 14-agent roster. Policy in a doc nobody reads changes nothing. The friction isn't a missing feature; it's that memory, discipline, and frugality are not *enforced*, so they don't happen.

**Who this serves:**

| User | What they need |
|------|---------------|
| **Solo developer** (primary) | A full team of specialists, memory that survives sessions, and a process that holds — alone, at 2am, offline. |
| **Teams** | Shared standards that are actually followed, git-native shared knowledge, consistent process across people and projects. |
| **Downstream copilots** (codex-copilot, cli-copilot, product-creation-copilot) | Stable `cc`/`tc` contracts they build on; parity when those contracts change. |

---

## 2. The Essence

**Soul statement:**
<!-- INFERRED FROM DOCS (README, overview oneliner); CONFIRM -->
Claude Copilot is an **instruction layer for Claude Code** — markdown agents, commands, and two local CLIs (`cc`, `tc`) — that makes Claude Code's process **repeatable, inspectable, and stateful**: specialized agents with strict points of view, a design-led protocol enforced by mechanical hooks, persistent memory, and real task/worker orchestration.

**The deeper aim:**
Every developer gets the disciplined process of a strong team — encoded, enforced, and owned by them — without trading away their token budget, their privacy, or their honesty about what AI can actually guarantee.

**As a person, this product would be:**
<!-- INFERRED FROM voice across docs; CONFIRM -->
A precise, unflappable staff engineer who footnotes their own claims. Tells you exactly what is proven and what isn't. Enforces the rule rather than reminding you of it. Never oversells; says "Not magic" out loud.

**Would NOT be:**
A hype-driven platform evangelist who promises "better software," hides the limitations, and asks you to trust a cloud service with your code and your context.

| It IS | It IS NOT |
|-------|-----------|
| An instruction layer (markdown + two local CLIs) on top of Claude Code | Standalone software, a new IDE, or an AI coding platform |
| A process that runs *inside* Claude Code | A hosted service, daemon, or API server (no ports, no inbound endpoints) |
| An orchestrator of Claude Code | An LLM / model provider (it runs no inference) |
| Local- and git-native state (SQLite stores, git knowledge repos) | Cloud or remote state sync |
| A framework for **Claude Code** | A Codex / other-harness framework (that is `codex-copilot`) |
| Honest about measuring **process and context efficiency** | A guarantee of better software — "Not magic" |
| A generic, extendable base | A home for company-specific content (that lives in extensions) |

**Key boundary — read this twice:**
<!-- INFERRED FROM non-goals (overview "What it doesn't do", philosophy "What it is Not"); CONFIRM -->
It looks like a "product" or "platform," but it is an **instruction layer**: files Claude Code reads, plus two local CLIs. A borderline capability is allowed **only if** it can ship as instructions Claude Code reads and/or a local `cc`/`tc` command — *without* becoming standalone software, opening a network service, syncing state to a cloud, or running model inference. The optional `cc mcp serve` shim is the edge of this line: it is a *local stdio* shim, opt-in, and ships **off by default** (`.mcp.json` is empty). The moment a feature needs a daemon, a port, a server, or its own model, it belongs in a different product.

---

## 3. Design Principles

*3–5 named principles that actively reject features.*

### Principle 1: Instruction Layer, Never Software
**Meaning:** Everything ships as markdown Claude Code reads or a local `cc`/`tc` CLI command. The framework orchestrates Claude Code; it never becomes the thing being run.
**Rejection:** We reject any feature that requires a long-running daemon, an inbound network service/port, or running model inference of its own. (Codex-native behavior is rejected here too — it belongs to `codex-copilot`.)
**Test:** "Can this ship as instructions + a local CLI, with no server and no inference?" If no → different product.

### Principle 2: Mechanical Enforcement Over Polite Advice
**Meaning:** The rules that matter are enforced by hooks at runtime — force-delegate, the mandatory QA gate, safety primitives — not left as guidance in a doc. Standards that aren't enforced don't happen (94% of work stayed in the main session when delegation was only advisory).
**Rejection:** We reject "best-practice" features that are merely written down and hoped-for. If a discipline matters, it gets a hook or a gate, not a paragraph.
**Test:** "If this rule is important, what mechanically enforces it — and what's the escape hatch?" No enforcement path → it's decoration.

### Principle 3: Context Is the Budget
**Meaning:** The main session's token budget is the scarce resource. Work is delegated to agents, outputs are externalized to work products (~94% less context for externalized WPs vs inlining), agents return ~100 tokens, not their full reasoning.
**Rejection:** We reject anything that bloats the main session — inlining large outputs, reading the world at startup, agents that dump their transcript back into context.
**Test:** "Does this reduce, or at least not inflate, main-session tokens?" If it inflates context → redesign or reject.

### Principle 4: Honest About What It Measures
**Meaning:** We claim only what we can verify: process discipline and context efficiency. We do **not** claim better software, fewer defects, or speed of delivery — there is no defect/rework data. Self-correcting precision is the house style ("FTS5 keyword search," not "semantic"; "works, unproven at large scale," not "battle-tested").
**Rejection:** We reject any claim of output-quality guarantees, defect reduction, or "produces better software." "Not magic."
**Test:** "Is every claim here something we can measure?" An unverifiable promise → strike the claim, keep the feature.

### Principle 5: Local, Git-Native, Yours
**Meaning:** All state is local SQLite; shared knowledge is a git repo you own. Works offline, no accounts, no managed service. Extend without forking — the base stays generic; company specifics live in extensions/knowledge repos.
**Rejection:** We reject cloud/remote state sync, mandatory accounts, telemetry-by-default, and company-specific content baked into base agents.
**Test:** "Does this work fully offline, keep state local, and leave the base generic?" If it needs the cloud or hard-codes a company → reject or move to an extension.

### When Principles Conflict
*Settle the priority order in advance, so a live argument doesn't have to.*

<!-- TODO: owner — When two principles point opposite ways on a real feature (e.g. a richer
     enforcement hook (P2) that costs main-session context (P3), or a convenience that
     would mean a small always-on local service (P1) vs. frugality), which wins? State the
     order. This is a Founding Decision and must be ratified, not inferred. -->

Priority order: **[ TODO: owner ] > … **

---

## 4. Anti-Patterns

*Named failure modes — the specific ways this product could rot.*

### The Platform Creep
**Drift:** <!-- INFERRED FROM non-goals; CONFIRM --> A convenience feature "just needs a small always-on helper" — a watcher, a local server, a background sync. Each step is reasonable; the sum is that Claude Copilot quietly becomes standalone software with a daemon and ports.
**Why it kills us:** It stops being an instruction layer Claude Code reads and becomes a product to install, run, and operate — the exact thing the IS-NOT table refuses.
**Early warning:** "let's add a background service," "it should run as a daemon," "expose an endpoint," "needs to be always-on."
**Line in the sand:** <!-- INFERRED; CONFIRM --> No inbound network service, no daemon, no port. Local stdio shims only, opt-in, off by default. <!-- TODO: owner — ratify this as non-negotiable -->

### The Honesty Inflation
**Drift:** Marketing energy creeps into claims. "Process efficiency" quietly becomes "better software"; "unproven at scale" becomes "battle-tested"; "FTS5 keyword search" becomes "semantic search."
**Why it kills us:** The product's credibility *is* its honesty. Once it overpromises, it becomes the hype-driven evangelist it refuses to be, and users can't trust any claim.
**Early warning:** "produces better code," "reduces defects by," "10x," "battle-tested," "semantic," any metric with no measurement behind it.
**Line in the sand:** <!-- TODO: owner — confirm: every claim must name what measures it, or it doesn't ship -->

### The Context Glutton
**Drift:** Agents get "just a bit more" context to be smarter — more files read at startup, full reasoning returned to the main session, outputs inlined instead of stored as work products.
**Why it kills us:** It destroys the framework's core purpose (CLAUDE.md: "context bloat — the framework's core purpose"). The cure becomes the disease.
**Early warning:** "let the agent read everything," "return the full analysis," "inline the output," rising main-session turn counts.
**Line in the sand:** <!-- INFERRED; CONFIRM --> Outputs over the threshold externalize to work products; agents return ~100 tokens. <!-- TODO: owner — ratify -->

### The Company Fork
**Drift:** A specific team's methodology, voice, or vocabulary gets added directly into a base agent because it's faster than writing an extension.
**Why it kills us:** The base stops being generic and reusable; downstream consumers inherit one company's opinions. Extend-not-fork dies.
**Early warning:** company names, proprietary methods, or product-specific copy appearing in `.claude/agents/` base files.
**Line in the sand:** <!-- TODO: owner — confirm: base agents stay generic; all company specifics go to extensions/knowledge -->

<!-- TODO: owner — add a 5th anti-pattern if there's a distinct trap the founder steers
     away from (e.g. roster bloat — the restructure history suggests agent-count discipline
     is a live tension worth naming). -->

---

## 5. Feature Filter

*The instrument. Run any feature through these gates in order; it must pass all of them.*

### Gate 1: Layer Test
> "Can this ship as markdown instructions and/or a local `cc`/`tc` command Claude Code reads — with no daemon, no inbound port, no cloud state, and no model inference of its own?"

If it needs to become standalone software, a network service, or an LLM provider → it belongs in a different product. **Stop.**

### Gate 2: Context Test
> "Does it reduce — or at least not inflate — the main session's token budget?"

If it bloats context (more read at startup, large outputs inlined, full agent reasoning returned) → redesign to externalize, or reject.

### Gate 3: Honesty Test
> "Does it claim only what we can measure — process and context efficiency — and nothing about output quality we have no data for?"

If it promises "better software," defect reduction, or speed → strike the claim (the feature may still pass; the *promise* doesn't).

### Gate 4: Principle Test
> "Does it survive every principle in Section 3?"

One violation → redesign or reject.

### Gate 5: Anti-Pattern Test
> "Does building this drift toward Platform Creep, Honesty Inflation, the Context Glutton, or the Company Fork?"

If yes → reject, or redesign until it doesn't.

### Case Law (In / Out)

<!-- INFERRED FROM shipped features + non-goals; CONFIRM each verdict with owner. -->

| Feature | Verdict | Gate | Reasoning |
|---------|---------|------|-----------|
| Mechanical hook enforcement (force-delegate, QA gate) | **IN** | Principle 2 | Discipline that isn't enforced doesn't happen; enforce at runtime, with escape hatches. |
| Task Copilot work products (externalize outputs) | **IN** | Gate 2 | ~94% less context for externalized WPs vs inlining above the threshold. |
| Live Docs (`cc docs get`) | **IN** | Gate 1 / Gate 3 | Local-first, offline-safe; agents code against the *installed* API, not stale memory. Honest correctness. |
| `cc mcp serve` (optional MCP shim) | **IN** (opt-in, off by default) | Gate 1 | Local stdio shim, not a network service; ships disabled (`.mcp.json` empty). |
| Hosted / cloud state sync | **OUT** | Gate 1 / Principle 5 | All state is local SQLite; cross-machine sharing is a git knowledge repo, not built-in cloud. |
| Running model inference / being an LLM provider | **OUT** | Gate 1 / Principle 1 | It orchestrates Claude Code; it does not run inference. |
| Codex-native agent behaviors | **OUT** | IS-NOT | Codex translation is the separate `codex-copilot` product. |
| Company-specific content in base agents | **OUT** | Principle 5 / Company Fork | Base stays generic; specifics go to extensions/knowledge repos. |
| "Produces better software" / defect-reduction claims | **OUT** | Gate 3 / Honesty Inflation | No defect/rework data exists. "Not magic." |

---

## 6. Quality Bar

**The standard:**
<!-- INFERRED FROM CLAUDE.md guardrails, hooks README, VERSION rules; CONFIRM -->
"Done" means the discipline is *enforced and inspectable*, not merely documented — and every claim in the work is something you could verify.

**Non-negotiables:**

- [ ] No implementation ships without a `@agent-qa` pass that carries an `ARTIFACT:` marker (a bare `VERDICT: APPROVED` does not unblock the gate).
- [ ] Rules that matter are enforced by a hook or gate, each with a documented escape hatch (`COPILOT_*=off`).
- [ ] `VERSION.json` is the single source of truth for the framework version; `package.json` mirrors it, never leads.
- [ ] Agents return ~100 tokens to the main session; details go to work products.
- [ ] No time estimates anywhere — phases, priority, and complexity only.
- [ ] Base agents stay generic; no company-specific content.
- [ ] `cc`/`tc` contract changes preserve parity with downstream consumers (codex-copilot pins).

**Taste test:**
If a claim in a doc or agent output can't name what measures it, it fails — regardless of how good it sounds. Honesty is the aesthetic.

**Quality failure modes:**

| Failure | Symptom |
|---------|---------|
| Advisory drift | A rule that "should" be followed but nothing enforces it. |
| Unmeasured claim | A number or quality promise with no measurement behind it. |
| Context leak | Main-session turn count and token use climbing release over release. |
| Contract break | A `cc`/`tc` change that silently breaks codex-copilot's pinned versions. |

---

## 7. Voice & Tone

**Character:**
<!-- INFERRED FROM README/CLAUDE.md/philosophy phrasing; CONFIRM -->
Precise, technical, and self-correcting. Footnotes its own claims. Anti-hype to the point of bluntness. Uses the exact word ("FTS5 keyword," "local stdio shim") and refuses the impressive-but-wrong one ("semantic," "battle-tested"). Says what is unproven in the same breath as what works.

**Language rules:**

| We Say | We Don't Say |
|--------|--------------|
| "FTS5 keyword search" | "semantic search" |
| "We measure process and context efficiency, not output quality" | "Produces better software" |
| "Works; unproven at large scale — no proven >5-stream run" | "Battle-tested at scale" |
| "An instruction layer for Claude Code" | "A new AI coding platform" |
| "~94% less context for externalized work products" | "94% faster" |
| "Not magic — structured instructions" | "AI that writes perfect code" |

**Tone shifts:**

| Context | Tone |
|---------|------|
| Describing capability | Plain, exact, with the limitation stated inline. |
| Maturity caveats | Footnoted honesty, never hidden ("_works; unproven at large scale_"). |
| Enforcement / errors | Direct and mechanical — state the rule and the escape hatch. |
| Marketing / landing copy | Confident but caveated; "because Everyone Needs a Copilot," never overclaiming outcomes. |

---

## 8. Success Signals

**Positive signals (we're on track):**
<!-- INFERRED; CONFIRM and replace with real overheard quotes -->

- "`/continue` picked up exactly where I left off — weeks later, no re-explaining."
- "The QA gate wouldn't let it ship until tests actually ran. Good."
- "It told me what was unproven instead of pretending. I trust the rest more."
- "It runs entirely on my machine, offline — my code never left."

**Drift signals (we're losing the soul):**

| Signal | What it means |
|--------|---------------|
| Docs or output start claiming "better software" / defect reduction | Honesty Inflation — credibility is eroding. |
| A feature request needs a daemon, port, or cloud sync | Platform Creep — drifting out of the instruction layer. |
| Main-session token use rises release over release | Context Glutton — the cure is becoming the disease. |
| Company names / proprietary methods appear in base agents | Company Fork — the generic base is rotting. |
| Delegation rate falls; work pools in the main session | Enforcement is slipping back to advisory. |

**Recovery questions:**

1. Can this ship as instructions + a local CLI, with no server and no inference?
2. What measures the claim we're about to make — and if nothing does, why is it here?
3. What does this cost the main session's token budget?

---

## 9. Founding Decisions

*The calls that are settled, so they never have to be re-litigated.*

<!-- The following are STRONGLY EVIDENCED in the repo but must be owner-ratified before
     they count as settled. Marked INFERRED; confirm or correct. -->

1. **Instruction layer, not software.** <!-- INFERRED; CONFIRM --> It runs inside Claude Code as markdown + two local CLIs; no standalone runtime, no inference. Resolves Platform Creep and Principle 1.
2. **Mechanical enforcement is the April 2026 answer.** <!-- INFERRED FROM restructure doc; CONFIRM --> After a 6% delegation diagnostic, discipline moved from advisory to hook-enforced (force-delegate, QA gate). Resolves the advisory-drift failure mode.
3. **State is local; sharing is git, not cloud.** <!-- INFERRED; CONFIRM --> SQLite stores locally; knowledge is a git repo. Resolves Principle 5.
4. **Memory is FTS5 keyword search — never called "semantic."** <!-- INFERRED; CONFIRM --> An honesty decision baked into the docs.
5. **Honesty over hype: measure process/context, not output quality.** <!-- INFERRED; CONFIRM --> "Not magic." Resolves Honesty Inflation.

<!-- TODO: owner — Ratify the above, add the rationale/tension each truly resolves, and add
     any settled call only you know (e.g. the roster-count discipline behind the
     consolidate-then-restore-to-15 history; whether the optional MCP shim stays off by
     default permanently). Also set the §3 priority order here. -->

---

## 10. Evolution

This file changes only when:
- Real user outcomes shift what the product is for
- We learn something durable that contradicts a current principle or boundary
- The product's place in its ecosystem changes (another product takes over a job)

When updated, add the rationale to the changelog below.

### Changelog

| Date | Version | Change & rationale |
|------|---------|--------------------|
| 2026-06-28 | v0.1 | Drafted as root-level decision instrument, retrofitted from the repo's README, CLAUDE.md, philosophy doc, overview card, VERSION.json, and the hooks/agents surface. Inferences marked; owner-only sections (priority order, anti-pattern lines in the sand, founding-decision rationale) flagged for ratification. |
