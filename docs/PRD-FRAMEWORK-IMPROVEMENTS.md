# PRD: Claude Copilot Framework Improvements

**Version:** 1.0
**Status:** Draft
**Created:** 2025-12-29
**Owner:** @pabs

---

## Executive Summary

This PRD outlines improvements to the Claude Copilot framework based on competitive analysis of:
1. Alex's Claude Code Customization Guide (blog post)
2. claude-howto repository (633 GitHub stars)
3. Internal agent analysis (TA, SD, UXD, QA)

**Core Insight:** Claude Copilot has superior infrastructure (MCP servers, extensions, protocol) but inferior onboarding. claude-howto succeeds because it meets developers where they are with multiple entry points.

**Goal:** Adopt claude-howto's documentation patterns while preserving our infrastructure advantages.

---

## Problem Statement

### Current State
- Setup requires understanding 4 pillars before seeing value
- Documentation assumes full framework adoption
- No quick-start path for individual developers
- Agent files are 200+ lines (vs 60 in claude-howto)
- No decision matrices for "when to use what"
- Extension system is undiscoverable

### Evidence
- claude-howto has 633 stars with simpler approach
- Article emphasizes "zero setup" as key benefit
- Agent analysis identified 8 friction points in onboarding

### Impact
- Potential users abandon before experiencing value
- Teams miss extension system (biggest differentiator)
- Solo developers don't see path to team adoption

---

## Goals & Success Metrics

### Goals
1. Reduce time-to-first-value from ~30 min to ~5 min
2. Create multiple entry points (15 min / 1 hour / weekend)
3. Surface extension system during onboarding
4. Match claude-howto documentation quality
5. Simplify agent definitions without losing capability

### Success Metrics
| Metric | Current | Target |
|--------|---------|--------|
| Setup steps to first value | 8 | 3 |
| Documentation files | 15 | 25+ |
| Agent file length | ~200 lines | ~60 lines |
| Decision matrices | 0 | 5+ |
| Quick-start paths | 0 | 3 |

---

## Solution Overview

### Phase 1: Documentation Architecture
Create documentation that mirrors claude-howto's successful patterns:
- QUICK-REFERENCE.md (one-page cheat sheet)
- LEARNING-ROADMAP.md (numbered learning path)
- Decision matrices in existing docs
- Mermaid diagrams for visual learning

### Phase 2: Onboarding Simplification
Reduce friction in getting started:
- Unified /setup-copilot command
- 15-minute quick-start path (memory only)
- Template variables (no manual path editing)
- Progressive disclosure of features

### Phase 3: Framework Enhancements
Technical improvements for better DX:
- Skills auto-discovery (match native behavior)
- /memory command for transparency
- /extensions command for discoverability
- Smoke test validation suite

### Phase 4: Agent Simplification
Reduce agent complexity while preserving routing:
- Slim agents to ~60 lines
- Focus on purpose, not boilerplate
- Add example outputs
- Keep routing in protocol, not agents

---

## Detailed Requirements

### P0: Must Have

#### DOC-1: Quick Reference Card
**Description:** One-page cheat sheet for all Claude Copilot features
**Acceptance Criteria:**
- Single markdown file, printable
- Feature → Command → Example format
- Decision matrix: "I want to..." → use this
- Installation commands for each component

#### DOC-2: Learning Roadmap
**Description:** Numbered learning path from beginner to advanced
**Acceptance Criteria:**
- 5 milestones with clear progression
- Multiple quick-start paths (15 min, 1 hour, weekend)
- Success criteria for each milestone
- Mermaid diagram showing learning flow

#### DOC-3: Decision Matrices
**Description:** "When to use what" tables throughout docs
**Acceptance Criteria:**
- Feature comparison table in USER-JOURNEY.md
- Agent selection matrix in AGENTS.md
- Memory vs Skills vs Commands distinction
- Use case → recommended approach mapping

#### SETUP-1: Unified Setup Command
**Description:** Single /setup-copilot that auto-detects context
**Acceptance Criteria:**
- Detects if running from ~/.claude/copilot (machine setup)
- Detects if project already configured (update mode)
- Otherwise runs project setup
- No directory switching required

### P1: Should Have

#### SETUP-2: 15-Minute Quick Start
**Description:** Memory-only setup for immediate value
**Acceptance Criteria:**
- Single command installs memory only
- No agents, skills, or extensions
- /continue works immediately
- Clear upgrade path to full framework

#### SETUP-3: Template Variables
**Description:** Auto-inject paths in .mcp.json
**Acceptance Criteria:**
- $HOME expansion in templates
- $PROJECT_PATH expansion
- No manual editing of absolute paths
- Works on macOS and Linux

#### CMD-1: /memory Command
**Description:** Memory transparency dashboard
**Acceptance Criteria:**
- Shows current initiative status
- Lists recent memories stored
- Shows key files tracked
- Displays next session resume info

#### CMD-2: /extensions Command
**Description:** Extension system visibility
**Acceptance Criteria:**
- Shows global knowledge repo status
- Shows project knowledge repo status
- Lists active extensions
- Explains extension types

### P2: Nice to Have

#### AGENT-1: Simplified Agent Format
**Description:** Reduce agent files to ~60 lines
**Acceptance Criteria:**
- Keep: name, description, tools, model, identity, core behaviors
- Remove: verbose decision authority (move to protocol)
- Remove: extensive output format templates
- Add: example output for clarity

#### SKILLS-1: Auto-Discovery
**Description:** Skills load without manifest
**Acceptance Criteria:**
- Scans .claude/skills/ automatically
- Validates SKILL.md frontmatter
- Falls back gracefully on errors
- Supplements (doesn't replace) manifest

#### QA-1: Smoke Test Suite
**Description:** Validation scripts for framework
**Acceptance Criteria:**
- Tests each MCP server connectivity
- Tests agent file validity
- Tests extension resolution
- Runs in < 60 seconds

---

## Non-Goals

1. **Replace claude-howto** - We complement, not compete
2. **Simplify infrastructure** - MCP servers stay
3. **Remove protocol** - Agent-first routing stays
4. **Eliminate extensions** - Two-tier resolution stays
5. **Time estimates** - Per our policy, no timelines

---

## Technical Approach

### Documentation
- Create new files in /docs/
- Update existing files with matrices
- Add Mermaid diagrams inline
- Follow claude-howto formatting patterns

### Commands
- New commands in /.claude/commands/
- Bash scripts for template processing
- Environment variable detection

### Agent Changes
- Edit files in /.claude/agents/
- Extract routing to protocol
- Preserve functionality

### MCP Changes
- Modify skills-copilot for auto-discovery
- No changes to memory-copilot

---

## Dependencies

| Dependency | Required For | Status |
|------------|--------------|--------|
| claude-howto reference | Documentation patterns | Cloned to docs/ |
| Smoke tests | QA-1 | Created by QA agent |
| Memory Copilot | SETUP-1, SETUP-2 | Existing |
| Skills Copilot | SKILLS-1 | Existing |

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Breaking existing setups | Medium | High | Version templates, test upgrades |
| Documentation drift | Medium | Medium | Single source of truth principle |
| Agent simplification loses capability | Low | High | Test each agent after changes |
| Auto-discovery performance | Low | Medium | Cache discovered skills |

---

## Implementation Plan

### Phase 1: Documentation (P0 items)
- DOC-1: Quick Reference
- DOC-2: Learning Roadmap
- DOC-3: Decision Matrices

### Phase 2: Onboarding (P1 items)
- SETUP-1: Unified Setup
- SETUP-2: Quick Start
- SETUP-3: Template Variables

### Phase 3: Commands (P1 items)
- CMD-1: /memory
- CMD-2: /extensions

### Phase 4: Framework (P2 items)
- AGENT-1: Simplification
- SKILLS-1: Auto-Discovery
- QA-1: Smoke Tests

---

## Appendix

### Research Sources
1. **Alex's Article:** https://alexop.dev/posts/claude-code-customization-guide-claudemd-skills-subagents/
2. **claude-howto:** https://github.com/luongnv89/claude-howto (cloned to docs/claude-howto-reference/)
3. **Agent Analysis:** TA, SD, UXD, QA agents invoked 2025-12-29

### Key Files
- `/docs/PRD-FRAMEWORK-IMPROVEMENTS.md` - This document
- Task breakdown tracked in Task Copilot (use `task_list()` to view)
- `/docs/claude-howto-reference/` - Competitive reference
- `/docs/qa/` - Smoke test suite (created by QA agent)

### Agent Routing for Implementation
| Task Type | Agent | Rationale |
|-----------|-------|-----------|
| Documentation | @agent-doc | Technical writing |
| Commands | @agent-me | Code implementation |
| UX decisions | @agent-uxd | Interaction design |
| Agent changes | @agent-ta | Architecture decisions |
| Testing | @agent-qa | Validation |
