# Configuration Guide

This guide covers all configuration options for Claude Copilot, from basic setup to full team integration.

**Diátaxis mode:** Reference

---

## Quick Reference

| What | Where | Required |
|------|-------|----------|
| Project instructions | `CLAUDE.md` | Yes |
| Commands | `.claude/commands/` | Yes |
| Agents | `.claude/agents/` | Yes |
| cc CLI config | `~/.config/cc/config.json` (managed by `cc config`) | Yes for memory/skills |
| Local skills | `.claude/skills/` | No |
| Global knowledge | `~/.claude/knowledge/` | No |

---

## cc CLI Configuration

The `cc` CLI manages memory, skills, and stable reference values. Configure it after installing the framework.

### Core Path Keys

```bash
# Set the shared docs location (resolves CC_SHARED_DOCS in agents)
cc config set paths.shared_docs /path/to/shared/docs

# Set the knowledge repo location
cc config set paths.knowledge_repo /path/to/knowledge-repo

# View all configuration
cc config export
```

> **macOS paths with spaces:** Wrap in quotes. Example:
> `cc config set paths.shared_docs "/Users/you/Google Drive/Team Docs"`

### Reference Values (refs.*)

Register stable values that get injected as Known References at the start of every session:

```bash
# Register a named reference
cc config set refs.company_wiki https://wiki.example.com
cc config set refs.design_system /path/to/design-system
cc config set refs.staging_url https://staging.example.com

# List all refs
cc config export | grep refs
```

Reference values are injected by the `SessionStart` and `UserPromptSubmit` hooks at the first turn of each session. See [References Registry](./03-references-registry.md) for details.

### Inspect Configuration

```bash
# Get a single value (raw output)
cc config get paths.shared_docs --raw

# Export all config as key=value pairs
cc config export

# Show help
cc config --help
```

---

## Environment Variables

The `cc env` command exports environment variables for use in scripts and agent preambles:

```bash
# In agent preamble or script:
eval "$(cc env)"
# Hydrates: CC_SHARED_DOCS, CC_KNOWLEDGE_REPO, etc.
```

| Variable | Source | Purpose |
|----------|--------|---------|
| `CC_SHARED_DOCS` | `cc config get paths.shared_docs` | Path to shared documentation |
| `CC_KNOWLEDGE_REPO` | `cc config get paths.knowledge_repo` | Path to knowledge repository |
| `KNOWLEDGE_REPO_PATH` | Same as CC_KNOWLEDGE_REPO | Backward-compatible alias |

---

## Task Copilot (tc CLI)

The `tc` CLI manages PRDs, tasks, and work products. No configuration file — it uses the current project directory as workspace context.

| Variable | Default | Purpose |
|----------|---------|---------|
| `TASK_DB_PATH` | `~/.claude/tasks` | Override SQLite database path |
| `LOG_LEVEL` | `info` | Logging level |

```bash
# Verify tc is working
tc task list
tc progress
```

---

## Project Structure

After setup, your project looks like:

```
your-project/
├── CLAUDE.md              # Project instructions (auto-loaded by Claude Code)
└── .claude/
    ├── commands/          # Slash commands
    │   ├── protocol.md
    │   ├── continue.md
    │   ├── setup.md
    │   └── knowledge-copilot.md
    ├── agents/            # Agent definitions (16 files: 15 framework + kc setup-only)
    │   ├── ta.md
    │   ├── me.md
    │   ├── qa.md
    │   ├── do.md
    │   ├── doc.md
    │   ├── sd.md
    │   ├── uxd.md
    │   ├── uids.md
    │   ├── uid.md
    │   ├── sec.md
    │   ├── ind.md
    │   ├── cco.md
    │   ├── cw.md
    │   ├── cs.md
    │   ├── cpa.md
    │   └── kc.md
    └── skills/            # Project-specific skills (optional)
```

---

## CLAUDE.md

The `CLAUDE.md` file provides project-specific instructions to Claude Code. It is auto-loaded at the start of every session.

### Template Variables

When `/setup-project` creates this file, it replaces:

| Variable | Source |
|----------|--------|
| `{{PROJECT_NAME}}` | Folder name |
| `{{PROJECT_DESCRIPTION}}` | User input |
| `{{TECH_STACK}}` | User input |
| `{{KNOWLEDGE_STATUS}}` | Auto-detected |

### Adding Project Rules

Add your own rules in the "Project-Specific Rules" section:

```markdown
## Project-Specific Rules

- Use TypeScript for all new code
- All API endpoints require authentication
- Run `npm test` before committing
- Follow conventional commits
```

---

## Knowledge Configuration

### Global Knowledge (Recommended)

Set up once, available in all projects:

```bash
# Create or symlink
ln -sf ~/your-company-knowledge ~/.claude/knowledge

# Or create directly
mkdir -p ~/.claude/knowledge
```

**Required:** `knowledge-manifest.json` in the knowledge directory:

```json
{
  "version": "1.0",
  "name": "my-company",
  "description": "Company knowledge repository"
}
```

Register the path so agents always know where it is:

```bash
cc config set paths.knowledge_repo ~/.claude/knowledge
```

### Resolution Order

Knowledge and extensions are resolved in order:
1. Project-level (`CC_KNOWLEDGE_REPO` / `KNOWLEDGE_REPO_PATH`)
2. Machine-level (`~/.claude/knowledge`)

---

## Deploy Configuration

The `do` agent (DevOps) checks for a deploy CLI before running deployment commands:

```bash
# Register your deploy CLI
cc config set deploy.cli /path/to/deploy-script

# The do agent will check this before attempting deployment
# If absent, deployment steps requiring it are skipped with a warning
```

---

## Model Pinning (Recommended)

Use `.claude/claude-launcher` instead of `claude` directly. It reads `.claude/.model` (default: `claude-sonnet-4-6`) and passes `--model` automatically.

```bash
# Set default model for this project
echo "claude-sonnet-4-6" > .claude/.model

# Override per-session
CLAUDE_MODEL=claude-opus-4-5 .claude/claude-launcher
```

---

## Verification

After configuration, verify everything works:

### Check cc CLI

```bash
# Verify cc is installed
cc --version

# Verify configuration
cc config export

# Search for a skill
cc skill list | head -5

# Search memory
cc memory search "test"
```

### Check tc CLI

```bash
# Verify tc is installed
tc version

# List tasks
tc task list

# View progress
tc progress
```

### Check Knowledge

```bash
# Verify knowledge path
cc config get paths.knowledge_repo --raw

# Should return your knowledge repo path
ls "$(cc config get paths.knowledge_repo --raw)"
```

---

## Troubleshooting

### cc or tc Not Found

```bash
# Install cc CLI
bash ~/.claude/copilot/tools/cc/install.sh

# Install tc CLI
pip install -e ~/.claude/copilot/tools/tc

# Or add to PATH manually
export PATH="$PATH:~/.claude/copilot/tools/cc/src"
```

### Configuration Not Persisting

```bash
# Check config file location
cc config export

# If empty, the config file may be in a different location
# Force-set a value and check where it's written
cc config set test.key test_value
cc config get test.key
```

### Knowledge Not Found

- Check symlink: `ls -la ~/.claude/knowledge`
- Verify manifest exists: `cat ~/.claude/knowledge/knowledge-manifest.json`
- Check resolution order (project overrides global)
- Ensure path is registered: `cc config get paths.knowledge_repo`

---

## Next Steps

- [User Journey](../01-getting-started/01-user-journey.md) - Complete setup walkthrough
- [Agents](../10-architecture/01-agents.md) - All 16 specialist agents
- [Customization](./02-customization.md) - Extensions and private skills
- [References Registry](./03-references-registry.md) - Stable reference injection
