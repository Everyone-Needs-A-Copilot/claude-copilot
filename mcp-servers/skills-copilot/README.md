# Skills Copilot MCP Server

On-demand skill loading from multiple sources. Reduces token overhead by 85% compared to loading all skills upfront.

## Features

- **Multi-Source Fetching**: Private DB (Postgres) + SkillsMP (25K+ skills) + Local files
- **Intelligent Caching**: SQLite cache with configurable TTL
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
│    3. Fetch from SkillsMP (public skills)               │
│    4. Fallback to local files                           │
│                                                           │
└──────────────────────────────────────────────────────────┘
       │              │              │              │
       ▼              ▼              ▼              ▼
   SQLite         Postgres       SkillsMP       Local
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
# Required for public skills
SKILLSMP_API_KEY=sk_live_skillsmp_your_key_here

# Required for private skills (optional if only using public)
POSTGRES_URL=postgresql://user:pass@host:5432/database

# Optional
CACHE_PATH=~/.claude/skills-cache
CACHE_TTL_DAYS=7
LOCAL_SKILLS_PATH=./03-ai-enabling/01-skills
LOG_LEVEL=info
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
        "SKILLSMP_API_KEY": "sk_live_skillsmp_...",
        "POSTGRES_URL": "postgresql://...",
        "CACHE_PATH": "~/.claude/skills-cache",
        "LOG_LEVEL": "info"
      }
    }
  }
}
```

### 6. Restart Claude Code

Changes take effect after restarting.

## Tools

| Tool | Description |
|------|-------------|
| `skill_get` | Fetch skill by name from best available source |
| `skill_search` | Search skills across all sources |
| `skill_list` | List available skills by source |
| `skill_save` | Save skill to private database |
| `skill_cache_clear` | Clear cache (all or specific skill) |
| `skills_hub_status` | Check provider status |

## Usage Examples

### Get a skill

```
skill_get({ name: "nextjs-app-router-patterns" })
```

Returns full SKILL.md content from SkillsMP.

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

## Skills Registry (CLAUDE.md)

For fastest performance, add a Skills Registry to your CLAUDE.md:

```markdown
## Skills Registry

### Private Skills
| Skill | Keywords |
|-------|----------|
| forces-analysis | forces, blockers, resistance |
| colab | colab, alignment, leadership |

### Public Skills (SkillsMP)
| Skill | Keywords | Author |
|-------|----------|--------|
| nextjs-app-router-patterns | nextjs, ssr | wshobson |
| laravel | laravel, eloquent | vapvarun |
```

Claude reads this at session start (~200 tokens) and knows what skills are available. Full content loads on-demand via `skill_get`.

## Token Impact

| Scenario | Before | After |
|----------|--------|-------|
| Session start | 42,000 tokens | 5,000 tokens |
| Per skill load | N/A | ~2,000 tokens |
| Available skills | 21 | 25,000+ |

**Result: 85% reduction in baseline token usage**

## Development

```bash
# Watch mode
npm run dev

# Run directly (for testing)
node dist/index.js
```

## Troubleshooting

**SkillsMP API errors**
- Check API key is valid
- Ensure you have network access
- Check rate limits (authenticated: higher limits)

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
