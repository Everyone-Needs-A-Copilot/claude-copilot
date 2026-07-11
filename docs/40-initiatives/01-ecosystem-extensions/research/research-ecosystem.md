# Ecosystem Inventory — 3-Layer Extension Model Feasibility

Read-only investigation. Source of truth: `/Volumes/Dev/Sites/COPILOT/shared-docs/ECOSYSTEM.md`
(`shared-docs` is a symlink → `knowledge-copilot`). Reconciled against real code where repos exist.

---

## Headline finding: only 3 of the 4 named projects exist

| Project | Exists? | Status |
|---|---|---|
| **CLI Copilot** | Yes | Active, private repo, real code |
| **Knowledge Copilot** | Yes | Active, public repo (renamed from `shared-docs` 2026-06-29) |
| **Codex Copilot** | Yes | Active, public repo, real code |
| **Cloud Copilot** | **NO** | **Not built, not planned in registry.** Zero footprint: no `/Volumes/Dev/Sites/COPILOT/*cloud*` dir, no dossier under `02-products/`, no mention anywhere in `shared-docs`. It is a vision-only concept the user is proposing; the registry does not contain it. Treat as greenfield in the feasibility doc. |

The framework repo the user is sitting in is **Claude Copilot** (`/Volumes/Dev/Sites/COPILOT/claude-copilot`),
a Layer-1 Foundational product — NOT one of the four named targets, but the hub all three real ones orbit.

---

## The Claude / Codex / Cloud relationship (per registry)

- **Claude Copilot** (Layer-1, public, active): the instruction layer for Claude Code — specialized agents,
  hook-enforced protocol, persistent memory, orchestration. Owns the `cc` and `tc` CLIs (`tools/cc`, `tools/tc`).
- **Codex Copilot** (Layer-1, public, active): a *Codex-native* operating layer that **mirrors** Claude Copilot's
  intent using Codex primitives (`AGENTS.md`, Codex skills, `$protocol`). It does NOT reimplement Claude runtime
  hooks; it **reuses the shared `cc`/`tc` CLIs from claude-copilot's `tools/`**. It tracks Claude Copilot as a
  parity baseline (`parity/claude-baseline.json`). So: Claude Copilot and Codex Copilot are **twin host-specific
  framework layers** (Claude Code vs Codex) over a shared CLI/memory/task substrate.
- **Cloud Copilot**: does not exist. No registry entry. Any "cloud" framing (hosted/remote sessions) is unbuilt.
  Note cli-copilot's dossier explicitly states it "does not start a remote/cloud session."

---

## The four projects — profiles

### 1. CLI Copilot — `/Volumes/Dev/Sites/COPILOT/cli-copilot`
- **Repo:** `github.com/Everyone-Needs-A-Copilot/cli-copilot` — **private**, branch `main`, HEAD `22544ee`.
- **What it IS:** the `copilot` binary — a Python 3.11 Typer+Rich CLI fronting ~24 services (a *client* binary,
  not a server; no MCP/HTTP/webhook of its own). Version 1.1.0.
- **Entry points:** `copilot_cli/main.py` (Typer `app`), `copilot_cli/services/*` (one dir per service),
  `copilot_cli/config/settings.py` (Pydantic Settings), `pyproject.toml` console scripts `copilot`/`cli_copilot`
  → `copilot_cli.main:app`.
- **Config:** single `.env` via Pydantic Settings; resolution `COPILOT_ENV_FILE` → nearest `.env` up-tree → CWD `.env`.
  Ecosystem `.env` at `/Volumes/Dev/Sites/COPILOT/cli-copilot/.env` (per global CLAUDE.md).
- **Extension / integration REGISTRY (key for layering vision):**
  Integrations are **registered as code, not data.** Each service is a Python subpackage under
  `copilot_cli/services/<name>/` exposing a Typer `app`, imported and wired in `copilot_cli/main.py` via
  `app.add_typer(<svc>_app, name="<name>", help=...)`. Real registered set (main.py lines 50–94):
  git, docker, shell, fireflies, discord, fs, services, db, crm, brevo, n8n, docs, bi, monitoring, coolify,
  **infisical**, insights, project, conv, skill, reddit, uspto. Config for each lives in
  `copilot_cli/config/settings.py` + `.env.example`.
  **There is NO plugin/connector manifest and NO notion of "company-wide vs personal" integrations today.**
  Adding an integration = write a subpackage + edit `main.py` + add Pydantic fields. It is a single flat,
  hard-coded, per-user registry keyed off one `.env`. The user's "layer company vs personal integrations"
  goal has **no existing seam** here — it would be net-new (e.g. a manifest/registry + scoped `.env` layering).
- **Knowledge/integrations connection:** consumes Claude Copilot's MCP servers only inside its own repo via
  `.mcp.json.example`; `coolify` service can read creds from an existing `.mcp.json`
  (`services/coolify/core/config.py find_mcp_credentials`). Global `--json` flag for machine-readable output.

### 2. Knowledge Copilot — `/Volumes/Dev/Sites/COPILOT/knowledge-copilot`
- **Repo:** `github.com/Everyone-Needs-A-Copilot/knowledge-copilot` — **public**, `main`, HEAD `061f8710`.
  `shared-docs` is a **symlink** to this dir. Renamed from `shared-docs` 2026-06-29.
- **What it IS:** the shared company knowledge base (methodologies, brand/voice, product dossiers, skills,
  agent extensions). This is the **Layer-2/3 knowledge** repo the whole ecosystem reads from.
- **Structure (consumption contract, `docs/00-knowledge-copilot/02-consumption-contract.md`):**
  stable canonical sub-paths resolved against `$CC_KNOWLEDGE_REPO`:
  `01-company/{01-brand,02-voice,03-services,04-gtm,05-patterns,06-methodologies,07-reference}`,
  `02-products/{01-ecosystem,02-foundational,03-work,04-applications}`, `03-ai-enabling/{01-skills,02-profiles}`,
  `04-shared-systems/design-system/`. Also carries `ECOSYSTEM.md` (the registry), `knowledge-manifest.json`
  (v1.4.0, agent extension registry: sd override, uxd extension, etc.), and its own `plugins/codex-copilot`
  install (`.codex-copilot.json`).
- **How `cc` points at it (verified in code):** config keys `paths.shared_docs` / `paths.knowledge_repo`
  default `None` (`tools/cc/src/cc/core/config.py:33-49`); `knowledge_repo` is the ONLY list-valued key
  (`LIST_VALUED_KEYS`, `config.py:59`) normalized by `resolve_knowledge_repos()` (`config.py:176-201`).
  Merge precedence CC_* env > project > machine > defaults in `get_resolved_config()` (`config.py:204-245`),
  with `@machine` sentinel resolution at `config.py:240-242`. `cc env` (`commands/env.py:run_env` 32-83) emits
  dotted keys as `CC_UPPER_UNDERSCORE`, plus short aliases `CC_KNOWLEDGE_REPO`←first list element (`env.py:68-81`)
  and `CC_SHARED_DOCS`. `refs.*` are arbitrary user keys (not in schema), stored via `config_set()`
  (`commands/config.py:106-130`) and surfaced on turn 1 by the UserPromptSubmit hook
  (`.claude/hooks/user-prompt-submit.sh:213-251`). Contract rule: agents READ from it, never copy content in.

### 3. Codex Copilot — `/Volumes/Dev/Sites/COPILOT/codex-copilot`
- **Repo:** `github.com/Everyone-Needs-A-Copilot/codex-copilot` — **public** (MIT), `main`, HEAD `e1620f7`. v0.5.0.
- **What it IS:** Codex-native framework layer mirroring Claude Copilot (see relationship section). Ships no
  service/API/MCP. Entry points: `AGENTS.md`, `plugins/codex-copilot/{skills,agent-catalog.json}`, `scripts/`
  (`setup-project.sh`, `copilot-gate.sh`, `activate-pack.py`), `packs/` (dormant specialist packs), `parity/`.
- **Config/extension:** projects wired via `scripts/setup-project.sh` (writes `AGENTS.md`, symlinks skills).
  **Capability packs** (`packs/business-creative`, `packs/writing-legal`) are its extension model — opt-in via
  `activate-pack.py`, keeping domain specialists local not global. Reuses shared `cc`/`tc` (pinned in `VERSION.json`).

### 4. Cloud Copilot — DOES NOT EXIST
- No repo, no dir, no dossier, no registry line. Report as **greenfield / vision-only**. Do not invent behavior.

---

## Current inter-project connective tissue

1. **`cc env` hydration** — the primary glue. `eval "$(cc env)"` exports `CC_SHARED_DOCS`, `CC_KNOWLEDGE_REPO`,
   `CC_PATHS_KNOWLEDGE_REPO`, and registered `refs.*`. Every agent preamble runs it. (cc owned by claude-copilot.)
2. **Shared `cc` + `tc` CLIs** — claude-copilot's `tools/cc` and `tools/tc`, reused verbatim by codex-copilot
   (version-pinned). This is the shared substrate under both host frameworks.
3. **`COPILOT_ENV_FILE`** — points the `copilot` binary at a project `.env`; the ecosystem `.env` lives in cli-copilot.
4. **knowledge-copilot** — the read-target for brand/voice/methodology/product knowledge, via `$CC_KNOWLEDGE_REPO`.
5. **cli-copilot's `copilot` binary** — invoked cross-project for Discord handoffs, skill runtime, etc.
   (pip-installed from git). No server; pure CLI integration.
6. **MCP** — a few live MCP servers exist as *products* (Convoco `mcp.convocoai.com`), and claude-copilot ships
   memory/skills MCP servers, but the ecosystem's preferred direction (per user memory `cli-over-mcp-preference`)
   is CLIs over MCP — converting MCP connectors into `copilot` subcommands.

---

## The layering seam that ALREADY exists (feeds the vision directly)

There is a **working prototype of the 3-layer knowledge/extension model** — not for CLI integrations, but for
knowledge + agent extensions — via `paths.knowledge_repo`:

- **`paths.knowledge_repo` is now list-valued** (cc >= 1.6.0 / framework 5.13.0). `cc config add
  paths.knowledge_repo <path>` appends idempotently, order-preserving. So a **shared company layer**
  (knowledge-copilot) and a **personal layer** can be wired side by side at machine scope.
  (Source: `claude-copilot-private/EXTENSIONS.md`, written from actual code
  `tools/cc/src/cc/core/config.py::get_resolved_config` and `tools/cc/src/cc/commands/env.py::run_env`.)
- **Resolution order (verified in code):**
  1. Env `CC_PATHS_KNOWLEDGE_REPO` / `CC_KNOWLEDGE_REPO` (highest, session-only)
  2. Project config `<git root>/.claude/cc/config.json`
  3. Machine config `~/.claude/cc/config.json` (untracked)
  4. Built-in default `null`
  Within the winning layer the value can be an ordered list of repos.
- **Public repo stays clean:** `claude-copilot/.claude/cc/config.json` uses `"@machine"` sentinels for
  `shared_docs` and `knowledge_repo`, deferring entirely to untracked machine config. So a private layer needs
  zero change to the public tracked tree.
- **IMPORTANT GAP:** the shipped `cc` does NOT auto-merge override/extension `.md` files across agents. There is
  **no** `knowledge.py`, no `.override.md`/`.extension.md` parser, no `ExtensionType` code in `tools/cc/src`.
  The multi-repo per-agent fallback merge in `docs/40-extensions/00-extension-spec.md` is **design intent, not
  shipped behavior.** Today `knowledge-manifest.json` + `.claude/extensions/*.md` are a **file convention** agents
  are told (via prompts/CLAUDE.md) to read manually after hydrating `CC_KNOWLEDGE_REPO`. So Layer resolution for
  knowledge = real (list-valued pointer); automatic extension merging = aspirational.

### The private companion repo (already created) — `/Volumes/Dev/Sites/COPILOT/claude-copilot-private`
- **Repo:** `github.com/pablitoalejo/claude-copilot-private` — **private, personal account** (NOT the org), `main`.
- **What it IS:** private companion to public claude-copilot. Holds `memory/entries/`, `settings.local.json`,
  `mcp.json`, `docs-private/`, and `knowledge/` (a personal extension repo). `bootstrap.sh` symlinks these into a
  sibling claude-copilot checkout AND runs `cc config add paths.knowledge_repo <knowledge dir>` to wire the layer.
- **`knowledge/` layout mirrors knowledge-copilot's convention:** `knowledge-manifest.json` (v1.0,
  name `pablo-personal-knowledge`, framework minVersion 5.12.0), `.claude/extensions/` (template override),
  `skills/`, `docs/glossary.md`. This is the **personal (Layer-3?) knowledge layer** already scaffolded.

---

## Git topology (public vs private, orgs)

| Repo | Local | Remote / org | Visibility |
|---|---|---|---|
| claude-copilot | `/…/claude-copilot` | `Everyone-Needs-A-Copilot/claude-copilot` | **public** |
| codex-copilot | `/…/codex-copilot` | `Everyone-Needs-A-Copilot/codex-copilot` | **public** |
| knowledge-copilot | `/…/knowledge-copilot` (`shared-docs`→symlink) | `Everyone-Needs-A-Copilot/knowledge-copilot` | **public** |
| cli-copilot | `/…/cli-copilot` | `Everyone-Needs-A-Copilot/cli-copilot` | **private** |
| **claude-copilot-private** | `/…/claude-copilot-private` | **`pablitoalejo/claude-copilot-private`** (personal acct) | **private** |

- **Two GitHub owners:** `Everyone-Needs-A-Copilot` org (all products) and `pablitoalejo` personal account
  (the private companion, plus `n8n-copilot` and `transformation` per registry `owner:` notes).
- The "3 will be open source" plan maps cleanly: claude-copilot, codex-copilot, knowledge-copilot are already
  public in the org; cli-copilot is the one currently private (fronts real infra creds). Cloud Copilot is unbuilt.

---

## Feasibility signal for the 3-layer model

- **Knowledge/agent-extension layering:** a real seam exists (list-valued `paths.knowledge_repo` + `cc config add`,
  `@machine` sentinels keep public repo clean, private companion repo already scaffolds a personal layer).
  Auto-merge of agent extension `.md` files is NOT yet implemented — that's the build gap.
- **CLI integration layering (company vs personal):** NO existing seam. cli-copilot registers integrations as
  hard-coded Python subpackages wired in `main.py` off one flat `.env`. "Company-wide vs personal-only" integration
  scoping would be net-new architecture (a connector manifest/registry + layered `.env`/config scopes).
- **Cloud Copilot:** greenfield; nothing to extend.
