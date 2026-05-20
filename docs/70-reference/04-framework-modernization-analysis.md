---
title: "Framework Modernization Analysis — PRD-2 Record"
status: Current
date: 2026-05-20
scope: >
  Internal mechanics, correctness debt, and native-Claude-Code redundancy for the Claude Copilot
  framework. External competitive benchmarking lives in the companion doc
  docs/70-reference/03-competitive-landscape.md — this document does NOT duplicate it.
diátaxis-mode: Reference
---

# Framework Modernization Analysis — PRD-2 Record

> **Diátaxis mode:** Reference. This document is an accurate record of what was analyzed, decided, built, and remains. It does not change framework behavior.

**Companion doc:** [`03-competitive-landscape.md`](./03-competitive-landscape.md) — external benchmarking, ecosystem context, strategic positioning. That doc owns external comparison. This doc owns internal mechanics, the native-CC redundancy axis, and the PRD-2 implementation record.

**Source work products:** WP-28 (capability inventory) · WP-29 (original analysis) · WP-30 (ground-truth) · WP-31 (plan) · WP-32 (plan revision 2) · WP-33 through WP-49 (implementation and QA).

---

## Executive Summary

Claude Code (v2.1.x, early 2026) has absorbed many primitives Claude Copilot was originally built to provide: sub-agents, hooks, Skills (SKILL.md), plugins/marketplaces, git worktrees, native task tooling, and session memory. PRD-2 analyzed every framework component against its native CC equivalent, then executed a targeted batch of correctness fixes, infrastructure improvements, and a full skills upgrade — while preserving the framework's genuine value-adds.

**Two corrected premises from the original analysis:**

> **Premise 1 — no semantic search.**
> The framework and its documentation claimed "semantic search" for `cc memory search`, `tc wp search`, and `cc skill evaluate --threshold`. All three were false.
> - `cc memory search` and `tc wp search` are SQLite **FTS5 keyword / BM25**, not vector/embedding search (`CC_MEMORY_EMBEDDING_MODEL=none`).
> - `cc skill evaluate --threshold` was a **verified no-op** — the threshold parameter was marked "Not yet implemented" in-code; the command scored nothing.
> The framework had NO semantic/vector edge over native auto-memory. Its actual memory edges are: (a) entries committed to the repo and travel with it; (b) FTS5 keyword index; (c) typed entries (`decision | context | lesson | reference | person`).
> **PRD-2 resolution:** honest rename everywhere + pluggable `SearchBackend` seam added so embeddings can be wired in later. `cc skill evaluate` removed entirely.

> **Premise 2 — skills were under-built, not over-built.**
> The original analysis framed skills as "reduce to markdown / lean on native SKILL.md." Ground-truth investigation (WP-30) found the opposite: the framework's 29 skill files were flat markdown — they had NO L3 executable layer despite containing logic (DREAD arithmetic, OWASP checklists, Dockerfile rules) that the model re-derived from scratch each session, inconsistently.
> The correct path was not removal — it was **upgrade to the Anthropic 3-level architecture** (L1 metadata / L2 prose / L3 executable scripts run via Bash; source never enters context).
> **PRD-2 resolution:** 16 skills converted to code-bearing (Python stdlib scripts + pytest, 16/16 green); 13 legitimately-prose skills kept as pure markdown. `@include` dropped as primary contract (it was a documentation convention, not a parsed mechanism).

**Net verdict:** The framework's genuine, not-natively-replaceable value remains a focused set: tc work products (context offload), cross-session task persistence with deps/claim/priority, tc handoff + agent_log, the knowledge-repo per-agent override mechanism, methodology-embedded agents, and hook-enforced workflow logic. PRD-2 removed the false claims and built what was missing; it preserved every component with genuine value.

---

## 1. Capability Mapping Table

**Verdict key:** FULLY REDUNDANT — mechanism duplicates native with no added value; PARTIALLY REDUNDANT — native covers the common case, framework adds a specific edge; NOT NATIVE — no native equivalent (framework value-add, genuine or narrow).

| Framework Component | Native CC Equivalent | Verdict | Confidence | PRD-2 Action |
|---|---|---|---|---|
| `cc memory` store/get/list, typed entries, committed `.md` | Auto Memory `MEMORY.md` + topic files, `/memory`, `autoMemoryEnabled` (v2.1.59+); first 200 lines auto-load, topic files on-demand | **PARTIALLY REDUNDANT** — native covers cross-session persistence; framework adds repo-commit + typed entries + FTS5 index | High | Fixed: honest rename; SearchBackend seam; wired into 7 agent preambles (was dormant) |
| `cc memory search` (FTS5 keyword) | None native (native = file/glob/content match only) | **NOT NATIVE** — value is FTS5 keyword/BM25; edge is narrow and was previously overclaimed as "semantic" | High | Fixed: renamed from "semantic"; seam added for future opt-in embeddings |
| `cc memory index` (rebuild/status, SQLite cache) | None (native unindexed) | **NOT NATIVE** — genuine, small value-add over grep | Med | No change |
| `tc tasks` (cross-session, claim, deps, priority, parent) | `TaskCreate/Update/List/Get` (GA v2.1.142) — session-local only | **PARTIALLY REDUNDANT** — native tasks have NO cross-session persistence, NO deps/claim/priority | High | No change (kept as-is; strongest value-add) |
| `tc work products` (hybrid inline/file, FTS search) | None (sessions persist transcript `.jsonl`, not typed WPs) | **NOT NATIVE** — genuine value-add (~94% context reduction) | High | Fixed: externalization threshold 100KB→8KB so offload actually fires |
| `tc handoff` / `agent_log` / cross-agent context | None (native subagents are context-isolated; no shared WP or handoff) | **NOT NATIVE** — genuine value-add | High | No change |
| `tc deploy` (formerly Coolify-hardcoded) | None | **NOT NATIVE** — but was vendor-coupled; does not belong in an agent-agnostic CLI | High | Fixed: config-gated via `CC_DEPLOY_CLI` env var → `cc config deploy.cli` → built-in default; vendor no longer hardcoded |
| Agents (methodology-embedded, model/tool-scoped, iteration) | `.claude/agents/*.md` (GA: frontmatter, model, effort, allowed-tools, memory, max_turns, path-scoping, auto-delegate, `@agent-name`, parallel) | **PARTIALLY REDUNDANT** — native is the substrate/runtime; framework value = embedded methodology + routing guardrails + session-boundary protocol + WP integration | High | Fixed: `skill_evaluate` removed from 6 frontmatter `tools:` entries; archived agent names corrected |
| Hooks (force-delegate / qa-gate / session-cap) | Native hooks GA (PreToolUse exit2, SubagentStart/Stop, SessionStart, TaskCreated/Completed, PreCompact, regex matchers, `settings.json`) | **PARTIALLY REDUNDANT** — native hooks ARE the substrate; the enforcement LOGIC (force-delegate, qa-gate, retry/fallback) is the value-add, not the mechanism | High | Fixed: QA-gate clearing bug (see §5); `tc` task/WP commands added to QA-safe prefixes |
| Skills (L1 metadata / L2 prose / L3 executable scripts) | Native `SKILL.md` progressive disclosure (when_to_use, model, effort, `!cmd`, `$ARGUMENTS`, model-invocation) | **PARTIALLY REDUNDANT** mechanism — native SKILL.md is the contract; L3 scripts are the framework's genuine value-add over flat markdown | High | Upgraded: 16 skills converted to L1/L2/L3 (stdlib Python + pytest); 13 prose skills kept markdown; `@include` dropped as primary contract |
| `cc skill evaluate --threshold` (scoring) | None native — BUT the implementation was a NO-OP | **FULLY REDUNDANT** — implemented nothing; native progressive disclosure surfaces skills by description | High | Removed entirely (TASK-29) |
| `cc skill search` (keyword name/desc/tags) | Native loads skill name+description always-in-context | **PARTIALLY REDUNDANT** — native disclosure covers model-side discovery | Med | No change |
| Known-references registry | None native | **NOT NATIVE** — new feature delivered in PRD-2 | High | Delivered: UserPromptSubmit hook injects configured paths (shared_docs, knowledge_repo, refs.* keys, memory entries of type `reference`) as a system message at session turn 1 |
| `/protocol` + flow routing (defect/experience/technical/infra) | Subagent auto-delegation + `/goal` (work-until-condition) + output styles + path-scoped conditional activation | **PARTIALLY REDUNDANT** — native auto-delegate + `/goal` cover much; framework adds opinionated, **deterministic** multi-agent flow sequencing | Med | KEPT as-is — no native equivalent for guaranteed ordered flow; "shrink protocol" recommendation withdrawn |
| `/continue`, `/pause` (session memory) | Session persistence (`.jsonl` resume/fork) + auto memory | **PARTIALLY REDUNDANT** — native resume/fork overlaps; framework adds structured memory store | Med | No change |
| `/map`, `/orchestrate` | Git worktrees (native), Agent Teams, `/schedule` | **PARTIALLY REDUNDANT** — orchestration partly native; `tc stream` worktree wiring is value-add | Med | No change |
| Extension system (knowledge-repo agent OVERRIDE, 2-tier resolution) | Plugins GA (bundle skills+agents+hooks+MCP, marketplaces) — but NO native "override THIS agent" | **NOT NATIVE** — genuine value-add; plugins are distribution, not per-agent override | High | No change (P2 item) |
| MCP remnants (`cc mcp serve` / config bridge) | MCP GA (stdio/SSE/remote, tool search, Channels) | **FULLY REDUNDANT** — retained bridge is legacy post-migration; native MCP is canonical | Med | Removed worktree + bridge (TASK-30: ~100MB reclaimed) |

---

## 2. PRD-2 Status

### Done — P0 Correctness Fixes

All items verified live by QA (WP-48, WP-49).

| Task | Fix | Location |
|---|---|---|
| TASK-24 | Removed dead `protocol_violation_log()` instruction | `.claude/hooks/protocol-injection.md` lines 42, 71 |
| TASK-25 | Purged retired-MCP tool docs (violations / security / auto-checkpoint sections) | `.claude/hooks/README.md` |
| TASK-26 | Established single canonical version source; reconciled version drift | `package.json`, `VERSION.json`, component fields |
| TASK-27 | Removed `skill_evaluate` fake-tool from 6 agent frontmatters + preamble calls | `me.md`, `qa.md`, `do.md`, `doc.md`, `sd.md`, `design.md` |
| TASK-28 | Fixed archived agent names (`uxd/uids/cw/cco`) | `ta.md`, `extension-spec.md`, `project-context.md` |

### Done — P1 Infrastructure and Honesty

| Task | Delivered | Detail |
|---|---|---|
| TASK-29 | Deleted `cc skill evaluate` subcommand entirely | 214 lines removed; `COMMANDS.md` updated; `CLAUDE.md` updated |
| TASK-30 | Deleted ~100MB pre-migration `Stream-Foundation` worktree + `cc mcp` bridge remnant | Local cleanup; not shipped |
| TASK-31 | Config-gated deploy vendor | Resolution chain: `CC_DEPLOY_CLI` env → `cc config deploy.cli` → built-in default (`python -m copilot_cli`); `_COOLIFY_*` constants renamed; vendor name no longer hardcoded in shared framework |
| TASK-32 | Honest FTS5 rename + pluggable `SearchBackend` | `SearchBackend` Protocol (runtime_checkable) with index/remove/rebuild/search/status; `FTS5Backend` implements it; module-level functions accept `backend=` injection; 17 test cases |
| TASK-33 | Wired `cc memory` store/search into 7 agent preambles | `me`, `ta`, `qa`, `do`, `doc`, `sd`, `design` — memory was dormant (zero entries, no agent called it before this fix) |
| TASK-34 | WP externalization threshold lowered 100KB→8KB | `WP_CONTENT_SIZE_THRESHOLD` in `tc/__init__.py`; observed WP range is 300B–20KB; 8KB keeps short/medium inline, externalizes large WPs correctly |
| TASK-35 | Exemplar L1/L2/L3 skill: `stride-dread` | `dread_score.py` (190 lines, stdlib); 45 pytest cases, all green; establishes the reusable pattern |
| TASK-36 | Skills rollout recipe + `SKILLS-ROLLOUT.md` | `@include` dropped as primary contract; 16-skill queue documented with batches; security batch (skills 1–4) converted in same task |
| TASK-42 | Known-references registry | `user-prompt-submit.sh` emits Known References system message on turn 1; reads `paths.shared_docs`, `paths.knowledge_repo`, `refs.*` cc config keys, and memory entries of type `reference`; graceful no-op when unconfigured. Register: `cc config set refs.<name> <value>` |
| TASK-44 | QA-gate clearing bug fixed | Root cause, fix, and cautionary note: see §5 |

### Done — Skills Conversion (all 16/16 green, WP-49)

See `SKILLS-ROLLOUT.md` for the rollout recipe and full status table.

**Code-bearing skills (L1/L2/L3 — Python stdlib scripts + pytest):**

| # | Skill | Script | Deterministic Core |
|---|---|---|---|
| 1 | `security/stride-dread` | `dread_score.py` | DREAD 5-dim average + band assignment |
| 2 | `security/threat-modeling` | `stride_coverage.py` | STRIDE category coverage checking + DREAD scoring |
| 3 | `security/web-security` | `owasp_score.py` | OWASP Top 10 category coverage + severity tally |
| 4 | `security/crypto-patterns` | `crypto_check.py` | Weak-algorithm/key-size/mode detection (NIST SP 800-131A / OWASP / RFC lookup) |
| 5 | `testing/pytest-patterns` | `pytest_smell.py` | AST-based: 7 smells (no-assert, empty test, bare except, magic number ≥1000, sleep, print) |
| 6 | `testing/jest-patterns` | `jest_smell.py` | Regex-based: 7 smells (.only, .skip, no expect, async-no-await, setTimeout(0), console.log, done callback) |
| 7 | `code/refactoring-patterns` | `refactor_metrics.py` | AST/regex: long_function >20L, deep_nesting >4, long_param_list >3, large_file >300L, many_functions >10 |
| 8 | `code/python-idioms` | `python_lint.py` | AST-based: MUTABLE_DEFAULT, BARE_EXCEPT (HIGH); EQ_NONE, RANGE_LEN, TYPE_COMPARE (MEDIUM) |
| 9 | `code/javascript-patterns` | `js_patterns.py` | Regex lint-lite: VAR_DECL, LOOSE_EQUALITY, CALLBACK_NESTING (MEDIUM); CONSOLE_LOG (LOW) |
| 10 | `code/react-patterns` | `react_patterns.py` | Structural regex: INDEX_AS_KEY, HOOK_IN_CONDITIONAL (HIGH); MISSING_KEY (MEDIUM) |
| 11 | `devops/docker-patterns` | `docker_lint.py` | Dockerfile linter: root USER, :latest tag, missing HEALTHCHECK, apt flags, secrets in ENV/ARG, layer-bloat (CIS §4.1, §4.10) |
| 12 | `devops/kubernetes` | `k8s_lint.py` | K8s manifest: missing resource limits/probes, :latest image, privileged, hostNetwork, no non-root securityContext (CIS §5.2.1, §5.2.4, §5.2.6) |
| 13 | `devops/ci-cd-patterns` | `cicd_lint.py` | GitHub Actions: unpinned action versions, missing timeout, no permissions block, hardcoded secrets (OSSF Scorecard) |
| 14 | `devops/git-workflows` | `git_check.py` | Conventional Commits 1.0.0 format + valid-type check (HIGH); branch prefix/kebab-case (MEDIUM) |
| 15 | `documentation/api-docs` | `api_coverage.py` | OpenAPI 3.x/Swagger 2.0: 12 rules — missing summaries/descriptions/examples, undocumented params, missing 4xx responses, auth error codes, operationId casing |
| 16 | `architecture/system-design-patterns` | `arch_fitness.py` | ADR structural completeness (Nygard format, 7 required fields) + coverage banding (ISO/IEC 25010) + trade-off checklist gap detection |

**Legitimately-prose skills (keep as pure markdown — no genuine deterministic core):**

| Skill | Reason |
|---|---|
| `copywriting/litmus-test` | Subjective judgment about whether copy passes brand voice criteria |
| `copywriting/voice-tone` | Voice and tone are generative/taste — no closed rule set |
| `copywriting/voice-and-tone` | Same as above |
| `design/aesthetic-directions` | Aesthetic evaluation is irreducibly subjective |
| `design/color-palettes` | Color choices depend on brand context and perceptual judgment |
| `design/design-heuristics` | Nielsen heuristics are judgment calls, not deterministic checks |
| `design/design-patterns` | Pattern applicability requires contextual judgment |
| `design/motion-choreography` | Motion quality is perceptual |
| `design/premium-interaction-craft` | "Premium" is a subjective quality |
| `design/spatial-luminous-design` | Design taste |
| `design/typography-pairings` | Typographic harmony is aesthetic judgment |
| `design/ux-patterns` | UX pattern selection is contextual |
| `documentation/tutorial-patterns` | Tutorial pedagogy is Diátaxis judgment, not a deterministic check |

**The split principle (from stride-dread exemplar):** Extract ONLY the deterministic core into L3 script; keep all prose judgment in L2 markdown. A skill that manufactures a script for taste or voice concerns is worse than no script.

### Remains — P2 (optional, last, complexity: High)

| Item | What It Is | Dependency |
|---|---|---|
| Unify two FTS5 stacks | `cc memory_index.py` (manual drop+reinsert rebuild) and `tc` schema triggers (trigger-maintained `work_products_fts`) solve the same problem with divergent designs. Prefer trigger-maintained (incremental). | After TASK-32, TASK-34 |
| Programmatic tool-calling path for `tc` and `cc` | Expose as code-execution callable so agents manipulate task/WP data without round-tripping full payloads through context. Largest unpulled lever for context reduction. | After FTS5 unification |
| Extension → native plugin packaging | Bundle agents + skills + hooks + MCP via `marketplace.json` + `extraKnownMarketplaces` for team auto-discovery. **Must preserve per-agent OVERRIDE** (`[agent].override.md`) — native plugins have no equivalent; must be retained as a thin custom layer. | After TASK-26, TASK-36 |
| Opt-in embeddings | Wire `CC_MEMORY_EMBEDDING_MODEL` for true semantic recall; the `SearchBackend` seam (TASK-32) is the injection point. This is strictly opt-in — the honest FTS5 default is correct behavior without it. | P2 only |

---

## 3. The Skills Architecture

Skills follow the **Anthropic 3-level progressive disclosure model**:

| Level | What It Is | Always In Context? |
|---|---|---|
| L1 | Frontmatter metadata (`name`, `description`, `when_to_use`, `allowed-tools`) | Yes — the model reads this to decide whether to invoke the skill |
| L2 | Prose instructions, heuristics, judgment guidance | On invoke — loaded when the skill is used |
| L3 | Executable script (`scripts/*.py`), run via Bash tool | Never — only the **output** enters context; script source stays out |

**Why L3 matters:** For logic the model re-derives from scratch each session (DREAD arithmetic, OWASP coverage gaps, Dockerfile rule lookup), re-derivation is both possible and error-prone. Bundling the deterministic core in a script guarantees consistent results, eliminates re-derivation, and keeps script source out of context. The tradeoff: scripts add a Bash invocation step; skills require `allowed-tools: [Bash]`.

**The `@include` note:** `@include .claude/skills/NAME/SKILL.md` was a documentation convention. The `@include` syntax causes Claude Code to literally insert file contents — it is fine for manual loading but was never a parsed framework contract. Nothing read or enforced it. It has been dropped as the primary invocation mechanism. `SKILL.md` (frontmatter + prose) is the canonical skill contract; `@include` may appear as an optional manual-load note.

**Rollout recipe:** `SKILLS-ROLLOUT.md` is the authoritative step-by-step recipe for converting future skills. Do not deviate from it without updating that document.

---

## 4. Memory: Fixed, Not Removed

The framework's `cc memory` was dormant before PRD-2: zero entries existed, and no agent called `cc memory store` or `cc memory search`. PRD-2 fixed this with three changes:

1. **Honest rename** — "semantic search" replaced with "full-text (FTS5 keyword) search" in CLAUDE.md, architecture docs, agent preambles, and the competitive landscape companion doc.
2. **Pluggable `SearchBackend` seam** — `memory_index.py` refactored to introduce a `SearchBackend` Protocol (runtime_checkable). `FTS5Backend` is the default implementation. Future embeddings back-end wires in via `set_default_backend()` without changing call sites.
3. **Wired into 7 agent preambles** — `me`, `ta`, `qa`, `do`, `doc`, `sd`, `design` now call `cc memory search` at start and `cc memory store` at end per the CLAUDE.md Agent Shared Behaviors block.

**What memory is now:** FTS5 keyword/BM25 recall over typed entries committed to the repo. The edge over native auto-memory: entries travel with the repo across machines; typed entry kinds (`decision | context | lesson | reference | person`) enable structured filtering; the index survives repo clone without re-run.

**What memory is not:** Semantic or vector search. Opt-in embeddings is a P2 item gated on the SearchBackend seam being stable.

---

## 5. QA-Gate Clearing Bug — Cautionary Note

The mechanical QA-gate hook (`.claude/hooks/subagent-stop.sh`) had a clearing bug discovered and fixed as TASK-44 (WP-44).

**Root cause:** `handle_qa_completion` extracted only the **first** TASK-N from QA's verdict message and cleared only that task from `pending_tasks`. When QA's message referenced a task from prior context (e.g., TASK-36) but the actual pending task was different (TASK-42), `pending_tasks` was never cleared. The gate stayed permanently blocked — including blocking ALL Bash calls, which meant QA itself could not execute tests to issue a verdict. A self-blocking gate.

**Fix:** Two-part:

1. Added `extract_all_task_ids()` — returns a JSON array of all TASK-N IDs from the message.
2. Rewrote the pass path: compute intersection of all mentioned IDs against current `pending_tasks`. If intersection non-empty → clear only those (targeted). If intersection empty (ID mismatch) → clear ALL `pending_tasks` (full-clear fallback).
3. Pass verdict no longer requires a task_id — a passing QA verdict unblocks the session even if task extraction returns empty.

Additionally, `tc task create`, `tc task update`, `tc wp store`, `tc handoff`, `tc prd`, and `tc stream` were added to `QA_GATE_SAFE_PREFIXES` so agents can perform task bookkeeping while the gate is active.

**Lesson for mechanical enforcement:** Exit-2 hooks that gate ALL tool calls must be tested against the full class of QA message formats, including ones that mention previous-session task IDs. A gate that can block the clearing agent is a design flaw, not just a bug. Fail-open on parse errors (implemented in the fix) is mandatory for any hook of this type.

---

## 6. Preserve Through Any Cut

The following capabilities have **no native Claude Code equivalent**. They are the irreducible core of the framework's value. Any future removal track must keep these intact.

- **`tc` work products** — typed, hybrid inline/file storage with FTS search; ~94% context reduction for agent outputs; externalization threshold calibrated at 8KB (P1 fix).
- **`tc` cross-session task persistence** with dependency tracking, atomic `claim`, and priority ordering.
- **`tc handoff` + `agent_log`** — structured cross-agent context passing (native subagents are context-isolated).
- **Knowledge-repo per-agent OVERRIDE mechanism** — `[agent].override.md` replaces agent methodology sections; native plugins have no equivalent override path.
- **Methodology-embedded agents** — IDEO (sd), Nielsen + Rams + Atomic Design (design), ADR / Fitness Functions (ta), Kent Beck (me), Diátaxis (doc), 12-Factor / SRE (do), Meszaros (qa); plus per-agent model assignment.
- **Hook-enforced workflow logic** — force-delegate (5-consecutive-tool block), qa-gate (mandatory `@agent-qa` after every `@agent-me`), session-cap advisory; these are behavioral contracts enforced at exit2.
- **`/protocol` deterministic flow sequencing** — `sd → design → ta → me → qa` as a guaranteed ordered chain; native auto-delegation is probabilistic, not guaranteed-ordered.
- **Known-references registry** — session-start injection of configured CLI paths and reference memory entries; zero-configuration fallback.

---

## References

### Native Claude Code Documentation (authoritative)

- Memory system: <https://code.claude.com/docs/en/claude-code/memory>
- Sub-agents: <https://code.claude.com/docs/en/claude-code/sub-agents>
- Hooks: <https://code.claude.com/docs/en/claude-code/hooks>
- Skills (SKILL.md): <https://code.claude.com/docs/en/claude-code/skills>
- Plugins + marketplaces: <https://code.claude.com/docs/en/claude-code/plugins>
- Tasks (native): <https://code.claude.com/docs/en/claude-code/tasks>
- MCP integration: <https://code.claude.com/docs/en/claude-code/mcp>
- Settings + `settings.json`: <https://code.claude.com/docs/en/claude-code/settings>
- Agent Skills API: <https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview>

### Internal

- External competitive benchmarking: [`docs/70-reference/03-competitive-landscape.md`](./03-competitive-landscape.md)
- Skills rollout recipe + status: [`SKILLS-ROLLOUT.md`](../../SKILLS-ROLLOUT.md)
- Capability inventory: `tc wp get 28`
- Original analysis (superseded stances): `tc wp get 29`
- Ground-truth correction: `tc wp get 30`
- Implementation plan: `tc wp get 31`
- Skills exemplar (stride-dread): `tc wp get 33`
- QA-gate bug fix: `tc wp get 44`
- QA final verification: `tc wp get 48`, `tc wp get 49`
