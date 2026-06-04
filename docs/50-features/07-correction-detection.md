# Correction Detection and Reflection

**Diátaxis mode:** Reference

This page documents the surviving mechanism for capturing and acting on user corrections after the MCP-server era. The MCP `correction_detect` tool and its associated Node.js server were removed in the v5.1.0 CLI migration. What remains is the `/reflect` command and the `cc memory` CLI.

---

## What Was Removed

The MCP-era correction detection system included a `correction_detect` tool (TypeScript, in `mcp-servers/copilot-memory`), a SQLite `corrections` table, and six correction-specific MCP tools (`correction_list`, `correction_update`, `correction_route`, `correction_apply`, `correction_stats`). These are no longer active. The `mcp-servers/copilot-memory/` directory still exists as a legacy artifact but is not wired into any active session.

---

## What Exists Now

### /reflect Command

The `/reflect` command at `.claude/commands/reflect.md` is the surviving mechanism for periodic review of session context, decisions, and lessons.

**Usage:**

```
/reflect
```

Run `/reflect` at the end of a work session to review decisions made, surface gaps or errors in reasoning, and store corrections as memory entries.

### cc memory — Storing Corrections Manually

When a user identifies that an agent made an error or a decision needs revision, store the correction directly via the memory CLI:

```bash
# Store a lesson (preferred type for "we got this wrong")
cc memory store --type lesson "Correction: use async/await instead of callbacks in Express middleware. Previous guidance was wrong."

# Store a context correction
cc memory store --type context "Project uses Yarn workspaces, not npm — correction to earlier assumption."
```

**Memory types for corrections:**

| Memory Type | When to Use |
|-------------|-------------|
| `lesson` | Process or technique that was wrong and is now corrected |
| `context` | Factual correction about the project, codebase, or environment |
| `decision` | Revised architectural or design decision |
| `reference` | Corrected external fact (API endpoint, library version, etc.) |

---

## Workflow: Capturing a Correction

1. User identifies an error in agent output during a session.
2. User states the correction conversationally.
3. Agent (or user directly) stores it via `cc memory store --type lesson "..."`.
4. At session end, run `/reflect` to review stored context and flag anything missed.
5. Next session: `cc memory search "<topic>"` retrieves the correction before work begins.

---

## Search and Retrieval

Memory is FTS5 keyword search — not semantic or vector search.

```bash
# Find all corrections on a topic
cc memory search "async await"

# List recent lessons
cc memory list --type lesson --limit 10
```

---

## What /reflect Does Not Do

- It does not automatically detect patterns in user messages (the `correction_detect` pattern-matching engine was MCP-era and is removed).
- It does not maintain a pending/approved/rejected queue.
- It does not route corrections to skill or agent files automatically.

If you need to update a skill based on a correction, edit the SKILL.md file directly or delegate to `@agent-me`.

---

## Related Documentation

- [Memory Copilot FTS5 Search](./13-memory-fts5.md)
- [Skills Authoring Guide](../30-operations/06-skills-authoring-guide.md)
