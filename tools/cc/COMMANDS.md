# cc CLI Command Reference

Quick-reference card for agents and developers.

## Memory

```bash
cc memory store --type <decision|context|lesson|reference|person> [--tags t1,t2] [--scope project|global] "<content>"
cc memory get <id>
cc memory list [--type TYPE] [--tags TAG] [--scope SCOPE]
cc memory search "<query>"
cc memory delete <id> [--yes]
cc memory index --rebuild
cc memory index --status
cc memory migrate --from-global [--dry-run] [--all] [--status]
```

## Skills

```bash
cc skill list [--scope project|machine|all]
cc skill search "<query>"
cc skill get <name>
cc skill path <name>
```

## Config

```bash
cc config get <key>
cc config set [--project] <key> <value>
cc config unset [--project] <key>
cc config list [--scope machine|project|effective]
cc config where <key>
cc config validate [--scope machine|project|both]
cc config edit [--project]
cc config init [--machine] [--project]
cc config export [--machine] [--json] [--mask-secrets]
cc config doctor
cc env                    # eval "$(cc env)" to hydrate shell
cc env --json
cc env --include-secrets

# paths.* — well-known directory paths
cc config set paths.shared_docs /path/to/docs
cc config set paths.knowledge_repo /path/to/knowledge

# refs.* — named references surfaced to main session at turn 1
cc config set refs.project_board https://...
cc config set refs.design_system /path/to/tokens
```

## Docs (Live Docs)

```bash
cc docs resolve <pkg> [--lang js|npm|python|pip] [--json]
cc docs get <pkg> [--topic TOPIC] [--lang LANG] [--source auto|local|fetch] [--refresh] [--json]
cc docs search <pkg> <query> [--lang LANG] [--json]
cc docs sources [--json]
cc docs cache --status [--json]
cc docs cache --clear [--json]
```

**Source order:** `local` (installed package on disk, offline) → `fetch` (network, requires `cc[fetch]` extra).
**Config keys:** `docs.source_order`, `docs.cache_ttl_hours` (default 168), `docs.cache_dir`, `docs.context7_endpoint` (reserved).
**Note:** Context7 is not included at this release; the `SourceBackend` seam accepts it as a future drop-in.

## MCP Shim

```bash
cc mcp serve              # start MCP server on stdio
cc mcp config             # print .mcp.json snippet
```

## Diagnostics

```bash
cc doctor
cc --version
```

---

## Agent Preamble Pattern

Add this as the first shell step in any agent to hydrate config into the environment:

```bash
eval "$(cc env)"
```

## Common Patterns

```bash
# Store a decision
cc memory store --type decision --tags auth "Use JWT with 1h expiry; refresh tokens stored in DB"

# Search before storing to avoid duplicates
cc memory search "JWT" && cc memory store --type decision "..."

# Get skill content for @include
cc skill get stride-dread

# Get skill path for native @include
cc skill path python-idioms
# → /path/.claude/skills/python-idioms/SKILL.md

# Check config health before starting work
cc config doctor

# Migrate legacy memory on first use
cc memory migrate --from-global --dry-run   # preview
cc memory migrate --from-global             # execute
```
