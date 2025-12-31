# Task Copilot Testing Guide

Quick reference for running integration tests.

## Quick Start

```bash
cd mcp-servers/task-copilot
npm run test:full
```

## Test Suites

### Full Integration Tests
Comprehensive test suite covering all MCP tools (24 tests).

```bash
npm run test:full
```

**Coverage**: PRD lifecycle, task management, work products, checkpoints, iterations, hooks, progress summary, error handling

**Duration**: ~5-10 seconds

### Iteration Tests
Focused tests for Ralph Wiggum iteration system.

```bash
npm run test:integration
```

**Coverage**: Iteration start/validate/next/complete, hooks, safety guards

**Duration**: ~3-5 seconds

## Test Files

| File | Purpose | Tests |
|------|---------|-------|
| `full-integration.test.ts` | Complete MCP tool coverage | 24 |
| `iteration.integration.test.ts` | Iteration system focused | 9 |
| `iteration-guards.test.ts` | Safety guard unit tests | Multiple |
| `stop-hooks.test.ts` | Hook system unit tests | Multiple |
| `session-guard.test.ts` | Session guard unit tests | Multiple |

## Running Specific Tests

### Build Only
```bash
npm run build
```

### Run Specific Test File
```bash
npm run build
node dist/tools/full-integration.test.js
node dist/tools/iteration.integration.test.js
```

### Using Test Runner Script
```bash
chmod +x run-integration-tests.sh
./run-integration-tests.sh
```

## Expected Output

### Success
```
======================================================================
TASK COPILOT COMPREHENSIVE INTEGRATION TESTS
======================================================================

1. PRD Create
============================================================
  ✓ Created PRD: PRD-xxxxx
  ✓ Title: User Authentication System
  ✓ Status: active
✅ PASS: PRD Create

[... 22 more tests ...]

======================================================================
TEST SUMMARY
======================================================================
Total tests: 24
Passed: 24 ✅
Failed: 0 ❌
Duration: 5.23s
======================================================================

🎉 ALL TESTS PASSED! 🎉
```

### Failure
```
❌ FAIL: Task Create
   Error: Assertion failed: Task should have an ID

======================================================================
TEST EXECUTION HALTED
======================================================================
Tests run before failure: 4
Passed: 3 ✅
Failed: 1 ❌
Duration: 1.45s
======================================================================
```

## Test Coverage

| Area | Coverage |
|------|----------|
| PRD Tools | 100% (3/3) |
| Task Tools | 100% (4/4) |
| Work Product Tools | 100% (3/3) |
| Initiative Tools | 100% (2/2) |
| Checkpoint Tools | 100% (5/5) |
| Iteration Tools | 100% (4/4) |
| Hook Tools | 100% (4/4) |
| Error Handling | 100% |

**Total**: 25 tools tested

## Debugging Failed Tests

### Enable Debug Logging
```bash
LOG_LEVEL=debug npm run test:full
```

### Check Database State
Tests create temporary databases in `/tmp/task-copilot-test-*`

### Common Issues

1. **Build Errors**: Run `npm run build` first
2. **Module Not Found**: Check `node_modules` installed (`npm install`)
3. **TypeScript Errors**: Check `tsconfig.json` is correct
4. **Database Locked**: Close other connections to test databases

## CI/CD Integration

### GitHub Actions Example
```yaml
name: Test Task Copilot

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-node@v2
        with:
          node-version: '18'
      - run: npm install
      - run: npm run test:full
```

### Pre-commit Hook
```bash
#!/bin/bash
# .git/hooks/pre-commit
cd mcp-servers/task-copilot
npm run test:full || exit 1
```

## Adding New Tests

### Template
```typescript
async function testNewFeature(): Promise<void> {
  const db = createTestDatabase();

  try {
    setupInitiative(db);

    // Test logic here
    const result = await myNewTool(db, input);

    assert(result.id !== undefined, 'Should have ID');
    console.log(`  ✓ Test passed`);
  } finally {
    db.close();
  }
}
```

### Register Test
```typescript
// In runAllTests()
await runTest('New Feature Test', testNewFeature);
```

## Performance Benchmarking

```bash
# Run with timing
time npm run test:full

# Expected: < 10 seconds
```

## Documentation

- **Test Plan**: `INTEGRATION-TEST-PLAN.md`
- **Test Results**: `TEST-RESULTS.md`
- **Task Copilot README**: `README.md`

## Support

For test failures or questions:
1. Check `TEST-RESULTS.md` for known issues
2. Review `INTEGRATION-TEST-PLAN.md` for expected behavior
3. Enable debug logging: `LOG_LEVEL=debug`
4. Check MCP server README for tool documentation
