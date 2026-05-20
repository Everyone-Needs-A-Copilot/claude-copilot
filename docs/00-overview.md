# Claude Copilot Overview

**Diátaxis mode:** Tutorial (quick-start orientation)

Claude Copilot is an instruction layer for Claude Code. It gives you persistent memory, 8 specialized agents, on-demand skills, ephemeral task storage, and battle-tested workflows — entirely through markdown files and two CLI tools.

---

## What You Get

| Feature | Status | How |
|---------|--------|-----|
| **Persistent memory** | Enabled after setup | `cc memory` CLI + SQLite (FTS5 keyword search) |
| **8 specialist agents** | Enabled after setup | Markdown agent files in `.claude/agents/` |
| **On-demand skills** | Enabled after setup | `cc skill` CLI, local `.claude/skills/` |
| **Task management** | Enabled after setup | `tc` CLI (PRDs, tasks, work products) |
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

# Find a skill
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
| **Skills** | `cc skill` | On-demand best practices, code-checking scripts |
| **Tasks** | `tc` | PRDs, task tracking, agent work products |
| **Protocol** | `/protocol`, `/continue` | Consistent workflows, agent routing |

---

## The 8 Agents

| Agent | Domain |
|-------|--------|
| `ta` | Technical architecture — ADRs, system design |
| `me` | Engineering — implementation, bug fixes |
| `qa` | QA — test strategy, edge cases |
| `do` | DevOps — CI/CD, infrastructure |
| `doc` | Documentation — READMEs, API docs (Diátaxis) |
| `sd` | Service design — journey maps, user experience strategy |
| `design` | Interaction + visual design — flows, components, color, typography |
| `kc` | Knowledge Copilot setup (run `/knowledge-copilot`) |

> Security reviews: load the `security/stride-dread` skill instead of using a dedicated agent.

---

## What's Next

- [User Journey](./01-getting-started/01-user-journey.md) — full setup walkthrough
- [Architecture Overview](./10-architecture/00-overview.md) — how the five pillars fit together
- [Agents](./10-architecture/01-agents.md) — meet the 8 specialists
- [Configuration](./20-configuration/01-configuration.md) — cc config, references registry
- [Working Protocol](./30-operations/01-working-protocol.md) — the Agent-First Protocol
