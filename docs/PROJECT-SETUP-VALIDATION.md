# Claude Copilot Project Setup Validation

Use this prompt to validate and fix your project's Claude Copilot configuration.

---

## Validation Prompt

Copy and paste this prompt into Claude Code:

```
Validate my Claude Copilot setup. Perform these checks:

## 1. MCP Configuration Check
- Read my .mcp.json file
- Verify copilot-memory points to: ~/.claude/copilot/mcp-servers/copilot-memory/dist/index.js
- Verify skills-copilot points to: ~/.claude/copilot/mcp-servers/skills-copilot/dist/index.js
- If paths are wrong (e.g., ~/.claude/mcp-servers/ without /copilot/), update them

## 2. Global Installation Check
- Verify ~/.claude/copilot/ exists and is a git repo
- Run: cd ~/.claude/copilot && git status
- If behind origin, pull latest
- Rebuild MCP servers if needed:
  - cd ~/.claude/copilot/mcp-servers/copilot-memory && npm run build
  - cd ~/.claude/copilot/mcp-servers/skills-copilot && npm run build

## 3. CLAUDE.md Check
- Verify CLAUDE.md exists in project root
- Check it references Claude Copilot framework
- If missing, copy from ~/.claude/copilot/templates/CLAUDE.template.md

## 4. Shared Docs Check (if applicable)
- Check if docs/shared-docs/ or docs/shared/ exists
- If yes, verify knowledge-manifest.json exists
- Verify LOCAL_SKILLS_PATH in .mcp.json points to correct skills location

## 5. Test MCP Servers
- Call initiative_get to verify copilot-memory works
- Call skill_list to verify skills-copilot works

Report any issues found and fix them. Show me a summary of what was checked and any changes made.
```

---

## Quick Fix Commands

If you need to manually fix common issues:

### Update MCP paths in .mcp.json

```json
{
  "mcpServers": {
    "copilot-memory": {
      "command": "node",
      "args": ["~/.claude/copilot/mcp-servers/copilot-memory/dist/index.js"],
      "env": {
        "LOG_LEVEL": "info",
        "MEMORY_PATH": "~/.claude/memory"
      }
    },
    "skills-copilot": {
      "command": "node",
      "args": ["~/.claude/copilot/mcp-servers/skills-copilot/dist/index.js"],
      "env": {
        "LOG_LEVEL": "info",
        "CACHE_PATH": "~/.claude/skills-cache"
      }
    }
  }
}
```

### Rebuild global installation

```bash
cd ~/.claude/copilot
git pull
cd mcp-servers/copilot-memory && npm run build
cd ../skills-copilot && npm run build
```

### Copy CLAUDE.md template

```bash
cp ~/.claude/copilot/templates/CLAUDE.template.md ./CLAUDE.md
```

---

## Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| `vec0 knn` errors | Old MCP server build | Rebuild at ~/.claude/copilot |
| MCP server not found | Wrong path in .mcp.json | Update to ~/.claude/copilot/... |
| No memories found | Different project hash | Check MEMORY_PATH env var |
| Skills not loading | Wrong LOCAL_SKILLS_PATH | Update path in .mcp.json |

---

## Canonical Paths

Always use these paths for Claude Copilot:

| Component | Path |
|-----------|------|
| Global installation | `~/.claude/copilot/` |
| Memory MCP server | `~/.claude/copilot/mcp-servers/copilot-memory/` |
| Skills MCP server | `~/.claude/copilot/mcp-servers/skills-copilot/` |
| Memory database | `~/.claude/memory/{project-hash}/` |
| Skills cache | `~/.claude/skills-cache/` |
| Templates | `~/.claude/copilot/templates/` |
