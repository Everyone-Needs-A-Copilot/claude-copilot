> **Deprecated:** `copilot-memory` and `skills-copilot` are superseded by the `cc` CLI (`tools/cc/`).
> See `mcp-servers/copilot-memory/DEPRECATED.md` and `mcp-servers/skills-copilot/DEPRECATED.md` for migration guides.

# MCP Servers Directory

This directory contains MCP (Model Context Protocol) server configurations and the universal launcher script.

## Architecture

```
mcp-servers/
├── run-mcp.sh          # Universal launcher script
├── README.md           # This file
└── [category]/         # Server directories organized by function
    └── [server-name]/
        └── src/
            └── index.js
```

## Usage

### Running a Server

```bash
# From project root
./mcp-servers/run-mcp.sh category/server-name/src/index.js
```

### Configuration in .mcp.json

```json
{
  "mcpServers": {
    "server-name": {
      "command": "./mcp-servers/run-mcp.sh",
      "args": ["category/server-name/src/index.js"],
      "env": {
        "LOG_LEVEL": "info"
      }
    }
  }
}
```

## Benefits

| Feature | Description |
|---------|-------------|
| **Portable** | Same config works on any machine |
| **Git-friendly** | Can commit .mcp.json to repository |
| **Multi-runtime** | Supports .js, .ts, and .py servers |

## Adding a New Server

1. Create directory: `mcp-servers/[category]/[server-name]/`
2. Add your server code in `src/`
3. Add configuration to `.mcp.json`
4. Install dependencies: `cd mcp-servers/[category]/[server-name] && npm install`

## Server Categories

| Category | Purpose |
|----------|---------|
| `dev-tools/` | Development utilities |
| `data/` | Database and data access |
| `monitoring/` | Observability tools |
| `integrations/` | External service connectors |

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Server not found" | Check path is relative to `mcp-servers/` |
| Permission denied | Run `chmod +x mcp-servers/run-mcp.sh` |
| Module not found | Run `npm install` in server directory |
