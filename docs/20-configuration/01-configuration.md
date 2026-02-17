# Configuration Guide

This guide covers all configuration options for Claude Copilot, from basic offline setup to full external service integration.

---

## Quick Reference

| What | Where | Required |
|------|-------|----------|
| MCP servers | `.mcp.json` | Yes |
| Project instructions | `CLAUDE.md` | Yes |
| Commands | `.claude/commands/` | Yes |
| Agents | `.claude/agents/` | Yes |
| Local skills | `.claude/skills/` | No |
| Global knowledge | `~/.claude/knowledge/` | No |

---

## The .mcp.json File

This file configures the MCP servers that power Claude Copilot.

### Basic Setup (Works Offline)

```json
{
  "mcpServers": {
    "copilot-memory": {
      "command": "node",
      "args": ["/Users/yourname/.claude/copilot/mcp-servers/copilot-memory/dist/index.js"],
      "env": {
        "MEMORY_PATH": "/Users/yourname/.claude/memory",
        "WORKSPACE_ID": "your-project-name"
      }
    },
    "skills-copilot": {
      "command": "node",
      "args": ["/Users/yourname/.claude/copilot/mcp-servers/skills-copilot/dist/index.js"],
      "env": {
        "LOCAL_SKILLS_PATH": "./.claude/skills"
      }
    }
  }
}
```

> **Important:** Replace `/Users/yourname` with your actual home directory path. The `~` tilde does **NOT** expand in MCP args.

**What works offline:**
- All 14 lean agents (with on-demand skill loading)
- Memory persistence (local SQLite)
- Local project skills
- Knowledge search (if configured)
- All commands (`/protocol`, `/continue`, etc.)

### Full Setup (With External Services)

```json
{
  "mcpServers": {
    "copilot-memory": {
      "command": "node",
      "args": ["/Users/yourname/.claude/copilot/mcp-servers/copilot-memory/dist/index.js"],
      "env": {
        "MEMORY_PATH": "/Users/yourname/.claude/memory",
        "WORKSPACE_ID": "your-project-name"
      }
    },
    "skills-copilot": {
      "command": "node",
      "args": ["/Users/yourname/.claude/copilot/mcp-servers/skills-copilot/dist/index.js"],
      "env": {
        "LOCAL_SKILLS_PATH": "./.claude/skills",
        "SKILLSMP_API_KEY": "sk_live_skillsmp_your_key_here",
        "POSTGRES_URL": "postgresql://user:pass@host:5432/database"
      }
    }
  }
}
```

---

## Environment Variables

### Memory Copilot

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `MEMORY_PATH` | No | `~/.claude/memory` | Where databases are stored |
| `WORKSPACE_ID` | No | Auto-hash of path | Unique project identifier |

**WORKSPACE_ID Notes:**
- By default, each project gets a unique database based on its path hash
- Set explicitly to preserve memories when renaming/moving projects
- Use the same ID across projects to share memory

### Skills Copilot

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `LOCAL_SKILLS_PATH` | No | `./.claude/skills` | Project-specific skills |
| `SKILLSMP_API_KEY` | No | - | Access to 25K+ public skills |
| `POSTGRES_URL` | No | - | Team-shared private skills |
| `KNOWLEDGE_REPO_PATH` | No | - | Project-specific knowledge |
| `GLOBAL_KNOWLEDGE_PATH` | No | `~/.claude/knowledge` | Machine-wide knowledge |

### Task Copilot

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `TASK_DB_PATH` | No | - | Override SQLite database path |
| `WORKSPACE_ID` | No | - | Workspace identifier for task scoping |
| `LOG_LEVEL` | No | `info` | Logging level |
| `HTTP_API_HOST` | No | `127.0.0.1` | API host |
| `HTTP_API_PORT` | No | `9090` | API port |
| `ECOMODE_THRESHOLD_LOW` | No | `0.3` | Ecomode low threshold (0-1) |
| `ECOMODE_THRESHOLD_MEDIUM` | No | `0.7` | Ecomode medium threshold (0-1) |

---

## External Services

### Skill Marketplace (SkillsMP)

[Skill Marketplace](https://skillsmp.com) provides access to 25,000+ public skills—curated prompts, workflows, and domain expertise packaged as reusable skills.

**What you get:**
- Framework patterns (React, Next.js, Laravel, Rails, Django, etc.)
- Language idioms and best practices
- Security checklists and compliance guides
- Design system implementations
- API design standards

**To get your API key:**

1. Visit [skillsmp.com](https://skillsmp.com)
2. Create an account or sign in
3. Navigate to Settings → API Keys
4. Generate a new API key
5. Add to your `.mcp.json` as `SKILLSMP_API_KEY`

### PostgreSQL (Team Skills)

For teams that want to share proprietary skills, methodologies, or company standards.

**Option 1: Managed PostgreSQL (Recommended)**

| Provider | Free Tier | Setup Time |
|----------|-----------|------------|
| [Supabase](https://supabase.com) | 500MB | 5 minutes |
| [Neon](https://neon.tech) | 512MB | 5 minutes |
| [Railway](https://railway.app) | $5 credit | 5 minutes |

**Setup steps:**

1. Create account at your chosen provider
2. Create a new PostgreSQL database
3. Get your connection string (format: `postgresql://user:pass@host:port/db`)
4. Run the schema migration:
   ```bash
   psql "your_connection_string" -f ~/.claude/copilot/mcp-servers/skills-copilot/schema.sql
   ```
5. Add `POSTGRES_URL` to your `.mcp.json`

**Option 2: Self-Hosted PostgreSQL**

```bash
# Using Docker
docker run -d \
  --name skills-db \
  -e POSTGRES_PASSWORD=yourpassword \
  -p 5432:5432 \
  postgres:15

# Run migrations
psql -h localhost -U postgres -f ~/.claude/copilot/mcp-servers/skills-copilot/schema.sql
```

**Saving private skills:**

```javascript
skill_save({
  name: "company-api-standards",
  description: "Our REST API design standards",
  content: "Your skill content here...",
  category: "architecture",
  keywords: ["api", "rest", "standards"],
  isProprietary: true
})
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

### Project-Specific Knowledge

Override global knowledge for a specific project:

```json
{
  "mcpServers": {
    "skills-copilot": {
      "env": {
        "KNOWLEDGE_REPO_PATH": "/path/to/project-specific/knowledge"
      }
    }
  }
}
```

### Resolution Order

Knowledge is searched in order:
1. Project-level (`KNOWLEDGE_REPO_PATH`)
2. Machine-level (`~/.claude/knowledge`)

---

## Project Structure

After setup, your project looks like:

```
your-project/
├── .mcp.json              # MCP server configuration
├── CLAUDE.md              # Project instructions
└── .claude/
    ├── commands/          # Slash commands
    │   ├── protocol.md
    │   ├── continue.md
    │   ├── setup.md
    │   └── knowledge-copilot.md
    ├── agents/            # Agent definitions
    │   ├── ta.md
    │   ├── me.md
    │   ├── qa.md
    │   └── ... (12 total)
    └── skills/            # Project-specific skills
```

---

## CLAUDE.md

The `CLAUDE.md` file provides project-specific instructions to Claude.

### Template Variables

When `/setup` creates this file, it replaces:

| Variable | Source |
|----------|--------|
| `{{PROJECT_NAME}}` | Folder name |
| `{{PROJECT_DESCRIPTION}}` | User input |
| `{{TECH_STACK}}` | User input |
| `{{WORKSPACE_ID}}` | From .mcp.json |
| `{{KNOWLEDGE_STATUS}}` | Auto-detected |
| `{{EXTERNAL_SKILLS_STATUS}}` | Auto-detected |

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

## Verification

After configuration, verify everything works:

### Check MCP Servers

```
/mcp
```

Expected:
```
● copilot-memory
● skills-copilot
```

### Check Memory

```
/continue
```

Should load any existing initiative or report none found.

### Check Knowledge

```
knowledge_search("company")
```

Should return results if knowledge is configured.

### Check Skills

```
skill_search("react")
```

Should return results (from local, Postgres, and/or SkillsMP).

---

## Troubleshooting

### MCP Servers Not Connecting

1. **Check paths are absolute** (not `~`)
   ```json
   "args": ["/Users/yourname/..."]  ✓
   "args": ["~/.claude/..."]        ✗
   ```

2. **Verify servers are built**
   ```bash
   ls ~/.claude/copilot/mcp-servers/copilot-memory/dist/index.js
   ls ~/.claude/copilot/mcp-servers/skills-copilot/dist/index.js
   ```

3. **Restart Claude Code** after changing `.mcp.json`

### Build Fails

**Native module errors:**
```bash
# macOS
xcode-select --install

# Then rebuild
cd ~/.claude/copilot/mcp-servers/copilot-memory
npm rebuild better-sqlite3
npm run build
```

### Memory Not Persisting

- Memory is workspace-scoped (per `WORKSPACE_ID`)
- Check `~/.claude/memory/` for database files
- Ensure write permissions on the directory

### Knowledge Not Found

- Check symlink: `ls -la ~/.claude/knowledge`
- Verify manifest exists: `cat ~/.claude/knowledge/knowledge-manifest.json`
- Check resolution order (project overrides global)

---

## Next Steps

- [User Journey](USER-JOURNEY.md) - Complete setup walkthrough
- [Agents](AGENTS.md) - All 12 specialist agents
- [Customization](CUSTOMIZATION.md) - Extensions and private skills
