# Installing Claude Copilot as a Native Plugin vs Cloning

Claude Copilot supports two installation modes. Both are fully supported and share the same asset tree — no files are duplicated.

---

## The Two-Environment Reality

### What the plugin bundles (prompt-layer assets — pure markdown/JSON/shell)

- **Agents** — ta, me, qa, sd, design, do, doc, kc (base methodology agents)
- **Skills** — all skill categories (code, design, devops, documentation, security, testing, copywriting, architecture)
- **Commands** — all slash commands (/protocol, /continue, /pause, /map, /memory, /orchestrate, /setup-project, etc.)
- **Hooks** — pretool-check.sh, subagent-stop.sh, user-prompt-submit.sh (enforcement hooks)

These assets have no Python runtime dependency; they work the moment the plugin is installed.

### What the plugin does NOT bundle (requires separate install)

| Tool | What it provides | Install |
|------|-----------------|---------|
| `cc` CLI | Memory storage/search, skill CLI, extension resolution, agent override layer | `bash tools/cc/install.sh` or `pipx install claude-cli` |
| `tc` CLI | Task copilot — PRDs, tasks, work products, handoffs | `pip install -e tools/tc` or homebrew |

The agents call `cc` and `tc` via Bash. If those binaries are absent, memory and task-tracking features degrade gracefully — the agent markdown still loads and the methodology still works; only the persistence features are unavailable.

Run `cc doctor` after installing the CLIs to verify both are reachable and see exactly which features would be degraded if either were missing.

---

## Installation Paths

### Path A — Plugin install (recommended for teams)

Use this when you want Claude Code to auto-discover the framework and you manage it through the plugin system.

**Step 1 — Add the marketplace (one-time per team)**

Add the following to your Claude Code user or project settings:

```json
{
  "extraKnownMarketplaces": [
    "https://raw.githubusercontent.com/<org>/claude-copilot/main/.claude-plugin/marketplace.json"
  ]
}
```

**Step 2 — Install the plugin**

```
/plugin install claude-copilot
```

This installs the prompt-layer assets (agents, skills, commands, hooks).

**Step 3 — Install the CLIs (required for full functionality)**

```bash
# cc CLI — memory, skills, extension resolution
bash tools/cc/install.sh

# tc CLI — task copilot
pip install -e tools/tc
```

**Step 4 — Verify**

```bash
cc doctor
```

`cc doctor` reports which features are active and names any degraded capabilities if `cc` or `tc` are absent from PATH.

---

### Path B — Direct clone (existing users, local development)

Use this when you want full control, plan to modify the framework, or prefer a traditional git workflow.

```bash
git clone <repo> ~/.claude/copilot
cd ~/.claude/copilot
/setup
```

The `.claude/settings.json` wires hooks with absolute paths. The `cc` and `tc` CLIs are installed the same way as Path A (Step 3 above).

**Clone users are unaffected by the plugin manifest.** The `.claude-plugin/` directory is purely additive — removing or ignoring it leaves the clone working identically.

---

## The Floor/Ceiling Model (Override Layer Preservation)

This is the load-bearing constraint of the plugin design:

```
┌─────────────────────────────────────────────────────┐
│  CEILING — cc + knowledge-repo override layer        │
│  (project $KNOWLEDGE_REPO_PATH → global              │
│   ~/.claude/knowledge → base agent)                  │
│  Runtime prompt-assembly via cc extension_get.       │
│  Company-specific overrides, extensions, skill sets. │
├─────────────────────────────────────────────────────┤
│  FLOOR — plugin-provided base agents                 │
│  (generic, standalone-functional, open-source)       │
│  Same files in .claude/agents/ whether installed     │
│  via plugin or via clone.                            │
└─────────────────────────────────────────────────────┘
```

**Key facts:**

- Native Claude Code plugins ADD agents (the floor). They have no mechanism to REPLACE a specific agent's methodology with a per-team override — that is intentional.
- The knowledge-repo override layer (`.override.md`, `.extension.md`, `.skills.json` per agent) is a RUNTIME step performed by the `cc` CLI at agent-invocation time. It reads the knowledge repo, merges the override on top of the base agent's markdown, and supplies the combined prompt.
- Installing via plugin vs clone makes NO difference to overrides. In both cases: `cc extension_get <agent>` returns `base + project-override + global-override` at invocation. The plugin merely changes how the base agent is discovered; `cc` still assembles the final prompt.
- This means teams can install the base framework as a plugin for easy auto-discovery and still apply their full methodology layer on top via the knowledge repo. The two layers compose cleanly.

For the override layer to work, the `cc` CLI must be installed (Step 3 above) and `$KNOWLEDGE_REPO_PATH` must be set in the project or user environment.

See `docs/40-extensions/00-extension-spec.md` for the full override resolution spec.

---

## Hook Portability

The same hook scripts live in `.claude/hooks/`. The two install modes reference them differently:

| Mode | Hook path style |
|------|----------------|
| Plugin install | `${CLAUDE_PLUGIN_ROOT}/../.claude/hooks/<script>.sh` (resolved at plugin load time) |
| Direct clone | Absolute path in `.claude/settings.json` (e.g. `/home/user/.claude/copilot/.claude/hooks/<script>.sh`) |

Both paths reach the same scripts. No script changes are needed. The `update-project` command regenerates the absolute paths in `settings.json` for clone users when the repo location changes.

---

## Drift Guard

The fitness check at `.claude-plugin/check-manifest.py` verifies that `plugin.json` and `marketplace.json` are always consistent with the `.claude/` asset tree:

```bash
python3 .claude-plugin/check-manifest.py
```

Run this in CI or before merging changes to `.claude/` to ensure the two discovery mechanisms (settings.json for clone users, plugin.json for plugin users) never diverge from the actual asset tree.

---

## Feature Matrix by Install Mode

| Feature | Plugin install | Direct clone |
|---------|---------------|-------------|
| Base agents (ta/me/qa/etc.) | Loaded via plugin | Loaded via .claude/agents/ |
| Skills (@include) | Available | Available |
| Slash commands | Available | Available |
| Hooks (enforcement) | Via ${CLAUDE_PLUGIN_ROOT} | Via settings.json absolute paths |
| Memory (cc memory) | Requires cc CLI | Requires cc CLI |
| Tasks (tc task) | Requires tc CLI | Requires tc CLI |
| Agent overrides (knowledge-repo) | Requires cc CLI + KNOWLEDGE_REPO_PATH | Requires cc CLI + KNOWLEDGE_REPO_PATH |
| Modify agents locally | Not directly (plugin manages assets) | Edit .claude/agents/ directly |
| Auto-update via /plugin | Yes | Manual git pull + /update-project |

---

## Troubleshooting

**"cc: command not found"** — Install cc: `bash tools/cc/install.sh`. Full memory, skill, and override features require this.

**"tc: command not found"** — Install tc: `pip install -e tools/tc`. Task copilot features require this.

**Hooks not firing in plugin mode** — Verify `${CLAUDE_PLUGIN_ROOT}` is set by your Claude Code version. If not, fall back to the direct-clone path and use `settings.json` absolute paths.

**Override not applied** — Verify `cc` is installed, `$KNOWLEDGE_REPO_PATH` points to your knowledge repo, and the override file exists: `$KNOWLEDGE_REPO_PATH/agents/<agent-name>.override.md`.

**Version mismatch between plugin.json and VERSION.json** — Run `/update-project` to resync, or manually update the `version` field in `.claude-plugin/plugin.json` to match `VERSION.json`'s `framework` field.
