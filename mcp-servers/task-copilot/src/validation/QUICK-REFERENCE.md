# Iteration Validation Quick Reference

## Import

```typescript
import {
  getIterationEngine,
  DEFAULT_ITERATION_CONFIG,
  type ValidationContext,
  type IterationValidationRule
} from './validation/index.js';
```

## Basic Usage

```typescript
const engine = getIterationEngine();

const context: ValidationContext = {
  taskId: 'TASK-123',
  workingDirectory: process.cwd(),
  agentOutput: '<promise>COMPLETE</promise>',
  taskNotes: 'Implementation complete',
  latestWorkProduct: '# Implementation\n...'
};

const report = await engine.validate(
  rules,
  context,
  'TASK-123',
  1 // iteration number
);

console.log('Passed:', report.overallPassed);
```

## Rule Templates

### Command Validator
```typescript
{
  type: 'command',
  name: 'tests_pass',
  command: 'npm test',
  expectedExitCode: 0,
  timeout: 60000,
  enabled: true
}
```

### Content Pattern
```typescript
{
  type: 'content_pattern',
  name: 'check_promise',
  pattern: '<promise>COMPLETE</promise>',
  target: 'agent_output',
  mustMatch: true,
  enabled: true
}
```

### Coverage
```typescript
{
  type: 'coverage',
  name: 'coverage_check',
  reportPath: 'coverage/lcov.info',
  reportFormat: 'lcov',
  minCoverage: 80,
  enabled: true
}
```

### File Existence
```typescript
{
  type: 'file_existence',
  name: 'files_created',
  paths: ['src/index.ts', 'src/test.ts'],
  allMustExist: true,
  enabled: true
}
```

### Custom Validator
```typescript
// 1. Register
engine.registerCustomValidator('my-validator', async (rule, context) => {
  return {
    ruleName: rule.name,
    passed: true,
    message: 'Validation passed',
    duration: 100,
    timestamp: new Date().toISOString()
  };
});

// 2. Use
{
  type: 'custom',
  name: 'custom_check',
  validatorId: 'my-validator',
  config: { /* any config */ },
  enabled: true
}
```

## Agent Rules

```typescript
// Get rules for specific agent
const qaRules = DEFAULT_ITERATION_CONFIG.agentRules['qa'].rules;
const engineerRules = DEFAULT_ITERATION_CONFIG.agentRules['me'].rules;
const securityRules = DEFAULT_ITERATION_CONFIG.agentRules['sec'].rules;
```

## Report Structure

```typescript
report = {
  taskId: 'TASK-123',
  iterationNumber: 1,
  overallPassed: true,
  totalRules: 5,
  passedRules: 5,
  failedRules: 0,
  erroredRules: 0,
  totalDuration: 12345,
  validatedAt: '2025-01-01T00:00:00.000Z',
  results: [
    {
      ruleName: 'tests_pass',
      passed: true,
      message: 'Command executed successfully',
      duration: 2500,
      timestamp: '2025-01-01T00:00:00.000Z',
      details: { /* ... */ }
    }
  ]
}
```

## Common Patterns

### Check if validation passed
```typescript
if (report.overallPassed) {
  // Proceed to next iteration
} else {
  // Provide feedback and retry
}
```

### Get failed rules
```typescript
const failed = report.results
  .filter(r => !r.passed && !r.error)
  .map(r => r.ruleName);
```

### Get error messages
```typescript
const errors = report.results
  .filter(r => r.error)
  .map(r => `${r.ruleName}: ${r.error}`);
```

### Custom timeout
```typescript
{
  type: 'command',
  command: 'npm run build',
  timeout: 300000, // 5 minutes
  // ...
}
```

### Enable/disable rules
```typescript
const customRules = DEFAULT_ITERATION_CONFIG.agentRules['qa'].rules.map(rule => ({
  ...rule,
  enabled: rule.name === 'tests_pass' // Only enable tests_pass
}));
```

## Environment Setup

```typescript
{
  type: 'command',
  command: 'npm test',
  workingDirectory: '/custom/path',
  env: {
    NODE_ENV: 'test',
    CI: 'true'
  },
  // ...
}
```

## Regex Patterns

```typescript
// Case-insensitive
pattern: 'error',
flags: 'i'

// Multiline
pattern: '^# Heading',
flags: 'm'

// Both
flags: 'im'

// Escape special chars
pattern: '\\[required\\]'  // Matches [required]
```

## Coverage Scopes

```typescript
scope: 'lines'      // Line coverage
scope: 'branches'   // Branch coverage
scope: 'functions'  // Function coverage
scope: 'statements' // Statement coverage
```

## Error Handling

All validators handle errors gracefully:

```typescript
// Timeout
{
  error: 'Command timeout after 60000ms',
  passed: false
}

// Command not found
{
  error: 'command not found: nonexistent',
  passed: false
}

// File not found
{
  error: 'ENOENT: no such file or directory',
  passed: false
}

// Invalid pattern
{
  error: 'Invalid regular expression',
  passed: false
}
```

## Configuration Override

```typescript
import { initIterationEngine } from './validation/index.js';

initIterationEngine({
  defaultTimeout: 120000,
  maxConcurrentValidations: 10,
  globalRules: [
    {
      type: 'command',
      name: 'global_check',
      command: 'npm run verify',
      expectedExitCode: 0,
      timeout: 30000,
      enabled: true
    }
  ]
});
```

## See Also

- Full documentation: `ITERATION-VALIDATION.md`
- Examples: `iteration-example.ts`
- Default config: `iteration-default-config.ts`
