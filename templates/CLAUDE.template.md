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
| **Agents** | 16 specialists via `/protocol` | Expert guidance routed by task type |
| **Knowledge** | `knowledge_search`, `knowledge_get` | Search company/product documentation |
| **Skills** | `cc skill search`, `cc skill get` | Load expertise on demand |

### Agents

| Agent | Domain |
|-------|--------|
| `ta` | Tech Architect - system design, task breakdown |
| `me` | Engineer - code implementation |
| `qa` | QA - testing, edge cases |
| `sec` | Security - vulnerabilities, OWASP |
| `doc` | Documentation - technical writing |
| `do` | DevOps - CI/CD, infrastructure |
| `sd` | Service Designer - customer journeys |
| `uxd` | UX Designer - interaction design |
| `uids` | UI Designer - visual design |
| `uid` | UI Developer - component implementation |
| `cw` | Copywriter - microcopy, voice |
| `cco` | Creative Director - brand strategy, art direction, creative concepts |
| `ind` | Industrial Designer - essentialism, reduction, product-as-object |
| `cs` | Sales Advisor - sales strategy, pipeline, deal architecture |
| `kc` | Knowledge Copilot - shared knowledge setup |
| `cpa` | CPA Copilot - tax strategy, financial modeling, hiring economics |

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

## Project-Specific Rules

### No Time Estimates
All plans, roadmaps, and task breakdowns MUST omit time estimates. Use phases, priorities, complexity ratings, and dependencies instead of dates or durations. See `~/.claude/copilot/CLAUDE.md` for full policy.

{{PROJECT_RULES}}
