# Copilot Memory MCP Server

Session memory with semantic search for Claude Code. Replaces manual initiative file tracking with automated persistence.

## Features

- **Semantic Search**: Natural language queries across all stored memories
- **Initiative Tracking**: Automatic session context persistence
- **Project Isolation**: Each project has its own memory store
- **Auto-Migration**: Migrates existing initiative files on first use
- **Backward Compatible**: Falls back to file-based tracking if unavailable

## Installation

### 1. Install dependencies

```bash
cd docs/shared-docs/03-ai-enabling/04-mcp-servers/copilot-memory
npm install
```

### 2. Build

```bash
npm run build
```

### 3. Add to MCP profile

Add to `~/.claude/mcp-profiles/core.json`:

```json
{
  "mcpServers": {
    "copilot-memory": {
      "command": "node",
      "args": ["docs/shared-docs/03-ai-enabling/04-mcp-servers/copilot-memory/dist/index.js"],
      "env": {
        "LOG_LEVEL": "info"
      }
    }
  }
}
```

Or using the launcher script pattern:

```json
{
  "mcpServers": {
    "copilot-memory": {
      "command": "./mcp-servers/run-mcp.sh",
      "args": ["core-business/copilot-memory/dist/index.js"],
      "env": {
        "LOG_LEVEL": "info",
        "MEMORY_PATH": "~/.claude/memory"
      }
    }
  }
}
```

### 4. Restart Claude Code

Changes take effect after restarting Claude Code.

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `MEMORY_PATH` | `~/.claude/memory` | Base path for memory storage |
| `WORKSPACE_ID` | (auto-generated) | Explicit workspace identifier (see below) |
| `LOG_LEVEL` | `info` | Logging level: debug, info, warn, error |

## Data Storage

Data is stored per-workspace at:
```
~/.claude/memory/<workspace-id>/memory.db
```

By default, the workspace ID is an MD5 hash of the project's absolute path. This ensures project isolation but means **renaming or moving a project creates a new empty database**.

### WORKSPACE_ID: Preserving Memory Across Project Changes

To maintain access to your memories when renaming or moving a project, set an explicit `WORKSPACE_ID`:

```json
{
  "mcpServers": {
    "copilot-memory": {
      "command": "node",
      "args": ["~/.claude/copilot/mcp-servers/copilot-memory/dist/index.js"],
      "env": {
        "MEMORY_PATH": "~/.claude/memory",
        "WORKSPACE_ID": "my-project"
      }
    }
  }
}
```

**When to use WORKSPACE_ID:**

| Scenario | Recommendation |
|----------|----------------|
| New project | Leave empty (auto-generated hash) |
| Before renaming/moving project | Set to current hash to preserve memories |
| Multiple related projects | Set same ID to share memories |
| Monorepo with sub-projects | Set unique IDs per sub-project |

**Finding your current workspace hash:**

```bash
# Get hash for current directory
node -e "console.log(require('crypto').createHash('md5').update(process.cwd()).digest('hex').substring(0, 12))"

# Get hash for specific path
node -e "console.log(require('crypto').createHash('md5').update('/path/to/project').digest('hex').substring(0, 12))"
```

**Migration example:**

```bash
# 1. Find current hash before moving
cd /old/project/path
HASH=$(node -e "console.log(require('crypto').createHash('md5').update(process.cwd()).digest('hex').substring(0, 12))")
echo "Current hash: $HASH"

# 2. Add WORKSPACE_ID to .mcp.json
# "WORKSPACE_ID": "<hash-from-step-1>"

# 3. Move/rename project
mv /old/project/path /new/project/path

# 4. Memories are preserved!
```

## Tools

### Memory Operations

| Tool | Description |
|------|-------------|
| `memory_store` | Store a new memory with auto-embedding |
| `memory_update` | Update existing memory (regenerates embedding if content changes) |
| `memory_delete` | Delete a memory |
| `memory_get` | Get a memory by ID |
| `memory_list` | List memories with optional filters |
| `memory_search` | Semantic search using natural language |

### Initiative Operations

| Tool | Description |
|------|-------------|
| `initiative_start` | Start a new initiative (archives existing) |
| `initiative_update` | Update current initiative progress |
| `initiative_get` | Get current initiative as markdown |
| `initiative_complete` | Complete and archive current initiative |

### Utility

| Tool | Description |
|------|-------------|
| `health_check` | Server health and statistics |

## Resources

| URI | Description |
|-----|-------------|
| `memory://initiative/current` | Current initiative in markdown format |
| `memory://context/project` | Project context with recent decisions/lessons |

## Usage Examples

### Store a decision

```json
{
  "tool": "memory_store",
  "arguments": {
    "content": "Decided to use sqlite-vec for vector search because it's embedded and works offline",
    "type": "decision",
    "tags": ["architecture", "database"],
    "metadata": {
      "alternatives": ["Qdrant", "Pinecone"],
      "rationale": "Portability and simplicity"
    }
  }
}
```

### Semantic search

```json
{
  "tool": "memory_search",
  "arguments": {
    "query": "what did we decide about the database",
    "type": "decision",
    "limit": 5
  }
}
```

### Start an initiative

```json
{
  "tool": "initiative_start",
  "arguments": {
    "name": "Batch Validation System",
    "goal": "Reduce submission errors from 15% to <1%"
  }
}
```

### Update progress

```json
{
  "tool": "initiative_update",
  "arguments": {
    "completed": ["Research ICCES requirements"],
    "inProgress": ["Design database schema"],
    "decisions": ["Use Laravel validation rules for consistency"],
    "keyFiles": ["app/Rules/BatchValidation.php"]
  }
}
```

## Memory Types

| Type | Use For |
|------|---------|
| `decision` | Architectural choices, technology selections |
| `lesson` | Insights learned during development |
| `discussion` | Important conversations or context |
| `file` | File-related notes or summaries |
| `initiative` | Initiative-related memories |
| `context` | General context information |

## Embedding Model

Uses [Transformers.js](https://huggingface.co/docs/transformers.js) with the `all-MiniLM-L6-v2` model:

- 384-dimension embeddings
- ~25MB model size (downloaded on first use)
- Runs locally (no API calls)
- Fast inference (<100ms per query)

## Database Schema

- **memories**: Core memory storage with content, type, tags, metadata
- **memory_embeddings**: Vector embeddings for semantic search (sqlite-vec)
- **initiatives**: Current initiative state (one per project)
- **initiatives_archive**: Completed initiatives
- **sessions**: Session tracking
- **memories_fts**: Full-text search index

## Integration with /continue

The `/continue` command automatically:

1. Checks if copilot-memory is available
2. If yes: Uses `initiative_get` for context
3. If no: Falls back to initiative file
4. Migrates file-based initiatives to memory on first use

## Development

```bash
# Watch mode
npm run dev

# Run directly (for testing)
node dist/index.js
```

## Troubleshooting

**Model download slow on first use**
- The embedding model (~25MB) downloads on first use
- Cached in `~/.cache/huggingface` after that

**sqlite-vec errors**
- Ensure you're running Node.js 18+
- Try `npm rebuild better-sqlite3`

**Memory not persisting**
- Check `MEMORY_PATH` is writable
- Verify project path hasn't changed (or set `WORKSPACE_ID` to preserve across moves)

**Lost memories after project rename/move**
- The default workspace ID is a hash of the project path
- Find your old hash: `node -e "console.log(require('crypto').createHash('md5').update('/old/path').digest('hex').substring(0, 12))"`
- Add `"WORKSPACE_ID": "<old-hash>"` to your `.mcp.json`
- Restart Claude Code

## License

MIT
