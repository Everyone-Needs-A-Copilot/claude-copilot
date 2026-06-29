# AI Ecosystem Research — Methodology & Findings (for technical review)

**Status:** Research complete; no code changed. This is a reviewable record, not a directive.
**Date:** 2026-06-29
**Author:** Claude Code session (Opus 4.8), originating in the `voice-copilot` workspace.
**Companion (identical evidence):** `codex-copilot/docs/ai-ecosystem-research-methodology.md`
**Narrative / essay-oriented version:** `voice-copilot/thoughts/research/AI Ecosystem/` (5 topic docs).

---

## 0. Why this document exists, and why it lives here

The research originated in `voice-copilot` (a writing project) as feedstock for a thought
piece on "the idea of an AI ecosystem." But the build-relevant conclusions concern **this
framework** (`claude-copilot`) and its downstream port (`codex-copilot`) — so the technical
record is placed here, where a developer would actually review and act on it.

**The goal of this document is falsifiability.** Every factual claim below should be
independently re-checkable from the repos, and every recommendation should be traceable to
the facts it rests on. Where a claim is judgment rather than fact, it is labelled as such.
A reviewer should be able to disagree with the *conclusions* while trusting the *evidence*.

---

## 1. The question investigated

The owner runs a multi-product "Copilot" ecosystem and described his mental model as four
layers — **Knowledge / Capabilities / Framework / Project** — plus two adjuncts (internal
hosting + secrets; external third-party systems). Three sub-questions:

1. **Comparison & gaps** — how does this model compare to 2025–2026 state-of-the-art agentic
   ecosystem architecture, and what is it missing?
2. **Measurement** — for any gap worth closing, how would you actually *measure* it at solo
   (single-operator) scale?
3. **Build locus & agent strategy** — if the gaps were closed, *which repos* would change?
   And: are specialized agents still the right approach given tool evolution?

---

## 2. Methodology

### 2.1 Approach — parallel sub-agent decomposition

Research was split across four independent sub-agents so each worked from a clean context
and could be cross-checked. Two rounds:

| Pass | Mandate | Method / tools | Output | Confidence tier |
|------|---------|----------------|--------|-----------------|
| **A — External benchmark** | How leaders decompose agentic ecosystems (2025–26); what a 4-layer model omits; good-for/not-good-for per element | Web research (WebSearch/WebFetch), ~15 sources, prioritising primary/practitioner sources | Layer-model union, ranked omissions, cutting-edge patterns | **2 (sourced)** |
| **B — Internal grounding** | Capture how the ecosystem is *documented* + the owner's vocabulary | Read `shared-docs`/`knowledge-copilot` `ECOSYSTEM.md`, product cards, the (empty) draft essay | Documented model + vocabulary + doc-vs-absent map | **1/2** |
| **C — Code-grounded verification** | Verify, by reading source, what each component *actually is* — and the Memory/Task mechanics | Repo reads of `claude-copilot`, `codex-copilot`, `cli-copilot`, `knowledge-copilot`; cited file:line | Corrected component map; Memory/Task mechanics | **1 (checkable)** |
| **D — Measurement research** | Solo-scale evals/observability/cost, mapped to this stack | Web research, 2025–26 tooling & eval practice | 3-domain measurement design + priority order | **2 (sourced)** |

Pass C deliberately **superseded** Pass B wherever they disagreed: docs were treated as
claims, source code as truth. The most consequential corrections (see §3) came from this.

### 2.2 Verification principles applied

- **Code over docs.** A documented behaviour was not accepted until confirmed in source;
  claims carry `file:line` so a reviewer can re-open them.
- **Trace to the consumer, not the producer.** For "which repo changes" (§4.2), the method
  was to follow each proposed change to where the code that *runs* it lives (`cc`, `tc`,
  hooks, `quality-gates.json`), not where it is described.
- **Existing data is the contract.** Component counts/roles were taken from authoritative
  source (e.g. `main.py` typer registrations, `manifest.json`), not from prose docs, which
  were found to undercount.
- **Corrections logged, not silently smoothed.** Where the initial (docs-based) read was
  wrong, the delta is recorded so the reasoning chain is auditable.

### 2.3 Confidence tiers (used throughout)

- **Tier 1 — High, checkable.** Code-grounded facts about this ecosystem. A reviewer can
  re-verify by reading the cited files. Treat as fact unless the code has since changed.
- **Tier 2 — Medium, sourced.** The external-field synthesis and measurement tooling claims.
  Sources are cited, but the orchestrator did **not** independently re-derive each from
  primary material — spot-check via §8 before relying on any single one.
- **Tier 3 — Judgment.** Recommendations (§4.2–4.4). Reasoning from Tier 1+2; explicitly
  opinion, offered with its derivation so it can be argued with.

### 2.4 Limitations (read before trusting)

- **No code was executed or tested.** All mechanics in §3 were derived by *reading* source,
  not by running it. A behaviour could differ at runtime from what the source implies.
- **The external benchmark (Pass A/D) is single-pass synthesis.** It was not adversarially
  re-verified claim-by-claim. The five-figure-runaway-cost anecdote, specific tool feature
  claims, and any pricing/limit figures are **time-sensitive and second-hand** — verify
  against §8 sources before citing.
- **Recall bias.** Some session memory referenced a *legacy* system; this was caught by
  Pass C (see §3.2) but is a reminder that prior-context claims need code confirmation.
- **Scope.** "Solo operator" framing was assumed throughout; conclusions about what is
  "overkill" are scale-dependent and would change for a team.

---

## 3. Verified facts (Tier 1 — re-checkable)

A reviewer can confirm each of these directly. Suggested checks in `> blockquotes`.

### 3.1 Component map (corrected)

- **Claude Copilot = markdown agents + hook-enforced protocol + `cc`/`tc` Python CLIs.**
  Not standalone software (`README.md:26`). **15 framework agents + `kc`** in
  `.claude/agents/manifest.json` (not the "7" of the README's core-subset table). Versions
  in `VERSION.json` (framework 5.11.0, cc 1.5.0, tc 1.2.0, agents 5.6.0 at time of research).
  Hook enforcement introduced in the April-2026 restructure
  (`docs/10-architecture/04-framework-restructure-2026-04.md`) after a measured 6% delegation rate.
  > Check: `jq '.agents | length' .claude/agents/manifest.json`; read the restructure doc.

- **Codex Copilot = hand-maintained Codex-native port, not an auto-mirror.** Shares only the
  `cc`/`tc` binaries (pinned in `codex-copilot/VERSION.json`); roster/routing are re-authored
  as `SKILL.md` files; runtime hooks are **not implemented** (substituted by
  `scripts/copilot-gate.sh` + parity tests). Parity is a manual checklist
  (`parity/claude-baseline.json`), no sync script either direction.
  > Check: `grep -ri "cc\|tc" codex-copilot/VERSION.json`; inspect `parity/` and `tests/test_mirror_parity.py`.

- **CLI Copilot = standalone `copilot` CLI, 22 service groups, zero coupling to memory/task.**
  Registered in `cli-copilot/.../main.py` (the "~20" in docs is a stale undercount). Discord
  handoff is a real bot (REST + Gateway), thread state in `~/.copilot-cli/discord/handoffs.json`.
  It is an HTTP client to hosted products, **not** a wrapper of `cc`/`tc`.
  > Check: count `app.add_typer(` calls in `main.py`; `grep -rl "\bcc\b\|\btc\b\|memory\|task" copilot_cli/` returns nothing.

- **Knowledge Copilot = plain-markdown vault, not a binary.** ~900 `.md` files; no root
  package manifest. Boundary doc + One-Direction Principle at
  `00-best-practices/04-knowledge-vs-capability-boundary.md`.
  > Check: `ls knowledge-copilot` (no `package.json`/`pyproject.toml` at root); read the boundary doc.

### 3.2 Memory & Task mechanics — the largest correction

**The initial read (legacy `copilot-memory` MCP, `WORKSPACE_ID` scope, `initiative_*` tools)
was WRONG. That system was removed in the April-2026 restructure.** Corrected, code-grounded:

- **Memory = `cc memory`.** UUID-named **markdown files are the source of truth**
  (`tools/cc/src/cc/core/entry_store.py`), under `<git-root>/.claude/memory/entries/`
  (project scope) or `~/.claude/memory/entries/` (global) — **scope is project-vs-global,
  not `WORKSPACE_ID`**. SQLite FTS5 (`memory.db`) is a disposable, gitignored cache. Entry
  types: `decision | context | lesson | reference | person`. No auto-expiry; staleness is
  *detected* via `cc memory check` (default 90 days), not deleted.
- **Task = `tc`** over `.copilot/tasks.db` (per-project, directory-scoped). Model:
  PRD → stream → task (+ dependency DAG) → work_product; work products > 8 KB externalize to
  `.copilot/wp/`. **Initiative/progress state lives here now, not in memory.**
- **`initiative_*` MCP tools no longer exist** (`CHANGELOG.md` ~line 274). Any doc instructing
  "call `initiative_update`" is stale. A dead `task-copilot` node-MCP entry also persists in
  `knowledge-copilot/.mcp.json`.
  > Check: `grep -n "initiative" CHANGELOG.md`; `ls ~/.claude/copilot/mcp-servers` (absent);
  > `cc memory store --type lesson "test"` then inspect `.claude/memory/entries/`.

---

## 4. Conclusions and their derivation

Each conclusion states: **the claim → what it's derived from → how to falsify it.**

### 4.1 The Loop (Tier 3 — conceptual model)

- **Claim:** the four-element model names the system *at rest* (assets/tools/method/target)
  but omits the *runtime + learning* dimension, which the field models as a loop:
  **RUN → OBSERVE → JUDGE → CONSOLIDATE.** The ecosystem already implements RUN (Task
  Copilot) and cross-session recall (Memory Copilot) and partial OBSERVE (`cc usage`,
  `agent_log`); it lacks **JUDGE** (no output-quality evals) and a systematic **CONSOLIDATE**
  edge (no path promoting a durable `cc memory` lesson into the Knowledge vault).
- **Derived from:** §3 (Memory/Task exist and do this work) + Pass A (every reference
  architecture treats memory/eval/feedback as first-class peers — Anthropic "augmented LLM",
  Bain three-layer, agentic-memory literature).
- **Falsify by:** showing an existing eval/quality-measurement surface (would refute "lacks
  JUDGE"), or an existing automated memory→knowledge promotion (would refute the CONSOLIDATE
  gap). The One-Direction Principle intentionally forbids a *sync engine*, so CONSOLIDATE is
  expected to be a human-approved promotion, not automation.

### 4.2 Build locus — which repo changes (Tier 1 reasoning, Tier 3 recommendation)

Traced each proposed move to the code that runs it:

| Repo | Changes? | Why (traced) |
|------|----------|--------------|
| **claude-copilot** | **Primary** | Owns `cc`, `tc`, hooks, `quality-gates.json`. All three measurement moves (§4.3) land here. |
| **codex-copilot** | **Inherit + hand-port** | Shares `cc`/`tc` binaries → budget cap inherited free. No runtime hooks → trace + eval-gate need a Codex-side equivalent via `copilot-gate.sh`/parity. |
| **cli-copilot** | **No** | Zero coupling to memory/task (§3.1) and not the agent dispatcher — `/orchestrate` + `tc` workers spawn agents. |
| **knowledge-copilot** | **No code** | Only a CONSOLIDATE *ritual* + docs; the One-Direction Principle forbids a sync engine. |

- **Eval-cases caveat:** the *machinery* is framework-level (here); the *golden-set cases*
  live beside each agent. Framework agents' cases → `claude-copilot`. Project-specific agents
  (e.g. `voice-copilot`'s `critic`, `provocateur`, exec lenses — which are **not** in this
  repo's 15-agent manifest) → their owning project.
- **Falsify by:** finding that `cli-copilot` does spawn `claude -p` (would pull it into scope),
  or that Codex implements runtime hooks after all (would remove the hand-port).

### 4.3 Measurement architecture (Tier 2 design / Tier 3 priority)

Three domains, each with a minimum-viable form for this stack; full detail and sources in
`voice-copilot/thoughts/research/AI Ecosystem/03-measuring-it.md`. Priority order
(highest leverage-to-effort first):

1. **Cost cap** — per-task `--max-budget-usd` on non-interactive `tc`/dispatch, actual cost
   logged to the task. *Closes runaway-spend risk; starts cost history.*
2. **Quality gate** — a 10-case golden set per agent (deterministic + LLM-as-judge, binary
   scoring, CoT-before-verdict, **judged by a different model than under test**), run via
   `promptfoo`, pass-rate → `cc memory`, wired into `quality-gates.json`. *Directly answers
   "did a framework change degrade behaviour."*
3. **Trace** — `PostToolUse`/`Stop` hook appends one JSONL line per tool call / sub-agent
   handoff into `cc memory`. *Makes runs debuggable; eval scores can later attach to spans.*
- **Deliberately deferred (Tier 3, judged overkill at solo scale):** Langfuse self-hosted,
  Braintrust/LangSmith, annotation queues, OTEL, online production monitoring.
- **Falsify by:** demonstrating an existing budget/eval/trace mechanism that already covers these.

### 4.4 Specialized agents — still warranted? (Tier 3)

- **Claim:** the real decision is not "agents yes/no" but a per-agent test:
  **(1) does it need context isolation** (large intermediate work / parallelism / clean
  window) **or (2) a distinct tool/permission scope?** Yes to either → keep as a sub-agent.
  No to both → it is *expertise* better delivered as an on-demand **skill/command**, not a
  resident persona. The fading anti-pattern is role-flavour-only agents invoked on small
  tasks. The owner's *writing/lens* agents pass the test (bounded perspective + isolation +
  per-agent rule enforcement); the **6-stage sequential software design chain
  (`sd→uxd→uids→uid→ta→me`) is the candidate for over-decomposition at solo scale.**
- **Derived from:** Anthropic context-engineering guidance (sub-agent isolation is the
  durable rationale; "prefer the simplest pattern"), the framework's own 6% delegation
  diagnostic (the weak link was *orchestration*, not the agents), and the coexistence of
  Skills (3.3.0) with agents in this repo.
- **The decisive test is empirical, not aesthetic:** once §4.3 move 2 exists, run the same
  golden set against the specialized agent vs. a single generalist prompt. **Let the eval
  adjudicate per agent.** This is the only resolution that doesn't reduce to preference.

---

## 5. How a reviewer can verify

- **Tier-1 facts (§3):** run the `> Check:` commands inline. They are designed to confirm or
  break each claim in under a minute.
- **Tier-2 claims (§4.1, §4.3):** spot-check against §8 sources — especially any pricing,
  rate-limit, or tool-feature claim, which are time-sensitive.
- **Tier-3 recommendations (§4.2–4.4):** the falsification hooks are stated inline. The agent
  question (§4.4) is settled empirically by the golden-set A/B, not by argument.

---

## 6. Open questions / what this research did NOT establish

- Whether the 6-stage design chain actually underperforms a leaner chain — **untested**;
  needs the §4.3-move-2 experiment.
- Real runtime behaviour of `cc`/`tc` (read, not executed).
- Whether any deferred tooling (§4.3) becomes justified — depends on future pain not yet present.
- The external-field synthesis was not adversarially verified; treat §4.1's field claims as
  well-sourced but not independently reproduced.

---

## 7. Implications for THIS repo (`claude-copilot`)

This is the **primary build locus** for everything in §4.3. Concretely, were the owner to
proceed (he has stated he will *not* build now — this is documentation only):

- `tc`: add a per-task `budget_usd` / `max_tool_calls` field and pass `--max-budget-usd`
  through the worker/orchestrate dispatch; record actual cost back to the task.
- Hooks + `quality-gates.json`: add a `promptfoo`-runner gate and a `PostToolUse`/`Stop`
  JSONL trace emitter.
- Golden-set cases for the **15 framework agents** live here; project agents' cases do not.
- Stale-reference cleanup that this research surfaced (independent of any build):
  any `initiative_update` instruction (removed), and coordinate with `knowledge-copilot` on
  its dead `task-copilot` `.mcp.json` entry.

The identical evidence base, framed for the port, is in
`codex-copilot/docs/ai-ecosystem-research-methodology.md` §7.

---

## 8. Provenance & sources

**Method:** 4 parallel Claude Code sub-agents (2 web-research, 2 repo-read), 2026-06-29.
**Repo evidence:** `claude-copilot`, `codex-copilot`, `cli-copilot`, `knowledge-copilot`
working trees as of 2026-06-29 (paths/line refs in §3 are point-in-time).

**External sources (Tier 2 — spot-check before relying):**
Anthropic [Building Effective Agents](https://www.anthropic.com/research/building-effective-agents) ·
Anthropic [Effective Context Engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) ·
[Bain — Three Layers of an Agentic AI Platform](https://www.bain.com/insights/the-three-layers-of-an-agentic-ai-platform/) ·
[Anatomy of Agentic Memory (arXiv 2602.19320)](https://arxiv.org/html/2602.19320v1) ·
[Interoperability protocols survey (arXiv 2505.02279)](https://arxiv.org/html/2505.02279v1) ·
[Confident AI — agent eval guide](https://www.confident-ai.com/blog/llm-agent-evaluation-complete-guide) ·
[Evidently — LLM-as-judge](https://www.evidentlyai.com/llm-guide/llm-as-a-judge) ·
[promptfoo](https://github.com/promptfoo/promptfoo) · [promptfoo CI/CD](https://www.promptfoo.dev/docs/integrations/ci-cd/) ·
[Langfuse — observability](https://langfuse.com/docs/observability/overview) ·
[Claude Code — costs docs](https://code.claude.com/docs/en/costs) · [ccusage](https://ccusage.com/guide/) ·
[Self-preference bias (arXiv 2410.21819)](https://arxiv.org/pdf/2410.21819).
Full annotated list: `voice-copilot/thoughts/research/AI Ecosystem/04-external-benchmark.md`.
