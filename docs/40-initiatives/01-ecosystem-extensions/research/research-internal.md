# Claude Copilot Extensibility — Current-State Research (feasibility of 3-layer model)

Scope: read-only trace of how each extensible dimension is discovered/resolved TODAY, what
layering exists, and what new machinery a public→company→personal (Layer 1/2/3) merge would need.

Vision recap: one unified experience; content resolves across three git repos —
L1 PUBLIC framework, L2 COMPANY private, L3 PERSONAL private. Dimensions that must layer:
AGENTS, SKILLS, COMMANDS/PROTOCOL, KNOWLEDGE, INTEGRATIONS (MCP/CLI).

---

## The single most important structural fact

There are **two independent resolution engines**, and only one of them can layer deterministically:

1. **Native Claude Code discovery** — governs AGENTS, COMMANDS, SKILLS (auto-fire), and MCP.
   It scans fixed directories: `.claude/agents/`, `.claude/commands/`, `.claude/skills/` (project)
   and `~/.claude/agents|commands|skills/` (user/machine), plus plugin skills. It offers at most
   **two tiers** (project + user), name-keyed, **whole-unit override** (no section merge). It
   **cannot discover from arbitrary external dirs** — content must physically live in (or be
   symlinked into) those paths.
2. **`cc` CLI config resolution** (`tools/cc/src/cc/core/config.py`) — governs KNOWLEDGE only.
   Precedence `env CC_* > project config > machine config > default`. This is the ONLY place a
   real **ordered list** of layers is resolved deterministically today (`resolve_knowledge_repos`,
   config.py:176-201).

Consequence: The framework already consumes native "project" tier by **copying** framework agents/
commands into each project's `.claude/` (see update-project below). So a 3-layer public→company→
personal model cannot be expressed through native discovery alone (2 tiers, one already used). Every
native-discovered dimension therefore needs a **materialization/sync step** (a resolver + build that
writes merged results into the discovery paths) OR symlink bridging. Only KNOWLEDGE escapes this,
because `cc` resolves a list of *pointers* that agents read at runtime — no discovery-path constraint.

---

## Dimension 1 — AGENTS

**Discovery TODAY (native):** `.claude/agents/*.md` (project) and `~/.claude/agents/*.md` (user).
Flat markdown + frontmatter. Native override is name-keyed, project-wins, **whole-file** (no merge).

**How framework populates it:** `/update-project` **copies** framework agents into the project tree.
`.claude/commands/update-project.md:186-255` (Step 7) reads the roster from `VERSION.json.components.
agents.frameworkAgents` and does `cp $COPILOT/.claude/agents/<agent>.md .claude/agents/` for each.
This is a copy, not a symlink or merge.

**Layering that exists TODAY:**
- `owner: project` frontmatter marker → sync never overwrites/removes that file (update-project.md:190,
  233-237; CLAUDE.md "Project-Owned Agents"). This is a **one-level, whole-file override** (project beats
  framework) — the only real agent layering shipped.
- The spec's per-agent `<id>.override.md` / `<id>.extension.md` with `overrideSections`/`preserveSections`
  section merging + `requiredSkills` validation is **documented convention, NOT implemented** (see Gap
  section). No code parses or merges these.

**Constraints for 3-layer:** native gives project+user only; section-level merge does not exist anywhere.
Company and personal agents can't both be "user tier" without one clobbering the other by name.

**Verdict: layerable-by-convention-today (whole-file override only). 3-layer merge = needs-new-machinery.**
Needs: a resolver + build/sync step that walks L1/L2/L3 repos, resolves per-agent precedence
(personal > company > public) and/or section merges, and **materializes** the winner into
`.claude/agents/` (the native discovery path). A manifest per layer declaring which agents it
overrides/extends would drive it deterministically.

---

## Dimension 2 — SKILLS

**Discovery TODAY (two paths, keep them distinct):**
- **Native auto-fire** (primary): Claude Code surfaces every skill's name+description from
  `.claude/skills/**/SKILL.md` (project), `~/.claude/skills/**/SKILL.md` (machine), and plugin skills,
  and fires on prompt match. Framework skills live at `.claude/skills/<category>/<name>/SKILL.md`.
- **`cc skill search`** (fallback): `skill_store.default_skill_paths()` (skill_store.py:53-73) scans
  **only** project `.claude/skills/` and machine `~/.claude/skills/`. Resolution order project→machine
  →framework, dedup by name first-wins (`discover_skills_with_sources`, skill_store.py:273-289).

**Key finding — knowledge-repo skills are NOT discovered:** neither native auto-fire nor
`cc skill search` looks inside a knowledge repo's `skills/` dir. The private layer ships
`knowledge/skills/` (with only `.gitkeep` today) and the spec references `<id>.skills.json` injection,
but nothing loads them automatically. `paths.global_skills_dir` defaults to `~/.claude/skills`
(config.py:37) — the machine tier, not the knowledge repo.

**Bridging affordance that DOES exist:** `discover_skills` walks with `os.walk(..., followlinks=True)`
(skill_store.py:236) — comment explicitly: "shared framework skills can be bridged into project-local
.claude/skills without copying." So symlinking an external layer's skill dir into `.claude/skills/`
makes both native auto-fire and `cc` see it.

**Verdict: layerable-by-convention-today (via symlink bridging into a discovery path).**
Deterministic 3-layer = needs a materialize/symlink step. Needs: sync that symlinks (or copies)
L2 company + L3 personal `skills/` trees into `.claude/skills/` (or `~/.claude/skills/`), with a
name-collision precedence rule. No section-merge needed (skills are whole units), so this is the
**cheapest dimension to make deterministic** — a symlink-farm build step suffices.

---

## Dimension 3 — COMMANDS / PROTOCOL-WORKFLOWS

**Discovery TODAY (native):** `.claude/commands/*.md` (project) + `~/.claude/commands/*.md` (user).
Framework **copies** its 7 project commands in via `/update-project` Step 6
(update-project.md:158-182, explicit `rm` + `cp` per command). Whole-file, 2-tier, project-wins.

**Protocol workflow chains** (the sd→uxd→…→me routing, defect/experience/technical flows) are NOT a
data structure that layers — they are prose in `.claude/commands/protocol.md` plus routing edges in
`.claude/agents/manifest.json` (the `_comment` there names consumers: session-start banner,
pretool-check valid-agent list, VERSION.json, /protocol routing). Adding a step (e.g. an
industrial-designer stage) means editing protocol.md + manifest.json + the agent roster —
a whole-file framework edit with no layering seam.

**Verdict: commands = layerable-by-convention-today (whole-file copy/override). Protocol chains =
needs-new-machinery.** A layered protocol would need the workflow chain expressed as **mergeable data**
(a manifest of stages/routes each layer can insert into) plus a resolver that composes L1+L2+L3 chains
and regenerates protocol.md/manifest.json. Today it's hand-edited monolithic prose.

---

## Dimension 4 — KNOWLEDGE  ← the one deterministic layer

**Discovery/resolution TODAY (cc):** single config key `paths.knowledge_repo`, resolved by
`config.py`. As of cc 1.7.0 / framework 5.13.0 it is **list-valued** (`LIST_VALUED_KEYS`, config.py:59):
- `resolve_knowledge_repos()` (config.py:176-201) normalizes None→[], list→list, legacy string→[string].
- Precedence unchanged: `CC_PATHS_KNOWLEDGE_REPO` env > project config > machine config > default
  (config.py:293-315). **Lists are NOT concatenated across layers** — the highest-precedence source
  that *sets* the key supplies the whole ordered list (spec.md:196-203; also verified: env/project/
  machine each override, no cross-layer merge).
- `cc config add/remove paths.knowledge_repo <path>` append/remove idempotently
  (`add_to_list_config` config.py:362-390) — how `bootstrap.sh` wires the personal layer.
- `cc env` (commands/env.py:46-83) emits `CC_PATHS_KNOWLEDGE_REPO` = comma-joined list (order
  preserved) and back-compat alias `CC_KNOWLEDGE_REPO` = **first element only** (env.py:80-81).
- Project config uses `@machine` **sentinels** (`.claude/cc/config.json` = `{"paths":{"shared_docs":
  "@machine","knowledge_repo":"@machine"}}`) so the tracked public repo defers entirely to untracked
  machine config — nothing public changes to add a personal layer (EXTENSIONS.md:59-72).

**But consumption is convention:** `cc` resolves only the *pointer list*. It does NOT parse
`knowledge-manifest.json`, merge a glossary, or load `.claude/extensions/*.md`. Agents are instructed
(CLAUDE.md, agent prompts) to read files under the resolved `CC_KNOWLEDGE_REPO` themselves.

**Verdict: layerable-deterministically-today (ordered-list pointer resolution is real and shipped).**
This is the model to generalize. The 3-layer vision *already works* for knowledge:
`cc config add paths.knowledge_repo <company>` then `<personal>` → both resolve in order. Gap is only
that runtime *consumption* of the resolved list is by-convention, and content-level merge (glossary,
overrides) is unspecified/deterministic-nowhere.

---

## Dimension 5 — INTEGRATIONS (MCP / CLI)

**MCP (native):** Claude Code reads `.mcp.json` (project) + user config (`~/.claude.json` / user
settings) + enterprise scope — native **multi-scope merge exists** here (more than the 2 tiers agents
get). The framework's approach: `claude-copilot-private/bootstrap.sh:29` **symlinks** the private
`mcp.json` in as the project `.mcp.json` (single file, whole-file, not a merge across the three product
repos). Note `/update-project` explicitly leaves `.mcp.json` untouched (update-project.md:494).

**CLI (`cc`/`tc`):** installed machine-globally (`tools/cc/install.sh`, `pip install -e tools/tc`);
config is the two-layer machine+project `cc` system (with `secrets.env` machine+project, config.py:
152-159). CLIs themselves are not per-project layered — one binary set per machine.

**Verdict: MCP = layerable-by-convention-today (native scope-merge helps, but framework uses a single
symlinked file). CLI = machine-global, not layered.** For 3-repo MCP composition deterministically:
needs a resolver/build that merges each layer's server declarations into the project `.mcp.json`
(or leans on native user+project+enterprise scopes, mapping company→user, personal→project). CLI
integrations would need a plugin/registry mechanism to layer per-repo.

---

## The spec-vs-implementation gap (confirmed)

`docs/40-extensions/00-extension-spec.md` describes a rich engine: `type: override|extension|skills`,
`<id>.override.md` / `<id>.extension.md` with `overrideSections`/`preserveSections` section merging,
`knowledge-manifest.json` parsing, `requiredSkills` validation with `use_base|use_base_with_warning|
fail` fallback, `ExtensionType`/`ResolvedExtension` types, two-tier project→global→base resolution.

**None of that is implemented.** Evidence:
- The spec's own banner (spec.md:5-21) states `cc` resolves ONLY `paths.knowledge_repo`/`shared_docs`
  as config values (now an ordered list) and everything richer is "an **agent-read convention**…
  no `cc` command parses a manifest, merges an `.extension.md`, or validates `requiredSkills`."
- There is **no `knowledge.py`** in `tools/cc/src/cc/core/` (dir listing: config.py, sentinels.py,
  skill_store.py, memory/docs modules — no knowledge/extension parser). EXTENSIONS.md:46-49 confirms
  "no `.override.md`/`.extension.md` parser, no `ExtensionType`/`ResolvedExtension` code anywhere in
  `tools/cc/src`."
- `claude-copilot-private/EXTENSIONS.md` (written from the running code) is the authoritative
  reconciliation: what's real = the pointer, its precedence chain, and list-valued layering. Manifest +
  extension files = documented convention only.

So today the "extension system" is: **(a) a deterministic ordered-list of knowledge-repo pointers
(real), and (b) a file-layout convention agents may choose to honor (not enforced).**

---

## Feasibility summary (per dimension)

| Dimension | Discovered/resolved by | Layering TODAY | Verdict | Machinery for 3-layer |
|-----------|------------------------|----------------|---------|------------------------|
| Agents | Native `.claude/agents` (copied in by update-project) | `owner: project` whole-file override; 2 native tiers | by-convention (override only) | Resolver + **materialize** step into `.claude/agents/`; per-layer manifest; section-merge engine if sub-file merge wanted |
| Skills | Native auto-fire + `cc skill search`, both scan `.claude/skills` + `~/.claude/skills` | Symlink bridging (`followlinks=True`); knowledge-repo skills NOT auto-discovered | by-convention (symlinkable) | Symlink/copy **build step** farming L2/L3 skills into a discovery path + name-collision rule (cheapest to make deterministic) |
| Commands | Native `.claude/commands` (copied in) | Whole-file copy, 2 tiers | by-convention (commands) | Materialize step |
| Protocol chains | Prose in protocol.md + routes in manifest.json | None (monolithic) | needs-new-machinery | Express chain as mergeable data + composer that regenerates protocol.md/manifest.json |
| Knowledge | **`cc` ordered-list pointer** (config.py `resolve_knowledge_repos`) | **Real ordered list**, env>project>machine, `cc config add` | **deterministic-today** | Already works for pointers; add deterministic content-merge if desired |
| Integrations (MCP) | Native multi-scope `.mcp.json`/user/enterprise; framework symlinks one file | Native scope-merge; framework uses single symlink | by-convention | Resolver merging per-repo server decls, or map company→user / personal→project scope |
| Integrations (CLI) | Machine-global install | None | needs-new-machinery | Plugin/registry layering |

## Bottom line for the architecture doc

- **One dimension (KNOWLEDGE) already implements the 3-layer ordered-list vision deterministically**
  via `cc`'s `paths.knowledge_repo` list + `cc config add` + `cc env`. It is the proof-of-concept and
  the natural place to generalize the model.
- **Everything else is gated by native Claude Code discovery**, which offers only 2 fixed tiers
  (project + user) and whole-unit override. A true 3-layer merge therefore requires a **build/sync
  ("materialize") step**: a resolver that reads L1/L2/L3 repos (driven by per-layer manifests),
  computes precedence (personal > company > public), and writes/symlinks the merged result into the
  native discovery paths (`.claude/agents`, `.claude/commands`, `.claude/skills`, `.mcp.json`).
- The **existing convention scaffolding is reusable**: `owner: project` marker, the symlink pattern in
  `bootstrap.sh` + `followlinks=True` skill discovery, `@machine` sentinels keeping public config clean,
  and the ordered-list config primitives (`add_to_list_config`/`remove_from_list_config`). The missing
  piece is a **deterministic resolver/merger** (currently agent-read convention) and per-layer manifests
  — not a rebuild of the discovery model.
- Skills are the cheapest to make deterministic (symlink farm, no merge). Protocol chains and CLI
  integrations are the hardest (no layering seam exists; needs new data model).
