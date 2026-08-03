# Product Composition Over One Shared Layer-Resolver

| | |
|---|---|
| **Status** | Design / Proposed (extends [`02-four-tier-and-github-topology.md`](../docs/80-initiatives/01-ecosystem-extensions/02-four-tier-and-github-topology.md)) |
| **Branch** | `ecosystem-extensions` |
| **Question answered** | "How do THREE product families — Claude/Codex Copilot (foundation), Knowledge Copilot, CLI Copilot — compose over one resolver across 4 tiers, adopted progressively, so a worker gets deep focus not the whole-org corpus?" |

---

## 0. Bottom line up front

**A product is a bundle of dimensions; the resolver resolves dimensions, not products.** There is exactly one resolution engine (the manifest-driven, rank-ordered walk from doc 02), and every product family simply contributes rows to the dimension×tier matrix it already understands. Adding a product family is additive by construction — it introduces new *dimensions* (or populates existing ones at new tiers), never a new *engine*. Progressive adoption is therefore free: the foundation product resolves standalone with zero knowledge/CLI layers, and `copilot extend <product>` folds a product's four tiers into the existing manifest as more `layers[]` entries carrying more dimension roots.

The single load-bearing insight that makes "focus, not corpus" work: **the knowledge dimension resolves department-scoped**, so a Finance user's manifest engages Finance + org + foundation knowledge roots and *never clones or points at* Engineering's — the corpus is bounded at the manifest, before any content is read.

---

## 1. Product-as-a-dimension-set

The resolver from doc 02 is a fold over an ordered list of **layers**, where each layer is `{id, role, rank, unit?, source{repo,ref,path}, auth, activation}`. A layer's `source` root contains **dimension subtrees**: `agents/`, `skills/`, `commands/`, `protocol/`, `knowledge/`, `memory/`, `tasks/`, `integrations/`. The resolver walks layers by rank and, per dimension, applies that dimension's resolution *semantics* (override | accumulate | personal-write | project-local — §6). It has no concept of "product."

A **product family** is nothing more than *which dimension subtrees it authors* plus *the tiers at which it authors them*:

| Product family | Owns dimensions | Tiers it populates |
|---|---|---|
| **Claude/Codex Copilot** (FOUNDATION product) | `agents`, `skills`, `commands`, `protocol`, `memory` (Memory Copilot), `tasks` (Task Copilot) | all 4 — foundation ships the base set; org/dept/personal override & extend |
| **Knowledge Copilot** | `knowledge` | org, dept, personal (foundation ships an empty/example knowledge root; real knowledge is private) |
| **CLI Copilot** | `integrations` (connectors, MCP declarations, `copilot` subcommands/config) | org, dept, personal (foundation ships the `copilot` binary + base connectors) |

**The resolver is product-agnostic — confirmed.** Each cell in this table is already a `(dimension, tier)` pair the doc-02 resolver handles. Knowledge Copilot's dimension is *literally the seam that already ships* (`paths.knowledge_repo`, list-valued, `resolve_knowledge_repos()` in `config.py:176`). Claude Copilot's agent/skill/command dimensions are the materialize-into-`.claude/` path (doc 02 §on materialize-don't-merge; findings §5.1). CLI Copilot's `integrations` dimension is the one net-new subtree, but it resolves through the *same* rank-ordered walk — a connector registry keyed by name, resolved per-name with the same override/accumulate policy. No product carries bespoke resolution logic; each is a set of subtrees the one resolver reads.

The consequence: the manifest is the *composition* surface. "Which products has this user adopted, at which tiers" is answered entirely by reading `copilot.layers.yml` and asking which dimension subtrees exist under each layer's `source`.

---

## 2. Progressive adoption without breakage

**Invariant: adopting a product is purely additive.** The foundation product installs first and is fully functional with a manifest containing exactly one layer (`foundation`, rank 40) whose `source` roots `agents/skills/commands/protocol/memory/tasks`. There is no `knowledge` root beyond an example, and no `integrations` beyond the base `copilot` binary. The resolver walks a one-element list; every dimension resolves; nothing references a knowledge or CLI tier because none is declared. **A missing dimension is the empty resolution, never an error** — `resolve_knowledge_repos()` already returns `[]` for absent config (config.py:195), and the resolver generalizes that: an unpopulated dimension contributes nothing and the base wins.

Adding Knowledge Copilot later is one manifest edit:

```bash
copilot extend knowledge --tier org  git@github-work:acme-corp/copilot-org.git#knowledge/
copilot extend knowledge --tier department --unit finance \
    git@github-work:acme-corp/copilot-dept-finance.git#knowledge/
```

`copilot extend <product>` does three things, all reversible:

1. **Registers the product's tiers as layers** in `copilot.layers.yml` — or, if the org/dept layers already exist (because the foundation product's org layer is there), it *marks those layers as carrying the product's dimension root* (adds/points `source.path` at the product subtree). One physical layer repo can carry multiple products' subtrees; `(repo, path)` addressing (doc 02 §4) makes a layer's knowledge root and agent root independently locatable.
2. **Wires `cc` config** — for the knowledge dimension specifically, it appends to the existing `paths.knowledge_repo` list (`cc config add`, back-compat preserved) so `CC_PATHS_KNOWLEDGE_REPO` keeps emitting. For other dimensions it's a manifest `rank` insert.
3. **Re-materializes** — `copilot update` re-runs resolve; the new dimension now resolves; every previously-resolved dimension is byte-identical because its layers and ranks are unchanged.

**Dependency graph:** `foundation` is the only mandatory node. `knowledge` and `integrations` are optional dimensions that depend on `foundation` (they need the resolver + `cc`/`tc` substrate) but **not on each other**. Adopting CLI Copilot without Knowledge Copilot, or vice versa, both resolve cleanly. There is no product that must precede another except the foundation. Because adoption only ever *adds layers or populates dimension roots at existing layers*, and the resolver is a pure fold, the pre-adoption resolved set is a strict subset of the post-adoption set for every unchanged dimension — that is the formal statement of "additive, no breakage."

---

## 3. The "focus, not corpus" mechanism — the core value prop

**A Finance user gets Finance + org + foundation knowledge and NOT Engineering's because the *manifest itself* engages only the Finance department layer.** This is doc 02 §5 (department selection) applied to the knowledge dimension.

Concretely:

1. `cc config set layers.department finance` (or the project pins it, or `CC_LAYERS_DEPARTMENT=finance`). This is the deterministic, offline selection key — never a live team-membership lookup.
2. The manifest's `department`-role layer templates its source on that key: `repo: …/copilot-dept-${layers.department}.git` → resolves to `copilot-dept-finance`. **Engineering's dept layer is never named, never cloned, never added to `paths.knowledge_repo`.**
3. The resolved knowledge stack is therefore exactly: `personal knowledge` › `finance knowledge` › `org knowledge` › `foundation knowledge`. Under Option A topology (separate repos, doc 02 §6.2 — the recommended default precisely *because* department exists to scope content), the Engineering repo is not even readable by the Finance user's credential.

The corpus is bounded **at manifest resolution, before content load** — not by filtering a big loaded blob at read time. A worker is deep in a narrow area because their knowledge dimension resolves to a small, focused set of roots. This is the whole value prop, and it is a direct, already-shipping consequence of department-scoped resolution on the accumulate-typed knowledge dimension.

**Multi-department** (doc 02 §5): declare two `department`-role layers with distinct `unit` and `rank`; both accumulate. Focus is still bounded — you get *your* two departments, not all of them.

**Does memory tier?** Yes — see §4. The same focus logic applies: shared memory accumulates department-scoped on the read side, so a Finance user recalls Finance + org + foundation decisions, not Engineering's.

**Does Task Copilot tier?** No — tasks are project-local (§4). Focus there is the working tree, not the tier stack.

---

## 4. How Memory Copilot & Task Copilot fit the tiers

These are the stateful dimensions, so they need read/write path separation — the resolution semantics differ by direction.

### Memory Copilot — ACCUMULATE on read, PERSONAL/PROJECT on write

**Recommendation: memory reads accumulate across personal + department + org + foundation; writes land in the personal (or project) layer only.**

- **Read path (accumulate, like knowledge).** `cc memory search` resolves an ordered list of memory roots exactly as knowledge does — a `memory` dimension list, `[personal, dept, org, foundation]`, each contributing `entries/*.md` to the FTS5 index. The index is a local cache built over all resolved roots (union, deduped by entry UUID; nearest-tier wins on UUID collision, mirroring override for identity but accumulate for the corpus). A worker recalls **company decisions** (org memory: "we standardized on X"), **department lessons** (dept memory: Finance's close-process gotchas), and **personal context** in one search — department-scoped, so Engineering's memory is not in the index.
- **Write path (personal/project only).** `cc memory store` **always writes to the personal layer** (`~/.claude/memory` today, or the personal repo's `memory/entries/` — already scaffolded in `claude-copilot-private`). It **never** writes up-tier. Promoting a personal memory entry to org/dept shared memory is a *deliberate, reviewed* action — the same one-way promotion valve as foundation promotion (doc 02 §8): `copilot promote memory <uuid> --to org` cherry-picks the entry into the org memory repo via PR. This preserves the "writes are local, sharing is governed" boundary and prevents an agent from silently polluting company-wide memory.

Rationale: shared org memory (company decisions, architectural standards) is real and valuable, and it *reads* like knowledge — additive, tiered, focus-bounded. But write-up-tier would be a governance and blast-radius disaster (any session mutating company memory). The read/write split is the clean resolution: **read accumulates down the stack; write lands at the bottom (personal); up-tier movement is a promotion event, not a store.**

### Task Copilot — PROJECT-LOCAL

**Recommendation: tasks/PRDs are project-local; they do not tier.**

Tasks and PRDs are ephemeral, per-initiative, and bound to a working tree (a specific repo + branch + worktree). They are not a shared corpus and have no meaningful org/dept/personal cascade — an org-wide "task" is a different concept (a program/roadmap item), out of scope for `tc`. `tc` continues to read/write the project's `.claude/` (or its configured store). The only tier interaction: a task's *work products* may be **promoted** to knowledge (a durable WP becomes org knowledge) — again a deliberate promotion, not automatic tiering. Read and write are both project-local; there is no cross-tier read path for tasks.

---

## 5. Cross-product references

The three products interoperate **through the shared `cc`/`tc` env + resolver — not bespoke glue.** The wiring an org-tier agent uses to reach org knowledge and an org CLI tool:

1. **Agent → org knowledge (Knowledge Copilot):** the agent runs `eval "$(cc env)"` (already in the agent preamble, per CLAUDE.md shared behaviors) which emits `CC_PATHS_KNOWLEDGE_REPO` = the resolved, department-scoped, ordered knowledge roots. The agent reads those paths directly. **This seam exists today.** The org agent authored at the Claude-Copilot org layer and the org knowledge at the Knowledge-Copilot org layer meet through one env var the resolver populated — neither product knows about the other's internals.
2. **Agent → org CLI tool (CLI Copilot):** the agent invokes `copilot <subcommand>` / `cc …` / `tc …` via Bash. The `copilot` binary resolves *its own* integration dimension through the same manifest (org connectors resolve over personal ones by rank). The agent doesn't wire the connector; it calls the CLI, and CLI Copilot's resolved integration stack answers.
3. **The common substrate is the contract.** Every product reads the same `cc config` cascade (env›project›machine) and the same `copilot.layers.yml`. An org agent needing an org connector needing org knowledge is three dimensions resolved by one resolver, surfaced through `cc env` + the `copilot`/`cc`/`tc` CLIs. Because the resolver lives in the shared `cc`/`tc` substrate (findings §5.3, §6), both Claude Copilot and Codex Copilot inherit this interop for free — Codex calls the same CLIs and reads the same env.

There is **no product-to-product API**. Interop is mediated entirely by (a) the resolved env (`CC_*`), (b) the shared CLIs, and (c) the shared manifest. That is the definition of composing over one resolver rather than gluing products together.

---

## 6. What lives where — the authoritative resolution-semantics matrix

Rows = dimensions; columns = the 4 tiers (PERSONAL rank 10 › DEPARTMENT 20 › ORG 30 › FOUNDATION 40). Cell = the semantics the resolver applies for that dimension at that tier.

Legend: **override** = nearest-tier whole-unit wins (shadowing reported); **accumulate** = all tiers contribute, ordered, nearest-first; **personal-write** = read accumulates, writes land here only; **project-local** = not tiered, bound to working tree; **base** = ships the default, lowest precedence.

| Dimension (owning product) | PERSONAL (10) | DEPARTMENT (20) | ORG (30) | FOUNDATION (40) |
|---|---|---|---|---|
| **agents** (Claude/Codex) | override | override | override | override (base) |
| **skills** (Claude/Codex) | override | override | override | override (base) |
| **commands** (Claude/Codex) | override | override | override | override (base) |
| **protocol** (Claude/Codex) | override¹ | override¹ | override¹ | override¹ (base) |
| **knowledge** (Knowledge Copilot) | accumulate | accumulate (dept-scoped) | accumulate | accumulate (base/empty) |
| **memory** (Memory Copilot) | personal-write | accumulate (read, dept-scoped) | accumulate (read) | accumulate (read, base) |
| **tasks** (Task Copilot) | project-local | project-local | project-local | project-local |
| **CLI-integrations** (CLI Copilot) | override² | override² | override² | override² (base) |

**Notes:**

- ¹ **protocol** is override at the whole-chain level today (materialize the winning `protocol.md` + routes). Chain-level *composition* (a dept inserting an industrial-designer stage into the org chain — findings §5.5, §7 workstream 5) is the hardest, P2 dimension; until the chain-as-data composer ships, protocol resolves whole-unit override like commands. The matrix cell is override now, *accumulate-of-stages* later — a semantics upgrade contained entirely within this one dimension.
- ² **CLI-integrations** default to override (a personal connector named `slack` replaces the org `slack`), but individual connector *lists* may be marked accumulate (both an org and a personal MCP server appear) — the same override-vs-accumulate per-name choice knowledge already makes. This is the net-new dimension (findings §4, §7 workstream 4); its registry is keyed by connector name and resolved by the same rank walk.
- **memory** is the only split-direction row: the read path is accumulate (dept-scoped, like knowledge), the write path is personal-write. That single asymmetry is the entire design decision of §4.
- **tasks** is the only non-tiered row — project-local by nature; promotion to knowledge is the only cross-tier movement and it is a deliberate valve, not resolution.

This matrix is the authoritative contract: **per dimension, per tier, exactly one semantics**, and every one of them is a policy the single doc-02 resolver already applies or (protocol composition, CLI accumulate) applies within one dimension's own upgrade path. No product changes the resolver; each product only adds rows and populates cells.

---

## 7. Decisions to ratify

| # | Decision | Complexity |
|---|---|---|
| 1 | Product = dimension-bundle; one product-agnostic resolver resolves dimensions, not products | Low (confirms existing design) |
| 2 | Adoption is additive: `copilot extend <product>` adds layers / points `source.path` at product subtrees; missing dimension = empty resolution, never error | Low |
| 3 | Focus-not-corpus = department-scoped resolution on the knowledge dimension; corpus bounded at manifest, before content load | Low (ships today for knowledge) |
| 4 | **Memory: accumulate on read (dept-scoped), personal-write on store; up-tier only via `copilot promote memory`** | Med |
| 5 | Tasks: project-local, not tiered; WP→knowledge promotion is the only cross-tier movement | Low |
| 6 | Cross-product interop is mediated ONLY by resolved `CC_*` env + shared `copilot`/`cc`/`tc` CLIs + shared manifest — no product-to-product API | Low |
| 7 | The §6 matrix is the authoritative resolution-semantics contract per dimension per tier | Low |
