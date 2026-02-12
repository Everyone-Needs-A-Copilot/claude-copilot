# Testing Guide for Claude Copilot Framework

**Quick Reference:** How to validate the framework works correctly

---

## Test Levels

| Level | Purpose | Run When | Script |
|-------|---------|----------|--------|
| **Smoke** | Each component works in isolation | Every commit, before push | `./scripts/smoke-test.sh` |
| **Integration** | Components work together | Every PR, before merge | `./scripts/integration-test.sh` |
| **E2E** | Complete workflows succeed | Weekly, before release | Manual (see below) |
| **Regression** | Previous bugs don't return | Every release | Automated + Manual |

---

## Quick Start

### Run All Automated Tests

```bash
# From repository root
cd /Users/pabs/Sites/COPILOT/claude-copilot

# 1. Smoke tests (fast, ~30 seconds)
./scripts/smoke-test.sh

# 2. Integration tests (medium, ~1 minute)
./scripts/integration-test.sh

# 3. Time estimate policy check
./scripts/audit-time-language.sh --report
```

**Expected output:**
```
✓ All smoke tests PASSED
✓ All integration tests PASSED
✓ No time estimate violations found
```

If any test fails, see the detailed logs for which specific test failed and why.

---

## Detailed Test Documentation

### Smoke Tests

**Purpose:** Validate each component works in isolation

**What it checks:**
- File structure (agents, commands, MCP servers)
- Agent file validity (required sections present)
- MCP configuration syntax
- TypeScript builds succeed
- Documentation files exist
- Time estimate policy compliance

**Run:**
```bash
./scripts/smoke-test.sh
```

**When to run:**
- Before every commit
- After making changes to agents
- After updating MCP servers
- After documentation changes

**Output:**
- ✓ Green checkmarks for passing tests
- ✗ Red X for failures
- Summary count at end

**Common failures and fixes:**

| Failure | Cause | Fix |
|---------|-------|-----|
| Agent file missing section | Required section deleted/renamed | Add back required section (see Required Agent Sections) |
| MCP server build failed | TypeScript error | Fix TypeScript errors, check `npm run build` output |
| Invalid JSON in .mcp.json | Syntax error | Run `jq . .mcp.json` to validate |
| Time estimate violation | Prohibited language in agent files | Remove time-based language, see policy |

**Lean Agent Model (v1.8+)**

Current state: All 14 agents use the lean agent model (under 120 lines each) with on-demand skill loading via `skill_evaluate()`. Shared boilerplate is extracted to "Agent Shared Behaviors" in CLAUDE.md.

**Agents with full structure:**
- cw.md (Copywriter)
- kc.md (Knowledge Copilot)
- uid.md (UI Developer)
- uids.md (UI Designer)

**Agents with simplified format (missing required sections):**
- do.md (DevOps)
- doc.md (Documentation)
- me.md (Engineer)
- qa.md (QA Engineer)
- sd.md (Service Designer)
- sec.md (Security)
- ta.md (Tech Architect)
- uxd.md (UX Designer)

**Required sections per CLAUDE.md:**
- `## Identity` - Role, Mission, Success criteria
- `## Core Behaviors` - Always do / Never do
- `## Route To Other Agent` - When to hand off
- `## Decision Authority` - Autonomous vs escalate

**Impact:** Smoke and integration tests will fail for simplified agents until they are updated to include all required sections. Tests are currently configured to check all agents for full structure.

---

### Integration Tests

**Purpose:** Validate components work together correctly

**What it checks:**
- MCP servers built and loadable
- Provider chain complete in Skills Copilot
- Extension resolution logic (two-tier)
- Agent routing tables correct
- Commands reference correct MCP tools
- Template files match framework structure

**Run:**
```bash
./scripts/integration-test.sh
```

**When to run:**
- Before every PR
- After smoke tests pass
- After changing MCP server code
- After modifying extension system

**Output:**
- Detailed test sections
- Pass/fail for each integration point
- Summary with failed test list

**Common failures and fixes:**

| Failure | Cause | Fix |
|---------|-------|-----|
| Provider missing from build | Import not included | Check `src/providers/index.ts` exports |
| Extension frontmatter invalid | YAML syntax error | Validate frontmatter syntax |
| Agent routing table missing | Table deleted or malformed | Restore routing table in agent file |
| Command references wrong tool | Tool name changed | Update command to reference correct tool |

---

### End-to-End Tests (Manual)

**Purpose:** Validate complete developer workflows

**What it checks:**
- New project setup works
- Agent invocation and routing works
- Memory persistence across sessions
- Extension override behavior
- Protocol enforcement

**Run:** Follow scenarios in `framework-validation-strategy.md`

**Key E2E scenarios to test:**

#### E2E-01: New Project Setup

```bash
# Create fresh project
mkdir /tmp/test-project && cd /tmp/test-project
git init

# Open in Claude Code
claude

# Run setup
/setup-project

# Verify files created
ls -la .claude/
cat .mcp.json
```

**Expected:** All files created, MCP config valid, agents present

---

#### E2E-03: Bug Investigation Workflow

```bash
# In Claude Code session
/protocol

# User message:
"Users can't log in - getting 500 error on POST /auth/login"

# Expected:
# [PROTOCOL: DEFECT | Agent: @agent-qa | Action: INVOKING]
# QA agent investigates...
# Routes to Engineer for fix...
# Engineer fixes...
# Routes back to QA for verification...
```

**Expected:** Correct agent invoked, proper routing, fix verified

---

#### E2E-06: Session Persistence

**Session 1:**
```bash
/protocol
"Implement password reset feature"

# Work progresses...
# At end of session, initiative_update called with progress
```

**Session 2 (new day):**
```bash
/continue

# Expected:
## Resuming: Password Reset Feature
**In Progress:** [previous work]
**Resume Instructions:** [next steps]
```

**Expected:** Context restored accurately, seamless continuation

---

### Regression Tests

**Purpose:** Ensure previous bugs don't return

**Key regression checks:**

#### RT-01: No Time Estimates

```bash
./scripts/audit-time-language.sh --report
```

**Expected:** Zero violations in agent files

**Frequency:** Every commit (automated via pre-commit hook)

---

#### RT-02: MCP Server Compatibility

```bash
# Update MCP SDK
cd mcp-servers/copilot-memory
npm update @modelcontextprotocol/sdk

# Rebuild
npm run build

# Test (requires MCP Inspector)
# Verify all tools still work
```

**Expected:** Build succeeds, tools callable

**Frequency:** Monthly, when SDK updates

---

## Performance Benchmarks

### Smoke Test Performance

**Target:** < 60 seconds

**Measure:**
```bash
time ./scripts/smoke-test.sh
```

**If slow:**
- Check TypeScript build time
- Check file count in node_modules
- Consider caching builds

---

### Integration Test Performance

**Target:** < 90 seconds

**Measure:**
```bash
time ./scripts/integration-test.sh
```

**If slow:**
- Reduce test file I/O
- Cache provider chains
- Parallelize independent tests

---

## CI/CD Integration

### Pre-Commit Hook

**Setup:**
```bash
# Add to .git/hooks/pre-commit
#!/bin/bash
./scripts/smoke-test.sh || exit 1
./scripts/audit-time-language.sh || exit 1
```

**Make executable:**
```bash
chmod +x .git/hooks/pre-commit
```

**Effect:** Blocks commits if smoke tests or time estimate audit fails

---

### GitHub Actions Workflows

**Smoke Tests:** `.github/workflows/smoke-tests.yml`
- Runs on every push and PR
- Installs dependencies
- Builds MCP servers
- Runs smoke test suite
- Uploads test artifacts
- Blocks merge if tests fail

**Time Estimate Check:** `.github/workflows/time-estimate-check.yml`
- Runs on changes to agent/command/template files
- Scans for prohibited time-based language
- Comments on PR if violations found
- Blocks merge if violations detected

**Status:** Both workflows are active and will run automatically on PRs.

---

## Test Data Management

### Creating Test Fixtures

**Location:** `/tests/fixtures/` (to be created)

**Contents:**
- Sample memories (JSON)
- Sample extensions (MD files)
- Sample knowledge repos (directory structures)
- Test initiatives (JSON)

**Example:**
```bash
mkdir -p tests/fixtures/{memories,extensions,initiatives}

# Sample memory
cat > tests/fixtures/memories/decision-001.json <<EOF
{
  "content": "Decided to use JWT for authentication",
  "type": "decision",
  "tags": ["auth", "security"]
}
EOF

# Sample extension
cat > tests/fixtures/extensions/ta.override.md <<EOF
---
extends: ta
type: override
---
# Test Tech Architect Override
EOF
```

---

## Debugging Failed Tests

### Smoke Test Failures

**Enable verbose output:**
```bash
# Edit smoke-test.sh, add:
set -x  # Print each command before executing
```

**Check specific component:**
```bash
# Test MCP server build manually
cd mcp-servers/copilot-memory
npm run build
# Check for TypeScript errors
```

**Check file permissions:**
```bash
ls -la .claude/agents/
# Should be readable
```

---

### Integration Test Failures

**Check test workspace:**
```bash
# Integration test creates /tmp/claude-copilot-integration-test-*
# If test fails, workspace may remain for inspection
ls -la /tmp/claude-copilot-integration-test-*
```

**Validate JSON manually:**
```bash
jq . .mcp.json
jq . tests/fixtures/knowledge/knowledge-manifest.json
```

**Check environment variables:**
```bash
echo $MEMORY_PATH
echo $WORKSPACE_ID
echo $KNOWLEDGE_REPO_PATH
```

---

### E2E Test Failures

**Enable MCP debug logging:**
```json
// In .mcp.json
{
  "mcpServers": {
    "copilot-memory": {
      "env": {
        "LOG_LEVEL": "debug"
      }
    }
  }
}
```

**Check Memory Copilot database:**
```bash
# Find workspace hash
ls ~/.claude/memory/

# Inspect database
sqlite3 ~/.claude/memory/<hash>/memory.db
.schema
SELECT * FROM initiatives;
SELECT * FROM memories LIMIT 10;
```

**Check Skills Copilot cache:**
```bash
ls ~/.claude/skills-cache/
# Should contain cached skills
```

---

## Test Coverage Goals

| Component | Target | Current | Status |
|-----------|--------|---------|--------|
| Agent file structure | 100% | TBD | 🔴 |
| MCP server tools | 100% | TBD | 🔴 |
| Command validity | 100% | TBD | 🔴 |
| Extension resolution | 100% | TBD | 🔴 |
| E2E workflows | 80% | TBD | 🔴 |
| Time estimate policy | 100% | TBD | 🔴 |

---

## Continuous Monitoring

### Daily
- [ ] CI runs on all PRs
- [ ] Pre-commit hooks active

### Weekly
- [ ] Run E2E-03 (bug workflow)
- [ ] Run E2E-06 (session persistence)
- [ ] Check test performance benchmarks

### Monthly
- [ ] Full E2E suite (all scenarios)
- [ ] Performance benchmarks
- [ ] Update MCP SDK compatibility

### Quarterly
- [ ] Usability testing with new developers
- [ ] Documentation accuracy review
- [ ] Test data freshness check

---

## Contributing Tests

### Adding a New Smoke Test

**Edit:** `scripts/smoke-test.sh`

**Template:**
```bash
#############################
# ST-XX: New Test Name
#############################
section "ST-XX: New Test Name"

# Test logic
if [[ condition ]]; then
  pass "Test passed"
else
  fail "Test failed: reason"
fi
```

**Commit with:**
- Test description in commit message
- Update to this TESTING.md file
- Update to framework-validation-strategy.md if needed

---

### Adding a New Integration Test

**Edit:** `scripts/integration-test.sh`

**Template:**
```bash
#############################
# IT-XX: New Integration Test
#############################
section "IT-XX: New Integration Test"

# Setup
# Test logic
# Verification

if [[ condition ]]; then
  pass "Integration test passed"
else
  fail "Integration test failed: reason"
fi
```

---

### Adding a New E2E Scenario

**Edit:** `docs/qa/framework-validation-strategy.md`

**Add to "3. End-to-End Tests" section:**
```markdown
### E2E-XX: Scenario Name

**Purpose:** What this scenario validates

**Scenario:** User story

**Steps:**
1. Step 1
2. Step 2

**Expected Results:**
- [ ] Expected behavior 1
- [ ] Expected behavior 2

**Pass Criteria:**
- Specific pass conditions

**Failure Mode:** What goes wrong if it fails

**Frequency:** How often to run
```

---

## Getting Help

### Test Failures

1. Check this guide for common failures
2. Check detailed strategy: `docs/qa/framework-validation-strategy.md`
3. Run tests with verbose output (`set -x`)
4. File issue with test output and environment details

### Test Coverage Gaps

1. Review framework-validation-strategy.md for comprehensive test plan
2. Check if scenario is documented but not automated
3. File issue requesting new test coverage

### Performance Issues

1. Check benchmark targets in this guide
2. Profile slow tests with `time` command
3. File issue with performance metrics

---

## Quick Reference Commands

```bash
# Run all automated tests
./scripts/smoke-test.sh && ./scripts/integration-test.sh

# Check time estimate policy
./scripts/audit-time-language.sh --report

# Build MCP servers
cd mcp-servers/copilot-memory && npm run build
cd ../skills-copilot && npm run build

# Inspect Memory database
sqlite3 ~/.claude/memory/<hash>/memory.db

# Validate JSON configs
jq . .mcp.json
jq . knowledge-manifest.json

# Clean test artifacts
rm -rf /tmp/claude-copilot-*-test-*
```

---

**File Locations:**
- This guide: `/Users/pabs/Sites/COPILOT/claude-copilot/docs/qa/TESTING.md`
- Full strategy: `/Users/pabs/Sites/COPILOT/claude-copilot/docs/qa/framework-validation-strategy.md`
- Smoke tests: `/Users/pabs/Sites/COPILOT/claude-copilot/scripts/smoke-test.sh`
- Integration tests: `/Users/pabs/Sites/COPILOT/claude-copilot/scripts/integration-test.sh`
- Time audit: `/Users/pabs/Sites/COPILOT/claude-copilot/scripts/audit-time-language.sh`
