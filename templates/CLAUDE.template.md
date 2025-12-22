# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

## Project Overview

**Name:** [PROJECT_NAME]
**Description:** [PROJECT_DESCRIPTION]
**Stack:** [TECH_STACK]

---

## Claude Copilot

This project uses [Claude Copilot](https://github.com/Everyone-Needs-A-Copilot/claude-copilot) for AI-enabled development.

### Commands

| Command | Purpose |
|---------|---------|
| `/protocol` | Start fresh work with Agent-First Protocol |
| `/continue` | Resume previous work via Memory Copilot |

### Memory Tools

| Tool | Purpose |
|------|---------|
| `initiative_get` | Retrieve current initiative |
| `initiative_start` | Begin new initiative |
| `initiative_update` | Update progress, decisions, lessons |
| `initiative_complete` | Archive completed initiative |
| `memory_store` | Store decisions, lessons, context |
| `memory_search` | Semantic search across memories |

### Agents

| Agent | Name | Domain |
|-------|------|--------|
| `me` | Engineer | Code implementation |
| `ta` | Tech Architect | System design |
| `qa` | QA Engineer | Testing |
| `sec` | Security | Security review |
| `doc` | Documentation | Technical writing |
| `do` | DevOps | CI/CD, infrastructure |
| `sd` | Service Designer | Experience strategy |
| `uxd` | UX Designer | Interaction design |
| `uids` | UI Designer | Visual design |
| `uid` | UI Developer | UI implementation |
| `cw` | Copywriter | Content/copy |

---

## Session Management

### Starting Work

Use `/protocol` to activate the Agent-First Protocol.

### Resuming Work

Use `/continue` to load context from Memory Copilot.

### End of Session

Call `initiative_update` with:

| Field | Content |
|-------|---------|
| `completed` | Tasks finished |
| `inProgress` | Current state |
| `resumeInstructions` | Next steps |
| `lessons` | Insights gained |
| `decisions` | Choices made |
| `keyFiles` | Important files touched |

---

## Project-Specific Rules

[ADD YOUR PROJECT-SPECIFIC RULES HERE]

Examples:
- Coding conventions
- Testing requirements
- Deployment processes
- File organization
