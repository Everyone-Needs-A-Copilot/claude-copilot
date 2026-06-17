# Memory Copilot: Full-Text (FTS5) Search

**Diátaxis mode:** Explanation + Reference

`cc memory` is **full-text keyword search**, not semantic/vector search. Understanding this distinction prevents silent retrieval failures.

---

## What It Is

Memory Copilot indexes entries in a SQLite FTS5 (Full-Text Search version 5) table. Queries are ranked by BM25 — a standard term-frequency × inverse-document-frequency scoring algorithm. The index tokenizes on whitespace and punctuation; it does not use word embeddings, cosine similarity, or any neural model.

**What this means in practice:**

| Query | Will match | Will NOT match |
|-------|-----------|----------------|
| `"WAL SQLite"` | entries containing "WAL" and/or "SQLite" | entries about "journal mode database concurrency" with no "WAL" token |
| `"authentication"` | entries with "authentication" | entries with only "auth" or "login" or "OAuth" |
| `"token budget"` | entries with both tokens | entries about "context limits" that never say "token" |

**Rule of thumb:** use the exact words you expect to appear in the stored entry, not a paraphrase or higher-level concept.

---

## Entry Types

Every entry is tagged with one of the following types, committed as a Markdown file to `.claude/memory/entries/`:

| Type | Use for |
|------|---------|
| `decision` | Architectural or design choices with rationale |
| `context` | Session context, background, style preferences |
| `lesson` | Things learned from mistakes or debugging |
| `reference` | External facts, links, canonical values to recall |

The type is part of the filename (`<uuid>-decision.md`, etc.) and is indexed. Filtering by type narrows recall precision.

---

## Storage Layout

```
.claude/memory/
  entries/
    <uuid>-decision.md     ← committed to the repo
    <uuid>-lesson.md
    ...
  memory.db                ← local SQLite FTS5 index (gitignored)
```

The `.md` files travel with the repo (persistent across machines). The `.db` index is local. If the index is missing or stale, `memory_search` falls back to case-insensitive substring scan of all `.md` files before returning no results.

Rebuild the index at any time:

```bash
cc memory index --rebuild
```

---

## How Agents Store and Recall

### Storing

```bash
# CLI
cc memory store --type decision "Use WAL mode for SQLite writes"

# python3 block (cc.api)
from cc.api import memory_store
memory_store(entry_type="decision", content="Use WAL mode for SQLite writes",
             tags=["sqlite", "performance"])
```

Agent preambles run `eval "$(cc env)"` to hydrate `CC_SHARED_DOCS` and other paths, then can call `cc memory store` at any point in the workflow.

### Recalling

```bash
# CLI
cc memory search "WAL SQLite"

# python3 block (cc.api)
from cc.api import memory_search
hits = memory_search("WAL SQLite")
```

Recall is wired into agent preambles: `cc memory search "<query>"` runs before starting work, loading relevant decisions and lessons into context.

---

## Search Behaviour: FTS5 + Fallback

`memory_search` (both CLI and `cc.api`) follows this algorithm:

1. Try FTS5 index (BM25 ranking).
2. If the DB does not exist **or** returns no results: fall back to case-insensitive substring scan across all `.md` files.

The fallback ensures partial-index gaps (new entries not yet indexed, or a missing `.db`) never silently hide results. It does mean that an empty FTS5 result set triggers a full file scan — acceptable at typical memory sizes (<1000 entries).

---

## Pluggable SearchBackend Seam (Future)

The search layer is designed around an abstract `SearchBackend` protocol. The current implementation is `FTS5Backend`. An `EmbeddingsBackend` that wraps a local embedding model is a documented future option — it would allow semantic queries — but it is **not implemented** and is **opt-in** when it ships.

Do not document or depend on embedding-based search in current workflows. Use exact-keyword queries.

---

## Writing Good Entries for Recall

Because recall is keyword-based, entry quality directly affects search success:

**Include the specific terms you will search for:**

```markdown
# Good
Decision: Use WAL journal mode for SQLite. Prevents SQLITE_BUSY when readers
and writers overlap. Configured via PRAGMA journal_mode=WAL.

# Poor (will not match a search for "WAL")
Decision: Chose the non-blocking journal strategy for the embedded database.
```

**Tag with relevant tokens:**

```bash
cc memory store --type decision --tags sqlite,performance \
  "Use WAL mode for SQLite — prevents reader/writer contention"
```

Tags are indexed separately and can narrow searches.

**Use the right entry type:**

- Decisions that future agents should follow → `decision`
- Things that went wrong and why → `lesson`
- External URLs, canonical values → `reference`
- Transient session context → `context`

---

## CLI Quick Reference

```bash
cc memory store --type <type> "<content>"   # Store a new entry
cc memory search "<keywords>"               # FTS5 search
cc memory list                              # List all entries (newest first)
cc memory list --type decision              # Filter by type
cc memory get <id-prefix>                  # Retrieve a specific entry
cc memory index --rebuild                  # Rebuild FTS5 index from .md files
```

---

## See Also

- `tools/cc/README.md` — full `cc.api` and CLI reference
- [Code Execution Path](./12-code-execution-path.md) — how to call `memory_store` / `memory_search` inside a python3 block
- [Goal-Driven Agents](./04-goal-driven-agents.md) — where memory recall fits in the agent preamble
