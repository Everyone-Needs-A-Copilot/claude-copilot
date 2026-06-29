# AI Ecosystem Gap Findings — Independent Audit Report

**Date:** 2026-06-29
**Scope:** Adversarial independent review of `ai-ecosystem-research-methodology.md` and its six-document corpus; no code changed; no build greenlit.
**Auditor:** @agent-ta (architecture review lens)

**Documents audited:**
- `claude-copilot/docs/70-reference/ai-ecosystem-research-methodology.md` — the findings/methodology record
- `voice-copilot/thoughts/research/AI Ecosystem/00-README.md`
- `voice-copilot/thoughts/research/AI Ecosystem/01-ecosystem-analysis.md`
- `voice-copilot/thoughts/research/AI Ecosystem/02-the-loop.md`
- `voice-copilot/thoughts/research/AI Ecosystem/03-measuring-it.md`
- `voice-copilot/thoughts/research/AI Ecosystem/04-external-benchmark.md`
- `voice-copilot/thoughts/research/AI Ecosystem/05-good-for-not-good-for.md`

**Source work products:**
- WP-165: core adversarial audit (verdict, methodology red flags, ground-truth table)
- WP-166: deep-dive addendum (AXIS A — gap hardened; AXIS B — audit corrected its own earlier error)
- WP-167: full remediation plan for the 3 confirmed gaps

---

## Executive Summary

This audit reviewed a six-document research corpus and its associated methodology record, which identify capability gaps in the "Everyone Needs a Copilot" AI ecosystem. The research is well-disciplined in its Tier-1 (code-grounded) layer — component counts, version numbers, and the absence of evaluation infrastructure all check out against direct inspection of the repository. The Tier-1 facts survive scrutiny.

The bottom-line verdict is **(b) real but mischaracterized/misscoped**, shading into **(c) overstated** on the framing. The research is NOT a biased artifact — its code-grounded core is too well-grounded for that characterization — but its narrative packaging inflates what are genuinely three bounded gaps into a "two missing stages of THE Loop" headline that overstates one gap (JUDGE) and originally mischaracterized a second (CONSOLIDATE).

**The single most important takeaway:** There are exactly **3 real gaps** — automated cross-version regression eval (absent), per-task cost-cap enforcement (observe-only, not enforced), and memory-to-knowledge consolidation (partially built, the specific edge unbuilt) — wrapped in a narrative frame that manufactures the appearance of a grander structural absence. Additionally, this audit caught and corrected one of its own earlier errors: the initial verdict excused the CONSOLIDATE gap as a "deliberate One-Direction-Principle design choice." The deep-dive (AXIS B) proved this defense was wrong — the principle only bars vault-to-silo sync, and an existing, tested, compliant promotion path (`knowledge-sync`) already exists in the other direction. Memory-to-knowledge consolidation is therefore a genuine unbuilt gap, not an intentional non-goal. That self-correction is a feature of the audit's integrity, not a weakness.

---

## What Was Audited and How

### The Three Pillars Under Examination

The audit examined the foundational layer of the ecosystem across three components:

| Pillar | What it is | Primary repo |
|--------|-----------|--------------|
| **Knowledge Copilot** | Plain-markdown vault (~900 `.md` files); no binary; the One-Direction Principle governs data flows | `knowledge-copilot/` |
| **CLI Copilot** | Standalone `copilot` CLI, 22 service groups, zero coupling to `cc`/`tc`/memory/task | `cli-copilot/` |
| **Claude Copilot** (at center) | Markdown agents + hook-enforced protocol + `cc`/`tc` Python CLIs; primary build locus | `claude-copilot/` |

Note on scope: the research frames its investigation as the foundational four repos, not the ~20-product portfolio listed in `shared-docs/ECOSYSTEM.md`. The term "ecosystem" silently narrows from ~20 products to 4 foundational repos. This scope mismatch is flagged as a methodology red flag below.

### Adversarial Method

The audit used a steelman-then-refute approach:

1. **Steelman pass:** identify the strongest case that the gap is NOT real or is overstated
2. **Refutation pass:** identify the strongest case that the gap IS real
3. **Ground-truth check:** verify every Tier-1 claim against actual repo state using `jq`, `find`, `grep`, `rg`, and `Read` against live files — not the research's self-report

Ground-truth sources: `shared-docs/ECOSYSTEM.md`, `claude-copilot/{VERSION.json, .claude/agents/manifest.json, .claude/quality-gates.json, CLAUDE.md}`, live `cc`/`tc` repo state.

**Verified with independent commands:**
- `jq '.agents|length' manifest.json` → 16 entries (15 framework + 1 setup-only `kc`) — confirmed
- `find /Volumes/Dev/Sites/COPILOT -type d -name evals` → only vendored venv trees, not owner's — confirmed absent
- `find` / `rg` for `promptfoo*`, `deepeval*`, `*.eval.yaml`, `golden*` across the full tree → no match
- `rg "max.budget.usd|max_budget|budget_usd"` across `tools/` + `.claude/` → no enforcement wiring
- `tools/cc/src/cc/commands/usage.py:108-162` — observe-only, no exit/cap/threshold
- `test_mirror_parity.py:12-80` — structure-only (roster membership, section headers), no output scoring
- `grep promote|consolidat|graduate` in `tools/cc/src/cc` → no memory-to-knowledge path

### Deep-Dive Verification Pass

Following the initial audit (WP-165), a second pass (WP-166) verified the two load-bearing axes:

- **AXIS A:** Direct repo inspection of the regression-eval and cost-cap claims — both confirmed absent, confidence raised to High
- **AXIS B:** Review of the One-Direction Principle's actual scope, the `knowledge-sync` mechanism, and the `/reflect` command — resulted in the audit retracting its own "CONSOLIDATE is deliberately forbidden" defense

---

## Verdict

**Verdict: (b) real but mischaracterized/misscoped — with a (c) overstated framing layer.**

This is NOT (a) fully correct as characterized. It is NOT (d) an artifact of biased analysis.

| Claim component | Assessment | Confidence |
|-----------------|-----------|-----------|
| Regression-eval gap (F1) | REAL, correctly load-bearing, survives all checks | High |
| Cost-cap gap (F2) | REAL and actionable | High |
| "JUDGE is missing" as stated | OVERSTATED — procedural JUDGE exists (QA gate); only automated/scored regression is absent | High |
| "OBSERVE only partial" | UNDERSELLS reality — `cc memory check` + shipped verification/observability workstream exist | Medium-High |
| "CONSOLIDATE missing" as a gap | PARTIALLY CORRECT — not forbidden, but the specific memory→knowledge edge is genuinely unbuilt | Medium-High |
| "Loop / two-missing-stages" gestalt | ANALYTIC ARTIFACT of a constructed frame + essay optimization, never skeptically tested | Medium-High |
| Scope ("ecosystem") | MISSCOPED — silently narrows from ~20 products to 4 foundational repos | High |

---

## The 3 Confirmed Real Gaps

### Gap 1 — Automated cross-version regression eval

**What is absent:**
- No `.claude/evals/` directory anywhere in `/Volumes/Dev/Sites/COPILOT/*`
- Zero `promptfoo*`, `deepeval*`, `*.eval.yaml`, or `*golden*` configs across the full tree
- No `cc eval` or `tc eval` subcommand (grep of `tools/cc/src` and `tools/tc/src` → empty)
- No CI model-output regression check — CI covers only `codeql`, `no-hardcoded-paths`, `smoke-tests`, `time-estimate-check`, and `cli-copilot/ci.yml`
- Codex parity is structural, not behavioral: `test_mirror_parity.py:12-80` asserts roster membership and required section headers; it never scores output quality

**What exists (procedural, not scored):**
The mandatory QA gate (`CLAUDE.md` Testing Gate) — `@agent-me` is never final; `@agent-qa` must emit `ARTIFACT:`/`VERDICT:` markers; `adversarial-run` is availability-gated — validates a **single run** pass/fail. It does NOT detect cross-version behavioral drift. These are different guarantees.

**The honest restatement of the gap:** The shared framework (`cc`/`tc`/agents) is reused across ~16 portfolio products plus the codex-copilot port. An unverified framework or agent bump degrades everything downstream at once. No harness scores agent output quality across model/framework version bumps. That blast radius is real and large.

**Citations:** WP-165 G4/G5; WP-166 A.1

---

### Gap 2 — Per-task cost-cap enforcement

**What is absent:**
- No `budget_usd`, `max_tool_calls`, or `--max-budget-usd` wired in `tools/` or `.claude/` — `rg "max.budget.usd|max_budget|budget_usd|max_tool_calls|--max-budget"` across `tools/` + `.claude/` → no enforcement hit
- `--max-budget-usd` is a Claude Code native print-mode flag the research recommends wiring; it is not wired into any `tc`/dispatch path
- No hook halts runaway spend on a per-task basis

**What exists (observe-only):**
`cc usage` (`tools/cc/src/cc/commands/usage.py:108-162`) — described as "Show Claude session quota / rate-limit state" (`:128`); probes or reads cache and prints. No `exit`, cap, threshold, or halt in the body. It is a readout, not a control.

The OBSERVE/ENFORCE distinction is the entire point: observing spend is present; enforcing a ceiling is absent.

**Citations:** WP-165 F2; WP-166 A.2

---

### Gap 3 — memory-to-knowledge consolidation (the genuinely unbuilt edge)

**What is absent:**
- No `promote`, `consolidate`, or `graduate` path referencing knowledge/vault in `tools/cc/src/cc`
- The specific `cc memory` → knowledge-vault promotion (episodic-to-semantic graduation) is unbuilt

**What exists (adjacent, not the same edge):**
- `knowledge-sync` (`docs/50-features/03-knowledge-sync.md`; `scripts/knowledge-sync/`; `tests/integration/knowledge-sync.test.ts`): a real, tested, Production-Ready (v1.0.0) automated running-system → vault promotion — git-release commits between tags are categorized and written into the knowledge vault, then auto-committed. This is genuine consolidation INTO knowledge, but from release commits, not from `cc memory` entries.
- `/reflect` (`.claude/commands/reflect.md:1-18, 68-108`): consolidates WITHIN memory only — reviews lessons/decisions/context, stores corrections, deletes stale. Does NOT promote memory→knowledge.
- `knowledge-sync`'s own roadmap lists Task Copilot work products / architecture decisions / security reviews → knowledge as "Not implemented yet" / Future Enhancements (`:302-359, 733-757`).

**The corrected characterization:** Memory-to-knowledge consolidation is a **legitimate, unbuilt, non-forbidden gap**. The research undersold what exists (`knowledge-sync`); the initial audit wrongly excused it. See the self-correction section below.

**Citations:** WP-165 G7; WP-166 B.1–B.3; `knowledge-copilot/00-best-practices/04-knowledge-vs-capability-boundary.md:42-48`

---

## Where the Findings Overstated / Mischaracterized

### The "Two Missing Loop Cells" Inflation

The research concludes that JUDGE and CONSOLIDATE are two missing stages of a living system. The audit found this characterization inflated in both cases.

**JUDGE:** "Nothing measures whether an agent's output was good" (`02-the-loop.md:99`) is false as stated. A mandatory, hook-enforced QA gate exists (G5, WP-165). What is genuinely absent is a *golden-set regression score* across framework versions — a narrower and more precise claim. The procedural JUDGE validates a single run; it does not detect cross-version behavioral drift. The honest sub-claim is "no automated cross-version regression eval," not "no JUDGE."

**CONSOLIDATE:** The initial audit verdict (WP-165) accepted the research's implicit argument that the One-Direction Principle makes memory-to-knowledge consolidation a deliberate non-goal. **That was wrong, and the audit retracted it in WP-166.**

The sequence of errors:
1. The research stated: *"there is no path that promotes... into the Knowledge vault"* and *"learnings stay trapped in per-project memory"* (`02-the-loop.md:110-125`) — this was false in general, because `knowledge-sync` already promotes release content into the vault automatically.
2. The initial audit defended the absence as "a deliberate One-Direction-Principle design choice — a feature, not a bug" — this was also wrong. The One-Direction Principle (`knowledge-vs-capability-boundary.md:42-48`) bars only **vault-to-closed-silo** two-way sync. It explicitly endorses inbound flow: *"A source silo is something to drain"* (`:46`). An automated, principle-compliant system-to-vault promotion (`knowledge-sync`) already exists and proves this.
3. The corrected position (WP-166 B.3): memory-to-knowledge promotion is **not forbidden by the principle** — it is simply unbuilt, and the `knowledge-sync` roadmap shows it is wanted.

**Honest synthesis:** BOTH "nothing exists" (the research) and "deliberately forbidden" (the initial audit) were wrong. The truth is between them: a partial consolidation path exists via `knowledge-sync` (commits→vault), the specific `cc memory`→vault edge is unbuilt, and that edge is neither forbidden nor an intentional non-goal.

The One-Direction Principle doc was added to `knowledge-copilot` on 2026-06-28 (git history, `knowledge-vs-capability-boundary.md:5`), one day before the 06-29 research. The concept predates the formal write-up (it appears in archived decisions for conversations-copilot), but the near-contemporaneous formal write-up compounds concern that the principle was being used to explain an absence it does not actually govern.

**The self-correction is a feature.** An audit that catches and corrects its own error mid-process earns credibility. This is preserved, not sanded off.

---

## Methodology Red Flags

These do not invalidate the Tier-1 findings but they do explain why the narrative overstates the real gaps.

### RF1 — The "Loop" is a gap-manufacturing frame (most important)

RUN→OBSERVE→JUDGE→CONSOLIDATE is a **four-cell model the research authored**, not a named field standard. None of the cited sources (Anthropic augmented-LLM = model+retrieval+tools+memory; Bain three-layer; agentic-memory literature) uses this four-verb loop (`04-external-benchmark.md:10-35`). Two cells map to existing components, two don't — and "the gap" is definitionally the two empty cells. Choosing a 2×2-style frame and then reporting which quadrants are empty embeds the conclusion in the model. SC2 ("every mature architecture models it as this loop") is the overstatement that does the load-bearing work.

### RF2 — Illusory triangulation

Three documents appear to independently corroborate the JUDGE gap: `02-the-loop.md` (the Loop), `04-external-benchmark.md` (literature), `05-good-for-not-good-for.md` (the matrix). They are the same argument in three notations. `05` literally derives the gap by listing the owner's known elements and noticing none is "measurement" (`05:103-108`). A matrix seeded with the elements you already named cannot surface a gap it wasn't seeded to surface; it re-expresses the Loop conclusion, it does not confirm it independently.

### RF3 — Essay-optimized framing

The corpus is explicitly feedstock for a thought piece (`00-README.md:3`, `methodology:13-16`). The chosen beat — "you'd already built half of it without realizing" (`02-the-loop.md:143-150`) — is selected for being "the strongest essay angle" (`00-README.md:54`). Optimizing a findings document for narrative surprise is a bias vector: the most essay-worthy reading is privileged over the most boring-but-true one.

### RF4 — The skeptical challenge was prescribed but never run

Both the corpus and the methodology flag that the "I'd-already-built-it / model-in-motion" thesis *"rests on a claim a skeptic will poke"* and recommend `/challenge --skeptical` **before** committing (`00-README.md:53-55`, `02-the-loop.md:148-150`, `methodology:84-87`). That challenge was not run. By the authors' own standard the headline is provisional, not validated.

### RF5 — "External benchmark" is a literature checklist, not a benchmark

`04-external-benchmark.md` is real external sourcing (Anthropic, Bain, arXiv, promptfoo, Langfuse) — not self-assessment dressed as external. The sourcing itself is legitimate. BUT the methodology admits it is "single-pass synthesis... not adversarially re-verified claim-by-claim" and time-sensitive figures are "second-hand" (`methodology:84-87`). More importantly, it benchmarks nothing measurable: there is no head-to-head against a peer system's actual implementation. It produces a normative checklist ("the field emphasizes evals/observability/cost") and then flags which items the owner's articulation doesn't name. That is a legitimate completeness check, but calling its output a "benchmark" overstates its evidentiary weight.

**Unverifiable specifics to treat with caution:** the `$47k`/11-day runaway-cost anecdote (`03:113`); arXiv IDs dated 2026-02 (e.g. `2602.19320` — plausible given today is 2026-06-29 but not re-checked here); any pricing or quota figures.

### RF6 — Scope equivocation ("ecosystem" = 4 repos, not ~20 products)

The gap is identified at the foundational-framework layer only. `ECOSYSTEM.md` lists ~20 products across Foundational / Work / Applications layers (Convoco, Insights Copilot, Research Copilot, Method, etc.). The research analyzed only the 4 foundational repos. The gap is unproven for the product portfolio (WP-165 G12). Whether portfolio products have their own evals or cost caps was not examined.

---

## Remediation Plan

This plan is **for review only**. No executable tasks have been created; no build has been greenlit.

**Highest-leverage gap:** GAP 1 (regression eval). The shared `cc`/`tc`/agents layer is reused across ~16 portfolio products plus the codex-copilot port; an unverified framework or agent bump degrades everything downstream at once. That blast radius is why GAP 1 is P0.

---

### GAP 1 — Automated cross-version regression eval — P0

**Solution headline:** Adopt promptfoo as the assertion/LLM-judge engine, wrapped behind a thin native `cc eval` subcommand. Wrapping keeps the user surface CLI-consistent (`cc memory`/`skill`/`docs`/`usage`/`eval`) and local-first/offline-degrading — deterministic assertions always; LLM-judge cases skip with "judge-unavailable" when no key/network, matching the `adversarial-pass.sh` availability-gating philosophy. Store golden/regression cases as `.claude/evals/<agent>/*.yaml` (in-repo, diffable, git-versioned) — assertions on expected PROPERTIES, never verbatim output.

**Components to add or change:**
- `tools/cc/`: new `cc eval` command group; optional-dep detection + degrade path; `cc.api` facade entry
- `.claude/evals/qa/*.yaml`: first golden set (~10 cases) on one agent (`qa`) to prove the pattern, then extend by template
- `.github/workflows/eval-regression.yml`: PR + version-bump gate (deterministic assertions on every PR; LLM-judge cases only when API secret is present)
- `.claude/quality-gates.json`: add eval pass-rate threshold and P0-case-regression block
- `VERSION.json` bump flow/release script: call `cc eval` before tagging

**Acceptance criteria / fitness functions:**
- FF1: `cc eval --agent qa` returns pass/fail JSON; exits non-zero if pass-rate < threshold or any P0 case regresses
- FF2 (meta-test): deliberately removing the `ARTIFACT` requirement from the `qa` agent makes `cc eval --agent qa` FAIL — proves the harness catches regressions
- FF3: a PR bumping `components.agents.version` without a green eval is blocked in CI
- FF4: run scores are retrievable via `cc memory search "eval qa"`

**Trade-offs accepted:** Node/`npx` dependency in a Python-CLI stack — mitigated by making promptfoo an optional dependency with graceful deterministic-only degradation.

---

### GAP 2 — Per-task cost-cap enforcement — P1 (native-flag layer is P0-cheap)

**Solution headline:** Feed `cc usage` output into a hook that can `exit 2`. Two enforcement layers: (1) wire `--max-budget-usd` into every non-interactive dispatch — `tc` worker, `/orchestrate` stream workers, Discord dispatch; (2) per-task tracked budget in `tc` with in-session soft guard in `pretool-check.sh`. GAP 2 reuses `cc usage`; it does not replace it.

**Components to add or change:**
- `tools/tc/`: schema migration (`budget_usd`, `max_tool_calls`, `actual_cost_usd`); `tc task create --budget-usd`; worker/orchestrate dispatch passes `--max-budget-usd`; `tc task update` records actual cost
- `.claude/hooks/pretool-check.sh`: budget-rule branch (warn at ~80–85%, block via `exit 2` at 100%); state file `.claude/hooks/state/budget-<session_id>.json`
- `tools/cc/`: `cc usage --session-cost --json` consumable by the hook
- Escape hatch: `COPILOT_BUDGET=off`, folded into `COPILOT_SAFETY=off` convenience alias (parity with existing escape hatches)

**Acceptance criteria / fitness functions:**
- FF1: a task with `budget_usd: 0.50` that exceeds it has its next tool call blocked (`exit 2`) with a clear message; a synthetic runaway loop terminates
- FF2: `COPILOT_BUDGET=off` disables the block
- FF3: actual cost recorded on the task, visible via `tc task get`
- FF4: grep proves non-interactive `tc`/Discord dispatch always passes `--max-budget-usd`

**Trade-offs accepted:** Cost-attribution lag — `cc usage`'s probe/transcript estimate may trail real spend; in-session guard is a soft ceiling. Only `claude -p --max-budget-usd` is a hard ceiling. Document honestly.

**Codex-parity note:** codex-copilot has no runtime hooks (uses `scripts/copilot-gate.sh`); the hook-based in-session guard must be hand-ported or rely on `--max-budget-usd`-only enforcement there. Pablo decision required (see below).

---

### GAP 3 — memory-to-knowledge consolidation — P2

**Solution headline:** New `cc memory promote <uuid>` subcommand reusing `knowledge-sync`'s vault-write path, triggered from `/reflect`. One-way, human-gated — NEVER automatic. Flow is memory(open)→vault(open), one-way; no vault→memory and no vault→closed-silo backflow.

**Promotion criteria (what graduates):**
- Type in {`decision`, `lesson`, `reference`} — exclude `context`/`person` (project-local or PII)
- Durable (survived `cc memory check` staleness or recurs across sessions) AND cross-project-general
- Human-approved only — memory is "accreted, noisy"; auto-promotion would pollute canonical knowledge

**Components to add or change:**
- `tools/cc/`: `cc memory promote` subcommand (+ `--list-candidates`, `--dry-run`, `--section`); reuse knowledge-sync write/commit helpers
- `.claude/commands/reflect.md`: add Step 6 promotion-review
- Vault note template with provenance YAML frontmatter (`source: cc-memory/<uuid>`, `promoted_at`, `tags`)

**Acceptance criteria / fitness functions:**
- FF1: `cc memory promote <uuid>` creates a hygiene-compliant `NN-slug.md` in the right vault section with provenance, auto-committed to `KNOWLEDGE_REPO`
- FF2 (One-Direction fitness function): static check proves NO code path writes vault→memory or vault→closed-silo
- FF3: `/reflect` only promotes on explicit user approval (never auto)
- FF4: dedup warns when a near-duplicate vault note exists

---

### Sequencing (phases by dependency and priority)

| Phase | Items | Priority | Complexity | Depends on |
|-------|-------|----------|-----------|------------|
| **Phase 0 — Foundation** | GAP 1 core: `cc eval` wrapping promptfoo, deterministic-first, `.claude/evals/qa/*.yaml` (one agent), scores→`cc memory`. PLUS GAP 2 native layer: wire `--max-budget-usd` into non-interactive dispatch. | P0 | Medium (eval) / Low (flag) | none |
| **Phase 1 — Enforce and Expand** | GAP 2 full: `tc budget_usd`/`actual_cost_usd` + PreToolUse budget hook + `COPILOT_BUDGET=off`. GAP 1 expand: golden sets to `ta`/`me` + skill-firing; `eval-regression.yml` CI + `quality-gates.json` threshold; `VERSION.json` bump hook. | P1 | Medium | Phase 0 |
| **Phase 2 — Consolidate** | GAP 3: `cc memory promote` + `/reflect` Step 6 + One-Direction fitness function (FF2). | P2 | Medium (high conceptual care) | Benefits from a mature memory corpus |

**Rationale for order:** GAP 1 first — largest blast radius (protects every downstream product from a bad shared-framework bump). The `--max-budget-usd` flag bundles into Phase 0 because it is one flag that closes the runaway-spend tail risk independently. GAP 3 last — real but lowest urgency (knowledge flywheel, not breakage/spend prevention) and most valuable once durable lessons have accumulated.

---

## Decisions Required Before Any Build

No build work should start without Pablo resolving all five of the following. These are genuine decision forks where the owner's judgment defines the correct path.

- [ ] **GAP 1 engine:** Accept promptfoo as the wrapped engine (adds an optional Node dep, degrades to deterministic-only offline) — vs. a pure-Python `cc eval` (deepeval or hand-rolled, no Node)? Recommendation: wrap promptfoo.
- [ ] **GAP 1 CI cost posture:** Run LLM-judge cases in CI (needs API secret + paid calls per PR) — or deterministic-in-CI with judge running locally on version bump? Recommendation: deterministic-in-CI, judge-on-secret/local.
- [ ] **GAP 2 strictness and default:** Hard-block (`exit 2`) at 100% with warn at 80% — vs. warn-only? And the default budget multiplier (~3–5x median for the task type). Recommendation: warn-80/block-100 with `COPILOT_BUDGET=off`.
- [ ] **GAP 2 codex parity:** Accept `--max-budget-usd`-only enforcement in codex-copilot (no runtime hooks) — or hand-port the in-session guard via `scripts/copilot-gate.sh`?
- [ ] **GAP 3 trigger and criteria:** Fold promotion into `/reflect` (recommended) vs. standalone `cc memory promote` only — and the exact durability/cross-project thresholds that qualify an entry to graduate.

---

## Appendix — Source Work Products

| Work product | Location | Contents |
|---|---|---|
| **WP-165** | `.copilot/wp/165.md` | Core adversarial audit: central claims restated, methodology red flags (RF1–RF6), ground-truth verification table (G1–G13), steelman vs. refutation, final verdict |
| **WP-166** | `.copilot/wp/166.md` | Deep-dive addendum: AXIS A (regression eval and cost-cap confirmed absent by direct repo inspection); AXIS B (One-Direction Principle scope, `knowledge-sync` existence, audit self-correction on CONSOLIDATE) |
| **WP-167** | `.copilot/wp/167.md` | Full remediation plan for 3 confirmed gaps: solution architecture, components, acceptance criteria, sequencing, 5 open decisions |

**Audited document:** `claude-copilot/docs/70-reference/ai-ecosystem-research-methodology.md`

**Underlying research corpus:** `voice-copilot/thoughts/research/AI Ecosystem/` (6 documents: 00-README through 05-good-for-not-good-for)

**Ground truth used:** `shared-docs/ECOSYSTEM.md`, `claude-copilot/{VERSION.json, .claude/agents/manifest.json, .claude/quality-gates.json, CLAUDE.md}`, live `cc`/`tc` repo state as of 2026-06-29.
