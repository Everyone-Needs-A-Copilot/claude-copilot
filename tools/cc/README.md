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

```bash
# Read a value (effective = project overrides machine)
cc config get paths.memory
cc config get paths.shared_docs

# Write a value
cc config set paths.knowledge_repo /path/to/repo        # machine (default)
cc config set --project paths.shared_docs /team/docs    # project layer

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
      skill.py            # list, search, get, path, evaluate
      config.py           # get, set, unset, list, where, validate, edit, init, export, doctor
      env.py              # cc env (shell hydration)
      mcp.py              # serve, config
      doctor.py           # cc doctor (standalone health check)
    core/                 # entry_store, entry_format, memory_index, skill_store, config, config_paths
    utils/                # output helpers
  tests/
    conftest.py
    test_main.py
```
