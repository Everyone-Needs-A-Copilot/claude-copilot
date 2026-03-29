# Skills Copilot MCP Server (OPTIONAL)

**Note: This MCP server is OPTIONAL.** For simple local skill loading, use native `@include` directives instead (see "When to Use" below).

Advanced on-demand skill loading from multiple sources when you need marketplace access, private skill storage, or cross-source search.

## When to Use

### Use Native @include (Recommended)

For local skills, use native Claude Code directives:

```markdown
## Context
When working with Laravel:
@include ~/.claude/skills/laravel/SKILL.md

When writing tests:
@include .claude/skills/testing/SKILL.md
```

**Benefits:**
- Zero MCP overhead (~500 tokens saved per skill vs MCP)
- Instant loading, no network/database
- No setup required (just create files)
- Full control over skill content

### Use Skills Copilot MCP (This Server)

Only install if you need:

| Feature | Requires MCP |
|---------|--------------|
| skills.sh public catalog (curated Anthropic skills) | ✓ Yes |
| Private skill storage in Postgres | ✓ Yes |
| Cross-source skill search | ✓ Yes |
| Usage analytics and caching | ✓ Yes |
| Knowledge repository extensions | ✓ Yes |
| Local skill loading | ✗ No (use @include) |

## Features

- **Multi-Source Fetching**: Private DB (Postgres) + skills.sh (public catalog) + Local files
- **Auto-Discovery**: Automatically scans `.claude/skills` directories (no manifest needed)
- **Intelligent Caching**: SQLite cache with configurable TTL + mtime-based skill cache
- **On-Demand Loading**: Skills load only when needed (~2K tokens per skill)
- **Unified Search**: Search across all sources with relevance ranking
- **Usage Analytics**: Track which skills are used most

## Architecture

```
Claude Code Session
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│                  Skills Copilot MCP                       │
│                                                           │
│  skill_get(name)                                         │
│    1. Check SQLite cache                                 │
│    2. Query Postgres (private skills)                    │
│    3. Fetch from skills.sh (public skills)              │
│    4. Fallback to local files                           │
│                                                           │
└──────────────────────────────────────────────────────────┘
       │              │              │              │
       ▼              ▼              ▼              ▼
   SQLite         Postgres      skills.sh      Local
   Cache          (private)      (public)       Files
```

## Installation

### 1. Install dependencies

```bash
cd ~/.claude/copilot/mcp-servers/skills-copilot
npm install
```

### 2. Build

```bash
npm run build
```

### 3. Configure environment

Copy `.env.example` to `.env` and configure:

```bash
# Public skills via skills.sh — no API key needed (free, Vercel-backed)

# Required for private skills (optional if only using public)
POSTGRES_URL=postgresql://user:pass@host:5432/database

# Optional
CACHE_PATH=~/.claude/skills-cache
CACHE_TTL_DAYS=7
LOCAL_SKILLS_PATH=./.claude/skills
LOG_LEVEL=info

# Knowledge repository for agent extensions (optional)
KNOWLEDGE_REPO_PATH=/path/to/your/knowledge-repo
```

### 4. Set up database (for private skills)

Run the schema against your Postgres database:

```bash
psql -d your_database -f schema.sql
```

Or in Supabase SQL Editor, paste the contents of `schema.sql`.

### 5. Add to MCP configuration

Add to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "skills-copilot": {
      "command": "node",
      "args": ["~/.claude/copilot/mcp-servers/skills-copilot/dist/index.js"],
      "env": {
        "POSTGRES_URL": "postgresql://...",
        "CACHE_PATH": "~/.claude/skills-cache",
        "LOG_LEVEL": "info"
      }
    }
  }
}
```

**Note:** skills.sh is the public skills provider and requires no API key or configuration. It is automatically available when the MCP server starts.

### 6. Restart Claude Code

Changes take effect after restarting.

## Tools

### Skill Tools

| Tool | Description |
|------|-------------|
| `skill_get` | Fetch skill by name from best available source |
| `skill_search` | Search skills across all sources |
| `skill_list` | List available skills by source (shows auto-discovered vs manifest) |
| `skill_save` | Save skill to private database |
| `skill_cache_clear` | Clear cache (all or specific skill) |
| `skill_discover` | Force re-scan of auto-discovery paths |
| `skill_auto_detect` | Auto-detect skills based on file patterns and keywords |
| `skills_hub_status` | Check provider status (includes discovery stats) |

### Extension Tools

| Tool | Description |
|------|-------------|
| `extension_get` | Get agent extension from knowledge repository |
| `extension_list` | List all available agent extensions |
| `manifest_status` | Check knowledge repository configuration |

## Auto-Discovery

Skills Copilot automatically discovers skills from standard directories without requiring manifest configuration.

### Discovery Paths

Skills are auto-discovered from:
1. `.claude/skills/` (project-level)
2. `~/.claude/skills/` (user-level)

### Skill Structure

Each skill must be in its own directory with a `SKILL.md` file:

```
.claude/skills/
├── my-skill/
│   └── SKILL.md
└── another-skill/
    └── SKILL.md
```

### Required Frontmatter

Skills must have valid YAML frontmatter with at minimum:
- `name` or `skill_name`: Unique skill identifier
- `description`: Brief description

Optional trigger fields for context-based auto-detection:
- `trigger_files`: Array of file patterns (glob-like) that trigger this skill
- `trigger_keywords`: Array of keywords that trigger this skill

```markdown
---
skill_name: my-custom-skill
description: Does something useful
trigger_files: ["*.test.ts", "*.spec.js"]
trigger_keywords: [testing, jest, vitest]
---

# Skill Content

Your skill content here...
```

### Validation

Skills are validated on discovery:
- Missing `name` or `description` → Logged as warning, skipped
- Parse errors → Logged as warning, skipped
- Valid skills → Cached for fast access

### Caching

- Discovered skills are cached with modification time
- Skills are only re-parsed if file has changed
- Use `skill_discover()` to force re-scan
- Cache persists across server restarts (in-memory per session)

### Force Re-scan

```
skill_discover({ clearCache: false })  // Re-scan without clearing main cache
skill_discover({ clearCache: true })   // Full refresh
```

## Context-Triggered Skills

Skills can define triggers to enable context-based auto-detection. When you're working with specific files or discussing certain topics, relevant skills can be automatically suggested.

### Trigger Types

| Trigger Type | Format | Example |
|--------------|--------|---------|
| File patterns | Glob-like patterns | `*.test.ts`, `**\/docs/**\/*.md` |
| Keywords | Text keywords | `testing`, `documentation`, `validation` |

### File Pattern Matching

Patterns support:
- Wildcards: `*.md` matches any markdown file
- Path segments: `**\/test/**\/` matches test directories anywhere
- Extensions: `.test.ts`, `.spec.js`
- Combined: `src/**\/*.test.ts`

### Auto-Detection

Use `skill_auto_detect` to find skills matching your current context:

```
skill_auto_detect({
  files: ["docs/api.md", "docs/setup.md"],
  text: "We need to validate the documentation structure",
  limit: 5
})
```

Returns ranked list of skills with match scores based on:
- File pattern matches (+10 points per file)
- Keyword matches (+5 points per keyword)

### Example Skill with Triggers

```markdown
---
skill_name: test-automation
description: Generate test suites for TypeScript code
trigger_files: ["*.test.ts", "*.spec.ts", "**\/__tests__/**\/*"]
trigger_keywords: [testing, jest, vitest, test-suite, unit-test]
---

# Test Automation

Generate comprehensive test suites...
```

### Integration with Agents

Agents can call `skill_auto_detect` at the start of a task to automatically load relevant skills based on:
- Files mentioned in task description
- Keywords in user request
- Files being modified

This reduces the need to manually search for skills and ensures relevant expertise is always available.

## Usage Examples

### Get a skill

```
skill_get({ name: "nextjs-app-router-patterns" })
```

Returns full SKILL.md content from skills.sh or local sources.

### Search for skills

```
skill_search({ query: "laravel testing", limit: 5 })
```

Returns matching skills from all sources.

### Save a private skill

```
skill_save({
  name: "forces-analysis",
  description: "Identify organizational forces blocking progress",
  content: "---\nname: forces-analysis\n...",
  category: "analysis",
  keywords: ["forces", "blockers", "organization"],
  isProprietary: true
})
```

### Check status

```
skills_hub_status()
```

Returns provider connection status and cache stats.

## Knowledge Repository Extensions

Knowledge repositories can extend base agents with company-specific methodologies. Configure via `KNOWLEDGE_REPO_PATH` environment variable.

### Get extension for an agent

```
extension_get({ agent: "sd" })
```

Returns the extension content (override, extension, or skills injection).

### List available extensions

```
extension_list()
```

Returns all extensions defined in the knowledge repository manifest.

### Check configuration

```
manifest_status()
```

Returns:
```json
{
  "configured": true,
  "path": "/path/to/knowledge-repo",
  "manifest": {
    "name": "company-knowledge",
    "extensions": 4,
    "skills": 5
  }
}
```

See [extension-spec.md](/docs/40-extensions/00-extension-spec.md) for full documentation on creating knowledge repositories.

## Skills Registry (CLAUDE.md)

For fastest performance, add a Skills Registry to your CLAUDE.md:

```markdown
## Skills Registry

### Private Skills
| Skill | Keywords |
|-------|----------|
| forces-analysis | forces, blockers, resistance |
| colab | colab, alignment, leadership |

### Public Skills (skills.sh)
| Skill | Keywords | Author |
|-------|----------|--------|
| nextjs-app-router-patterns | nextjs, ssr | wshobson |
| laravel | laravel, eloquent | vapvarun |
```

Claude reads this at session start (~200 tokens) and knows what skills are available. Full content loads on-demand via `skill_get`.

## Token Impact

### Native @include vs MCP

| Method | Session Start | Per Skill | When to Use |
|--------|---------------|-----------|-------------|
| Native @include | ~0 tokens (no MCP overhead) | ~1,500 tokens (direct read) | Local skills only |
| Skills Copilot MCP | ~500 tokens (MCP init) | ~2,000 tokens (with metadata) | Marketplace/search/DB |

### Historical Context

| Scenario | Before MCP | With Skills Copilot | With Native @include |
|----------|------------|---------------------|---------------------|
| Session start (all skills) | 42,000 tokens | 5,000 tokens | ~0 tokens |
| On-demand skill load | N/A | ~2,000 tokens | ~1,500 tokens |
| Available skills | 21 (preloaded) | Curated catalog (skills.sh) | Unlimited (local files) |

**Result: Native @include is most efficient for local skills, MCP adds value for marketplace access**

## Migration Guide

### From skill_get() to @include

**Before (MCP):**
```typescript
// In agent prompt or session
const skill = await skill_get({ name: "laravel" });
// ~2,000 tokens per call
```

**After (Native):**
```markdown
## Context
@include ~/.claude/skills/laravel/SKILL.md
# ~1,500 tokens, no MCP overhead
```

### When to Keep Using MCP

Keep `skill_get()` if you:
- Search the skills.sh public catalog (`skill_search`)
- Store private skills in database (`skill_save`)
- Need cross-source search (DB + skills.sh + local)
- Track usage analytics
- Use knowledge repository extensions

### Hybrid Approach (Recommended)

Use both for maximum flexibility:

```markdown
## Context
# Native for local/frequent skills
@include .claude/skills/testing/SKILL.md
@include ~/.claude/skills/laravel/SKILL.md

# MCP for skills.sh catalog/search/one-time skills
When needed, search skills.sh: skill_search({ query: "nextjs app router" })
```

## Creating Skills for Native @include

### Skill File Structure

```
.claude/skills/
├── laravel/
│   └── SKILL.md
├── testing/
│   └── SKILL.md
└── custom-workflow/
    └── SKILL.md
```

### Skill File Format

```markdown
---
skill_name: laravel
description: Laravel best practices and patterns
version: 1.0
---

# Laravel Skill

Your skill content here...
```

### Using Skills in Prompts

**In CLAUDE.md:**
```markdown
## Available Skills

Local skills (load with @include):
- Laravel: `.claude/skills/laravel/SKILL.md`
- Testing: `.claude/skills/testing/SKILL.md`
```

**In conversation:**
```markdown
I need to build a Laravel API endpoint.

@include .claude/skills/laravel/SKILL.md
```

### Global vs Project Skills

| Location | Scope | Use For |
|----------|-------|---------|
| `~/.claude/skills/` | All projects | Language frameworks, common patterns |
| `.claude/skills/` | Single project | Project-specific workflows, domain logic |

## Development

```bash
# Watch mode
npm run dev

# Run directly (for testing)
node dist/index.js
```

## Troubleshooting

**skills.sh connectivity issues**
- Ensure you have network access
- skills.sh is Vercel-backed with ~50ms response time; transient failures are rare
- No API key required — if requests fail, check firewall/proxy settings

**Postgres connection failed**
- Verify connection string format
- Check network/firewall rules
- Ensure database exists

**Skills not found**
- Run `skills_hub_status()` to check providers
- Try `skill_search()` to find similar skills
- Check local skills path is correct

**Cache issues**
- Clear with `skill_cache_clear()`
- Check CACHE_PATH is writable
- Default TTL is 7 days

## License

MIT
