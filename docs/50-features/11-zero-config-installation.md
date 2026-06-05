# Installation Guide

**Diátaxis mode:** How-to

**Status:** Current — installation uses `bash tools/cc/install.sh` + `pip install -e tools/tc`. No npm or Node.js required.

---

## Prerequisites

- Python 3.10+
- Git
- Claude Code CLI

No Node.js, npm, or MCP server build step is required. The framework is entirely Python + markdown.

---

## Step 1 — Clone the Repository (Machine Setup, Once)

```bash
mkdir -p ~/.claude
cd ~/.claude
git clone https://github.com/Everyone-Needs-A-Copilot/claude-copilot.git copilot
```

## Step 2 — Open Claude Code in the Copilot Directory

```bash
cd ~/.claude/copilot
claude
```

## Step 3 — Run Machine Setup

Inside Claude Code, run:

```
/setup
```

The setup wizard:
- Checks Python 3 is available
- Runs `bash tools/cc/install.sh` to install the `cc` CLI to `~/.local/bin/cc`
- Runs `pip install -e tools/tc` to install the `tc` CLI
- Installs global commands (`/setup-project`, `/update-project`, `/knowledge-copilot`)

## Step 4 — Set Up Each Project

Open Claude Code in any project directory and run:

```
/setup-project
```

This copies `.claude/` (agents, commands, skills), `CLAUDE.md`, and hooks into the project.

## Step 5 — Update Projects (After Pulling Framework Updates)

```bash
cd ~/.claude/copilot
git pull origin main
```

Then in each project:

```
/update-project
```

---

## What Gets Installed

### Machine Level (`~/.claude/copilot/`)

| Component | Purpose |
|-----------|---------|
| `tools/tc/` | `tc` CLI — PRD, task, and work product management |
| `tools/cc/` | `cc` CLI — unified memory + skills tool |
| `.claude/agents/` | 16 specialized agent definitions |
| `.claude/commands/` | Source command files |
| `templates/` | Project setup templates |

### User Binaries (`~/.local/bin/`)

| Binary | Installed By |
|--------|-------------|
| `cc` | `bash tools/cc/install.sh` |
| `tc` | `pip install -e tools/tc` |

### Per-Project (`<project>/.claude/`)

| Path | Purpose |
|------|---------|
| `agents/` | 16 agent definitions (synced from framework) |
| `commands/` | Protocol commands |
| `skills/` | Project-specific skills |
| `hooks/` | Pre-tool enforcement hooks |
| `memory/entries/` | Memory entries (committed, travel with repo) |

---

## Verify Installation

```bash
cc --version
tc --version
cc skill list | head -5
cc memory search "test"
```

---

## Configure Optional Paths

```bash
# Shared documentation (optional)
cc config set paths.shared_docs /path/to/your/shared/docs

# Knowledge repository (optional, for /knowledge-copilot)
cc config set paths.knowledge_repo ~/.claude/knowledge

# Stable project references
cc config set refs.staging_url https://staging.example.com
```

---

## (Optional) Set Up Shared Knowledge

```
/knowledge-copilot
```

Creates `~/.claude/knowledge/` with a knowledge manifest and agent extensions for company/team-specific methodologies.

---

## Troubleshooting

### `cc: command not found`

`install.sh` automatically appends `~/.local/bin` to `~/.zshrc`, `~/.zprofile`, `~/.bashrc`, and `~/.bash_profile` idempotently — no manual PATH edit is needed. If `cc` is still not found after running the installer, reload your shell:

```bash
source ~/.zshrc   # or ~/.bash_profile / ~/.zprofile on macOS
```

### `tc: command not found`

Reinstall with pip in editable mode:

```bash
pip install -e ~/.claude/copilot/tools/tc
```

### Python version too old

The framework requires Python 3.10+. Check with `python3 --version`. On macOS, install via `brew install python@3.12`.

### Agent files missing after `/setup-project`

Run `/update-project` to re-sync. If an agent file has `owner: project` in its frontmatter, it will never be overwritten by sync — this is intentional.

---

## Updating

```bash
# Pull latest framework
cd ~/.claude/copilot
git pull origin main

# Reinstall CLIs if tools/ changed
bash tools/cc/install.sh
pip install -e tools/tc

# Sync all projects
cd /your/project
# In Claude Code:
/update-project
```

---

## Uninstalling

```bash
# Remove global installation
rm -rf ~/.claude/copilot

# Remove CLIs
rm ~/.local/bin/cc ~/.local/bin/tc

# Remove from a project
rm -rf .claude/ CLAUDE.md
```
