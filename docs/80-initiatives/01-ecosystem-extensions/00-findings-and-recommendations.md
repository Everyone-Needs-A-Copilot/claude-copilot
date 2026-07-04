# Ecosystem Extensions — Feasibility & Recommendations

| | |
|---|---|
| **Status** | Research / Proposed |
| **Branch** | `ecosystem-extensions` |
| **Date** | 2026-07-04 |
| **Author** | Technical Architect (ADR / fitness-function review) |
| **Question answered** | "What would it take to build a 3-layer (public → company → personal) extension ecosystem where a user experiences ONE unified system?" |
| **Appendices** | [`research/research-internal.md`](research/research-internal.md) · [`research/research-ecosystem.md`](research/research-ecosystem.md) · [`research/research-priorart.md`](research/research-priorart.md) |

---

## 1. Bottom line up front

**Yes — the gold-standard vision is achievable, in phases, and one of the six dimensions already works today.** Knowledge layering is deterministic *right now* through `cc`'s list-valued `paths.knowledge_repo` resolver. That existing seam is the proof-of-concept the whole vision generalizes from.

**What it would take, in one paragraph:** Build a single central mechanism — **a deterministic layer resolver that MATERIALIZES the merged Layer-1/2/3 set into Claude Code's native discovery paths** (`.claude/agents/`, `.claude/skills/`, `.claude/commands/`, `.mcp.json`). Claude Code's native discovery is filesystem-based and layer-unaware: it scans two fixed tiers (project + user) with whole-unit override and cannot read from arbitrary external repos. So a true three-layer cascade cannot be expressed through native discovery — the resolver must *pre-compute* the winning item per name (personal > company > public) and write the result into the paths Claude Code already scans. This is exactly what mature tools do whenever the consumer can't merge for itself (chezmoi `apply`, Kustomize `build`, Ansible `install`, oh-my-zsh's custom dir). The supporting machinery is small and well-precedented: a per-layer **manifest**, a **lockfile** pinning each layer's commit SHA, a **fan-out `update`** command that pulls all layers and re-materializes, and a **`--explain`/provenance** view (git-config `--show-origin` model). Nothing here requires rebuilding the discovery model — it requires a resolver/materializer plus manifests, living in the shared `cc` substrate so both Claude Copilot and Codex Copilot inherit it.

**The honest caveat:** most of the "extension system" that's *documented today* (the per-agent `.override.md`/`.extension.md` section-merge engine in the extension spec) is **unimplemented** — it is an agent-read convention, not shipped code. Knowledge-pointer resolution is the only piece that is real. Everything else is either by-convention (symlink/copy) or needs new machinery.

---

## 2. The vision

One unified experience; content resolves across three git-repo layers, per ecosystem project:

- **Layer 1 — PUBLIC** open-source framework (owner-maintained; global to anyone).
- **Layer 2 — COMPANY** private repo on a company GitHub org (shared org-wide; company knowledge, company-wide skills/integrations).
- **Layer 3 — PERSONAL** private repos extending the company layer (a personal "accountant" agent; personal-only skills/knowledge/integrations only that user needs).

Users **create at the appropriate layer and pull to inherit.** The owner's own three concrete examples anchor the model:

| Need | Layer | Action |
|------|-------|--------|
| Personal-only agent (e.g. a personal **"accountant"** agent) | **Personal (L3)** | Create in personal repo; only you get it |
| Company-wide capability (e.g. an **"Excel-to-JSON" skill** everyone should have) | **Company (L2)** | Create in company layer; everyone inherits by pulling latest |
| Foundation change (e.g. adding an **industrial-designer step** to the protocol/workflow) | **Public (L1)** | Contribute to the public framework; global to all users |

**Updating** = pull latest from public + company + personal, then manage your private versions. **Dimensions that must layer:** AGENTS, SKILLS, COMMANDS/PROTOCOL-WORKFLOWS, KNOWLEDGE, INTEGRATIONS.

**The projects:** Cloud Copilot, Codex Copilot, Knowledge Copilot, CLI Copilot (three intended open source), plus **Claude Copilot** (this repo) as the Layer-1 foundational hub.

---

## 3. Current state — what exists today

### 3.1 Two independent resolution engines (the single most important structural fact)

There are two resolution engines, and **only one can layer deterministically**:

1. **Native Claude Code discovery** — governs AGENTS, COMMANDS, SKILLS (auto-fire), and MCP. Scans fixed directories: `.claude/agents|commands|skills/` (project) and `~/.claude/agents|commands|skills/` (user), plus plugin skills. Offers at most **two tiers** (project + user), name-keyed, **whole-unit override** (no section merge). It **cannot discover from arbitrary external dirs** — content must physically live in (or be symlinked into) those paths.
2. **`cc` CLI config resolution** (`tools/cc/src/cc/core/config.py`) — governs KNOWLEDGE only. Precedence `env CC_* > project config > machine config > default`. This is the **only** place a real ordered *list* of layers is resolved deterministically today (`resolve_knowledge_repos`, `config.py:176-201`).

**Consequence:** The framework already consumes the native "project" tier by **copying** framework agents/commands into each project's `.claude/` (`update-project` Steps 6–7). So the 3-layer model cannot be expressed through native discovery alone — two tiers, one already spent. Every native-discovered dimension needs a **materialization/sync step** (resolver + build that writes merged results into discovery paths), or symlink bridging. Only KNOWLEDGE escapes this, because `cc` resolves a list of *pointers* agents read at runtime — no discovery-path constraint.

### 3.2 The knowledge-list proof-of-concept (the seam that already works)

`paths.knowledge_repo` is the **only list-valued config key** (`LIST_VALUED_KEYS`, `config.py:59`), resolved by `resolve_knowledge_repos()` (`config.py:176-201`) as of cc 1.7.0 / framework 5.13.0:

- `cc config add paths.knowledge_repo <company>` then `<personal>` → both resolve, order-preserving (`add_to_list_config`, `config.py:362-390`).
- `cc env` emits `CC_PATHS_KNOWLEDGE_REPO` = comma-joined ordered list, plus back-compat `CC_KNOWLEDGE_REPO` = first element (`env.py:80-81`).
- The public repo stays clean: `.claude/cc/config.json` uses `"@machine"` **sentinels** so the tracked tree defers entirely to untracked machine config — a private layer needs zero change to the public tree.

**But consumption is convention:** `cc` resolves only the *pointer list*. It does not parse a manifest, merge a glossary, or load extension files — agents are *instructed* (CLAUDE.md, prompts) to read the resolved paths themselves. Layer resolution for knowledge is **real**; content-level merge is **aspirational**.

### 3.3 The private companion repo (already scaffolded)

`/Volumes/Dev/Sites/COPILOT/claude-copilot-private` → `github.com/pablitoalejo/claude-copilot-private` (private, personal account). Holds `memory/entries/`, `settings.local.json`, `mcp.json`, `docs-private/`, and a `knowledge/` tree mirroring knowledge-copilot's convention (`knowledge-manifest.json` v1.0 `pablo-personal-knowledge`, `.claude/extensions/`, `skills/`, `docs/glossary.md`). `bootstrap.sh` symlinks these into a sibling checkout **and** runs `cc config add paths.knowledge_repo <dir>` to wire the layer. **This is the personal (L3) layer already existing in prototype form.**

### 3.4 Only 3 of the 4 named projects exist

| Project | Exists? | Status | Repo / visibility |
|---|---|---|---|
| **CLI Copilot** | Yes | Active — the `copilot` binary (Typer/Rich CLI, ~24 services), integrations-as-code | `Everyone-Needs-A-Copilot/cli-copilot` · **private** |
| **Knowledge Copilot** | Yes | Active — shared knowledge base (`shared-docs` → symlink) | `Everyone-Needs-A-Copilot/knowledge-copilot` · **public** |
| **Codex Copilot** | Yes | Active — Codex-native twin, `packs/` extension model, reuses shared `cc`/`tc` | `Everyone-Needs-A-Copilot/codex-copilot` · **public** |
| **Cloud Copilot** | **NO** | **Greenfield / vision-only.** No repo, dir, dossier, or registry entry. Treat as unbuilt. | — |

**Claude Copilot** (this repo) is the Layer-1 foundational hub the three real ones orbit. Claude Copilot and Codex Copilot are **twin host-specific framework layers** (Claude Code vs Codex) over a **shared `cc`/`tc` substrate** — Codex reuses claude-copilot's `tools/cc` + `tools/tc` verbatim (version-pinned in `VERSION.json`, tracked via `parity/claude-baseline.json`).

### 3.5 The spec-vs-implementation gap (confirmed)

`docs/40-extensions/00-extension-spec.md` describes a rich engine: `type: override|extension|skills`, `<id>.override.md`/`<id>.extension.md` with `overrideSections`/`preserveSections` section-merging, `knowledge-manifest.json` parsing, `requiredSkills` validation, `ExtensionType`/`ResolvedExtension` types. **None of it is implemented.** There is no `knowledge.py` in `tools/cc/src/cc/core/`; no `.override.md`/`.extension.md` parser; no `ExtensionType` code anywhere in `tools/cc/src`. The spec's own banner concedes `cc` resolves only `paths.knowledge_repo`/`shared_docs` as config values, and everything richer is "an agent-read convention." `claude-copilot-private/EXTENSIONS.md` (written from the running code) is the authoritative reconciliation.

**So today the "extension system" is: (a) a deterministic ordered-list of knowledge-repo pointers (real), and (b) a file-layout convention agents may choose to honor (not enforced).**

---

## 4. Feasibility by dimension

| Dimension | Resolved by today | Layering today | Verdict | Mechanism to reach 3-layer | What's missing |
|-----------|-------------------|----------------|---------|----------------------------|----------------|
| **Knowledge** | `cc` ordered-list pointer (`resolve_knowledge_repos`) | **Real ordered list**; env>project>machine; `cc config add` | **Deterministic today** | Already works for pointers | Deterministic *content* merge (glossary/overrides) if desired |
| **Skills** | Native auto-fire + `cc skill search` (scan `.claude/skills` + `~/.claude/skills`) | Symlink bridging (`followlinks=True`); knowledge-repo skills NOT auto-discovered | **By-convention today** | Symlink/copy build step farming L2/L3 skills into a discovery path + collision rule | **Cheapest** — no section merge; just a symlink-farm/copy step + precedence |
| **Agents** | Native `.claude/agents` (copied in by update-project) | `owner: project` whole-file override; 2 native tiers | **By-convention today** (override only) | Resolver + **materialize** into `.claude/agents/`; per-layer manifest | 3-layer merge; optional section-merge engine (the unbuilt spec) |
| **Commands** | Native `.claude/commands` (copied in) | Whole-file copy, 2 tiers | **By-convention today** | Materialize step | 3-layer precedence + manifest |
| **Protocol chains** | Prose in `protocol.md` + routes in `manifest.json` | None (monolithic) | **Needs new machinery** | Express chain as **mergeable data**; composer regenerates `protocol.md`/`manifest.json` | The whole data model + composer — **hardest** |
| **Integrations — MCP** | Native multi-scope `.mcp.json`/user/enterprise; framework symlinks one file | Native scope-merge exists; framework uses single symlink | **By-convention today** | Resolver merging per-layer server decls, or map company→user / personal→project scope | Deterministic multi-repo `.mcp.json` composition |
| **Integrations — CLI** | Machine-global install (`cc`/`tc`/`copilot`) | None — flat hard-coded registry off one `.env` | **Needs new machinery** | Plugin/connector registry + scoped config layering | The entire scoping seam — none exists |

**Reading the table:** one dimension is done (Knowledge), three are a build-step away (Skills, Agents, Commands — all gated only by native discovery being layer-unaware), and two need genuinely new data models (Protocol chains, CLI integrations).

---

## 5. Proposed architecture

### 5.1 The central decision — MATERIALIZE, not read-time merge

**Recommendation: materialize the resolved set into the discovery path. Do not rely on read-time merge.**

Claude Code's agent/skill/command discovery is filesystem-based and **layer-unaware** — it scans fixed dirs and cannot perform a three-layer cascade itself. Every prior-art system whose *consumer is unaware of layers* materializes: chezmoi `apply`, yadm, Kustomize `build`, Helm `template`, Ansible `install`, oh-my-zsh's custom dir on the fpath. Read-time merge (VS Code settings, git config) works *only* because those consumers are themselves the merge engine. Claude Code is not. Therefore:

- A **`resolve`/`sync` step** walks layers public → company → personal, computes the winning item per name, and writes the resolved set into `.claude/` (the discovery path).
- **Prefer copy over symlink** for the materialized output — portable, greppable, survives layers living on different volumes, and doesn't break on Windows/containers. Keep the layer repos as the editable source of truth.
- **Whole-item override, not deep field-merge** — an agent/skill is an atomic unit; a higher layer *replaces* the whole file. This dodges the tsconfig/Helm array-merge footguns. Offer opt-in field-level extension only where a real additive need exists (e.g. appending to a knowledge list — mirroring git's "list-typed keys accumulate").

### 5.2 Git topology — manifest + lockfile, no submodules

Per project, three independently-versioned, independently-authed repos: **public → company-private → personal-private.**

- A top-level **manifest** (`copilot.layers.yml`, west-style) lists the three layer repos with a pin per layer (branch, tag, or SemVer range) and an `auth` hint (public = anon HTTPS; company/personal = SSH/token).
- A generated **lockfile** (`copilot.lock`, Terraform/npm-lock model) records the exact resolved commit SHA of each layer so any machine reproduces the same resolved set.
- **Do NOT use submodules or subtree.** The layers have *different visibility/auth* (public OSS vs private company vs private personal) and *different release cadences* — nesting them into one history graph fights all three, and submodule detached-HEAD UX is the exact friction we're trying to avoid. Keep independent clones orchestrated by a fan-out.

### 5.3 The resolver

- **Precedence:** personal > company > public — last-writer-wins per named unit (the git-config cascade, applied per-item).
- **Whole-unit override with REPORTED shadowing:** shadowing is a feature when intended, but always surfaced. `copilot resolve --explain` prints, per item, which layer won and which were shadowed (git `--show-origin` model): *"personal/agents/qa.md shadows company/agents/qa.md shadows public/agents/qa.md."*
- **Hard-error on same-layer collisions:** two items colliding *within one layer* (or a manifest flagging `pin: exact`) is genuine ambiguity → error, don't silently pick (Nix's error-on-equal-priority rigor, without Nix's machinery). Optionally let an item declare `override: true` (intentional shadow, no warning) vs. an accidental same-name collision (warn).
- **Optional namespacing** to prevent accidental collisions and dependency-confusion-class bugs: layer scopes (`acme/qa`, `pablo/qa`) let a company `qa` run alongside the public `qa` when override is *not* intended, and keep routing authoritative.
- **Where it lives:** the shared **`cc`/`tc` substrate**, so BOTH Claude Copilot and Codex Copilot inherit it. This is the single most leverage-efficient placement — the resolver is written once and both host frameworks consume it, exactly as they already share knowledge-pointer resolution.

### 5.4 Update UX — one fan-out command

`copilot update` (or `cc layers sync`): for each layer in the manifest, `git pull` (respecting the pin), then **automatically re-run resolve/materialize** into `.claude/`, then print a **provenance/what-changed diff** — *"company/qa.md updated; personal override still wins; 2 new public skills added."* Supporting verbs:

- `copilot update --layer public` — pull one layer.
- `copilot resolve --explain` — effective set + shadowing.
- `copilot lock` — freeze current SHAs.
- `copilot diff` — preview what an update would change before applying (Kustomize/Terraform-plan ergonomics).
- Optional **conditional activation** (git `includeIf`): a layer/item activates only in matching contexts (company overlay auto-engages inside company repos), so one machine carries company + personal layers and the right one engages per project.

### 5.5 Dimension-by-dimension application

| Dimension | How it resolves + materializes |
|-----------|-------------------------------|
| **Knowledge** | Already works — ordered `paths.knowledge_repo` list; agents read resolved paths. Generalize the pattern; optionally add deterministic content-merge. |
| **Skills** | Cheapest: resolve walks L1/L2/L3 `skills/` trees, copies (or symlinks via existing `followlinks=True`) the per-name winner into `.claude/skills/`. Whole-unit, no merge. |
| **Agents** | Resolve per-name winner (personal > company > public), materialize into `.claude/agents/`. Reuse the `owner: project` marker semantics. Section-merge only if the spec's `.override.md` engine is later implemented. |
| **Commands** | Same as agents — materialize winning `*.md` into `.claude/commands/`. |
| **Protocol chains** | Requires new machinery: express the sd→…→me chain + defect/experience/technical flows as **mergeable data** (a manifest of stages/routes each layer inserts into), then a composer regenerates `protocol.md` + `manifest.json`. The owner's "add an industrial-designer step" example is precisely a company/public insert into this data model. |
| **Integrations — MCP** | Resolver merges each layer's server declarations into project `.mcp.json`, or map company→user scope / personal→project scope and lean on native multi-scope merge. |
| **Integrations — CLI** | Requires a connector/registry manifest + scoped config so `copilot` can load company vs personal integrations. Net-new (see §7, §8). |

---

## 6. Cross-project consistency

The four projects share the model through the **`cc`/`tc` substrate**, which is where the resolver belongs:

- **Claude Copilot** — the Layer-1 hub; owns `tools/cc` + `tools/tc`; the resolver ships here.
- **Codex Copilot** — reuses `cc`/`tc` verbatim (version-pinned). Placing the resolver in `cc` gives Codex parity **for free**; its existing `packs/` model becomes one materialization consumer.
- **Knowledge Copilot** — *already* the knowledge layer; the deterministic dimension. It is the L2 knowledge repo the whole ecosystem reads via `$CC_KNOWLEDGE_REPO`. The generalized resolver treats it as one company-layer input.
- **CLI Copilot** — the gap. Integrations are registered **as code** (Python subpackages wired in `main.py` off one flat `.env`); there is **no plugin/connector manifest and no company-vs-personal scoping seam**. Layering CLI integrations is net-new architecture: a connector registry/manifest + scoped `.env`/config layering.
- **Cloud Copilot** — greenfield. Nothing to extend; if built later, it consumes the same resolver.

---

## 7. Gaps & workstreams to build

1. **Manifest schema** — `copilot.layers.yml`: the three layer repos, pins (branch/tag/SemVer), `auth` hint per layer, optional `includeIf`-style activation conditions.
2. **Resolver / materializer** — walk L1/L2/L3, per-name precedence (personal > company > public), whole-unit override, copy into discovery paths. Lives in `cc`.
3. **Lockfile / pinning** — `copilot.lock` recording resolved SHA per layer; `copilot lock`/`diff` verbs.
4. **CLI-integration scoping** — the missing seam in cli-copilot: a connector/registry manifest + scoped config so integrations layer company vs personal.
5. **Protocol/workflow layering (hardest)** — turn the protocol chain + routing into mergeable data; a composer regenerates `protocol.md` + `manifest.json`.
6. **Provenance / inspect commands** — `resolve --explain`, `--show-origin`-style shadowing report, `update` what-changed diff.
7. **Decide: implement-or-retire the extension-spec merge engine** — the documented `.override.md`/`.extension.md` section-merge is unbuilt. Either implement it (only if whole-file override proves insufficient) or **retire it from the spec** so docs match reality. Recommendation: default to whole-file override (§5.1); implement section-merge only on demonstrated need.

---

## 8. Phased roadmap

*No time estimates — phases, priorities (P0/P1/P2), and complexity ratings (Low/Med/High) only, per framework policy.*

### P0 — Resolver MVP + generalize the proven seam

| Workstream | Complexity | Notes |
|-----------|-----------|-------|
| Manifest schema (`copilot.layers.yml`) | Low | Declarative; west/requirements.yml precedent |
| Resolver + materializer for **agents, skills, commands** via copy-into-discovery-path | **Med** | Whole-unit override, precedence personal>company>public |
| Generalize the knowledge ordered-list pattern into the resolver | Low | Knowledge already deterministic; fold it in |
| Lockfile (`copilot.lock`) + `lock` verb | Low | Record resolved SHA per layer |
| `copilot update` fan-out (pull all layers → re-materialize) | Med | west/`mr` model |

**P0 exit:** a user can wire public + company + personal repos, run one command, and get a correctly-merged `.claude/` for the three cheap dimensions plus knowledge — with reproducible pins.

### P1 — Scoping, provenance, company-layer bootstrap

| Workstream | Complexity | Notes |
|-----------|-----------|-------|
| CLI-integration scoping (connector registry + scoped config in cli-copilot) | **High** | Net-new; no existing seam |
| Provenance/inspect (`resolve --explain`, shadowing report, `diff`) | Med | git `--show-origin` model |
| Company-layer repo template + bootstrap | Med | Mirror the existing personal `claude-copilot-private/bootstrap.sh` |
| MCP multi-layer composition | Med | Merge per-layer server decls or map to native scopes |

### P2 — Protocol layering, Codex parity, Cloud

| Workstream | Complexity | Notes |
|-----------|-----------|-------|
| Protocol/workflow layering (chain-as-data + composer) | **High** | Hardest; unlocks the "add a stage" example |
| Codex Copilot parity | Low–Med | Mostly free via shared `cc`; validate `packs/` as a consumer |
| Cloud Copilot | **High** | Greenfield; scope must be defined first (see §10) |

**Dependency order:** P0 resolver is the spine everything else hangs on. P1 scoping/provenance depends on P0's resolver + manifest. P2 protocol layering depends on P0's manifest+composer patterns; Cloud depends on a scope decision that does not yet exist.

---

## 9. Risks & open questions

| # | Risk / question | Notes |
|---|-----------------|-------|
| 1 | **Cloud Copilot scope ambiguity** | It does not exist — no repo, dossier, or registry entry. Is it hosted/remote sessions? A fourth layer host? Undefined. Must be scoped before any P2 work; cli-copilot's dossier explicitly says it "does not start a remote/cloud session." |
| 2 | **Codex scope** | Codex is a twin *host* over the shared substrate, not a layer. Confirm the resolver in `cc` is the intended shared home and that `packs/` becomes a materialization consumer rather than a parallel system. |
| 3 | **Native-discovery limits** | Two fixed tiers, whole-unit override, filesystem-only. The materialize approach works *around* this but can't change it — sub-file merge will always require our own engine, never native support. |
| 4 | **Secrets/credentials in private layers** | Company/personal repos may carry `.env`/creds/`mcp.json` tokens. Materialization must never copy secrets into a public/tracked tree; the `@machine` sentinel discipline must extend to the resolver. |
| 5 | **Materialize staleness & regeneration triggers** | Copied output drifts from source if not re-resolved. Need clear triggers (post-pull hook, `update` always re-materializes) and a `resolve --check` to detect drift — mirror `cc memory check`. |
| 6 | **Version skew across layers** | Company pins "public ^5.x", personal pins "company ^2.x"; a personal override written against an old public agent may break after a public bump. Lockfile + `diff` preview mitigate; a compatibility/minVersion field per layer (already present in `knowledge-manifest.json`) should be enforced. |
| 7 | **Security of auto-pulling company code** | `copilot update` pulls and materializes executable-adjacent content (agents, skills, MCP servers) from a private org repo. Trust boundary + who can push to the company layer must be governed; consider signed commits (already enforced on claude-copilot). |
| 8 | **Same-name conflict policy** | Confirm: silent-but-reported shadow across layers, hard-error within a layer, optional `override: true` intent flag, optional namespacing. Needs an owner decision (see §11). |
| 9 | **Governance of the company layer** | Who owns/reviews `Everyone-Needs-A-Copilot`'s company layer? The org boundary implies multi-user write; needs a CODEOWNERS/review policy distinct from the personal layer. |

---

## 10. Recommendation

**Build the deterministic layer resolver in the shared `cc` substrate and generalize the knowledge-pointer pattern to all materializable dimensions — materialize, don't read-time-merge.** The vision is sound and mostly a matter of generalizing a seam that already ships. Sequence it: prove the resolver on the three cheap dimensions plus knowledge (P0), then add scoping/provenance and the company-layer bootstrap (P1), then tackle the two hard problems — protocol-chain layering and CLI-integration scoping — plus Codex parity and (once scoped) Cloud (P2).

Reconcile docs with reality early: either implement or retire the unbuilt extension-spec merge engine so the framework's own documentation stops promising code that doesn't exist.

### Immediate next steps

1. **Decide the conflict/namespacing policy** (§9 #8) — silent-shadow + report + hard-error-within-layer, with optional `override:`/scoping. This gates the resolver's core semantics.
2. **Define Cloud Copilot's scope** (§9 #1) — or explicitly defer it, so it stops distorting the four-project framing.
3. **Draft the manifest schema** (`copilot.layers.yml`) and lockfile shape — the smallest artifact that unblocks P0.
4. **Ratify materialize-over-merge and whole-file-override** as the architectural decision (this doc is the ADR seed).
5. **Spike the resolver against the existing personal companion repo** (`claude-copilot-private`) — it already scaffolds an L3 layer; it's the ideal first test fixture.

---

## Appendices

- [`research/research-internal.md`](research/research-internal.md) — current-state trace of how each dimension is discovered/resolved today (the two engines, per-dimension verdicts, spec-vs-impl gap).
- [`research/research-ecosystem.md`](research/research-ecosystem.md) — ecosystem inventory (which projects exist, git topology, the existing knowledge-layer seam, the private companion repo).
- [`research/research-priorart.md`](research/research-priorart.md) — external prior-art (Kustomize, git config cascade, ESLint extends chain, west/mr manifests, chezmoi) and the composite recommendation.
