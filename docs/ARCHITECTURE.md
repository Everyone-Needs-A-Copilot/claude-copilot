# Claude Copilot Architecture

Five-pillar framework: persistent memory, expert agents, on-demand skills, ephemeral task storage, battle-tested workflows.

---

## System Overview

| Layer | Pillar | Component | Purpose |
|-------|--------|-----------|---------|
| Persistence | 1 | Memory Copilot | Cross-session context, decisions, lessons |
| Expertise | 2 | 12 Agents | Specialized roles with routing |
| Knowledge | 3 | Skills Copilot | On-demand skill loading |
| Tasks | 4 | Task Copilot | Ephemeral PRD, task, work product storage |
| Workflow | 5 | Protocol | /protocol and /continue commands |

### Data Flow

```
User Request → Protocol → Agent → Skills + Memory → Output → Memory Update
```

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
| Experience | sd + uxd | uids | uid |
| Technical | ta | sec (if security) | me |
| Architecture | ta | sec + do | me |

### Cross-Cutting Concerns

| Concern | Routes To |
|---------|-----------|
| Security implications | sec |
| Documentation needed | doc |
| Testing required | qa |
| Deployment concerns | do |

---

## Storage

### Memory Copilot (SQLite per project)

| Table | Key Fields |
|-------|------------|
| initiatives | title, status, completed[], inProgress[], decisions[], lessons[], keyFiles[], resumeInstructions |
| memories | type, content, tags[], embedding (semantic search) |
| sessions | initiative_id, started_at, summary |

Location: `~/.claude/memory/{workspace-id}/memory.db`

### Skills Copilot (Priority Order)

| Source | Location | Purpose |
|--------|----------|---------|
| Local | `./.claude/skills/` | Project-specific |
| Cache | SQLite (7-day TTL) | Fast repeat access |
| Private DB | PostgreSQL | Organization skills |
| SkillsMP | API | 25,000+ public skills |

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
| Memory | Semantic search, relevant context only | ~80% |
| Skills | On-demand loading | ~95% |
| Agents | Specialized instructions | ~60% |
| Protocol | Two simple commands | ~90% |

---

## Security

| Concern | Approach |
|---------|----------|
| Data isolation | Per-project SQLite databases |
| Secrets | Never stored in memory/skills |
| Trust levels | Local > Private DB > Cache > API |
| Enforcement | sec agent reviews security concerns |

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
| 12 specialized agents | MCP SDK |
| Skills loading | Git, project files |
| Task storage | SkillsMP API, PostgreSQL |
| Protocol commands | |
