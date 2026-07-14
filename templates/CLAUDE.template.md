# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

## Project Overview

**Name:** {{PROJECT_NAME}}
**Description:** {{PROJECT_DESCRIPTION}}
**Stack:** {{TECH_STACK}}

---

## Claude Copilot

This project uses [Claude Copilot](https://github.com/Everyone-Needs-A-Copilot/claude-copilot).

**Full documentation:** `~/.claude/copilot/README.md`

### Commands

| Command | Purpose |
|---------|---------|
| `/protocol` | Start fresh work with Agent-First Protocol |
| `/continue` | Resume previous work via Memory Copilot |
| `/setup-project` | Initialize Claude Copilot in a new project |
| `/knowledge-copilot` | Build or link shared knowledge repository |

### Capabilities

| Capability | Tools | Purpose |
|------------|-------|---------|
| **Memory** | `cc memory` | Persist decisions, lessons, progress across sessions |
| **Agents** | 13 framework agents + kc (setup-only) | Expert guidance routed by task type — roster + domains: Task tool at delegation time, or `~/.claude/copilot/README.md#your-team` |
| **Knowledge** | `knowledge_search`, `knowledge_get` | Search company/product documentation |
| **Skills** | `cc skill search`, `cc skill get` | Load expertise on demand |

### Configuration

| Component | Status |
|-----------|--------|
| Memory | Workspace: `{{WORKSPACE_ID}}` |
| Knowledge | {{KNOWLEDGE_STATUS}} |
| Skills | Local: `.claude/skills/` {{EXTERNAL_SKILLS_STATUS}} |

---

## Session Management

**Start:** `/protocol` - Activates Agent-First Protocol

**Resume:** `/continue` - Loads from Memory Copilot

**End:** Run `cc memory store` to persist key decisions and lessons from the session

---

## Knowledge Copilot

Knowledge Copilot is the single source of truth for brand, voice, offerings, and processes. Consult it first — never invent or duplicate this knowledge.

```bash
eval "$(cc env)"   # hydrates CC_KNOWLEDGE_REPO
```

Domain paths under `$CC_KNOWLEDGE_REPO` (read on first use, not needed for routing): `$CC_KNOWLEDGE_REPO/docs/00-knowledge-copilot/02-consumption-contract.md`

---

## Project-Specific Rules

### No Time Estimates
All plans, roadmaps, and task breakdowns MUST omit time estimates. Use phases, priorities, complexity ratings, and dependencies instead of dates or durations. See `~/.claude/copilot/CLAUDE.md` for full policy.

{{PROJECT_RULES}}
