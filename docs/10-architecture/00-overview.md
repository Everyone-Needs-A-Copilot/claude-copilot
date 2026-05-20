# Claude Copilot Architecture

Five-pillar framework: persistent memory, expert agents, on-demand skills, ephemeral task storage, battle-tested workflows.

---

## System Overview

| Layer | Pillar | Component | Purpose |
|-------|--------|-----------|---------|
| Persistence | 1 | Memory Copilot | Cross-session context, decisions, lessons |
| Expertise | 2 | 8 Specialist Agents | Lean agents with on-demand skills |
| Knowledge | 3 | Skills (cc CLI) | On-demand skill loading via `cc skill search` / `cc skill get` |
| Tasks | 4 | Task Copilot | Ephemeral PRD, task, work product storage |
| Workflow | 5 | Protocol | /protocol and /continue commands |

### Data Flow

```
User Request → Protocol → Lean Agent → cc skill search → cc skill get → Execute → Store Work Product (tc wp store) → cc memory store
```

**Lean Agent Pattern:**
- Agent files are under 120 lines (workflow, routing, core behaviors)
- Shared boilerplate extracted to "Agent Shared Behaviors" in CLAUDE.md
- Domain expertise lives in skill files (200-500 lines each)
- Skills discovered by keyword match via `cc skill search "<query>"`
- Skills loaded on-demand via `cc skill get <name>` or native `@include`
- ~70% token reduction vs. monolithic agents

---

## Core Workflows

| Command | Flow | Result |
|---------|------|--------|
| `/protocol` | Classify request → Route to agent → Understand → Present findings → Get approval → Execute → Save to memory | Fresh work with agent-first approach |
| `/continue` | Load initiative → Present context → Resume work | Continue with full history |

---

## Agent Routing

### Understanding Phase

| Request Type | First Agent | Routes To | Finally |
|--------------|-------------|-----------|---------|
| Bug/Defect | qa | me (fix) | qa (verify) |
| Experience/UX | sd | design | ta → me |
| Technical | ta | me | qa |
| Architecture | ta | do (if infra) | me → qa |

### Cross-Cutting Concerns

| Concern | Routes To |
|---------|-----------|
| Security implications | Load `skills/security/stride-dread` |
| Documentation needed | doc |
| Testing required | qa |
| Deployment concerns | do |

### Current Agent Roster (8 agents + kc)

| Agent | Role |
|-------|------|
| `ta` | Technical architect — ADR/fitness functions |
| `me` | Engineer — Kent Beck simple design |
| `qa` | QA — Meszaros patterns |
| `do` | DevOps/infra — 12-Factor/SRE |
| `doc` | Documentation — Diátaxis |
| `sd` | Service design — IDEO methodology |
| `design` | Interaction/visual design — Nielsen + Rams + Atomic Design |
| `kc` | Knowledge copilot setup (run `/knowledge-copilot`) |

> Security reviews use the `security/stride-dread` skill, not a dedicated agent.

---

## Storage

### Memory Copilot (SQLite per project)

| Table | Key Fields |
|-------|------------|
| initiatives | title, status, completed[], inProgress[], decisions[], lessons[], keyFiles[], resumeInstructions |
| memories | type, content, tags[], content (full-text FTS5 keyword search) |
| sessions | initiative_id, started_at, summary |

Location: `~/.claude/memory/{workspace-id}/memory.db`

**Search:** Full-text keyword search (FTS5) with BM25 ranking. No embeddings or vector search — keyword matching only.

### Skills (cc CLI)

| Command | Purpose |
|---------|---------|
| `cc skill search "<query>"` | Discover skills by keyword (FTS5) |
| `cc skill get <name>` | Fetch a skill by name |
| `cc skill list` | List all available skills |
| `@include .claude/skills/NAME/SKILL.md` | Load directly in agent prompt (native) |

---

## Extension System

| Behavior | Effect |
|----------|--------|
| `override` | Replaces base agent |
| `extension` | Adds to base agent |
| `skills` | Injects additional skills |

Detected via `knowledge-manifest.json` in project or `docs/shared/`.

---

## Performance

| Component | Strategy | Token Savings |
|-----------|----------|---------------|
| Memory | Full-text keyword search (FTS5), relevant context only | ~80% |
| Skills | On-demand loading via cc CLI / @include | ~95% |
| Lean Agents | Minimal definitions + shared behaviors + external skills | ~70% |
| Protocol | Two simple commands | ~90% |
| Task Copilot | Work products stored externally | ~96% |

---

## Security

| Concern | Approach |
|---------|----------|
| Data isolation | Per-project SQLite databases |
| Secrets | Never stored in memory/skills |
| Trust levels | Local skills > cc config > API |
| Enforcement | Load `skills/security/stride-dread` for security reviews |

---

## Failure Modes

| Component Fails | Behavior | Impact |
|-----------------|----------|--------|
| Memory Copilot | New initiative, no history | Loss of context |
| Skills (all sources) | Agents work without skills | Less optimal |
| Skills (one source) | Falls back to next priority | Transparent |
| Specific Agent | Routes to alternative | Less specialized |

---

## System Boundaries

| Included | External |
|----------|----------|
| Memory persistence | Claude Code CLI |
| 8 lean agents with cc CLI skill loading | Git, project files |
| Skills loading (cc CLI / @include) | skills.sh API |
| Task storage (tc CLI) | PostgreSQL (optional org skills) |
| Protocol commands | |
