# Iteration Validation Engine

**Ralph Wiggum Phase 1 Integration**

The Iteration Validation Engine validates completion criteria for agent iterations, ensuring quality gates are met before proceeding to the next iteration.

## Overview

The validation engine supports multiple validator types that can be configured per-agent to verify:
- Command execution (tests, builds, linting)
- Content patterns (promises, documentation structure)
- Coverage thresholds (line, branch, function coverage)
- File existence (required files created)
- Custom validators (extensible for specialized checks)

## Validator Types

### 1. Command Validator

Executes shell commands and checks exit codes.

```typescript
{
  type: 'command',
  name: 'tests_pass',
  description: 'All tests must pass',
  command: 'npm test',
  expectedExitCode: 0,
  timeout: 120000, // 2 minutes in milliseconds
  enabled: true,
  workingDirectory?: '/path/to/project', // Optional
  env?: { NODE_ENV: 'test' } // Optional environment variables
}
```

**Use cases:**
- Running test suites (`npm test`, `pytest`, `cargo test`)
- Building projects (`npm run build`, `make`)
- Linting code (`npm run lint`, `eslint .`)
- Security scans (`npm audit`, `bandit`)

### 2. Content Pattern Validator

Matches regex patterns in agent outputs, task notes, or work products.

```typescript
{
  type: 'content_pattern',
  name: 'promise_complete',
  description: 'Agent declares completion',
  pattern: '<promise>COMPLETE</promise>',
  target: 'agent_output', // 'agent_output' | 'task_notes' | 'work_product_latest'
  flags?: 'i', // Optional regex flags
  mustMatch: true, // true = must match, false = must not match
  enabled: true
}
```

**Use cases:**
- Detecting completion promises from agents
- Verifying documentation structure (headings, code blocks)
- Checking for forbidden patterns (hardcoded secrets)
- Finding required content (decision records, diagrams)

### 3. Coverage Validator

Parses coverage reports and validates thresholds.

```typescript
{
  type: 'coverage',
  name: 'coverage_threshold',
  description: 'Minimum 80% line coverage',
  reportPath: 'coverage/lcov.info',
  reportFormat: 'lcov', // 'lcov' | 'json' | 'cobertura'
  minCoverage: 80, // Percentage (0-100)
  scope?: 'lines', // 'lines' | 'branches' | 'functions' | 'statements'
  enabled: true
}
```

**Supported formats:**
- **LCOV** - Standard coverage format (Jest, Istanbul)
- **JSON** - JSON coverage reports (Jest with `--json`)
- **Cobertura** - XML coverage format (common in Java/Python)

### 4. File Existence Validator

Checks if required files exist.

```typescript
{
  type: 'file_existence',
  name: 'implementation_files',
  description: 'Required files created',
  paths: [
    'src/components/MyComponent.tsx',
    'src/components/MyComponent.test.tsx',
    'src/components/MyComponent.stories.tsx'
  ],
  allMustExist: true, // true = all must exist, false = at least one
  enabled: true
}
```

**Use cases:**
- Verifying implementation files created
- Checking configuration files exist
- Validating generated artifacts

### 5. Custom Validator

Extensible validator for specialized checks.

```typescript
{
  type: 'custom',
  name: 'api_contract_valid',
  description: 'API contract matches schema',
  validatorId: 'openapi_validator',
  config: {
    schemaPath: 'api/openapi.yaml',
    strict: true
  },
  enabled: true
}
```

**Registration:**
```typescript
import { getIterationEngine } from './validation/iteration-engine.js';

const engine = getIterationEngine();

engine.registerCustomValidator('openapi_validator', async (rule, context) => {
  const startTime = Date.now();
  // Custom validation logic here
  const valid = await validateOpenAPI(rule.config);

  return {
    ruleName: rule.name,
    passed: valid,
    message: valid ? 'API contract valid' : 'API contract invalid',
    duration: Date.now() - startTime,
    timestamp: new Date().toISOString(),
  };
});
```

## Configuration

### Agent-Specific Rules

Each agent has its own validation rules defined in `iteration-default-config.ts`:

```typescript
agentRules: {
  qa: {
    agentId: 'qa',
    requireAllPass: true, // All rules must pass
    rules: [
      { type: 'command', name: 'tests_pass', ... },
      { type: 'coverage', name: 'coverage_threshold', ... }
    ]
  },
  me: {
    agentId: 'me',
    requireAllPass: true,
    rules: [
      { type: 'command', name: 'build_succeeds', ... },
      { type: 'command', name: 'lint_passes', ... }
    ]
  }
}
```

**Per-agent configuration:**
- **qa**: Tests pass, coverage thresholds, completion promises
- **me**: Build succeeds, lint passes, implementation files exist
- **sec**: Security scans, no hardcoded secrets
- **do**: Docker builds, config files exist
- **doc**: Code examples, proper structure, README exists
- **ta**: Architecture diagrams, decision records
- **uid**: UI tests pass, component files created

### Global Rules

Rules that apply to all iterations:

```typescript
globalRules: [
  {
    type: 'command',
    name: 'syntax_check',
    command: 'npm run check-syntax',
    expectedExitCode: 0,
    timeout: 30000,
    enabled: true
  }
]
```

### Runtime Configuration

Override defaults at runtime:

```typescript
import { initIterationEngine } from './validation/iteration-engine.js';

initIterationEngine({
  defaultTimeout: 120000, // 2 minutes
  maxConcurrentValidations: 10,
  globalRules: [/* custom global rules */],
  agentRules: {/* custom agent rules */}
});
```

## Usage

### Basic Validation

```typescript
import { getIterationEngine } from './validation/iteration-engine.js';
import { DEFAULT_ITERATION_CONFIG } from './validation/iteration-default-config.js';

const engine = getIterationEngine();
const agentConfig = DEFAULT_ITERATION_CONFIG.agentRules['qa'];

const context = {
  taskId: 'TASK-123',
  workingDirectory: '/path/to/project',
  agentOutput: '<promise>COMPLETE</promise>',
  taskNotes: 'Completed all tests',
  latestWorkProduct: '# Test Plan\n...'
};

const report = await engine.validate(
  agentConfig.rules,
  context,
  'TASK-123',
  1 // iteration number
);

console.log('Validation passed:', report.overallPassed);
console.log('Passed rules:', report.passedRules);
console.log('Failed rules:', report.failedRules);
```

### Validation Result Structure

```typescript
interface IterationValidationReport {
  taskId: string;
  iterationNumber: number;
  results: IterationValidationResult[];
  overallPassed: boolean;
  totalRules: number;
  passedRules: number;
  failedRules: number;
  erroredRules: number;
  totalDuration: number;
  validatedAt: string;
}

interface IterationValidationResult {
  ruleName: string;
  passed: boolean;
  message: string;
  details?: Record<string, unknown>;
  duration: number;
  timestamp: string;
  error?: string;
}
```

### Error Handling

The engine gracefully handles errors:
- Command timeouts → Result with `error` field set
- Missing files → Failed result with descriptive message
- Invalid patterns → Error result with regex error
- Network issues → Error result with network error

Errors don't crash the engine; they return a failed validation result.

## Performance

### Concurrency Control

Rules are validated in batches to prevent overwhelming the system:

```typescript
maxConcurrentValidations: 5 // Process 5 validators at a time
```

### Timeout Management

Each command validator has configurable timeout:

```typescript
{
  type: 'command',
  command: 'npm test',
  timeout: 120000 // 2 minutes
}
```

Global default timeout applies when not specified:

```typescript
defaultTimeout: 60000 // 1 minute
```

### Execution Time Tracking

Each validation result includes duration:

```typescript
{
  ruleName: 'tests_pass',
  duration: 45234, // milliseconds
  // ...
}
```

Total report includes overall duration:

```typescript
{
  totalDuration: 67891, // milliseconds
  // ...
}
```

## Integration with Ralph Wiggum

The validation engine is designed for Ralph Wiggum's iteration loop:

1. **Agent executes iteration** → Produces output, updates task
2. **Validation engine runs** → Checks completion criteria
3. **If passed** → Proceed to next iteration or complete
4. **If failed** → Provide feedback, retry with corrections

### Completion Promises

Agents can declare completion with promises:

```typescript
{
  type: 'content_pattern',
  pattern: '<promise>COMPLETE</promise>',
  target: 'agent_output',
  mustMatch: true
}
```

The agent includes in their output:

```
Implementation complete. All tests passing.

<promise>COMPLETE</promise>
```

### Feedback Loop

Failed validations provide actionable feedback:

```typescript
{
  ruleName: 'tests_pass',
  passed: false,
  message: 'Command exit code mismatch (expected 0, got 1)',
  details: {
    exitCode: 1,
    stderr: 'FAIL src/test.ts\n  × should handle edge case'
  }
}
```

This feedback can be fed back to the agent for correction.

## Best Practices

### Rule Configuration

1. **Enable only necessary rules** - Disable rules not applicable to specific tasks
2. **Set appropriate timeouts** - Balance thoroughness vs speed
3. **Use meaningful names** - Make validation results easy to understand
4. **Provide descriptions** - Help debugging when rules fail

### Content Patterns

1. **Anchor patterns** - Use `^` and `$` for precise matching
2. **Use flags wisely** - `i` for case-insensitive, `m` for multiline
3. **Test patterns** - Validate regex patterns before deploying
4. **Escape special chars** - Properly escape regex metacharacters

### Coverage Thresholds

1. **Start conservative** - Begin with achievable thresholds (60-70%)
2. **Increase gradually** - Ratchet up coverage over time
3. **Scope appropriately** - Lines vs branches vs functions
4. **Consider context** - Different thresholds for different code types

### Error Messages

1. **Be specific** - "Missing test file src/test.ts" vs "File missing"
2. **Include context** - Show expected vs actual values
3. **Suggest fixes** - "Run `npm test` to see details"
4. **Truncate output** - Limit stdout/stderr to 1000 chars

## Troubleshooting

### Command Validators Failing

**Issue**: Commands timeout or fail unexpectedly

**Solutions**:
- Increase timeout: `timeout: 300000` (5 minutes)
- Check working directory: `workingDirectory: '/correct/path'`
- Verify command exists: `which npm` or `command -v npm`
- Check environment: Add required env vars in `env` field

### Coverage Reports Not Found

**Issue**: Coverage validator can't read report

**Solutions**:
- Verify report path: `reportPath: 'coverage/lcov.info'` (relative to working dir)
- Run tests first: Ensure coverage is generated before validation
- Check report format: Use correct parser for your tool (`lcov`, `json`, `cobertura`)

### Pattern Not Matching

**Issue**: Content pattern validator failing unexpectedly

**Solutions**:
- Test pattern: Use regex tester (regex101.com) to verify
- Check target: Ensure `agent_output`, `task_notes`, or `work_product_latest` has content
- Add flags: Try `flags: 'i'` for case-insensitive or `flags: 'm'` for multiline
- Escape properly: Use `\\` for literal backslashes in patterns

### Performance Issues

**Issue**: Validation taking too long

**Solutions**:
- Increase concurrency: `maxConcurrentValidations: 10`
- Reduce timeouts: Lower timeout for fast-failing commands
- Disable slow rules: Set `enabled: false` for non-critical validators
- Use caching: Cache coverage reports, test results

## Future Enhancements

Potential improvements for Phase 2+:

1. **Parallel execution** - Run independent validators in parallel
2. **Caching** - Cache coverage reports and test results
3. **Incremental validation** - Only re-run failed validators
4. **Retry logic** - Auto-retry flaky validators
5. **Metrics** - Track validation success rates, durations
6. **Web UI** - Visual dashboard for validation reports
7. **Notifications** - Alert on validation failures
8. **Historical tracking** - Store validation history in database

## API Reference

### IterationValidationEngine

```typescript
class IterationValidationEngine {
  // Register custom validator
  registerCustomValidator(id: string, validator: CustomValidator): void

  // Validate all rules
  validate(
    rules: IterationValidationRule[],
    context: ValidationContext,
    taskId: string,
    iterationNumber?: number
  ): Promise<IterationValidationReport>
}
```

### Factory Functions

```typescript
// Get singleton instance
function getIterationEngine(): IterationValidationEngine

// Initialize with custom config
function initIterationEngine(config?: Partial<IterationValidationConfig>): void
```

### Validation Context

```typescript
interface ValidationContext {
  taskId: string;
  workingDirectory: string;
  agentOutput?: string;
  taskNotes?: string;
  latestWorkProduct?: string;
}
```

## Examples

See `iteration-default-config.ts` for comprehensive examples of each validator type configured per agent.
