# Test Strategy: Agent/Skill Framework

**Task:** Comprehensive unit tests covering agent invocation, skill loading, and orchestration workflows.

**Context:** Recent changes ensure specialized agents are invoked (not bypassed) during orchestration, and skills are auto-fired from their `description` field (primary path) or discovered via `cc skill search` (fallback). The `skill_evaluate` MCP tool is removed; discovery is now handled by native Claude Code reading skill frontmatter.

---

## Test Coverage Objectives

### Coverage Targets
- **Agent Invocation:** 90%+ (critical path)
- **Skill Loading:** 85%+ (integration points)
- **Orchestration:** 85%+ (workflow validation)
- **Integration:** 80%+ (end-to-end scenarios)

### Key Risk Areas
1. Agents bypassed during orchestration (generic responses instead of specialized)
2. Skills not loaded when context triggers them
3. `assignedAgent` field ignored or misused
4. Agent routing chains broken (sd → uxd → uids → uid)

---

## Test Suites

### Suite A: Agent Invocation Tests

**Objective:** Ensure specialized agents are invoked correctly during orchestration.

**Test Cases:**

1. **Agent Assignment Validation**
   - [ ] Task with `assignedAgent: "me"` invokes @agent-me
   - [ ] Task with `assignedAgent: "qa"` invokes @agent-qa
   - [ ] Task with `assignedAgent: "sd"` invokes @agent-sd
   - [ ] Task without `assignedAgent` defaults to @agent-ta
   - [ ] Invalid `assignedAgent` value throws error

2. **Agent Routing Chains**
   - [ ] @agent-sd routes to @agent-uxd when UX needed
   - [ ] @agent-uxd routes to @agent-uids when visual design needed
   - [ ] @agent-uids routes to @agent-uid when implementation needed
   - [ ] @agent-me routes to @agent-qa when tests needed
   - [ ] Any agent routes to @agent-sec when security needed

3. **Orchestration Agent Selection**
   - [ ] Worker prompt includes correct agent invocation syntax
   - [ ] Parallel workers maintain agent specialization
   - [ ] Stream context preserves agent assignment
   - [ ] Agent handoffs recorded in Task Copilot

4. **Agent Bypass Detection**
   - [ ] Generic responses without agent invocation detected
   - [ ] Missing "Co-Authored-By" in work products flagged
   - [ ] Agent-specific output format validated
   - [ ] Work product type matches assigned agent

**Test Data:**
```json
{
  "taskId": "TASK-test-123",
  "title": "Implement login API",
  "assignedAgent": "me",
  "metadata": {
    "streamId": "Stream-A",
    "files": ["src/auth/login.ts"]
  }
}
```

**Expected Behavior:**
- Orchestrator generates prompt: "Invoke @agent-me to implement login API"
- Work product stored with `agent_id: "me"`
- Agent handoff chain: ta → me → qa

---

### Suite B: Skill Loading Tests

**Objective:** Validate skill auto-firing (primary) and `cc skill search` discovery (fallback).

**Current Mechanism:** Skills auto-fire via native Claude Code reading the `description` field in each SKILL.md frontmatter. `cc skill search` is the fallback for agents in subagent contexts or explicit lookup. `skill_evaluate` (MCP tool) is removed.

**Test Cases:**

1. **Skill Frontmatter Validity** (pytest — `tests/test_skill_frontmatter.py`)
   - [ ] All SKILL.md files have a `name` field (not `skill_name`)
   - [ ] All have a `description` field (the auto-fire trigger surface)
   - [ ] All have a `version` field
   - [ ] Code-bearing skills (v2.x) have `allowed-tools` including `Bash`
   - [ ] No frontmatter references removed fields (`skill_name`, `trigger_files`, `trigger_keywords` are legacy-harmless but not required)

2. **cc skill CLI Discovery**
   - [ ] `cc skill list` returns all skills in `.claude/skills/`
   - [ ] `cc skill search "<keyword>"` returns matching skills by substring match on name + description
   - [ ] `cc skill get <name>` returns SKILL.md content

3. **Code-Bearing Script Validity** (pytest — `tests/test_parser_unit.py` and per-skill tests)
   - [ ] L3 scripts accept stdin (`-`) and file-path inputs
   - [ ] Valid input exits 0 with JSON + markdown output
   - [ ] Invalid input exits 1 with stderr message
   - [ ] Empty input exits 0 with empty-findings structure

4. **Skill Template Validation**
   - [ ] SKILL.md has all required L1/L2/L3 sections
   - [ ] Code-bearing skills have an Invocation section
   - [ ] Scripts are in `scripts/` subdirectory

**Expected Behavior:**
- Skills auto-fire when prompt context matches `description` field
- `cc skill search` used as explicit fallback
- L3 scripts invoked via `Bash` tool, output consumed directly

---

### Suite C: Orchestration Workflow Tests

**Objective:** Validate end-to-end orchestration from PRD generation to task execution.

**Test Cases:**

1. **PRD → Task → Agent Assignment Flow**
   - [ ] `/orchestrate generate` creates PRD in Task Copilot
   - [ ] Tasks created with `assignedAgent` field
   - [ ] Tasks include stream metadata (streamId, dependencies)
   - [ ] Stream dependencies validated (no cycles)
   - [ ] Foundation streams have empty dependencies

2. **Stream Execution Order**
   - [ ] Foundation streams start immediately
   - [ ] Parallel streams wait for dependencies
   - [ ] Integration streams wait for all parallels
   - [ ] Stream progress tracked per task
   - [ ] Completion detection works (100%)

3. **Worker Prompt Generation**
   - [ ] Worker prompt includes agent invocation
   - [ ] Prompt includes task context and files
   - [ ] Prompt includes skill loading hints
   - [ ] Prompt preserves assignedAgent value

4. **Parallel Execution**
   - [ ] Independent streams run simultaneously
   - [ ] File conflicts detected via stream_conflict_check
   - [ ] Dependency resolution correct
   - [ ] Progress tracked per stream

5. **Stream Archival on Initiative Switch**
   - [ ] Old streams archived when switching initiatives
   - [ ] `stream_list()` filters by current initiative
   - [ ] `stream_unarchive()` recovers archived streams
   - [ ] Archived streams not shown in watch-status

**Test Data:**
```json
// PRD structure
{
  "id": "PRD-test-001",
  "title": "User Authentication Feature",
  "streams": [
    {
      "streamId": "Stream-A",
      "streamName": "Foundation",
      "dependencies": []
    },
    {
      "streamId": "Stream-B",
      "streamName": "OAuth Integration",
      "dependencies": ["Stream-A"]
    }
  ]
}

// Task structure
{
  "id": "TASK-test-001",
  "prdId": "PRD-test-001",
  "assignedAgent": "me",
  "metadata": {
    "streamId": "Stream-A",
    "streamDependencies": [],
    "files": ["src/auth/types.ts"]
  }
}
```

**Expected Behavior:**
- @agent-ta creates PRD and tasks
- Tasks have correct assignedAgent
- Stream dependencies validated
- Workers spawned in correct order
- Agent specialization preserved

---

### Suite D: Integration Tests

**Objective:** Full workflow validation from user request to completed work products.

**Test Cases:**

1. **Full Orchestration Lifecycle**
   - [ ] User runs `/orchestrate generate`
   - [ ] @agent-ta creates PRD with 3 streams
   - [ ] Tasks created with correct agents: me, qa, doc
   - [ ] `/orchestrate start` spawns workers
   - [ ] Workers invoke specialized agents
   - [ ] Work products stored per agent
   - [ ] Progress tracked to 100%
   - [ ] Initiative marked complete

2. **Multi-Agent Collaboration**
   - [ ] @agent-sd creates experience strategy
   - [ ] Routes to @agent-uxd for interaction design
   - [ ] Routes to @agent-uids for visual design
   - [ ] Routes to @agent-uid for implementation
   - [ ] Handoff chain recorded in Task Copilot
   - [ ] Final consolidation by @agent-uid

3. **Skill Auto-Fire + Agent Invocation**
   - [ ] Task assigned to @agent-me
   - [ ] Worker invokes @agent-me
   - [ ] Skills auto-fire from description match (python-idioms, testing-patterns) or agent uses `cc skill search` fallback
   - [ ] Code written following skill patterns
   - [ ] Tests pass (validated via iteration loop)
   - [ ] Work product stored with agent_id

4. **Error Handling**
   - [ ] Missing assignedAgent defaults gracefully
   - [ ] Invalid agent name throws error
   - [ ] Circular dependencies detected
   - [ ] Missing skills logged but not fatal
   - [ ] Agent routing failures logged

**Test Scenarios:**

**Scenario 1: Feature Implementation**
```
Input: "Implement OAuth login with Google"
Expected Flow:
  1. @agent-ta creates PRD
  2. Stream-A (Foundation) → @agent-me: DB schema
  3. Stream-B (OAuth) → @agent-me: OAuth integration
  4. Stream-C (Tests) → @agent-qa: Integration tests
  5. Stream-D (Docs) → @agent-doc: API documentation
  6. All agents invoked correctly
  7. Skills loaded per agent: me=python-idioms, qa=testing-patterns
```

**Scenario 2: Bug Fix**
```
Input: "Fix authentication token expiry bug"
Expected Flow:
  1. @agent-qa reproduces bug
  2. Routes to @agent-me for fix
  3. @agent-me loads relevant skills
  4. Implements fix with tests
  5. @agent-qa validates fix
  6. Work products stored
```

**Scenario 3: UI Feature**
```
Input: "Design and implement dashboard UI"
Expected Flow:
  1. @agent-sd: Experience strategy
  2. @agent-uxd: Interaction design
  3. @agent-uids: Visual design
  4. @agent-uid: Implementation
  5. Routing chain preserved
  6. Skills loaded at each step
```

---

## Test Implementation

### Test Framework
- **Language:** TypeScript (for TS/Node.js codebase)
- **Runner:** Node.js built-in test runner (no external dependencies)
- **Structure:** Self-contained test files with assertion helpers

### Test File Organization
```
tests/
├── unit/
│   ├── agent-assignment.test.ts
│   ├── skill-discovery.test.ts
│   ├── skill-evaluation.test.ts
│   └── stream-dependencies.test.ts
├── integration/
│   ├── agent-invocation.test.ts
│   ├── skill-loading.test.ts
│   ├── orchestration-workflow.test.ts
│   └── multi-agent-collaboration.test.ts
└── e2e/
    └── full-orchestration.test.ts
```

### Test Utilities
```typescript
// tests/utils/test-helpers.ts
export function createMockTask(overrides?: Partial<Task>): Task;
export function createMockPRD(overrides?: Partial<PRD>): PRD;
export function createMockSkill(overrides?: Partial<Skill>): Skill;
export function assertAgentInvoked(workProduct: WorkProduct, agentId: string): void;
export function assertSkillLoaded(agentOutput: string, skillName: string): void;
```

### Mock Data
```typescript
// tests/fixtures/agents.ts
export const MOCK_AGENTS = {
  me: { id: 'me', name: 'Engineer', tools: [...] },
  qa: { id: 'qa', name: 'QA Engineer', tools: [...] },
  sd: { id: 'sd', name: 'Service Designer', tools: [...] }
};

// tests/fixtures/skills.ts
export const MOCK_SKILLS = {
  'python-idioms': { skill_name: 'python-idioms', trigger_files: ['*.py'] },
  'testing-patterns': { skill_name: 'testing-patterns', trigger_files: ['*.test.*'] }
};

// tests/fixtures/tasks.ts
export const MOCK_TASKS = {
  codeTask: { assignedAgent: 'me', title: 'Implement login' },
  testTask: { assignedAgent: 'qa', title: 'Write tests' }
};
```

---

## Test Execution

### Run All Tests
```bash
cd tests
node --test **/*.test.ts
```

### Run Specific Suite
```bash
# Agent invocation tests only
node --test tests/unit/agent-assignment.test.ts

# Integration tests only
node --test tests/integration/**/*.test.ts
```

### Coverage Report
```bash
node --test --experimental-test-coverage tests/**/*.test.ts
```

### CI/CD Integration
```yaml
# .github/workflows/test.yml
- name: Run Tests
  run: |
    cd tests
    npm install -g tsx
    node --test **/*.test.ts
```

---

## Success Criteria

### Test Pass Rate
- [ ] 100% of unit tests pass
- [ ] 95%+ of integration tests pass
- [ ] 90%+ of e2e tests pass

### Coverage Metrics
- [ ] Agent invocation: 90%+ coverage
- [ ] Skill loading: 85%+ coverage
- [ ] Orchestration: 85%+ coverage
- [ ] Integration: 80%+ coverage

### Quality Gates
- [ ] No agent bypass in orchestration
- [ ] All skills have valid frontmatter (`name` + `description`) and are discoverable via `cc skill search`
- [ ] Stream dependencies validated
- [ ] Agent routing chains preserved

### Performance
- [ ] Unit tests: < 100ms each
- [ ] Integration tests: < 1s each
- [ ] E2E tests: < 10s each
- [ ] Full suite: < 60s

---

## Known Limitations

1. **No Live CLI Mocking:** Tests use mock implementations (MockTaskCopilot). ST-01/ST-02 smoke tests cover the live `cc`/`tc` CLI layer.
2. **File System Dependencies:** Some tests create/modify files (require cleanup)
3. **Agent Invocation:** Cannot fully test Claude agent responses (mock responses used)
4. **Parallel Execution:** Orchestration tests run sequentially (no actual parallel workers)

---

## Future Enhancements

- [ ] Add snapshot testing for agent outputs
- [ ] Performance benchmarks for skill loading
- [ ] Fuzz testing for skill description matching patterns
- [ ] Contract testing for `tc`/`cc` CLI API surface
- [ ] Property-based testing for stream dependencies
- [ ] Chaos testing for orchestration failures

---

## References

- **Existing Tests:** `tests/`
- **Insights Copilot Tests:** `../insights-copilot/tests/`
- **Orchestration Docs:** `.claude/commands/orchestrate.md`
- **Agent Specs:** `.claude/agents/*.md`
- **Skill Specs:** `.claude/skills/*/SKILL.md`
