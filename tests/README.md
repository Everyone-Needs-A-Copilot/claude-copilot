# Claude Copilot Test Suite

Comprehensive tests for Claude Copilot framework, covering agent invocation, skill loading, orchestration workflows, and system features.

## Overview

This test suite validates:
- **Agent System:** Assignment, routing, invocation, and specialization
- **Skill System:** Discovery, evaluation, and injection into agent context
- **Orchestration:** PRD/task creation, stream dependencies, parallel execution
- **System Features:** Codebase mapping, hooks, corrections, lifecycle management

## Test Organization

```
tests/
├── TEST_STRATEGY.md                          # Comprehensive test strategy document
├── unit/                                     # Fast, isolated unit tests
│   ├── agent-assignment.test.ts              # Agent validation and routing
│   ├── skill-loading.test.ts                 # Skill discovery and evaluation
│   └── README.md
├── integration/                              # Integration tests with multiple components
│   ├── agent-skill-orchestration.test.ts     # Full workflow tests
│   ├── hooks-evaluation-corrections.test.ts  # Lifecycle hooks and corrections
│   ├── lean-agents-skills.test.ts            # Agent structure validation
│   ├── orchestration-lifecycle.test.ts       # Orchestration workflow
│   └── README.md
├── map-command.test.ts                       # Codebase mapping tests
└── hooks-evaluation-corrections.test.ts      # Legacy hooks test (root level)
```

## Running Tests

### Run All Tests

```bash
cd tests

# Run all unit tests
npx tsx unit/agent-assignment.test.ts
npx tsx unit/skill-loading.test.ts

# Run all integration tests
npx tsx integration/agent-skill-orchestration.test.ts
npx tsx integration/hooks-evaluation-corrections.test.ts
npx tsx integration/lean-agents-skills.test.ts
npx tsx integration/orchestration-lifecycle.test.ts

# Run system tests
npx tsx map-command.test.ts
```

### Run Quick Test Suite (Recommended)

```bash
# Run new agent/skill tests only
./run-agent-tests.sh
```

### Run with Node Test Runner

```bash
node --test tests/**/*.test.ts
```

## Test Structure

### Test Suites

| Suite | Test Count | Coverage |
|-------|-----------|----------|
| Tech Stack Detection | 15+ | Node.js, Rust, Go, Python, multi-language |
| Directory Structure Analysis | 7 | Tree generation, ignored directories, depth limits |
| Key Files Identification | 6 | Config, docs, entry points, depth/limits |
| PROJECT_MAP.md Generation | 17 | Content validation, formatting, sections |
| Refresh Mode | 6 | Preservation, updates, timestamps |
| .gitignore Respect | 4 | Ignored dirs/files, included dirs/files |
| Edge Cases | 9 | Empty projects, large structures, special chars |

**Total: 64+ test cases**

## Test Coverage

### Tech Stack Detection

**Languages Tested:**
- JavaScript/TypeScript (npm, yarn, pnpm)
- Rust (cargo)
- Go (go mod)
- Python (pip, poetry, pipenv)
- Multi-language projects

**Frameworks Tested:**
- Next.js
- React
- Vue
- Express

**Edge Cases:**
- Framework priority (Next.js > React)
- Missing package.json
- Corrupt package.json
- Multi-language detection

### Directory Structure

**Features Tested:**
- Tree command integration
- Find command fallback
- Depth limiting (maxDepth)
- .gitignore patterns
- Ignored directories: node_modules, dist, build, .git, __pycache__, .venv, target, vendor

**Edge Cases:**
- Empty directories
- Large directory structures (100+ dirs)
- Symlinks (no infinite loops)
- Special characters in names

### Key Files Identification

**File Types Detected:**
- Configuration: *.json, *.yaml, *.toml, *.config.*
- Documentation: README*, CLAUDE*, *.md
- Entry Points: main.*, index.*, app.*, cli.*

**Specific Configs Tested:**
- package.json, tsconfig.json
- eslint.config.js, prettier.config.js
- jest.config.ts, webpack.config.js
- tailwind.config.js, next.config.js
- vite.config.ts

**Edge Cases:**
- Empty projects
- Deeply nested files
- Files with spaces and special characters
- .gitignore filtering

### PROJECT_MAP.md Generation

**Structure Validated:**
- Header with project name
- Auto-generation notice
- Timestamp
- Tech Stack table
- Directory Structure code block
- Key Files sections (config, docs, entry points)
- Architecture Notes section with preservation comment

**Formatting Tested:**
- Markdown syntax
- Bullet lists for files
- Relative paths (not absolute)
- Proper table formatting

### Refresh Mode

**Features Tested:**
- Detection of existing PROJECT_MAP.md
- Preservation of Architecture Notes section
- Tech stack updates
- Directory structure updates
- Key files updates
- Timestamp updates

**Edge Cases:**
- Missing architecture notes section
- Malformed existing map

### .gitignore Respect

**Validated Exclusions:**
- node_modules/, dist/, build/, coverage/
- *.log files
- .env files
- .DS_Store

**Validated Inclusions:**
- src/, tests/, docs/
- package.json, README.md
- Config files not in .gitignore

## Test Utilities

### Helper Functions

| Function | Purpose |
|----------|---------|
| `detectTechStack()` | Detect languages, package managers, frameworks |
| `generateDirectoryTree()` | Generate directory structure with ignores |
| `identifyKeyFiles()` | Find config, docs, entry point files |
| `generateProjectMap()` | Create complete PROJECT_MAP.md content |
| `extractArchitectureNotes()` | Extract notes section for preservation |
| `extractTimestamp()` | Parse timestamp from map |

### Test Fixtures

Tests use temporary directories (`mkdtempSync`) with cleanup:
- Created in OS temp directory
- Unique names per test run
- Automatic cleanup in `after()` hooks

## Edge Cases Covered

1. **Empty projects** - No files or directories
2. **No package.json** - Projects without Node.js
3. **Large structures** - 100+ directories
4. **Special characters** - Spaces, dashes, underscores in filenames
5. **Corrupt files** - Invalid JSON in package.json
6. **Symlinks** - No infinite loops
7. **Multi-language** - Multiple tech stacks in one project
8. **Missing sections** - Incomplete PROJECT_MAP.md for refresh
9. **Deep nesting** - Files beyond maxDepth
10. **Platform differences** - Windows vs Unix paths

## Expected Behavior

### Success Criteria

✓ All tech stacks detected correctly
✓ Directory tree respects .gitignore
✓ Key files found within depth limits
✓ PROJECT_MAP.md has all required sections
✓ Refresh preserves architecture notes
✓ No crashes on edge cases
✓ Relative paths used (not absolute)
✓ Proper Markdown formatting

### Failure Scenarios

✗ Includes node_modules in tree
✗ Misses obvious config files
✗ Incorrect framework detection
✗ Overwrites architecture notes
✗ Absolute paths in output
✗ Crashes on empty projects
✗ Hangs on large directories

## Development

### Adding New Tests

1. Add test case to appropriate `describe()` block
2. Use temporary directories for file system operations
3. Clean up in `after()` hooks
4. Test both success and failure paths
5. Validate edge cases

### Test Template

```typescript
it('should <expected behavior>', () => {
  // Setup
  const testDir = mkdtempSync(join(tmpdir(), 'test-'));

  try {
    // Create test files/dirs
    writeFileSync(join(testDir, 'file.txt'), 'content');

    // Execute function
    const result = functionUnderTest(testDir);

    // Assert
    assert.ok(result.someProperty);
    assert.strictEqual(result.value, 'expected');
  } finally {
    // Cleanup
    rmSync(testDir, { recursive: true, force: true });
  }
});
```

## Continuous Integration

### CI Test Runs

```bash
# In CI pipeline
npm test
# or
node --test tests/**/*.test.ts
```

### Coverage Thresholds

Target coverage: 85%+ for all code paths

- Tech stack detection: 90%+
- Directory analysis: 85%+
- File identification: 85%+
- Map generation: 95%+

## Known Limitations

1. **Tree command** - Tests assume `tree` may not be available (uses fallback)
2. **Symlinks** - Tests skip symlink tests on Windows (requires admin)
3. **Large projects** - Tests limited to 100 dirs to prevent timeouts
4. **Semantic search** - Not tested (no semantic layer in map command)

## Future Enhancements

- [ ] Test map command as CLI invocation
- [ ] Test with real-world project structures
- [ ] Performance benchmarks
- [ ] Snapshot testing for map format
- [ ] Integration with Task Copilot
- [ ] Test multilingual projects (Chinese, Arabic, etc.)
- [ ] Test binary files handling
- [ ] Test with various .gitignore patterns

## Related Documentation

- [/map command specification](../.claude/commands/map.md)
- [Testing guidelines](../docs/operations/testing-guide.md)
- [Project structure](../PROJECT_MAP.md)

## Troubleshooting

### Tests Failing Locally

**Issue:** "tree command not found"
**Solution:** Tests automatically fall back to `find` command

**Issue:** Symlink tests failing
**Solution:** Tests skip symlink tests on Windows

**Issue:** Permissions errors
**Solution:** Tests use OS temp directory, check temp dir permissions

### Tests Passing Locally, Failing in CI

**Issue:** Different .gitignore behavior
**Solution:** Verify .gitignore is committed and read correctly

**Issue:** Platform-specific path separators
**Solution:** Use `path.join()` for all path operations

## Contributing

When adding features to `/map` command:

1. Write tests first (TDD)
2. Cover happy path and edge cases
3. Test all tech stack combinations
4. Validate .gitignore respect
5. Update this README with new coverage
