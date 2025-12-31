# Iteration Configuration Schema

JSON Schema and TypeScript validator for Ralph Wiggum iteration configurations.

## Overview

The iteration configuration schema validates hook configurations passed to `iteration_start`. It ensures that iteration loops have proper validation rules, completion signals, and safety guardrails.

## Files

- **`iteration-config.schema.json`**: JSON Schema (draft-07) defining the structure and constraints
- **`../src/validation/iteration-config-validator.ts`**: TypeScript validator using AJV
- **`../src/validation/iteration-config-validator.test.ts`**: Comprehensive test suite

## Schema Structure

### Required Fields

```typescript
{
  maxIterations: number;        // 1-100
  completionPromises: string[]; // Min 1 item, format: <promise>WORD</promise>
}
```

### Optional Fields

```typescript
{
  validationRules?: ValidationRule[];
  circuitBreakerThreshold?: number; // 1-20, default: 3
}
```

## Validation Rules

### Command Rule

Execute shell command and check exit code.

```typescript
{
  type: 'command',
  name: 'tests_pass',
  config: {
    command: string;              // Required
    expectedExitCode?: number;    // Default: 0
    successExitCodes?: number[];  // Alternative to expectedExitCode
    timeout?: number;             // 1000-600000ms, default: 60000
    workingDirectory?: string;
    env?: Record<string, string>;
  }
}
```

**Example:**
```typescript
{
  type: 'command',
  name: 'tests_pass',
  config: {
    command: 'npm test',
    expectedExitCode: 0,
    timeout: 120000
  }
}
```

### Content Pattern Rule

Regex matching in output.

```typescript
{
  type: 'content_pattern',
  name: 'promise_complete',
  config: {
    pattern: string;                                          // Required, regex pattern
    target: 'agent_output' | 'task_notes' | 'work_product_latest'; // Required
    flags?: string;                                           // Regex flags (i, m, g, etc.)
    mustMatch?: boolean;                                      // Default: true
  }
}
```

**Example:**
```typescript
{
  type: 'content_pattern',
  name: 'has_code_examples',
  config: {
    pattern: '```[\\s\\S]*?```',
    target: 'work_product_latest',
    mustMatch: true
  }
}
```

### Coverage Rule

Parse coverage reports and validate thresholds.

```typescript
{
  type: 'coverage',
  name: 'coverage_threshold',
  config: {
    minCoverage: number;                                // Required, 0-100
    format: 'lcov' | 'json' | 'cobertura';             // Required
    reportPath?: string;
    scope?: 'lines' | 'branches' | 'functions' | 'statements'; // Default: lines
  }
}
```

**Example:**
```typescript
{
  type: 'coverage',
  name: 'coverage_threshold',
  config: {
    minCoverage: 80,
    format: 'lcov',
    reportPath: 'coverage/lcov.info',
    scope: 'lines'
  }
}
```

### File Existence Rule

Check if files exist.

```typescript
{
  type: 'file_existence',
  name: 'implementation_files',
  config: {
    paths: string[];        // Required, min 1 item
    allMustExist?: boolean; // Default: true
  }
}
```

**Example:**
```typescript
{
  type: 'file_existence',
  name: 'test_files_created',
  config: {
    paths: ['src/feature.test.ts', 'src/feature.ts'],
    allMustExist: true
  }
}
```

### Custom Rule

Invoke custom validator.

```typescript
{
  type: 'custom',
  name: 'custom_validator',
  config: {
    validatorId: string;  // Required, alphanumeric + hyphens/underscores
    [key: string]: any;   // Additional custom parameters
  }
}
```

**Example:**
```typescript
{
  type: 'custom',
  name: 'security_scan',
  config: {
    validatorId: 'my-security-validator',
    scanLevel: 'strict'
  }
}
```

## Usage

### TypeScript Validation

```typescript
import {
  validateIterationConfig,
  validateIterationConfigOrThrow
} from './validation/iteration-config-validator.js';

// Option 1: Get validation result
const result = validateIterationConfig({
  maxIterations: 15,
  completionPromises: ['<promise>COMPLETE</promise>'],
  validationRules: [
    {
      type: 'command',
      name: 'tests_pass',
      config: { command: 'npm test' }
    }
  ]
});

if (!result.valid) {
  console.error('Validation errors:', result.errors);
} else {
  console.log('Valid config:', result.config);
}

// Option 2: Throw on error
try {
  const config = validateIterationConfigOrThrow({
    maxIterations: 15,
    completionPromises: ['<promise>COMPLETE</promise>']
  });
  // Use config...
} catch (error) {
  console.error('Invalid configuration:', error.message);
}
```

### Integration with iteration_start

```typescript
import { iterationStart } from './tools/iteration.js';
import { validateIterationConfigOrThrow } from './validation/iteration-config-validator.js';

export function iterationStartWithValidation(db, input) {
  // Validate configuration
  const validConfig = validateIterationConfigOrThrow(input);

  // Proceed with iteration start
  return iterationStart(db, validConfig);
}
```

### Specific Rule Validation

```typescript
import {
  validateCompletionPromises,
  validateCommandRule,
  validateContentPatternRule,
  validateCoverageRule,
  validateFileExistenceRule,
  validateCustomRule
} from './validation/iteration-config-validator.js';

// Validate just completion promises
const promiseErrors = validateCompletionPromises([
  '<promise>COMPLETE</promise>',
  '<promise>BLOCKED</promise>'
]);

if (promiseErrors.length > 0) {
  console.error('Promise errors:', promiseErrors);
}

// Validate individual rule config
const commandErrors = validateCommandRule({
  command: 'npm test',
  timeout: 120000
});

if (commandErrors.length > 0) {
  console.error('Command rule errors:', commandErrors);
}
```

## Complete Example

```typescript
const iterationConfig = {
  maxIterations: 15,
  completionPromises: [
    '<promise>COMPLETE</promise>',
    '<promise>BLOCKED</promise>'
  ],
  validationRules: [
    // Test execution
    {
      type: 'command',
      name: 'tests_pass',
      config: {
        command: 'npm test',
        expectedExitCode: 0,
        timeout: 120000
      }
    },
    // Build validation
    {
      type: 'command',
      name: 'build_succeeds',
      config: {
        command: 'npm run build',
        timeout: 180000
      }
    },
    // Lint check
    {
      type: 'command',
      name: 'lint_clean',
      config: {
        command: 'npm run lint',
        successExitCodes: [0]
      }
    },
    // Coverage requirement
    {
      type: 'coverage',
      name: 'coverage_threshold',
      config: {
        minCoverage: 80,
        format: 'lcov',
        reportPath: 'coverage/lcov.info',
        scope: 'lines'
      }
    },
    // Completion promise detection
    {
      type: 'content_pattern',
      name: 'promise_complete',
      config: {
        pattern: '<promise>COMPLETE</promise>',
        target: 'agent_output',
        mustMatch: false
      }
    }
  ],
  circuitBreakerThreshold: 3
};

// Validate and use
const validConfig = validateIterationConfigOrThrow(iterationConfig);
const result = iterationStart(db, {
  taskId: 'TASK-123',
  ...validConfig
});
```

## Error Handling

Validation errors include:

```typescript
interface ValidationError {
  field: string;      // Path to error (e.g., "maxIterations", "validationRules.0.config.command")
  message: string;    // Human-readable error message
  value?: unknown;    // The invalid value
  constraint?: string; // The constraint that failed (e.g., "minimum", "pattern")
}
```

**Example error output:**

```
Invalid iteration configuration:
maxIterations: Must be at least 1
completionPromises.0: Must match pattern: ^<promise>[A-Z]+</promise>$
validationRules.0.config.command: Missing required property: command
```

## Schema Validation Modes

The validator uses strict mode by default:

- **Strict types**: Enforces exact types (no coercion)
- **Strict numbers**: No NaN or Infinity
- **All errors**: Returns all validation errors, not just first
- **Verbose**: Includes detailed error information

## Testing

Run the test suite:

```bash
cd mcp-servers/task-copilot
npm test -- iteration-config-validator.test.ts
```

Tests cover:
- ✅ Valid configurations (minimal and complete)
- ✅ Missing required fields
- ✅ Constraint violations (min/max, patterns)
- ✅ All rule types with valid/invalid configs
- ✅ Edge cases (empty arrays, duplicates, invalid formats)
- ✅ Error message quality
- ✅ Singleton instance behavior

## JSON Schema Validation (Non-TypeScript)

For validation outside TypeScript (e.g., from other languages or tools):

```bash
# Using ajv-cli
npx ajv validate \
  -s schemas/iteration-config.schema.json \
  -d config.json

# Example config.json
{
  "maxIterations": 15,
  "completionPromises": ["<promise>COMPLETE</promise>"],
  "circuitBreakerThreshold": 3
}
```

## Design Decisions

### Why JSON Schema draft-07?

- Wide tooling support (AJV, JSON Schema validators in all languages)
- Mature specification with good documentation
- Supports oneOf, allOf for complex validation logic

### Why AJV for TypeScript validation?

- Industry standard JSON Schema validator
- Excellent performance (compiles schemas to optimized functions)
- TypeScript support via DefinitelyTyped
- Rich error reporting

### Why separate validation rules by type?

- Each rule type has different required fields
- Enables better error messages ("command missing" vs generic "property missing")
- Allows for future rule types without schema changes
- Type-safe validation in TypeScript

## Related Documentation

- **Design Doc**: `docs/architecture/stop-hook-design.md`
- **PRD**: `docs/prd/PRD-RW-001-ralph-wiggum-integration.md`
- **Iteration Types**: `../src/validation/iteration-types.ts`
- **Iteration Tools**: `../src/tools/iteration.ts`
- **Iteration Engine**: `../src/validation/iteration-engine.ts`

## Contributing

When adding new validation rule types:

1. Update `iteration-config.schema.json` with new rule definition
2. Add TypeScript type to `iteration-types.ts`
3. Add validation function to `iteration-config-validator.ts`
4. Add test cases to `iteration-config-validator.test.ts`
5. Update this README with example
6. Update iteration engine to handle new rule type

## License

MIT - See project LICENSE file
