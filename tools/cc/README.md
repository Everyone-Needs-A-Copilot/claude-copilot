# cc — Claude Copilot CLI

Unified CLI that replaces the `copilot-memory` and `skills-copilot` MCP servers with a single installable tool and an optional MCP shim.

## What Is `cc`?

`cc` is a Python/Typer CLI that consolidates persistent memory and skill management into one tool. It writes memory entries as plain markdown files (one file per entry), uses SQLite FTS for fast search, and reads skills from local `SKILL.md` files. A two-layer config system separates machine-wide settings from per-project overrides.

Benefits over the MCP servers:
- No Node.js runtime required for memory or skills
- Memory entries are git-trackable markdown files
- Works in headless/agent contexts via `eval "$(cc env)"`
- Optional `cc mcp serve` shim keeps MCP compatibility

---

## Install

```bash
bash tools/cc/install.sh
```

This creates a virtual environment at `tools/cc/.venv`, installs `cc` in editable mode, and places a shim at `~/.local/bin/cc`.

Make sure `~/.local/bin` is in your `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Add that line to `~/.zshrc` or `~/.bashrc` to persist it.

**Uninstall:**

```bash
bash tools/cc/uninstall.sh
```

---

## Command Reference

### Memory

Store and retrieve persistent memory entries as UUID-named markdown files.

```bash
# Store a new entry
cc memory store --type decision --tags auth,security "Use JWT with 1h expiry"
cc memory store --type context "Working on the checkout refactor"
cc memory store --type lesson --scope global "Always add --dry-run to migration scripts"
cc memory store --type reference "See RFC-001 for API conventions"

# Retrieve by UUID (full or prefix)
cc memory get fee71a3e
cc memory get fee71a3e-ce23-4ba9-a3a2-60ee3b7973e1

# List entries with optional filters
cc memory list
cc memory list --type decision
cc memory list --tags auth
cc memory list --scope global

# Search (FTS index when available, file-scan fallback)
cc memory search "JWT authentication"

# Delete
cc memory delete fee71a3e          # prompts for confirmation
cc memory delete fee71a3e --yes    # skip prompt

# Manage the FTS index
cc memory index --rebuild          # rebuild from files
cc memory index --status           # check sync state

# Migrate from legacy copilot-memory SQLite databases
cc memory migrate --from-global             # interactive — choose which DB
cc memory migrate --from-global --all       # migrate all without prompting
cc memory migrate --from-global --dry-run   # preview without writing
cc memory migrate --status                  # show source DB counts vs files
```

Entry types: `decision` | `context` | `lesson` | `reference` | `person`

Scope defaults to `project` when inside a git repo, otherwise `global`.

---

### Skills

Discover and inspect `SKILL.md` files from project and machine skill directories.

```bash
# List all available skills
cc skill list
cc skill list --scope project     # only .claude/skills/ in current repo
cc skill list --scope machine     # only ~/.claude/skills/

# Search skills by keyword
cc skill search "security"
cc skill search "testing patterns"

# Print full SKILL.md content (pipeable)
cc skill get stride-dread
cc skill get python-idioms

# Print absolute path to SKILL.md (pipeable to @include)
cc skill path stride-dread
# → /path/to/.claude/skills/security/stride-dread/SKILL.md

# Search for skills relevant to a topic (keyword match on name, description, tags)
cc skill search "security"
cc skill search "testing python"
```

---

### Config

Two-layer configuration: machine config (`~/.claude/cc/config.json`) is the base; project config (`.claude/cc/config.json` in git root) overrides specific keys. Use the `@machine` sentinel in project config to inherit the machine value explicitly.

Config keys live under two namespaces:
- **`paths.*`** — well-known directory paths (`memory`, `shared_docs`, `knowledge_repo`)
- **`refs.*`** — arbitrary named references surfaced to the main session at turn 1 (via the `user-prompt-submit` hook). Use this to register project boards, design system URLs, or any stable reference you want available every session without manual retrieval.

```bash
# Read a value (effective = project overrides machine)
cc config get paths.memory
cc config get paths.shared_docs

# Write a value
cc config set paths.knowledge_repo /path/to/repo        # machine (default)
cc config set --project paths.shared_docs /team/docs    # project layer

# Register named references (surfaced to main session at turn 1)
cc config set refs.project_board https://linear.app/...
cc config set refs.design_system /path/to/tokens

# List all keys with source annotation
cc config list
cc config list --scope machine
cc config list --scope project

# Show which layer provides a key
cc config where paths.shared_docs

# Remove a key
cc config unset paths.shared_docs
cc config unset --project paths.shared_docs

# Create default config templates
cc config init                    # machine config template
cc config init --project          # project config template

# Validate config files
cc config validate

# Open in $EDITOR
cc config edit
cc config edit --project

# Export effective config
cc config export
cc config export --json
cc config export --machine
cc config export --mask-secrets

# Health check
cc config doctor
```

**`@machine` sentinel example** — in `.claude/cc/config.json`:

```json
{
  "$schema": "cc-config-v1",
  "version": 1,
  "paths": {
    "shared_docs": "@machine",
    "knowledge_repo": "@machine"
  }
}
```

Keys set to `"@machine"` fall through to the machine config value, letting project config declare intent without hardcoding a path.

---

### Docs (Live Docs)

Fetch version-exact documentation for installed packages so agents code against the real API, not stale training-data memory.

**Source model — two ordered backends:**

| Backend | When it runs | Network required |
|---------|--------------|-----------------|
| `local` | Always (default first) | No — reads files the package ships on disk |
| `fetch` | Fallback (or explicit `--source fetch`) | Yes — requires `cc[fetch]` extra |

`auto` mode (the default) tries `local` first. If local docs are absent, it falls back to `fetch` — but only when `httpx` is installed. A core `cc` install never makes network calls.

**Install the fetch extra (optional):**

```bash
pip install 'cc[fetch]'    # enables network fallback
```

**Commands:**

```bash
# Detect installed/declared version of a package
cc docs resolve requests
cc docs resolve react --lang js
cc docs resolve requests --json

# Fetch documentation (main verb)
cc docs get requests
cc docs get requests --topic authentication
cc docs get react --lang js --topic hooks
cc docs get requests --source local       # force local only (offline-safe)
cc docs get requests --source fetch       # force network fetch
cc docs get requests --refresh            # bypass cache, fetch fresh
cc docs get requests --json               # machine-readable output

# Search documentation for a topic (returns a snippet)
cc docs search requests "session cookies"
cc docs search react "useState" --lang js --json

# List registered backends and whether each is available
cc docs sources
cc docs sources --json

# Inspect or clear the docs cache
cc docs cache --status
cc docs cache --clear
```

**How version detection works:**

`cc docs` resolves the installed version before fetching so docs match your exact dependency.

- Python priority: `importlib.metadata` (installed env) → `uv.lock` → `poetry.lock` → `pyproject.toml` constraint → `requirements*.txt`
- npm priority: `package-lock.json` → `yarn.lock` → `pnpm-lock.yaml` → `node_modules/<pkg>/package.json` → `package.json` declared range

When only a range is detected, the resolved version is marked `exact: false`.

**Caching:**

Results are cached locally at `~/.claude/cache/docs/` in a gitignored SQLite file. Default TTL is 168 hours (one week). Use `--refresh` to bypass cache for a single call.

**Limitations:**

- `local` docs are only as good as what a package ships on disk. Not all packages include full docs in their distribution.
- `fetch` requires the `cc[fetch]` extra and an active network connection. The fetch backend tries `llms.txt` → GitHub raw at the detected version tag → the package's docs site.
- **Context7 is not included at this release.** The `SourceBackend` seam accepts a Context7 backend as a future drop-in via `cc.core.docs_resolver.register_backend`. The config key `docs.context7_endpoint` is reserved but unused.

**Config keys:**

| Key | Default | Purpose |
|-----|---------|---------|
| `docs.source_order` | `local,fetch` | Comma-separated backend order |
| `docs.cache_ttl_hours` | `168` | Cache TTL in hours |
| `docs.cache_dir` | `~/.claude/cache/docs` | Override cache directory |
| `docs.context7_endpoint` | *(reserved)* | Future Context7 backend endpoint |

```bash
# Override source order (local only — fully offline)
cc config set docs.source_order local

# Shorten TTL to 24 hours
cc config set docs.cache_ttl_hours 24
```

**Agent usage pattern:**

```bash
# Get docs before writing code against an API
cc docs get pydantic --topic validators --json
cc docs search fastapi "dependency injection" --json
```

---

### `cc env` — Agent Shell Hydration

Exports effective config as `CC_*` environment variables, suitable for `eval` in agent preambles:

```bash
eval "$(cc env)"           # hydrate CC_* exports into current shell
cc env --json              # JSON dict for programmatic use
cc env --include-secrets   # also emit values from secrets.env
```

Agents that need config values should add `eval "$(cc env)"` as their first shell step. This avoids hardcoded paths and works across machines.

---

### MCP Shim

`cc mcp serve` starts an MCP-compatible server over stdio that delegates to the same underlying CLI commands. Use this for projects that still rely on MCP tool calls.

```bash
cc mcp serve          # start MCP server on stdio
cc mcp config         # print .mcp.json snippet to register cc
```

To register `cc` as an MCP server, run `cc mcp config` and paste the output into your project's `.mcp.json`:

```bash
cc mcp config >> .mcp.json   # or paste manually
```

The MCP shim requires the `cc[mcp]` extra:

```bash
pip install 'cc[mcp]'
```

---

### Diagnostics

```bash
cc doctor        # run all health checks (config paths, gitignore, permissions)
cc --version     # print installed version
```

---

## Code-Execution Path (Programmatic API)

For agents performing 3+ related memory operations, import `cc.api` in a single `python3` Bash block instead of multiple CLI calls. Each CLI call echoes a full JSON payload back into context; a python3 block returns only what you `print()`.

**Import surface:** `from cc.api import memory_store, memory_get, memory_list, memory_delete, memory_search, skill_get, skill_search`

**Worked example — store 5 decisions and search in one Bash call:**

```bash
python3 - << 'PY'
from cc.api import memory_store, memory_search

entries = [
    ("decision", "Use WAL mode for all SQLite connections"),
    ("lesson",   "Always add --dry-run to migration scripts"),
    ("decision", "JWT expiry set to 1h; refresh token 30 days"),
    ("context",  "Checkout v2 uses server-side cart"),
    ("lesson",   "Monkeypatch _git_root in tests for isolation"),
]
ids = []
for t, c in entries:
    ids.append(memory_store(entry_type=t, content=c)["id"][:8])
results = memory_search("SQLite WAL")
print(f"stored {len(ids)}: {ids}; search returned {len(results)} hits")
PY
```

Returns to context: one line (~25 tokens) instead of 5 CLI calls (~250-600 tokens each).

**Rules:**
- PREFER code-execution for >=3 related cc ops (batch stores, search-then-act, list-then-filter).
- KEEP CLI for single one-shot ops: `cc memory search "topic"`, `cc memory store --type decision "..."`.
- CRITICAL: cc and tc are in separate environments. Keep each block to ONE tool (cc-only OR tc-only).
- Typed exceptions: `EntryNotFound`, `EntryValidationError`, `SkillNotFound` — wrap in try/except and print a compact error line.

**Typed exceptions:**
```python
from cc.api import memory_get, EntryNotFound
try:
    entry = memory_get("abc123")
except EntryNotFound as e:
    print(f"ERROR: {e}")
```

---

## Two-Layer Config

| Layer | File | Purpose |
|-------|------|---------|
| Machine | `~/.claude/cc/config.json` | Defaults for all projects on this machine |
| Project | `.claude/cc/config.json` (git root) | Per-project overrides |

Resolution order: project → machine → built-in defaults.

A project key set to `"@machine"` explicitly inherits the machine value (useful for documentation and clarity). A missing project key also falls through to machine.

---

## Development

```bash
# Set up dev environment (venv + dev deps, no shim)
cd tools/cc && make dev

# Run tests
cd tools/cc && make test

# Install shim system-wide
cd tools/cc && make install

# Remove shim
cd tools/cc && make uninstall
```

---

## Layout

```
tools/cc/
  pyproject.toml          # package metadata and entry point
  src/cc/
    __init__.py           # version string
    main.py               # Typer app + subgroup registration
    commands/             # one module per subcommand group
      memory.py           # store, get, list, delete, search, index, migrate
      skill.py            # list, search, get, path
      config.py           # get, set, unset, list, where, validate, edit, init, export, doctor
      env.py              # cc env (shell hydration)
      docs.py             # resolve, get, search, sources, cache (Live Docs)
      mcp.py              # serve, config
      doctor.py           # cc doctor (standalone health check)
    api.py                # flat importable facade for code-execution use (memory_store/get/list/search, skill_get/search)
    core/                 # entry_store, entry_format, memory_index, skill_store, config, config_paths
      docs_resolver.py    # version detection + SourceBackend seam + layered lookup
      docs_cache.py       # SQLite cache (TTL-based, gitignored)
      docs_paths.py       # cache path helpers and config key resolution
      docs_backends/      # local.py (offline), fetch.py (httpx, optional)
    utils/                # output helpers
  tests/
    conftest.py
    test_main.py
```
