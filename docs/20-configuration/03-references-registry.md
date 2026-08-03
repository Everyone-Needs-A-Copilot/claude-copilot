# References Registry

**Diátaxis mode:** How-to + Reference

The references registry lets you store stable values — paths, URLs, IDs — once and have them injected automatically at the start of every Claude Code session. Agents and the protocol always know where to find shared docs, the knowledge repo, and any custom references you register.

---

## Why It Exists

Without it, every session either:
- Re-reads the same context from scratch (token waste), or
- Relies on the model to guess paths it has never seen (errors).

The registry solves this: store a value once, get it injected on turn 1.

---

## How It Works

At the start of every session, two hooks fire:

| Hook | When | What it injects |
|------|------|-----------------|
| `SessionStart` | On session open | Protocol guardrails + Known References block |
| `UserPromptSubmit` | On first user turn | Known References block (if session is new) |

Both hooks call `cc config export` and `cc memory list --type reference` to build a **Known References** block that looks like:

```
Known references (this session):
- shared_docs: /Users/you/Knowledge Copilot
- knowledge_repo: /Users/you/company-knowledge
- staging_url: https://staging.example.com
- [memory] CLI Copilot location: /Users/you/.claude/copilot
```

Agents see this block at the top of their context and can reference the values without asking the user.

---

## Registering References

### Standard Path Keys

Two paths get special treatment — they hydrate `CC_SHARED_DOCS` and `CC_KNOWLEDGE_REPO` environment variables (used by `eval "$(cc env)"` in agent preambles):

```bash
cc config set paths.shared_docs /path/to/shared/docs
cc config set paths.knowledge_repo /path/to/company-knowledge
```

### Arbitrary refs.* Keys

Register any stable value under a `refs.<name>` key:

```bash
cc config set refs.staging_url  https://staging.example.com
cc config set refs.company_wiki https://wiki.example.com
cc config set refs.design_system /path/to/design-system
cc config set refs.jira_project  PROJ
```

All `refs.*` keys are injected as named references at session start.

### Memory-Based References

Store reference-type entries in memory for values that change occasionally:

```bash
cc memory store --type reference "CLI Copilot location: /Users/you/.claude/copilot"
cc memory store --type reference "Primary database host: db.example.com:5432"
```

Memory references are included in the Known References block (first 5 entries).

---

## macOS Paths with Spaces

macOS paths often contain spaces (e.g., iCloud Drive, Google Drive). Always quote them when registering:

```bash
# Correct
cc config set paths.shared_docs "/Users/you/Library/Mobile Documents/com~apple~CloudDocs/Shared"
cc config set refs.team_drive "/Users/you/Google Drive/Team Files"

# The hook preserves internal spaces — only leading/trailing whitespace is stripped
```

---

## Inspecting Registered References

```bash
# View all configuration
cc config export

# View just refs
cc config export | grep refs

# Get a single value
cc config get paths.shared_docs --raw
cc config get refs.staging_url --raw

# View memory references
cc memory list --type reference
```

---

## What Gets Injected

The `UserPromptSubmit` hook injects on turn 1 of a new session. The `SessionStart` hook injects on every session open. Both inject the same Known References block.

**Priority of sources:**

1. `paths.shared_docs` → labeled `shared_docs`
2. `paths.knowledge_repo` → labeled `knowledge_repo`
3. All `refs.*` keys → labeled by name (e.g., `refs.staging_url` → `staging_url`)
4. `cc memory list --type reference` → labeled `[memory]` (first 5 entries)

**If no references are configured:** the Known References block is omitted entirely. The hooks never fail — they exit cleanly if `cc` is not in PATH.

---

## Session-Start Escape Hatch

To disable reference injection for a shell session:

```bash
export COPILOT_SESSION_START=off    # Skip SessionStart hook
export COPILOT_SESSION_CAP=off      # Skip UserPromptSubmit session-cap hook
```

---

## Examples

### Solo Developer Setup

```bash
cc config set paths.shared_docs ~/Documents/project-docs
cc config set refs.github_repo   git@github.com:you/project.git
```

### Team Setup

```bash
# Shared knowledge repo (cloned from GitHub)
cc config set paths.knowledge_repo ~/company-knowledge

# Shared resources
cc config set refs.design_system  https://design.example.com
cc config set refs.staging         https://staging.example.com
cc config set refs.jira            https://example.atlassian.net/browse/PROJ
```

### Updating a Reference

```bash
# Just run cc config set again — it overwrites
cc config set refs.staging https://new-staging.example.com
```

### Removing a Reference

```bash
# Set to empty string to clear
cc config set refs.old_key ""

# Or delete via the config file directly (~/.config/cc/config.json)
```

---

## Related

- [Configuration Guide](./01-configuration.md) — full cc config reference
- [SessionStart hook](../../.claude/hooks/session-start.sh) — injects on open
- [UserPromptSubmit hook](../../.claude/hooks/user-prompt-submit.sh) — injects on turn 1
- `cc memory store --type reference "<content>"` — add reference-type memory
