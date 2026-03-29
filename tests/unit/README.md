# Unit Tests

Focused tests for individual components and functions in the Claude Copilot framework.

## Test Files

### agent-assignment.test.ts

**Purpose:** Test agent assignment validation and invocation logic.

**Coverage:**
- Agent assignment validation (valid/invalid agents)
- Agent routing chains (sd → uxd → uids → uid)
- Worker prompt generation
- Agent bypass detection
- Agent file structure validation

**Run:**
```bash
npx tsx tests/unit/agent-assignment.test.ts
```

**Test Suites:**
1. **Agent Assignment Validation** - Validates agent names and defaults
2. **Agent Routing Chains** - Tests valid/invalid agent handoffs
3. **Worker Prompt Generation** - Ensures prompts include agent invocations
4. **Agent Bypass Detection** - Detects generic responses without agent routing
5. **Agent File Structure** - Validates agent markdown files have required sections

**Expected Output:**
```
======================================================================
  UNIT TESTS: AGENT ASSIGNMENT AND INVOCATION
======================================================================

📋 Testing Agent Assignment Validation...

✅ Valid agent assignment: me (2ms)
✅ Valid agent assignment: qa (1ms)
✅ Valid agent assignment: sec (1ms)
✅ Unassigned task defaults to ta (1ms)
✅ Invalid agent assignment rejected (2ms)
✅ All valid agents accepted (3ms)

🔄 Testing Agent Routing Chains...

✅ sd → uxd routing valid (1ms)
✅ uxd → uids routing valid (1ms)
✅ uids → uid routing valid (1ms)
✅ me → qa routing valid (1ms)
✅ me → sec routing valid (1ms)
✅ All agents can route to ta (2ms)
✅ Invalid routing: qa → sd rejected (1ms)
✅ Invalid routing: doc → me rejected (1ms)

📝 Testing Worker Prompt Generation...

✅ Prompt includes agent invocation (2ms)
✅ Prompt includes task title (1ms)
✅ Prompt includes task context (1ms)
✅ Prompt includes files when present (1ms)
✅ Unassigned task defaults to ta in prompt (1ms)
✅ Agent invocation extractable from prompt (1ms)

🚨 Testing Agent Bypass Detection...

✅ Work product with correct agent_id passes (1ms)
✅ Work product with mismatched agent_id fails (1ms)
✅ Work product type matches agent specialty (1ms)
✅ Generic response without agent invocation detected (1ms)
✅ Proper agent response includes invocation (1ms)

📁 Testing Agent File Structure...

✅ All agents have skill_evaluate tool (5ms)
✅ All agents have Skill Loading Protocol section (4ms)
✅ All agents include preflight_check tool (3ms)

======================================================================
  TEST SUMMARY
======================================================================

✅ Passed: 28
❌ Failed: 0
⏭️  Skipped: 0
📊 Total: 28

✅ ALL TESTS PASSED
```

---

### skill-loading.test.ts

**Purpose:** Test skill discovery, evaluation, and injection.

**Coverage:**
- Global skill discovery (`.claude/skills/`)
- Skill frontmatter validation
- skill_evaluate pattern matching (files + keywords)
- Confidence scoring and threshold filtering
- Skill injection into agent context

**Run:**
```bash
npx tsx tests/unit/skill-loading.test.ts
```

**Test Suites:**
1. **Skill Discovery** - Validates skills have proper structure
2. **Skill Evaluation** - Tests pattern matching and confidence scoring
3. **Skill Injection** - Validates skill loading into agent context

**Expected Output:**
```
======================================================================
  UNIT TESTS: SKILL LOADING AND EVALUATION
======================================================================

🔍 Testing Skill Discovery...

✅ Skills directory exists (2ms)
✅ Skills have valid frontmatter (12ms)
✅ Skills have code examples (8ms)
✅ Skills have token estimates within budget (6ms)

🎯 Testing Skill Evaluation...

✅ File pattern matching: Python files (3ms)
✅ File pattern matching: Test files (2ms)
✅ Keyword matching: React components (2ms)
✅ Combined signals: TypeScript testing (3ms)
✅ Threshold filtering works (2ms)
✅ Confidence levels categorized correctly (2ms)
✅ Recent activity boosts confidence (3ms)
✅ Limit parameter restricts results (2ms)

💉 Testing Skill Injection...

✅ Skill templates have required structure (2ms)
✅ Skills loaded via @include directive (1ms)
✅ Token budget respected: max 3 skills (1ms)

======================================================================
  TEST SUMMARY
======================================================================

✅ Passed: 15
❌ Failed: 0
⏭️  Skipped: 0
📊 Total: 15

✅ ALL TESTS PASSED
```

---

## Running All Unit Tests

```bash
# Run all unit tests (from repo root)
npx tsx tests/unit/agent-assignment.test.ts && \
npx tsx tests/unit/skill-loading.test.ts

# Or run via node test runner (if configured)
node --test tests/unit/**/*.test.ts
```

## Test Coverage

### Agent Assignment Tests (28 tests)
- ✅ Agent validation: 6 tests
- ✅ Routing chains: 8 tests
- ✅ Prompt generation: 6 tests
- ✅ Bypass detection: 5 tests
- ✅ File structure: 3 tests

### Skill Loading Tests (15 tests)
- ✅ Skill discovery: 4 tests
- ✅ Skill evaluation: 8 tests
- ✅ Skill injection: 3 tests

**Total: 43 unit tests**

## Key Assertions

### Agent Assignment
- All valid agents accepted (me, qa, sec, doc, do, sd, uxd, uids, uid, cw, ta)
- Invalid agent names rejected
- Unassigned tasks default to @agent-ta
- Routing chains follow specialization hierarchy
- Worker prompts include agent invocations
- Work products match assigned agents

### Skill Loading
- Skills have required frontmatter (skill_name, trigger_files, trigger_keywords)
- File patterns match correctly (*.py → python-idioms, *.test.* → testing-patterns)
- Keywords match text content
- Confidence scores calculated correctly
- Threshold filtering works
- Token budgets respected (< 3000 tokens per skill)

## Adding New Tests

1. Create test file: `tests/unit/your-feature.test.ts`
2. Import test framework (or copy from existing tests)
3. Define test suites with `async function testYourFeature()`
4. Use assertion helpers: `assert()`, `assertEquals()`, `assertContains()`
5. Run tests via `npx tsx tests/unit/your-feature.test.ts`

## Test Template

```typescript
async function testYourFeature() {
  console.log('\n🧪 Testing Your Feature...\n');

  await runTest('Test description', () => {
    // Setup
    const input = { /* ... */ };

    // Execute
    const result = functionUnderTest(input);

    // Assert
    assertEquals(result.value, 'expected', 'Should return expected value');
  });
}
```

## CI/CD Integration

```yaml
# .github/workflows/test.yml
- name: Run Unit Tests
  run: |
    npm install -g tsx
    npx tsx tests/unit/agent-assignment.test.ts
    npx tsx tests/unit/skill-loading.test.ts
```

## Dependencies

- **tsx:** TypeScript execution (install: `npm install -g tsx`)
- **Node.js:** Built-in modules (fs, path)
- **No external test frameworks:** Self-contained assertions

## See Also

- [Test Strategy](../TEST_STRATEGY.md)
- [Integration Tests](../integration/README.md)
- [Main Tests README](../README.md)

---

*Updated: January 2026*
