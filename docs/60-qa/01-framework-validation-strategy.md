# Claude Copilot Framework Validation Strategy

**Version:** 1.0
**Date:** 2025-12-29
**Owner:** @agent-qa

## Overview

This document defines the complete validation strategy for the Claude Copilot framework. It includes smoke tests for rapid feedback, integration tests for component interaction, and manual scenarios for developer experience validation.

**Framework Components:**
- Memory Copilot MCP server (initiative tracking, semantic search)
- Skills Copilot MCP server (skill loading, knowledge search, extensions)
- 12 Specialized Agents (routing, context isolation)
- Protocol commands (/protocol, /continue, /setup-project, /update-project, /update-copilot, /knowledge-copilot)
- Extension system (override, extension, skills injection)

---

## Test Strategy

| Level | Focus | Tools | Execution |
|-------|-------|-------|-----------|
| **Smoke** | Each component works in isolation | MCP Inspector, manual CLI | Every build |
| **Integration** | Components work together | Custom test scripts | Every PR |
| **E2E** | Developer workflows succeed | Real Claude Code sessions | Weekly |
| **Regression** | Previous bugs don't return | Automated + manual | Every release |

---

## 1. Smoke Tests (Component Isolation)

### ST-01: Memory Copilot MCP Server Connectivity

**Purpose:** Verify MCP server starts and responds to requests

**Steps:**
```bash
# 1. Start MCP server manually
cd /Users/pabs/Sites/COPILOT/claude-copilot/mcp-servers/copilot-memory
npm run build
node dist/index.js
```

**Verification:**
- [ ] Server starts without errors
- [ ] Server responds to stdio transport
- [ ] Database initializes correctly
- [ ] No missing dependencies

**Pass Criteria:** Server running, no error logs

**Failure Mode:** Server crashes, missing node modules, TypeScript errors

**Frequency:** Every build, before commit

---

### ST-02: Memory Copilot Tool Registration

**Purpose:** Verify all memory tools are registered and callable

**Steps:**
```bash
# Use MCP Inspector to list tools
mcp-inspector connect stdio "node dist/index.js"
# Send ListTools request
```

**Expected Tools:**
- `memory_store`
- `memory_update`
- `memory_delete`
- `memory_get`
- `memory_list`
- `memory_search`
- `initiative_start`
- `initiative_update`
- `initiative_get`
- `initiative_complete`

**Verification:**
```json
{
  "method": "tools/list",
  "result": {
    "tools": [
      {"name": "memory_store", "description": "..."},
      {"name": "initiative_start", "description": "..."}
    ]
  }
}
```

**Pass Criteria:** All 10 tools listed with valid schemas

**Failure Mode:** Missing tool, invalid schema, wrong parameter types

**Frequency:** Every build

---

### ST-03: Memory Copilot Basic Initiative Flow

**Purpose:** Verify core initiative lifecycle works

**Test Data:**
```json
{
  "title": "Test Initiative",
  "description": "Smoke test for initiative tracking",
  "scope": ["component-a", "component-b"]
}
```

**Steps:**
1. Call `initiative_start` with test data
2. Call `initiative_get` to retrieve
3. Call `initiative_update` with progress
4. Call `initiative_complete` to archive

**Verification:**
```bash
# Check SQLite database directly
sqlite3 ~/.claude/memory/<workspace-hash>/memory.db
SELECT * FROM initiatives WHERE title = 'Test Initiative';
```

**Pass Criteria:**
- [ ] Initiative created with valid ID
- [ ] Retrieved initiative matches input
- [ ] Update reflected in database
- [ ] Complete changes status to 'complete'

**Failure Mode:** Database write fails, invalid ID returned, status not updated

**Frequency:** Every build

---

### ST-04: Memory Copilot Semantic Search

**Purpose:** Verify embeddings and vector search work

**Test Data:**
```javascript
// Store 3 memories with related content
memory_store("Implemented authentication using JWT", "decision")
memory_store("Learned that bcrypt is slow for API routes", "lesson")
memory_store("Added user login form to dashboard", "context")
```

**Steps:**
1. Store test memories
2. Search for "authentication decisions"
3. Search for "performance lessons"

**Expected Results:**
```json
{
  "query": "authentication decisions",
  "results": [
    {"content": "Implemented authentication using JWT", "similarity": 0.85}
  ]
}
```

**Pass Criteria:**
- [ ] Embedding generation succeeds
- [ ] Search returns semantically similar results
- [ ] Results ranked by similarity score
- [ ] No errors in vector operations

**Failure Mode:** Embeddings not generated, vector search fails, wrong results

**Frequency:** Every build

---

### ST-05: Skills Copilot MCP Server Connectivity

**Purpose:** Verify Skills Copilot starts and responds

**Steps:**
```bash
cd /Users/pabs/Sites/COPILOT/claude-copilot/mcp-servers/skills-copilot
npm run build
node dist/index.js
```

**Verification:**
- [ ] Server starts without errors
- [ ] Cache directory created if missing
- [ ] Knowledge repo paths resolved

**Pass Criteria:** Server running, no error logs

**Failure Mode:** Server crashes, path resolution fails

**Frequency:** Every build

---

### ST-06: Skills Copilot Tool Registration

**Purpose:** Verify all skill tools are registered

**Expected Tools:**
- `skill_get`
- `skill_search`
- `skill_list`
- `skill_save`
- `knowledge_search`
- `knowledge_get`
- `extension_get`
- `extension_list`
- `manifest_status`

**Verification:**
```bash
# List tools via MCP Inspector
mcp-inspector connect stdio "node dist/index.js"
```

**Pass Criteria:** All 9 tools listed with valid schemas

**Failure Mode:** Missing tool, invalid schema

**Frequency:** Every build

---

### ST-07: Skills Copilot Knowledge Search (Two-Tier)

**Purpose:** Verify two-tier knowledge resolution works

**Test Setup:**
```bash
# Create global knowledge repo
mkdir -p ~/.claude/knowledge/.claude/extensions
echo "# Test Knowledge" > ~/.claude/knowledge/test.md

# Create project knowledge repo (if testing override)
mkdir -p /tmp/test-project-knowledge/.claude/extensions
echo "# Project Knowledge" > /tmp/test-project-knowledge/test.md
```

**Steps:**
1. Call `knowledge_search("test")` with no KNOWLEDGE_REPO_PATH
2. Call `knowledge_search("test")` with KNOWLEDGE_REPO_PATH set
3. Call `manifest_status()`

**Expected Behavior:**
- Without project path: Returns global knowledge only
- With project path: Returns project knowledge (higher priority)
- Manifest status shows both repos if configured

**Pass Criteria:**
- [ ] Global repo auto-detected at ~/.claude/knowledge
- [ ] Project repo used when KNOWLEDGE_REPO_PATH set
- [ ] Priority ordering correct (project > global > base)

**Failure Mode:** Can't find global repo, wrong priority, missing manifests

**Frequency:** Every build

---

### ST-08: Skills Copilot Extension Resolution

**Purpose:** Verify extension resolution algorithm works

**Test Data:**
```bash
# Create test extension in global repo
cat > ~/.claude/knowledge/.claude/extensions/sd.override.md <<'EOF'
---
extends: sd
type: override
description: Test override
---
# Test Service Designer Override
EOF
```

**Steps:**
1. Call `extension_get("sd")`
2. Call `extension_list()`

**Expected Result:**
```json
{
  "agentId": "sd",
  "type": "override",
  "content": "# Test Service Designer Override",
  "source": "global",
  "requiredSkills": [],
  "fallbackBehavior": "use_base"
}
```

**Pass Criteria:**
- [ ] Extension found in global repo
- [ ] Frontmatter parsed correctly
- [ ] Type and source identified
- [ ] Content returned complete

**Failure Mode:** Extension not found, parsing fails, wrong source

**Frequency:** Every build

---

### ST-09: Agent File Validity

**Purpose:** Verify all agent files are valid markdown with required sections

**Steps:**
```bash
# Check all agent files exist
ls -1 .claude/agents/*.md | wc -l
# Should be 14 agents

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
- [ ] 12 agent files present
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

**Scenario:** User requests feature requiring SD → UXD → UID flow

**Steps:**
1. User: "Design a new user onboarding flow"
2. Should trigger @agent-sd
3. SD completes service design, routes to @agent-uxd
4. UXD completes interaction design, routes to @agent-uid
5. UID produces implementation

**Verification:**
Check conversation log for:
```
[PROTOCOL: EXPERIENCE | Agent: @agent-sd | Action: INVOKING]
[... SD work ...]
Routing to @agent-uxd for interaction design

[PROTOCOL: EXPERIENCE | Agent: @agent-uxd | Action: INVOKING]
[... UXD work ...]
Routing to @agent-uid for implementation

[PROTOCOL: TECHNICAL | Agent: @agent-uid | Action: INVOKING]
```

**Pass Criteria:**
- [ ] Correct agent invoked first (SD)
- [ ] SD routes to UXD
- [ ] UXD routes to UID
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
- [ ] `.claude/agents/` directory created with all 14 agents
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
[[ $(ls .claude/agents/*.md | wc -l) -ge 14 ]] && echo "✓ All 14 agents"
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
3. @agent-uxd: Interaction design (toggle placement, preferences)
4. @agent-uids: Visual design (color palette, component variants)
5. @agent-uid: Implementation (CSS variables, toggle component)
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

**Reference:** See `/Users/pabs/Sites/COPILOT/claude-copilot/docs/qa/time-estimate-test-plan.md`

---

### RT-02: MCP Server Compatibility

**Purpose:** Verify MCP servers work with latest @modelcontextprotocol/sdk

**Steps:**
```bash
# Update SDK to latest
cd mcp-servers/copilot-memory
npm update @modelcontextprotocol/sdk
npm run build

# Test connectivity
node dist/index.js
```

**Pass Criteria:**
- [ ] Build succeeds
- [ ] Server starts
- [ ] All tools still callable
- [ ] No breaking changes

**Failure Mode:** Build fails, tools missing, protocol changes break server

**Frequency:** Monthly, when SDK updates

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

### PT-02: Skills Copilot Cache Hit Rate

**Scenario:** Repeated skill requests measure cache effectiveness

**Test Data:**
```bash
# Request same skill 10 times
for i in {1..10}; do
  skill_get("react-testing")
done
```

**Performance Target:**
- First request: < 2 seconds (network fetch)
- Cached requests: < 100ms

**Measurement:**
```bash
# Check cache logs
grep "cache hit" /tmp/skills-copilot.log
```

**Pass Criteria:**
- [ ] Cache hit rate > 90% for repeated requests
- [ ] Cache invalidation works correctly
- [ ] Stale content not served

**Failure Mode:** Low cache hits, stale content, cache corruption

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
# MCP Inspector (for protocol testing)
npm install -g @modelcontextprotocol/inspector

# SQLite (for database verification)
brew install sqlite3

# jq (for JSON validation)
brew install jq

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
- This document: `/Users/pabs/Sites/COPILOT/claude-copilot/docs/qa/framework-validation-strategy.md`
- Time estimate tests: `/Users/pabs/Sites/COPILOT/claude-copilot/docs/qa/time-estimate-test-plan.md`
- Test scripts: `/Users/pabs/Sites/COPILOT/claude-copilot/scripts/` (to be created)
- Test data: `/Users/pabs/Sites/COPILOT/claude-copilot/tests/fixtures/` (to be created)
