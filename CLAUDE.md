# CLAUDE.md

This file provides guidance to Claude Code when working with the Claude-Copilot framework.

## Overview

Claude-Copilot is an AI-enabled development framework providing 11 specialized agents for software development.

## Agents

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

## Agent Routing

Agents route to each other based on expertise:

| From | Routes To | When |
|------|-----------|------|
| Any | `ta` | Architecture decisions |
| Any | `sec` | Security concerns |
| `sd` | `uxd` | Interaction design needed |
| `uxd` | `uids` | Visual design needed |
| `uids` | `uid` | Implementation needed |
| Any | `me` | Code implementation |
| Any | `qa` | Testing needed |
| Any | `doc` | Documentation needed |

## Extension System

This framework supports extensions via knowledge repositories.

### Extension Types

| Type | Behavior |
|------|----------|
| `override` | Replaces base agent |
| `extension` | Adds to base agent |
| `skills` | Injects additional skills |

### Detecting Extensions

Check for `knowledge-manifest.json` in:
- Project root
- `docs/shared/`
- Parent directories

### Applying Extensions

1. Load `knowledge-manifest.json`
2. For each extension, check if required skills are available
3. Apply based on extension type
4. Fall back to base agent if skills unavailable

## File Locations

| Content | Location |
|---------|----------|
| Base agents | `.claude/agents/` |
| Extension spec | `docs/EXTENSION-SPEC.md` |
| Manifest schema | `docs/knowledge-manifest-schema.json` |

## Development Guidelines

### When Modifying Agents

- Keep base agents generic (no company-specific content)
- Use industry-standard methodologies
- Include routing to other agents
- Document decision authority

### When Adding Skills

- Skills go in `.claude/skills/`
- Keep skills focused and standalone
- Document when each skill should be used

## Commands

| Task | Command |
|------|---------|
| Copy to project | `cp -r .claude /path/to/project/` |
| Validate agents | Check each agent has required sections |

## Required Agent Sections

Every agent must include:

1. **Frontmatter** - name, description, tools, model
2. **Identity** - Role, Mission, Success criteria
3. **Core Behaviors** - Always do / Never do
4. **Output Formats** - Templates for deliverables
5. **Quality Gates** - Checklists
6. **Route To Other Agent** - When to hand off
7. **Decision Authority** - Autonomous vs escalate
