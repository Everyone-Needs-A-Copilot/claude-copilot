# Reflect Command

Review the memory captured this session — decisions, lessons, and context — surface
gaps or errors in reasoning, and store any corrections as memory entries.

## Overview

`/reflect` is the end-of-session review step on top of the `cc memory` CLI. It
replaces the MCP-era correction-detection system (the `correction_*` tools and the
pending/approved/rejected queue were removed in the CLI migration).

`/reflect` does **not**:
- Auto-detect correction patterns in user messages (the MCP pattern engine is gone).
- Maintain a pending/approved/rejected queue.
- Route corrections to skill or agent files automatically.

To update a skill or agent from a correction, edit the `SKILL.md` / agent file
directly or delegate to `@agent-me`.

## Arguments

- No arguments: review recent `lesson`, `decision`, and `context` entries.
- `--type <lesson|decision|context|reference>`: review only one entry type.
- `<search terms>`: review entries matching a topic (uses `cc memory search`).

## Step 1: Gather Memory

```bash
# Default review: recent lessons, decisions, and context (project scope)
cc memory list --type lesson --json
cc memory list --type decision --json
cc memory list --type context --json

# Single type (when --type is passed)
cc memory list --type <type> --json

# Topic review (when search terms are passed)
cc memory search "<terms>" --json
```

Read fuller content for any entry by UUID (full or prefix match):

```bash
cc memory get <entry-id>
```

## Step 2: Present a Review Dashboard

Format the gathered entries as a compact review (newest first; truncate long
content to ~100 chars). Example:

```
## Session Reflection

**Stored this session:** 3 lessons · 2 decisions · 1 context

### Lessons
- [a1b2c3] "Use async/await instead of callbacks in Express middleware…"
- [d4e5f6] "Yarn workspaces, not npm — earlier assumption was wrong"

### Decisions
- [g7h8i9] "Adopt FTS5 keyword search; defer semantic embeddings"

### Context
- [j0k1l2] "Auth service runs behind Cloudflare Access in staging"
```

## Step 3: Reflect

Review the session against what was stored and surface:
- **Gaps** — decisions made but not recorded as `decision` entries.
- **Errors** — guidance given that later proved wrong (candidate `lesson` entries).
- **Stale entries** — memory that is now outdated or contradicted.

Present these as a short list and ask the user which to store, revise, or remove.

## Step 4: Store Corrections

Persist confirmed corrections as memory entries (pick the type by intent):

```bash
# Process/technique that was wrong and is now corrected
cc memory store --type lesson "Correction: <what was wrong> → <correct guidance>."

# Factual correction about the project, codebase, or environment
cc memory store --type context "<corrected fact about the project>."

# Revised architectural or design decision
cc memory store --type decision "<revised decision and rationale>."

# Corrected external fact (API endpoint, library version, etc.)
cc memory store --type reference "<corrected reference fact>."
```

| Memory Type | When to Use |
|-------------|-------------|
| `lesson` | Process or technique that was wrong and is now corrected |
| `context` | Factual correction about the project, codebase, or environment |
| `decision` | Revised architectural or design decision |
| `reference` | Corrected external fact (API endpoint, library version, etc.) |

## Step 5: Remove Stale Entries

Delete memory that is outdated or was stored in error:

```bash
cc memory delete <entry-id>
```

## Edge Cases

**No memory stored this session:**

```
## Session Reflection

No memory entries found for review.

Tip: store decisions and lessons as you work with
`cc memory store --type decision "…"` so /reflect can review them.
```

## Retrieval Next Session

Stored corrections surface in the next session two ways:
- `type:reference` (and project context) entries are injected at turn 1 by the
  session-start hook.
- `cc memory search "<topic>"` retrieves any entry before work begins.

## Related Documentation

- [Correction Detection and Reflection](../../docs/50-features/07-correction-detection.md)
- [Memory Copilot FTS5 Search](../../docs/50-features/13-memory-fts5.md)

## End

Present the review dashboard, then guide the user through storing or removing entries.
