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

> **STATUS: RATIFIED v1.0 — 2026-06-28** (amended v1.1, v1.2 — 2026-07-14; see §10 Evolution). Owner-ratified at read-back: priority order set, a fifth anti-pattern (The Do-Everything Generalist) added, and the ecosystem MCP/CLI boundary settled. Evidenced inferences confirmed against the owner's docs.

---

## 1. The Job

*The struggling moment this product exists to resolve, in the user's own words.*

**When** a developer works with Claude Code across many sessions on real, complex software,
**they want to** keep their decisions, process, and context from evaporating every time a session ends — without burning their token budget rebuilding it,
**so they can** do disciplined, resumable, inspectable work instead of starting from zero every morning.

**The struggling moment:**
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
Claude Copilot is an **instruction layer for Claude Code** — markdown agents, commands, and two local CLIs (`cc`, `tc`) — that makes Claude Code's process **repeatable, inspectable, and stateful**: specialized agents with strict points of view, a design-led protocol enforced by mechanical hooks, persistent memory, and real task/worker orchestration.

**The deeper aim:**
Every developer gets the disciplined process of a strong team — encoded, enforced, and owned by them — without trading away their token budget, their privacy, or their honesty about what AI can actually guarantee.

**As a person, this product would be:**
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
It looks like a "product" or "platform," but it is an **instruction layer**: files Claude Code reads, plus two local CLIs. A borderline capability is allowed **only if** it can ship as instructions Claude Code reads and/or a local `cc`/`tc` command — *without* becoming standalone software, opening a network service, syncing state to a cloud, or running model inference. Within the ecosystem, connection is always via the local CLI (`cc`/`tc`) — **never MCP.** MCP is reserved exclusively for *application-level* servers that let users connect to a **live application's own domain from outside the ecosystem** (e.g., Convoco's MCP — for talking *about* your conversations and deals, not for building Convoco). MCP for development, technical planning, or ecosystem-internal tooling is refused. The optional `cc mcp serve` shim is therefore **transitional, trending to removal**, not a permanent feature. The moment a feature needs a daemon, a port, a server, or its own model, it belongs in a different product.

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
**Meaning:** The main session's token budget is the scarce resource. Work is delegated to agents; the detail is externalized to a work product instead of inlined into the conversation, and the agent hands back a compressed summary plus a pointer to that work product, not its full reasoning. The savings ratio this mechanism actually achieves, and the current per-agent-class return-size bar, are measured continuously and carried in the claims register (`framework-externalization-94pct`, `framework-agent-frugality`) rather than hard-coded here — see §6 for today's bar.
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

Priority order: **Instruction Layer, Never Software > Honest About What It Measures > Local, Git-Native, Yours > Mechanical Enforcement Over Polite Advice > Context Is the Budget.**

The first three are **identity boundaries** — cross any one and it stops being this product (it becomes software, loses the credibility that *is* the product, or breaks the local/privacy promise), so they sit on top. The bottom two are the live operational tradeoff: **enforcement outranks budget** — spend the context to make a discipline real rather than leave it as advice that won't be followed. *But* that ranking carries a rider: enforcement must be engineered to pay its context cost **once**, never per-turn. Load standards/ADRs into context a single time and trust the model to keep using them; gratuitous re-injection is a failure even when enforcement wins. **Smart enforcement, not expensive enforcement.**

---

## 4. Anti-Patterns

*Named failure modes — the specific ways this product could rot.*

### The Platform Creep
**Drift:** A convenience feature "just needs a small always-on helper" — a watcher, a local server, a background sync. Each step is reasonable; the sum is that Claude Copilot quietly becomes standalone software with a daemon and ports.
**Why it kills us:** It stops being an instruction layer Claude Code reads and becomes a product to install, run, and operate — the exact thing the IS-NOT table refuses.
**Early warning:** "let's add a background service," "it should run as a daemon," "expose an endpoint," "needs to be always-on."
**Line in the sand:** No inbound network service, no daemon, no port — non-negotiable. Per the ratified MCP boundary, even local stdio MCP shims are transitional; ecosystem-internal connection is CLI.

### The Honesty Inflation
**Drift:** Marketing energy creeps into claims. "Process efficiency" quietly becomes "better software"; "unproven at scale" becomes "battle-tested"; "FTS5 keyword search" becomes "semantic search."
**Why it kills us:** The product's credibility *is* its honesty. Once it overpromises, it becomes the hype-driven evangelist it refuses to be, and users can't trust any claim.
**Early warning:** "produces better code," "reduces defects by," "10x," "battle-tested," "semantic," any metric with no measurement behind it.
**Line in the sand:** Every claim must name what measures it, or it doesn't ship.

### The Context Glutton
**Drift:** Agents get "just a bit more" context to be smarter — more files read at startup, full reasoning returned to the main session, outputs inlined instead of stored as work products.
**Why it kills us:** It destroys the framework's core purpose (CLAUDE.md: "context bloat — the framework's core purpose"). The cure becomes the disease.
**Early warning:** "let the agent read everything," "return the full analysis," "inline the output," rising main-session turn counts.
**Line in the sand:** Outputs over the threshold externalize to work products; agents return within their class's current ratchet bar (§6), not their full reasoning — and enforcement that needs context pays the cost once, never per-turn.

### The Company Fork
**Drift:** A specific team's methodology, voice, or vocabulary gets added directly into a base agent because it's faster than writing an extension.
**Why it kills us:** The base stops being generic and reusable; downstream consumers inherit one company's opinions. Extend-not-fork dies.
**Early warning:** company names, proprietary methods, or product-specific copy appearing in `.claude/agents/` base files.
**Line in the sand:** Base agents stay generic; all company specifics live in extensions/knowledge repos.

### The Do-Everything Generalist
**Drift:** The general/main agent handles work itself — analysis, design, security, QA — instead of identifying the need and routing it to the equipped specialist. Each instance feels faster than delegating; the sum is that specialists exist on paper while the generalist does everything (the diagnostic: 94% of work stayed in the main session despite a full roster).
**Why it kills us:** You lose the specialist's lens — the specific point of view vital to the outcome — *and* you burn tokens doing inexpertly, in the main session, what an equipped specialist does better and faster. Roster size was never the problem; un-delegated work is.
**Early warning:** "I'll just handle this here," delegation rate falling, work pooling in the main session, adding more agents to fix outcomes instead of enforcing delegation to the ones you have.
**Line in the sand:** The generalist's job is to identify the need and bring in the right specialist at the right time — never to substitute itself for the specialist. The fix for weak outcomes is correct delegation, not a bigger roster.

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


| Feature | Verdict | Gate | Reasoning |
|---------|---------|------|-----------|
| Mechanical hook enforcement (force-delegate, QA gate) | **IN** | Principle 2 | Discipline that isn't enforced doesn't happen; enforce at runtime, with escape hatches. |
| Task Copilot work products (externalize outputs) | **IN** | Gate 2 | Externalizes agent output into inspectable, git-tracked work products above the threshold instead of inlining it into the main session; the current savings ratio is tracked in the claims register (`framework-externalization-94pct`), not restated here. |
| Live Docs (`cc docs get`) | **IN** | Gate 1 / Gate 3 | Local-first, offline-safe; agents code against the *installed* API, not stale memory. Honest correctness. |
| `cc mcp serve` shim for ecosystem-internal tooling | **OUT** (transitional, trending to removal) | MCP boundary | Within the ecosystem, connection is `cc`/`tc` CLI, never MCP. MCP is only for app-level servers serving external users (e.g., Convoco). |
| Hosted / cloud state sync | **OUT** | Gate 1 / Principle 5 | All state is local SQLite; cross-machine sharing is a git knowledge repo, not built-in cloud. |
| Running model inference / being an LLM provider | **OUT** | Gate 1 / Principle 1 | It orchestrates Claude Code; it does not run inference. |
| Codex-native agent behaviors | **OUT** | IS-NOT | Codex translation is the separate `codex-copilot` product. |
| Company-specific content in base agents | **OUT** | Principle 5 / Company Fork | Base stays generic; specifics go to extensions/knowledge repos. |
| "Produces better software" / defect-reduction claims | **OUT** | Gate 3 / Honesty Inflation | No defect/rework data exists. "Not magic." |

---

## 6. Quality Bar

**The standard:**
"Done" means the discipline is *enforced and inspectable*, not merely documented — and every claim in the work is something you could verify.

**Non-negotiables:**

- [ ] No implementation ships without a `@agent-qa` pass that carries an `ARTIFACT:` marker (a bare `VERDICT: APPROVED` does not unblock the gate).
- [ ] Rules that matter are enforced by a hook or gate, each with a documented escape hatch (`COPILOT_*=off`).
- [ ] `VERSION.json` is the single source of truth for the framework version; `package.json` mirrors it, never leads.
- [ ] Agent returns to the main session stay within their class's current ratchet bar (below); details go to work products.
- [ ] No time estimates anywhere — phases, priority, and complexity only.
- [ ] Base agents stay generic; no company-specific content.
- [ ] `cc`/`tc` contract changes preserve parity with downstream consumers (codex-copilot pins).

**Agent-return ratchet (by class), AMENDED 2026-07-14:** SOUL's original bar (~100 tokens, flat, all classes) was never met by any agent class once actually measured (`framework-agent-frugality`). Rather than carry an unmeetable bar, each class's bar is set at its current measured reality — honest today, not aspirational — and is explicitly a **ratchet**: it tightens as the return-contract work (agent instruction + return-format tightening, tracked separately) lands. The claims register (`claims.yaml`, `framework-agent-frugality`), not this table, is the source of truth for the live number; the table is a snapshot.

| Agent class | Bar (tokens, 2026-07-13 measured baseline) |
|---|---|
| `me` | ~854 |
| `doc` | ~490 |
| `sd` | ~3,786 |
| `uxd` | ~5,089 |
| `uids` | ~4,118 |
| `sec` | ~3,556 |
| Any other class (no class-specific bar measured yet) | ~893 (overall median, use until that class has its own n) |

A class's return exceeding its own bar in a later measurement is a regression to be treated seriously, not shrugged off as "the bar was always unrealistic" — that failure mode is exactly what put the old flat ~100 bar here in the first place.

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
Precise, technical, and self-correcting. Footnotes its own claims. Anti-hype to the point of bluntness. Uses the exact word ("FTS5 keyword," "local stdio shim") and refuses the impressive-but-wrong one ("semantic," "battle-tested"). Says what is unproven in the same breath as what works.

**Language rules:**

| We Say | We Don't Say |
|--------|--------------|
| "FTS5 keyword search" | "semantic search" |
| "We measure process and context efficiency, not output quality" | "Produces better software" |
| "Works; unproven at large scale — no proven >5-stream run" | "Battle-tested at scale" |
| "An instruction layer for Claude Code" | "A new AI coding platform" |
| "Work externalizes to work products; agents return a summary + pointer, not full reasoning" | "94% faster" |
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

1. **Instruction layer, not software.** It runs inside Claude Code as markdown + two local CLIs; no standalone runtime, no inference. Resolves Platform Creep and Principle 1.
2. **Mechanical enforcement over advice.** After the delegation diagnostic (6% delegation despite a full roster), discipline moved from advisory to hook-enforced (force-delegate, QA gate). Resolves advisory drift.
3. **State is local; sharing is git, not cloud.** SQLite stores locally; knowledge is a git repo you own. Resolves Principle 5.
4. **Memory is FTS5 keyword search — never called "semantic."** An honesty decision baked into the docs.
5. **Honesty over hype: measure process/context, not output quality.** "Not magic." Resolves Honesty Inflation.
6. **Within the ecosystem, connection is CLI — never MCP.** MCP servers are reserved exclusively for *application-level* servers that let users connect to a **live application's own domain from outside the ecosystem** (e.g., Convoco's MCP, for talking about your conversations and deals — not for building the app). MCP for development, technical planning, or ecosystem-internal tooling is refused; the `cc mcp serve` shim is transitional, trending to removal.
7. **Specialists are essential; the generalist delegates to them.** The right specialist at the right time brings the lens that improves the outcome and — because they arrive equipped with the understanding, principles, and skills — *saves* tokens. The general agent's job is to identify the need and route it, never to do the specialist's work. Weak outcomes are fixed by correct delegation, not a bigger roster. Resolves The Do-Everything Generalist.
8. **Priority order is settled:** Instruction Layer > Honest About What It Measures > Local, Git-Native, Yours > Mechanical Enforcement > Context Is the Budget — enforcement outranks budget, but must pay its context cost once, never per-turn.

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
| 2026-07-14 | v1.2 | **Amended (DEC-1, per-class ratchet).** §6's flat ~100-token agent-return bar was met by zero agent classes when actually measured (`framework-agent-frugality`: overall median 893, p90 3,474, n≈124). Replaced with a per-class bar set at each class's current measured reality (`me` ~854, `doc` ~490, `sd` ~3,786, `uxd` ~5,089, `uids` ~4,118, `sec` ~3,556) — an honest bar today, framed explicitly as a ratchet that tightens as the return-contract work lands. The claims register, not this document, is the source of truth for the live number. |
| 2026-07-14 | v1.1 | **Ratified (DEC-3, Option B).** Struck the falsified "~94% less context" figure from §3/§5/§7 (three sites) after population measurement showed it inverted (agent returns median 893 tokens vs work-product content median 353, `savings_ratio_median -1.53` — returns are ~2.5x LARGER than what they externalize, `framework-externalization-94pct`). Rewrote all three to state the *mechanism* (externalize to a work product; return a summary + pointer) and defer the *number* to the claims register, so a future measurement change doesn't require another SOUL edit. Mirrors the README's earlier correction (commit `7274e6b`). |
| 2026-06-28 | v1.0 | **Ratified** at read-back. Set the principle priority order (identity boundaries above the enforcement-vs-budget tradeoff; enforcement outranks budget but pays its context cost once, never per-turn). Added a fifth anti-pattern, The Do-Everything Generalist (the generalist doing specialist work instead of delegating). Settled the ecosystem MCP/CLI boundary: within the ecosystem connection is CLI, never MCP; MCP is reserved for app-level servers serving external users (e.g., Convoco). Confirmed the five evidenced founding decisions. |
| 2026-06-28 | v0.1 | Drafted as root-level decision instrument, retrofitted from the repo's README, CLAUDE.md, philosophy doc, overview card, VERSION.json, and the hooks/agents surface. Inferences marked; owner-only sections (priority order, anti-pattern lines in the sand, founding-decision rationale) flagged for ratification. |
