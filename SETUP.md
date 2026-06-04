# Claude Copilot Setup Guide

## Quick Start

### Step 1: Clone the Repository

```bash
mkdir -p ~/.claude
cd ~/.claude
git clone https://github.com/Everyone-Needs-A-Copilot/claude-copilot.git copilot
```

### Step 2: Open Claude Code in the Copilot Directory

```bash
cd ~/.claude/copilot
claude
```

### Step 3: Run Machine Setup

```
/setup
```

The setup wizard will:
- Check prerequisites (Python 3)
- Install the `tc` CLI (Task Copilot — PRD, task, and work product management)
- Install the `cc` CLI (memory and skills manager)
- Install global commands (`/setup-project`, `/update-project`, `/knowledge-copilot`)

### Step 4: Set Up Projects

Open Claude Code in any project and run:

```
/setup-project
```

### Step 5: Update Projects (When Needed)

After pulling Claude Copilot updates, refresh your projects:

```
/update-project
```

### Step 6: (Optional) Set Up Shared Knowledge

```
/knowledge-copilot
```

This creates a knowledge repository for company/product information shared across all projects.

---

## What Gets Installed

### Machine Level (`~/.claude/copilot/`)

| Component | Purpose |
|-----------|---------|
| `tools/tc/` | `tc` CLI — PRD, task, and work product management (required) |
| `tools/cc/` | `cc` CLI — unified memory + skills tool (required) |
| `.claude/agents/` | 16 specialized agent definitions |
| `.claude/commands/` | Source command files |
| `templates/` | Project setup templates |

### User Level (`~/.local/bin/`)

| Binary | Purpose |
|--------|---------|
| `cc` | Memory and skills CLI (installed by `tools/cc/install.sh`) |
| `tc` | Task Copilot CLI (installed by `pip install -e tools/tc`) |

### User Config (`~/.claude/`)

| Path | Purpose |
|------|---------|
| `commands/` | Global commands (`/setup-project`, `/update-project`, etc.) |
| `cc/config.json` | Machine-level cc config (gitignored) |
| `memory/entries/` | Cross-session memory entries (if using machine-level memory) |
| `skills/` | Global skills directory |
| `tasks/` | Task database storage |

### Project Level

| File/Directory | Purpose |
|----------------|---------|
| `.mcp.json` | MCP server configuration (third-party servers only — no Copilot MCP servers) |
| `CLAUDE.md` | Project-specific instructions |
| `.claude/commands/` | Project commands (`/protocol`, `/continue`, etc.) |
| `.claude/agents/` | Agent definitions |
| `.claude/skills/` | Project-specific skills |
| `.claude/memory/entries/` | Project memory entries (committed to git) |
| `.claude/cc/config.json` | Project-level cc config |

---

## Manual Setup (Alternative)

If you prefer to run steps manually:

### Prerequisites

| Requirement | Version | Check |
|-------------|---------|-------|
| Python | 3.9+ | `python3 --version` |

### Install CLIs

```bash
# tc CLI — Task Copilot (required)
pip install -e ~/.claude/copilot/tools/tc

# cc CLI — memory and skills (required)
bash ~/.claude/copilot/tools/cc/install.sh
cc config init --machine
mkdir -p ~/.claude/cache/models ~/.claude/skills
printf 'config.json\n' > ~/.claude/cc/.gitignore
```

### Install Global Commands

```bash
mkdir -p ~/.claude/commands
cp ~/.claude/copilot/.claude/commands/setup-project.md ~/.claude/commands/
cp ~/.claude/copilot/.claude/commands/update-project.md ~/.claude/commands/
cp ~/.claude/copilot/.claude/commands/update-copilot.md ~/.claude/commands/
cp ~/.claude/copilot/.claude/commands/knowledge-copilot.md ~/.claude/commands/
```

### Project Setup

1. Create directories:
   ```bash
   mkdir -p .claude/commands .claude/agents .claude/skills .claude/memory/entries
   touch .claude/memory/entries/.gitkeep
   printf 'memory.db\nmemory.db-*\n' > .claude/memory/.gitignore
   ```

2. Copy project commands and agents:
   ```bash
   cp ~/.claude/copilot/.claude/commands/protocol.md .claude/commands/
   cp ~/.claude/copilot/.claude/commands/continue.md .claude/commands/
   cp ~/.claude/copilot/.claude/agents/*.md .claude/agents/
   ```

3. Initialize project cc config:
   ```bash
   cc config init --project
   ```

4. Create `CLAUDE.md` from template at `~/.claude/copilot/templates/CLAUDE.template.md`

5. Restart Claude Code

---

## Migrating from 4.x (MCP Server Removal)

If you have an existing project that used the `copilot-memory` or `skills-copilot` MCP servers:

1. **Install the `cc` CLI** (replaces both MCP servers):
   ```bash
   bash ~/.claude/copilot/tools/cc/install.sh
   cc config init --machine
   ```

2. **Remove MCP server entries from `.mcp.json`**:
   - Delete the `copilot-memory` entry
   - Delete the `skills-copilot` entry
   - `.mcp.json` can now be `{"mcpServers":{}}` or removed entirely if no other servers

3. **Initialize project memory directory**:
   ```bash
   mkdir -p .claude/memory/entries
   touch .claude/memory/entries/.gitkeep
   printf 'memory.db\nmemory.db-*\n' > .claude/memory/.gitignore
   cc config init --project
   ```

4. **Run `/update-project`** to refresh agents and commands (handles step 3 automatically)

---

## Verification

After setup, verify the CLIs are installed:

```bash
tc version
cc --version
cc config doctor
```

Then verify in Claude Code:
- `/protocol` — Start working
- `/continue` — Resume previous work

---

## Troubleshooting

### `cc` Not Found

```bash
# Reinstall
bash ~/.claude/copilot/tools/cc/install.sh

# Ensure ~/.local/bin is in PATH
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### `tc` Not Found

```bash
pip3 install -e ~/.claude/copilot/tools/tc
tc version
```

### `cc config doctor` Reports Issues

Run `cc config doctor` to see specific issues. Common fixes:

```bash
# Missing directories
mkdir -p ~/.claude/cache/models ~/.claude/skills

# Missing machine config
cc config init --machine

# Missing project config
cc config init --project
```

### Commands Not Found

- For `/setup-project` or `/update-project`: Run machine setup first (`/setup`)
- For `/protocol` or `/continue`: Run `/setup-project` in your project

### Permission Errors

```bash
chmod -R 755 ~/.claude/copilot
```

---

## Environment Variables

### cc CLI

| Variable | Default | Purpose |
|----------|---------|---------|
| `CC_MACHINE_CONFIG` | `~/.claude/cc/config.json` | Machine config override |
| `CC_PROJECT_CONFIG` | `.claude/cc/config.json` | Project config override |

### tc CLI (Task Copilot)

| Variable | Default | Purpose |
|----------|---------|---------|
| `TASK_DB_PATH` | `~/.claude/tasks` | Task database storage |

---

## Per-Project Main-Session Model Pinning

For projects where you want every Claude Code session to use a specific model, use the project-local launcher:

- **`.claude/.model`** — plain-text file containing the model ID (e.g. `claude-sonnet-4-6[1m]`). Committed to the repo so all developers share the same default.
- **`.claude/claude-launcher`** — executable wrapper script. Run it instead of `claude` to launch Claude Code with the pinned model.

```bash
.claude/claude-launcher          # uses .claude/.model
CLAUDE_MODEL=claude-opus-4-5 .claude/claude-launcher  # env var overrides file
```

If `.claude/.model` is missing/empty and `CLAUDE_MODEL` is not set, the launcher falls back to Claude Code's default model selection.

---

## Knowledge Repository

Claude Copilot supports shared knowledge available across all projects.

### Quick Setup

Run `/knowledge-copilot` for guided setup that:
1. Creates a Git repository for your knowledge
2. Guides you through documenting company/voice/products/standards
3. Helps you push to GitHub for team sharing
4. Links to `~/.claude/knowledge` for automatic access

### Manual Setup

```bash
# Create and link
mkdir -p ~/my-company-knowledge
ln -sf ~/my-company-knowledge ~/.claude/knowledge

# Create manifest (required)
echo '{"version":"1.0","name":"my-company","description":"Company knowledge"}' > ~/.claude/knowledge/knowledge-manifest.json
```

### Team Members

```bash
# Clone team knowledge repo
git clone git@github.com:org/company-knowledge.git ~/company-knowledge

# Link it
ln -sf ~/company-knowledge ~/.claude/knowledge
```

---

## External Dependencies

### `copilot` CLI (from cli-copilot)

**Required for:** `tc deploy wait` and Flow E (Infrastructure) deploy verification.

**Optional for:** All other framework features.

**Installation:** See the [cli-copilot project](https://github.com/Everyone-Needs-A-Copilot/cli-copilot).

**Verify:**
```bash
copilot version
```

---

## Next Steps

After setup:
1. **Start working:** `/protocol`
2. **Resume work:** `/continue`
3. **Set up knowledge:** `/knowledge-copilot` (optional but recommended)
