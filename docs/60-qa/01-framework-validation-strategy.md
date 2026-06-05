# Claude Copilot Framework Validation Strategy

**Version:** 1.0
**Date:** 2025-12-29
**Owner:** @agent-qa

## Overview

This document defines the complete validation strategy for the Claude Copilot framework. It includes smoke tests for rapid feedback, integration tests for component interaction, and manual scenarios for developer experience validation.

**Framework Components:**
- Memory Copilot (`cc memory` CLI, SQLite + FTS5 keyword search)
- Skills Copilot (`cc skill` CLI, auto-firing via description + local skills + knowledge repo)
- 16 Specialized Agents (ta, me, qa, do, doc, sd, uxd, uids, uid, sec, ind, cco, cw, cs, cpa, kc)
- Task Copilot (`tc` CLI, PRD/task/work-product storage)
- Protocol commands (/protocol, /continue, /setup-project, /update-project, /update-copilot, /knowledge-copilot)
- Extension system (override, extension, skills injection)

---

## Test Strategy

| Level | Focus | Tools | Execution |
|-------|-------|-------|-----------|
| **Smoke** | Each component works in isolation | Manual CLI (`cc`, `tc`) | Every build |
| **Integration** | Components work together | Custom test scripts | Every PR |
| **E2E** | Developer workflows succeed | Real Claude Code sessions | Weekly |
| **Regression** | Previous bugs don't return | Automated + manual | Every release |

---

## 1. Smoke Tests (Component Isolation)

> **Architecture note (v5.1.0+):** The `copilot-memory` and `skills-copilot` MCP Node.js servers have been replaced by the `cc` and `tc` CLIs. Smoke tests validate the CLI layer. The `mcp-servers/` directories (`copilot-memory`, `skills-copilot`) have since been removed from the repo entirely. Smoke tests validate the CLI layer.

### ST-01: cc CLI Availability

**Purpose:** Verify the `cc` CLI is installed and reachable

**Steps:**
```bash
cc --version
cc memory list --limit 1
```

**Pass Criteria:**
- [ ] `cc --version` prints a version string
- [ ] `cc memory list` returns valid output (empty list is acceptable)
- [ ] No import errors or missing-dependency messages

**Failure Mode:** `cc: command not found`, Python import error

**Frequency:** Every build, before commit

---

### ST-02: tc CLI Availability

**Purpose:** Verify the `tc` CLI is installed and reachable

**Steps:**
```bash
tc version
```

**Pass Criteria:**
- [ ] `tc version` prints a version string
- [ ] Command exits 0

**Failure Mode:** `tc: command not found`, missing package

**Frequency:** Every build

---

### ST-03: Memory Store and Retrieve Round-Trip

**Purpose:** Verify core memory write → read lifecycle works

**Steps:**
```bash
cc memory store --type context "Smoke test: ST-03 verification entry"
cc memory search "ST-03 verification"
```

**Pass Criteria:**
- [ ] `memory store` exits 0 and prints the new entry ID
- [ ] `memory search` returns the stored entry in results
- [ ] Content matches what was stored

**Failure Mode:** Write exits non-zero, search returns empty, content mismatch

**Frequency:** Every build

---

### ST-04: Memory Copilot Keyword Search (FTS5)

**Purpose:** Verify full-text keyword search works correctly

**Test Data:**
```bash
cc memory store --type decision "Implemented authentication using JWT"
cc memory store --type lesson "Learned that bcrypt is slow for API routes"
cc memory store --type context "Added user login form to dashboard"
```

**Steps:**
1. Store test memories
2. Search for "authentication"
3. Search for "bcrypt"

**Expected Results:**
```json
[
  {"type": "decision", "content": "Implemented authentication using JWT"}
]
```

**Pass Criteria:**
- [ ] FTS5 keyword search returns relevant results
- [ ] Results ranked by BM25 relevance
- [ ] No vector/embedding dependencies
- [ ] Empty query returns no error

**Failure Mode:** FTS5 index not rebuilt, keyword mismatch, search returns nothing

**Frequency:** Every build

---

### ST-05: cc skill list

**Purpose:** Verify skill discovery is functional

**Steps:**
```bash
cc skill list
cc skill search "security"
```

**Pass Criteria:**
- [ ] `cc skill list` returns at least one skill entry
- [ ] `cc skill search "security"` returns the `stride-dread` skill or equivalent
- [ ] Both commands exit 0

**Failure Mode:** Empty list when `.claude/skills/` contains skills, command error

**Frequency:** Every build

---

### ST-06: pytest L3 Skill Tests

**Purpose:** Verify code-bearing skill scripts pass their unit tests

**Steps:**
```bash
python -m pytest tests/test_skill_frontmatter.py -v
python -m pytest tests/test_parser_unit.py -v
```

**Pass Criteria:**
- [ ] All tests pass (0 failures)
- [ ] No import errors

**Failure Mode:** Test failures, missing test file, Python version mismatch

**Frequency:** Every build, every commit (pre-commit hook)

---

### ST-07: Knowledge Repo Priority (cc env)

**Purpose:** Verify knowledge repo paths resolve correctly

**Steps:**
```bash
eval "$(cc env)"
echo "CC_KNOWLEDGE_REPO=$CC_KNOWLEDGE_REPO"
echo "CC_SHARED_DOCS=$CC_SHARED_DOCS"
```

**Pass Criteria:**
- [ ] `cc env` exits 0 and emits valid shell export statements
- [ ] `CC_KNOWLEDGE_REPO` resolves to an existing path (if configured)
- [ ] No unbound variable errors

**Failure Mode:** `cc env` exits non-zero, variables empty when configured, path does not exist

**Frequency:** Every build

---

### ST-08: Extension File Resolution

**Purpose:** Verify agent extension files in the knowledge repo are found and readable

**Steps:**
```bash
# If a knowledge repo is configured:
ls "${CC_KNOWLEDGE_REPO}/.claude/extensions/" 2>/dev/null || echo "no extensions"

# Verify extension frontmatter is parseable
python -m pytest tests/test_skill_frontmatter.py -v -k "extension" 2>/dev/null || echo "no extension-specific tests"
```

**Pass Criteria:**
- [ ] Extensions directory accessible if repo configured
- [ ] No YAML parse errors in extension files

**Failure Mode:** Directory not found when repo is set, malformed frontmatter

**Frequency:** Every PR

---

### ST-09: Agent File Validity

**Purpose:** Verify all agent files are valid markdown with required sections

**Steps:**
```bash
# Check all agent files exist
ls -1 .claude/agents/*.md | wc -l
# Should be 16 agents

# Verify each has required sections
for agent in .claude/agents/*.md; do
  grep -q "## Identity" "$agent" || echo "Missing Identity: $agent"
  grep -q "## Core Behaviors" "$agent" || echo "Missing Core Behaviors: $agent"
  grep -q "## Route To Other Agent" "$agent" || echo "Missing routing: $agent"
done
```

**Required Sections (per agent):**
1. Frontmatter (name, description, tools, model)
2. ## Identity (Role, Mission, Success criteria)
3. ## Core Behaviors (Always do / Never do)
4. ## Output Formats
5. ## Quality Gates
6. ## Route To Other Agent
7. ## Decision Authority

**Pass Criteria:**
- [ ] 16 agent files present (ta, me, qa, do, doc, sd, uxd, uids, uid, sec, ind, cco, cw, cs, cpa, kc)
- [ ] All required sections present in each
- [ ] No time estimate language (per policy)

**Failure Mode:** Missing sections, malformed frontmatter, time estimates present

**Frequency:** Every commit (via pre-commit hook)

---

### ST-10: Command File Validity

**Purpose:** Verify all command files are executable and valid

**Steps:**
```bash
# List commands
ls -1 .claude/commands/*.md

# Check for required commands
required_commands=("protocol.md" "continue.md" "setup-project.md" "update-project.md" "update-copilot.md" "knowledge-copilot.md")
for cmd in "${required_commands[@]}"; do
  [[ -f ".claude/commands/$cmd" ]] || echo "Missing: $cmd"
done
```

**Pass Criteria:**
- [ ] All 6 core commands present
- [ ] Each command has clear instructions
- [ ] Protocol enforcement rules included

**Failure Mode:** Missing command, unclear instructions

**Frequency:** Every build

---

## 2. Integration Tests (Component Interaction)

### IT-01: Agent Invokes Memory Copilot

**Purpose:** Verify agents can successfully store and retrieve memories

**Scenario:** QA agent creates test plan and stores lessons learned

**Steps:**
1. Start new Claude Code session
2. Invoke `/protocol`
3. User: "Create a test plan for authentication"
4. @agent-qa creates plan
5. Agent calls `memory_store` with lesson
6. Call `memory_search("test plan lessons")`

**Verification:**
```bash
# Check memory was stored
sqlite3 ~/.claude/memory/<workspace>/memory.db \
  "SELECT type, content FROM memories WHERE type='lesson' ORDER BY created_at DESC LIMIT 1;"
```

**Pass Criteria:**
- [ ] Agent successfully calls memory_store
- [ ] Memory stored in database
- [ ] Search retrieves the memory
- [ ] No MCP tool errors

**Failure Mode:** Tool call fails, memory not stored, search returns nothing

**Frequency:** Every PR

---

### IT-02: Agent Routing Chain

**Purpose:** Verify agents correctly route to each other

**Scenario:** User requests feature requiring SD → design chain flow

**Steps:**
1. User: "Design a new user onboarding flow"
2. Should trigger @agent-sd
3. SD completes service design, routes to @agent-uxd
4. uxd completes interaction design, routes to @agent-uids
5. uids completes visual design tokens, routes to @agent-uid
6. uid completes component specs, routes to @agent-ta

**Verification:**
Check conversation log for:
```
[PROTOCOL: EXPERIENCE | Agent: @agent-sd | Action: INVOKING]
[... SD work ...]
Routing to @agent-uxd for interaction design

[PROTOCOL: EXPERIENCE | Agent: @agent-uxd | Action: INVOKING]
[... uxd work ...]
Routing to @agent-ta for architecture specification
```

**Pass Criteria:**
- [ ] Correct agent invoked first (SD)
- [ ] SD routes to uxd
- [ ] uxd routes to ta (for architecture, or uids for visual design)
- [ ] Each agent completes its domain work
- [ ] No duplicate work across agents

**Failure Mode:** Wrong agent invoked, routing skipped, work duplicated

**Frequency:** Weekly

---

### IT-03: Extension Overrides Base Agent

**Purpose:** Verify extension system correctly applies overrides

**Test Setup:**
```bash
# Create override extension
mkdir -p ~/.claude/knowledge/.claude/extensions
cat > ~/.claude/knowledge/.claude/extensions/sd.override.md <<'EOF'
---
extends: sd
type: override
description: Custom methodology
---
# Service Designer — Custom Instructions
Use the "Moments Framework" for all service design work.
EOF
```

**Steps:**
1. Call `extension_get("sd")`
2. Invoke @agent-sd
3. Verify agent uses override content, not base

**Verification:**
```bash
# Agent instructions should mention "Moments Framework"
# Agent should NOT use base Service Blueprinting methodology
```

**Pass Criteria:**
- [ ] Extension detected
- [ ] Override applied completely
- [ ] Base agent content ignored
- [ ] Agent behavior matches override

**Failure Mode:** Base agent used, extension ignored, partial merge

**Frequency:** Every PR

---

### IT-04: Extension Fallback (Missing Skills)

**Purpose:** Verify fallback behavior when required skills unavailable

**Test Setup:**
```bash
# Create extension requiring unavailable skill
cat > ~/.claude/knowledge/.claude/extensions/ta.extension.md <<'EOF'
---
extends: ta
type: extension
requiredSkills:
  - proprietary-architecture-patterns
fallbackBehavior: use_base_with_warning
---
# Architecture Extensions
[Custom content]
EOF
```

**Steps:**
1. Call `extension_get("ta")`
2. System checks for skill "proprietary-architecture-patterns"
3. Skill not found
4. System applies fallbackBehavior

**Expected Behavior:**
- Warning shown to user: "Extension unavailable, using base agent"
- Base agent used instead
- No error thrown

**Pass Criteria:**
- [ ] Required skills checked
- [ ] Fallback applied when missing
- [ ] User warned appropriately
- [ ] Session continues with base agent

**Failure Mode:** Session fails, no warning, extension applied despite missing skills

**Frequency:** Every PR

---

### IT-05: /protocol Command Integration

**Purpose:** Verify /protocol command activates Agent-First Protocol

**Steps:**
1. Start fresh Claude Code session
2. Run `/protocol`
3. User: "Fix bug in login form"
4. Observe agent invocation

**Expected Behavior:**
```
[PROTOCOL: DEFECT | Agent: @agent-qa | Action: INVOKING]

<subagent spawned>
QA agent investigates the defect...
```

**Pass Criteria:**
- [ ] Protocol declaration appears
- [ ] Correct agent invoked for request type
- [ ] Agent spawned as subagent (not direct response)
- [ ] Protocol enforced throughout session

**Failure Mode:** No protocol declaration, wrong agent, direct response without invocation

**Frequency:** Every release

---

### IT-06: /continue Command Loads Initiative

**Purpose:** Verify /continue command retrieves previous session context

**Test Setup:**
```bash
# Create initiative in previous session
# (Use memory_store tool or run actual session)
```

**Steps:**
1. Run `/continue` in new session
2. System calls `initiative_get`
3. System calls `memory_search("recent context")`
4. System presents resume summary

**Expected Output:**
```markdown
## Resuming: [Initiative Name]

**Status:** IN PROGRESS

**Completed:**
- [Previous completed items]

**In Progress:**
- [Current tasks]

**Recent Context:**
- [Key decisions and lessons]

**Resume Instructions:**
[Next steps]

Protocol active. What would you like to work on?
```

**Pass Criteria:**
- [ ] Initiative retrieved from Memory Copilot
- [ ] Recent context loaded
- [ ] Resume summary presented
- [ ] Protocol activated after resume

**Failure Mode:** No initiative found, incomplete context, protocol not activated

**Frequency:** Weekly

---

### IT-07: Knowledge Search Respects Priority

**Purpose:** Verify project knowledge overrides global knowledge

**Test Setup:**
```bash
# Global knowledge
mkdir -p ~/.claude/knowledge
echo "# Global Version" > ~/.claude/knowledge/test-doc.md

# Project knowledge
export KNOWLEDGE_REPO_PATH=/tmp/project-knowledge
mkdir -p $KNOWLEDGE_REPO_PATH
echo "# Project Version" > $KNOWLEDGE_REPO_PATH/test-doc.md
```

**Steps:**
1. Call `knowledge_search("test-doc")`
2. Verify project version returned first

**Expected Result:**
```json
{
  "results": [
    {
      "title": "test-doc.md",
      "source": "project",
      "content": "# Project Version"
    },
    {
      "title": "test-doc.md",
      "source": "global",
      "content": "# Global Version"
    }
  ]
}
```

**Pass Criteria:**
- [ ] Project result appears first
- [ ] Global result appears second
- [ ] Both marked with correct source
- [ ] Priority order respected

**Failure Mode:** Wrong order, missing results, incorrect source labels

**Frequency:** Every PR

---

## 3. End-to-End Tests (Developer Workflows)

### E2E-01: New Project Setup

**Purpose:** Validate complete project setup workflow

**Scenario:** Developer sets up Claude Copilot in a fresh project

**Steps:**
```bash
# 1. Create test project
mkdir -p /tmp/test-project
cd /tmp/test-project
git init

# 2. Run setup command
claude
# User runs: /setup-project
```

**Expected Results:**
- [ ] `.mcp.json` created with correct server configs
- [ ] `CLAUDE.md` created with project instructions
- [ ] `.claude/commands/` directory created with protocol and continue
- [ ] `.claude/agents/` directory created with all 16 agents
- [ ] `.claude/skills/` directory created for project skills
- [ ] User informed of next steps

**Verification:**
```bash
# Check files created
test -f .mcp.json && echo "✓ MCP config"
test -f CLAUDE.md && echo "✓ Project instructions"
test -d .claude/commands && echo "✓ Commands"
test -d .claude/agents && echo "✓ Agents"
test -d .claude/skills && echo "✓ Skills"

# Verify MCP config valid JSON
jq . .mcp.json > /dev/null && echo "✓ Valid JSON"

# Check all agents present
[[ $(ls .claude/agents/*.md | wc -l) -ge 16 ]] && echo "✓ All 16 agents"
```

**Pass Criteria:**
- All files created in correct locations
- MCP config valid and complete
- Agent files not corrupted
- Instructions clear

**Failure Mode:** Missing files, invalid JSON, corrupted agents, unclear instructions

**Frequency:** Every release

---

### E2E-02: Update Existing Project

**Purpose:** Validate project update doesn't break existing config

**Scenario:** Developer updates an existing project with new framework version

**Steps:**
```bash
# 1. Create project with old version
# 2. Make local customizations to .mcp.json
# 3. Run /update-project
```

**Expected Results:**
- [ ] New agent versions copied to `.claude/agents/`
- [ ] New commands added to `.claude/commands/`
- [ ] Existing `.mcp.json` preserved or safely merged
- [ ] User warned of breaking changes (if any)
- [ ] Custom skills not overwritten

**Verification:**
```bash
# Check agents updated
grep "version:" .claude/agents/ta.md | grep "1.2.0"

# Check custom MCP config preserved
jq '.mcpServers.custom' .mcp.json

# Check custom skills untouched
test -f .claude/skills/my-custom-skill.md
```

**Pass Criteria:**
- Framework updated successfully
- Custom config preserved
- No data loss
- Clear migration instructions if needed

**Failure Mode:** Config overwritten, skills lost, broken references

**Frequency:** Every major release

---

### E2E-03: Bug Investigation Workflow

**Purpose:** Validate complete defect investigation and resolution

**Scenario:** User reports bug, QA investigates, Engineer fixes

**Steps:**
1. Run `/protocol`
2. User: "Users can't log in - getting 500 error"
3. @agent-qa investigates:
   - Reproduces issue
   - Identifies root cause
   - Creates bug report
   - Routes to @agent-me
4. @agent-me implements fix
5. @agent-qa verifies fix

**Expected Flow:**
```
[PROTOCOL: DEFECT | Agent: @agent-qa | Action: INVOKING]
QA investigates...
Bug Report: [Details]
Routing to @agent-me for implementation

[PROTOCOL: TECHNICAL | Agent: @agent-me | Action: INVOKING]
Engineer implements fix...
Fix applied, routing back to @agent-qa for verification

[PROTOCOL: DEFECT | Agent: @agent-qa | Action: INVOKING]
QA verifies fix...
Fix validated. Closing defect.
```

**Pass Criteria:**
- [ ] QA agent invoked for defect
- [ ] Bug reproduced and documented
- [ ] Correct routing to Engineer
- [ ] Fix implemented
- [ ] QA validates fix
- [ ] Lessons stored in Memory Copilot

**Failure Mode:** Wrong agent invoked, no routing, fix not verified, memory not stored

**Frequency:** Weekly

---

### E2E-04: Feature Design to Implementation

**Purpose:** Validate complete feature workflow across multiple agents

**Scenario:** User requests new feature requiring architecture, design, and implementation

**Steps:**
1. User: "Add dark mode to the application"
2. @agent-ta: Architecture decisions (state management, theme system)
3. @agent-uxd: Interaction design (toggle flow, interaction patterns)
4. @agent-uids: Visual design (color palette, design tokens for dark theme)
5. @agent-me: Implementation (CSS variables, toggle component)
6. @agent-qa: Test plan (visual regression, state persistence)

**Expected Results:**
- [ ] Architecture documented
- [ ] Design decisions made
- [ ] Implementation complete
- [ ] Tests written
- [ ] All decisions stored in Memory Copilot
- [ ] Each agent stayed in their domain

**Verification:**
```bash
# Check memories created
sqlite3 ~/.claude/memory/<workspace>/memory.db \
  "SELECT type, content FROM memories WHERE content LIKE '%dark mode%';"

# Verify agent routing occurred
# (Check conversation log for routing statements)
```

**Pass Criteria:**
- Complete workflow from concept to implementation
- No gaps in handoffs
- All decisions documented
- No duplicate work

**Failure Mode:** Agent skipped, missing documentation, work duplicated

**Frequency:** Monthly

---

### E2E-05: Knowledge Repository Setup

**Purpose:** Validate /knowledge-copilot command creates shared knowledge repo

**Steps:**
1. Run `/knowledge-copilot`
2. @agent-kc guides discovery interview
3. User answers questions about company methodologies
4. Knowledge repo created at ~/.claude/knowledge
5. Extensions created based on responses

**Expected Results:**
- [ ] Directory created: ~/.claude/knowledge
- [ ] knowledge-manifest.json created
- [ ] Extension files created in .claude/extensions/
- [ ] User guided through discovery
- [ ] Clear next steps provided

**Verification:**
```bash
# Check structure
test -d ~/.claude/knowledge/.claude/extensions
test -f ~/.claude/knowledge/knowledge-manifest.json

# Validate manifest
jq '.version' ~/.claude/knowledge/knowledge-manifest.json
```

**Pass Criteria:**
- Valid knowledge repo structure
- Manifest valid JSON
- Extensions created correctly
- User understands how to use it

**Failure Mode:** Invalid structure, missing manifest, unclear guidance

**Frequency:** Every release

---

### E2E-06: Session Persistence Across Restarts

**Purpose:** Verify work context survives session restarts

**Scenario:** Developer works on feature, closes Claude Code, resumes next day

**Session 1:**
```bash
# 1. Start work on feature
/protocol
User: "Implement password reset flow"

# 2. @agent-ta creates architecture
# 3. Store initiative and progress
initiative_update({
  inProgress: ["Database schema created"],
  resumeInstructions: "Next: implement email service"
})
```

**Session 2 (next day):**
```bash
# 1. Resume work
/continue

# Expected: Initiative loaded, context restored
# Should see:
## Resuming: Password Reset Flow
**In Progress:** Database schema created
**Resume Instructions:** Next: implement email service
```

**Pass Criteria:**
- [ ] Initiative persisted between sessions
- [ ] Context accurately restored
- [ ] No manual file management needed
- [ ] Seamless continuation

**Failure Mode:** Context lost, initiative not found, manual recovery needed

**Frequency:** Weekly

---

## 4. Regression Tests

### RT-01: No Time Estimate Language

**Purpose:** Ensure time estimate policy violations don't reappear

**Scope:** All agent files, command files, documentation

**Automated Check:**
```bash
./scripts/audit-time-language.sh --report
```

**Pass Criteria:**
- [ ] Zero violations in agent files
- [ ] Acceptable time references only (system specs, test characteristics)
- [ ] No regression from baseline

**Frequency:** Every commit (pre-commit hook), Every PR (CI)

**Reference:** See `docs/60-qa/time-estimate-test-plan.md`

---

### RT-02: cc/tc CLI Compatibility

**Purpose:** Verify CLIs work after Python or dependency updates

**Steps:**
```bash
pip install -e ~/.claude/copilot/tools/tc
bash ~/.claude/copilot/tools/cc/install.sh
cc --version
tc version
cc memory search "test"
```

**Pass Criteria:**
- [ ] Both CLIs install without errors
- [ ] Version strings print correctly
- [ ] Memory search executes without traceback

**Failure Mode:** Install fails, import error after Python upgrade, broken CLI entrypoint

**Frequency:** Monthly, after Python or dependency updates

---

### RT-03: Extension Backward Compatibility

**Purpose:** Ensure new framework versions don't break existing extensions

**Test Data:** Use known good extensions from previous release

**Steps:**
1. Create extension with old format
2. Load with new framework version
3. Verify extension still works

**Pass Criteria:**
- [ ] Old extensions load correctly
- [ ] Frontmatter parsed
- [ ] Extension applied
- [ ] No errors

**Failure Mode:** Extension fails to load, parsing errors, behavior changed

**Frequency:** Every major version

---

### RT-04: Database Migration Safety

**Purpose:** Verify database schema changes don't corrupt existing data

**Test Setup:**
```bash
# Create database with old schema
# Store test data
# Run migration
# Verify data intact
```

**Pass Criteria:**
- [ ] Migration completes without errors
- [ ] Existing data preserved
- [ ] New schema features work
- [ ] No data corruption

**Failure Mode:** Data lost, schema mismatch, corrupted database

**Frequency:** Every database schema change

---

## 5. Performance Tests

### PT-01: Memory Copilot Search Performance

**Scenario:** Large database with 10,000 memories

**Test Data:**
```bash
# Generate 10,000 test memories
for i in {1..10000}; do
  memory_store("Test memory $i with varying content", "context")
done
```

**Performance Target:** Search completes in < 500ms

**Measurement:**
```bash
time memory_search("specific content query")
```

**Pass Criteria:**
- [ ] Search < 500ms at 10K memories
- [ ] Results accurate
- [ ] No timeout errors
- [ ] Database size reasonable (<100MB)

**Failure Mode:** Slow search, timeouts, database bloat

**Frequency:** Monthly

---

### PT-02: cc skill search Latency

**Scenario:** Repeated skill searches measure `cc skill search` lookup speed. Note: `cc skill search` is a case-insensitive **substring** match over each skill's `name + description + tags` (NOT FTS5 — only Memory Copilot uses FTS5). The `skills-copilot` MCP server this test previously targeted was removed in the 5.6.0 cleanup; the `cc` CLI is the current interface.

**Test Data:**
```bash
# Run the same skill search 10 times and time it
for i in {1..10}; do
  time cc skill search "react testing"
done
```

**Performance Target:**
- Every request: < 500ms (local substring scan over skill metadata, no network)

**Measurement:**
```bash
# Time a single search and inspect output
time cc skill search "documentation"
```

**Pass Criteria:**
- [ ] All 10 searches complete in < 500ms
- [ ] Results are consistent across repeated calls
- [ ] No missing-index errors

**Failure Mode:** `cc: command not found`, or no skills found (verify `.claude/skills/` is populated and skill frontmatter has searchable `name`/`description`/`tags`)

**Frequency:** Monthly

---

### PT-03: Agent Invocation Overhead

**Scenario:** Measure time cost of agent spawning vs direct response

**Performance Target:** Agent invocation adds < 2 seconds overhead

**Measurement:**
```bash
# Time a simple agent invocation
# Compare to direct response time
```

**Pass Criteria:**
- [ ] Overhead < 2 seconds
- [ ] No exponential growth with nested agents
- [ ] Context size doesn't cause slowdown

**Failure Mode:** Slow invocation, context bloat, nested overhead

**Frequency:** Quarterly

---

## 6. Security Tests

### SEC-01: Memory Database Permissions

**Purpose:** Verify memory database not world-readable

**Steps:**
```bash
# Check file permissions
ls -la ~/.claude/memory/<workspace>/memory.db
# Should be 600 (user only)

# Verify no sensitive data logged
grep -r "password\|token\|secret" ~/.claude/memory/
```

**Pass Criteria:**
- [ ] Database files readable by user only
- [ ] No secrets in logs
- [ ] Workspace isolation maintained

**Failure Mode:** World-readable database, secrets logged, workspace leakage

**Frequency:** Every release

---

### SEC-02: Extension Injection Safety

**Purpose:** Verify extensions can't execute arbitrary code

**Test Data:**
```markdown
---
extends: ta
type: override
---
<script>alert('XSS')</script>
```

**Pass Criteria:**
- [ ] Extension content treated as text only
- [ ] No code execution
- [ ] No XSS vulnerabilities
- [ ] Markdown sanitized

**Failure Mode:** Code executed, XSS possible, injection vulnerability

**Frequency:** Every PR touching extension system

---

## 7. Usability Tests (Manual)

### UX-01: New User Onboarding

**Scenario:** Developer with no Claude Copilot experience sets up framework

**Steps:**
1. Provide only README.md
2. User attempts setup
3. Observe where they get stuck

**Success Metrics:**
- Setup completes in < 15 minutes
- No external documentation needed
- Clear error messages if stuck
- User understands next steps

**Common Issues to Watch:**
- Unclear what to run first
- MCP config confusing
- Agent invocation syntax unclear
- Don't understand protocol

**Frequency:** Every major release

---

### UX-02: Error Message Clarity

**Scenario:** Trigger common error conditions, evaluate messages

**Test Cases:**
- Missing MCP server
- Invalid .mcp.json syntax
- Extension with missing skills
- Memory database locked
- Network timeout fetching skill

**Pass Criteria:**
- [ ] Error message explains what went wrong
- [ ] Suggests specific fix
- [ ] Points to relevant documentation
- [ ] No cryptic stack traces

**Frequency:** Quarterly

---

### UX-03: Documentation Accuracy

**Scenario:** Follow all documentation guides step-by-step

**Documents to Test:**
- README.md
- SETUP.md
- CLAUDE.md
- EXTENSION-SPEC.md
- Each agent's inline documentation

**Pass Criteria:**
- [ ] All commands work as documented
- [ ] No broken references
- [ ] Examples actually run
- [ ] Terminology consistent

**Frequency:** Every release

---

## Test Execution Schedule

| Frequency | Tests | Owner |
|-----------|-------|-------|
| **Every Commit** | ST-09 (pre-commit hook), RT-01 (time estimates) | Automated |
| **Every Build** | ST-01 through ST-10 | Automated |
| **Every PR** | IT-01 through IT-07, SEC-02 | Automated + QA |
| **Weekly** | E2E-01, E2E-03, E2E-06 | QA |
| **Monthly** | E2E-04, PT-01, PT-02, RT-02 | QA |
| **Quarterly** | E2E-05, PT-03, UX-01, UX-02, UX-03 | QA + Product |
| **Every Release** | E2E-01, E2E-02, E2E-05, SEC-01, UX-03 | QA |
| **Schema Change** | RT-04 | DevOps + QA |
| **Major Version** | RT-03, UX-01 | QA |

---

## Test Environment Setup

### Required Tools
```bash
# Python 3.10+ (required for cc/tc CLIs)
python3 --version

# pytest (for L3 skill tests)
pip install pytest

# cc CLI
bash ~/.claude/copilot/tools/cc/install.sh

# tc CLI
pip install -e ~/.claude/copilot/tools/tc

# jq (for JSON validation in shell scripts — optional)
brew install jq  # macOS
# apt-get install jq  # Debian/Ubuntu

# Claude Code CLI
# (Already installed)
```

### Test Project Template
```bash
# Create clean test environment
mkdir -p /tmp/claude-copilot-test
cd /tmp/claude-copilot-test
git init
# Copy framework files
# Run tests
```

---

## Continuous Monitoring

### Metrics to Track

| Metric | Target | Measurement |
|--------|--------|-------------|
| Smoke test pass rate | 100% | Every build |
| Integration test pass rate | > 95% | Every PR |
| E2E test pass rate | > 90% | Weekly |
| Regression count | 0 new | Every release |
| Setup success rate | > 95% | User feedback |
| Agent invocation success | > 99% | Production logs |
| Memory search accuracy | > 85% | User feedback |

### Alerts

| Condition | Action |
|-----------|--------|
| Smoke test fails | Block commit/build |
| Integration test fails | Block PR merge |
| E2E test fails | Investigate immediately |
| Performance degradation > 50% | File bug, investigate |
| Security test fails | Emergency fix, block release |

---

## Documentation Output

### Test Report Template
```markdown
# Test Execution Report

**Date:** YYYY-MM-DD
**Release:** vX.Y.Z
**Tester:** [Name]

## Summary
- Smoke Tests: X/10 passed
- Integration Tests: X/7 passed
- E2E Tests: X/6 passed
- Regressions: X issues found

## Failures

### [Test ID]: [Test Name]
**Severity:** Critical / High / Medium / Low
**Description:** What failed
**Expected:** What should happen
**Actual:** What happened
**Root Cause:** Why it failed
**Fix:** What needs to be done

## Recommendations
- [Action item 1]
- [Action item 2]
```

---

## Success Criteria

**Framework is validated when:**
- [ ] All smoke tests pass (100%)
- [ ] Integration tests > 95% pass rate
- [ ] E2E tests > 90% pass rate
- [ ] Zero critical regressions
- [ ] Performance within targets
- [ ] Security tests pass (100%)
- [ ] New user can set up in < 15 minutes
- [ ] Documentation accurate and complete

---

## Next Steps

1. **Implement Automated Tests**
   - Create test scripts for ST-01 through ST-10
   - Set up CI pipeline integration
   - Configure pre-commit hooks

2. **Document Test Data**
   - Create test fixtures directory
   - Generate sample memories, skills, extensions
   - Version control test data

3. **Establish Baseline**
   - Run full test suite on current version
   - Document current pass rates
   - Identify known issues

4. **Create Monitoring Dashboard**
   - Track test results over time
   - Visualize regression trends
   - Alert on failures

5. **Schedule Regular Testing**
   - Set up weekly E2E test runs
   - Monthly performance benchmarks
   - Quarterly usability studies

---

**File Locations:**
- This document: `docs/60-qa/01-framework-validation-strategy.md`
- Time estimate tests: `docs/60-qa/time-estimate-test-plan.md`
- Test scripts: `scripts/` (to be created)
- Test data: `tests/fixtures/` (to be created)
