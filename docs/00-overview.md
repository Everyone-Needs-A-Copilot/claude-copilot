# Claude Copilot Overview

**Diátaxis mode:** Tutorial (quick-start orientation)

Claude Copilot is an instruction layer for Claude Code. It gives you persistent memory, 16 specialist agents, on-demand skills, ephemeral task storage, and battle-tested workflows — entirely through markdown files and two CLI tools.

---

## What You Get

| Feature | Status | How |
|---------|--------|-----|
| **Persistent memory** | Enabled after setup | `cc memory` CLI + SQLite ([FTS5](./70-reference/05-glossary.md#fts5) keyword search) |
| **16 specialist agents** | Enabled after setup | Markdown agent files in `.claude/agents/` |
| **Auto-firing skills** | Enabled after setup | Native auto-fire from skill `description`; `cc skill` CLI as fallback |
| **Task management** | Enabled after setup | `tc` CLI ([PRD](./70-reference/05-glossary.md#prd)s, tasks, [WP](./70-reference/05-glossary.md#wp-work-product)s) |
| **`/protocol` command** | Enabled after setup | Agent-first workflow enforcement |
| **`/continue` command** | Enabled after setup | Resume previous work from memory |
| **Knowledge repository** | Optional | Git-managed, shared via `~/.claude/knowledge` |

---

## Setup (2 Steps)

### Step 1: Machine Setup (once)

```bash
cd ~/.claude/copilot
claude
```

Then run:
```
/setup
```

This installs the `cc` and `tc` CLIs and copies global commands.

### Step 2: Project Setup (per project)

```bash
cd ~/your-project
claude
/setup-project
```

This creates `CLAUDE.md`, `.claude/agents/`, `.claude/commands/`, and `.claude/skills/`.

---

## Daily Usage

```bash
# Start fresh work
/protocol

# Resume previous work
/continue

# Search memory
cc memory search "authentication"

# Find a skill explicitly (fallback; skills auto-fire from their description)
cc skill search "docker"
cc skill get docker-patterns

# Track tasks
tc task list
tc progress
```

---

## The Five Pillars

| Pillar | Tool | Best For |
|--------|------|----------|
| **Memory** | `cc memory` | Decisions, lessons, cross-session context |
| **Agents** | `/protocol` | Expert tasks: architecture, testing, docs, design |
| **Skills** | Auto-fire + `cc skill` | Best practices auto-surface; code-bearing skills run executable scripts |
| **Tasks** | `tc` | PRDs, task tracking, agent work products |
| **Protocol** | `/protocol`, `/continue` | Consistent workflows, agent routing |

---

## The 16 Agents

**Core:**

| Agent | Domain |
|-------|--------|
| `ta` | Technical architecture — [ADR](./70-reference/05-glossary.md#adr)s, system design |
| `me` | Engineering — implementation, bug fixes |
| `qa` | QA — test strategy, edge cases |
| `do` | DevOps — CI/CD, infrastructure |
| `doc` | Documentation — READMEs, API docs (Diátaxis) |
| `sd` | Service design — journey maps, user experience strategy |
| `sec` | Security — STRIDE/DREAD threat modeling |
| `kc` | Knowledge Copilot setup (run `/knowledge-copilot`) |

**Design chain (sd → uxd → uids → uid → ta → me):**

| Agent | Domain |
|-------|--------|
| `uxd` | UX Designer — interaction flows, task design |
| `uids` | UI Design System — visual tokens, color, typography |
| `uid` | UI Developer — component implementation specs |

**Specialist branches:**

| Agent | Domain |
|-------|--------|
| `ind` | Industrial Designer — object-level essentialism (upstream of uxd) |
| `cco` | Creative Director — brand strategy, creative direction |
| `cw` | Copywriter — copy execution, messaging, microcopy |
| `cs` | Customer Success — support patterns, retention (business advisory) |
| `cpa` | CPA / Financial — tax implications, financial modeling (business advisory) |

---

## What's Next

- [User Journey](./01-getting-started/01-user-journey.md) — full setup walkthrough
- [Architecture Overview](./10-architecture/00-overview.md) — how the five pillars fit together
- [Agents](./10-architecture/01-agents.md) — meet the 16 specialists
- [Configuration](./20-configuration/01-configuration.md) — cc config, references registry
- [Working Protocol](./30-operations/01-working-protocol.md) — the Agent-First Protocol
- [Glossary](./70-reference/05-glossary.md) — FTS5, BM25, ADR, PRD, WP, L1/L2/L3, agent codes, and more
