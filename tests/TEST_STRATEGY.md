# Test Strategy: Agent/Skill Framework

**Task:** Comprehensive unit tests covering agent invocation, skill loading, and orchestration workflows.

**Context:** Recent changes ensure specialized agents are invoked (not bypassed) during orchestration, and skills are properly loaded via skill_evaluate.

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

**Objective:** Validate skill_evaluate auto-detection and skill injection into agent context.

**Test Cases:**

1. **Global Skill Discovery**
   - [ ] Skills in `~/.claude/skills/` discovered
   - [ ] Skills have valid frontmatter (skill_name, trigger_files, trigger_keywords)
   - [ ] Skills sorted by confidence score
   - [ ] Token estimates within budget (< 3000 tokens/skill)

2. **Local Skill Override**
   - [ ] Project skills in `.claude/skills/` take precedence
   - [ ] Same skill_name in local overrides global
   - [ ] Both local and global skills available
   - [ ] Override warning logged

3. **skill_evaluate Auto-Detection**
   - [ ] File patterns match: `*.test.ts` triggers testing skills
   - [ ] Keywords match: "authentication" triggers auth skills
   - [ ] Combined signals boost confidence
   - [ ] Recent activity weighted in scoring
   - [ ] Threshold filtering works (default 0.5)

4. **Skill Injection into Agent Context**
   - [ ] Agent includes skill_evaluate in tools list
   - [ ] Skill Loading Protocol section present
   - [ ] Skills loaded before task execution
   - [ ] Multiple skills loaded when relevant
   - [ ] Token budget respected (max 3 skills)

5. **Skill Template Validation**
   - [ ] SKILL-TEMPLATE.md has all required sections
   - [ ] Core Patterns section present
   - [ ] Anti-Patterns section present
   - [ ] Validation Checklist present
   - [ ] Code examples present (at least 2 blocks)

**Test Data:**
```typescript
// skill_evaluate input
{
  files: ['src/auth/login.test.ts'],
  text: 'Help with React testing patterns',
  threshold: 0.5
}

// Expected output
{
  matches: [
    { skillName: 'testing-patterns', confidence: 0.85, level: 'high' },
    { skillName: 'react-patterns', confidence: 0.72, level: 'high' },
    { skillName: 'javascript-patterns', confidence: 0.45, level: 'medium' }
  ]
}
```

**Expected Behavior:**
- Top 2-3 skills loaded (above threshold)
- Skills injected via @include directive
- Agent frontmatter lists skill_evaluate tool
- Skill Loading Protocol section validates context

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

3. **Skill Loading + Agent Invocation**
   - [ ] Task assigned to @agent-me
   - [ ] Worker invokes @agent-me
   - [ ] @agent-me calls skill_evaluate
   - [ ] Skills loaded: python-idioms, testing-patterns
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
cd /Users/pabs/Sites/COPILOT/claude-copilot/tests
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
- [ ] All skills discoverable via skill_evaluate
- [ ] Stream dependencies validated
- [ ] Agent routing chains preserved

### Performance
- [ ] Unit tests: < 100ms each
- [ ] Integration tests: < 1s each
- [ ] E2E tests: < 10s each
- [ ] Full suite: < 60s

---

## Known Limitations

1. **No MCP Server Mocking:** Tests run against actual MCP servers (Task Copilot, Skills Copilot)
2. **File System Dependencies:** Some tests create/modify files (require cleanup)
3. **Agent Invocation:** Cannot fully test Claude agent responses (mock responses used)
4. **Parallel Execution:** Orchestration tests run sequentially (no actual parallel workers)

---

## Future Enhancements

- [ ] Add snapshot testing for agent outputs
- [ ] Performance benchmarks for skill loading
- [ ] Fuzz testing for skill_evaluate patterns
- [ ] Contract testing for MCP server APIs
- [ ] Property-based testing for stream dependencies
- [ ] Chaos testing for orchestration failures

---

## References

- **Existing Tests:** `/Users/pabs/Sites/COPILOT/claude-copilot/tests/`
- **Insights Copilot Tests:** `/Users/pabs/Sites/COPILOT/insights-copilot/tests/`
- **Orchestration Docs:** `.claude/commands/orchestrate.md`
- **Agent Specs:** `.claude/agents/*.md`
- **Skill Specs:** `.claude/skills/*/SKILL.md`
