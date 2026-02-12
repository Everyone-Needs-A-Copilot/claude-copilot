---
name: setup-copilot
description: Universal Claude Copilot setup. Auto-detects context and routes to the appropriate setup command.
---

# Universal Setup Router

Auto-detects your context and runs the correct setup command.

## Step 1: Detect Context

```bash
pwd
ls .mcp.json 2>/dev/null && echo "MCP_EXISTS" || echo "NO_MCP"
echo $HOME
```

Store: `CURRENT_DIR`, `HOME_PATH`, `MCP_STATUS`

Check user's message for keywords: "minimal", "quick start", "memory only", "simple", "fast"
If found, set `MINIMAL_REQUESTED` = true.

## Step 2: Route

**If CURRENT_DIR ends with `/.claude/copilot`:**

Tell user: "Detected: Claude Copilot directory. Running machine setup."
Follow `/setup` command.

**Else if MCP_STATUS = "MCP_EXISTS":**

Tell user: "Detected: Existing project (.mcp.json found). Running project update."
Follow `/update-project` command.

**Else if MINIMAL_REQUESTED:**

Tell user: "Detected: New project. Running minimal (memory-only) setup."
Follow `/setup-project` command (the minimal keywords will trigger its minimal flow).

**Else:**

Tell user: "Detected: New project. Running full project setup."
Follow `/setup-project` command.
