# Validation Rule Engine - Implementation Summary

**Task**: TASK-RW-006
**Phase**: Ralph Wiggum Phase 1
**Status**: Complete

## Overview

Built a comprehensive validation rule engine for Ralph Wiggum iteration completion criteria. The engine validates agent outputs against configurable rules before proceeding to the next iteration.

## Files Created

### Core Implementation

| File | Purpose | Lines |
|------|---------|-------|
| `src/validation/iteration-types.ts` | Type definitions for validation rules and results | ~150 |
| `src/validation/iteration-engine.ts` | Main validation engine with 5 validator types | ~650 |
| `src/validation/iteration-default-config.ts` | Default validation rules per agent | ~200 |
| `src/validation/iteration-example.ts` | Usage examples and demonstrations | ~280 |

### Documentation

| File | Purpose |
|------|---------|
| `src/validation/ITERATION-VALIDATION.md` | Comprehensive documentation with examples |
| `VALIDATION-ENGINE-SUMMARY.md` | This summary document |

### Integration

- Updated `src/validation/index.ts` to export iteration validation components

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   IterationValidationEngine                  │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Command    │  │   Content    │  │   Coverage   │      │
│  │  Validator   │  │   Pattern    │  │  Validator   │      │
│  │              │  │  Validator   │  │              │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐                        │
│  │     File     │  │    Custom    │                        │
│  │  Existence   │  │  Validator   │                        │
│  │  Validator   │  │  (Extensible)│                        │
│  └──────────────┘  └──────────────┘                        │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│           Configuration & Context Management                 │
└─────────────────────────────────────────────────────────────┘
```

## Validator Types

### 1. Command Validator
- Executes shell commands
- Checks exit codes
- Configurable timeouts
- Environment variables support
- **Use cases**: Tests, builds, linting, security scans

### 2. Content Pattern Validator
- Regex pattern matching
- Multiple targets (agent output, task notes, work products)
- Positive/negative matching
- **Use cases**: Completion promises, documentation structure, forbidden patterns

### 3. Coverage Validator
- Parses coverage reports
- Supports LCOV, JSON, Cobertura formats
- Configurable scopes (lines, branches, functions, statements)
- **Use cases**: Code coverage thresholds, quality gates

### 4. File Existence Validator
- Checks file/directory existence
- All-must-exist or any-must-exist modes
- **Use cases**: Implementation verification, artifact validation

### 5. Custom Validator
- Extensible validator system
- Register custom validation logic
- **Use cases**: Domain-specific validation, API contracts, complex checks

## Key Features

### Error Handling
- Graceful handling of timeouts
- Errors don't crash the engine
- Returns structured error results
- Truncates large outputs (1000 chars)

### Performance
- Batch processing (max concurrent validations)
- Configurable timeouts per validator
- Duration tracking for all validations
- Default 60s timeout, configurable per rule

### Configuration
- Agent-specific rule sets
- Global rules for all agents
- Runtime configuration overrides
- Enable/disable rules individually

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

### Validation Results
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
```

## Agent-Specific Rules

### QA Engineer (qa)
- Tests pass (`npm test`)
- Coverage thresholds (80% lines)
- Completion promises

### Engineer (me)
- Build succeeds (`npm run build`)
- Lint passes (`npm run lint`)
- Implementation files exist

### Security Engineer (sec)
- Security scan passes (`npm audit`)
- No hardcoded secrets

### DevOps Engineer (do)
- Docker builds
- Config files exist

### Documentation Writer (doc)
- Code examples present
- Proper heading structure
- README exists

### Tech Architect (ta)
- Architecture diagrams (Mermaid)
- Decision records present

### UI Developer (uid)
- UI tests pass
- Component files created

## Usage Example

```typescript
import { getIterationEngine } from './validation/iteration-engine.js';
import { DEFAULT_ITERATION_CONFIG } from './validation/iteration-default-config.js';

const engine = getIterationEngine();
const qaConfig = DEFAULT_ITERATION_CONFIG.agentRules['qa'];

const context = {
  taskId: 'TASK-123',
  workingDirectory: '/path/to/project',
  agentOutput: '<promise>COMPLETE</promise>',
  taskNotes: 'All tests passing',
  latestWorkProduct: '# Test Plan\n...'
};

const report = await engine.validate(
  qaConfig.rules,
  context,
  'TASK-123',
  1
);

if (report.overallPassed) {
  console.log('Iteration complete! Proceed to next iteration.');
} else {
  console.log('Validation failed. Retry with corrections.');
  console.log('Failed rules:', report.failedRules);
}
```

## Acceptance Criteria Status

✅ **Engine validates against 3+ rule types**
- Command validator
- Content pattern validator
- Coverage validator
- File existence validator
- Custom validator (extensible)

✅ **Returns structured pass/fail results with details**
- `IterationValidationReport` with overall status
- Individual `IterationValidationResult` per rule
- Detailed `message` and `details` fields
- Duration tracking

✅ **Handles timeouts gracefully**
- Configurable per-validator timeouts
- Global default timeout (60s)
- Timeout errors don't crash engine
- Returns error result with timeout info

✅ **Errors don't crash the engine**
- Try-catch around all validators
- Errors return structured error results
- `error` field with error message
- `erroredRules` count in report

## Integration Points

### Phase 1 (Current)
- Standalone validation engine
- Configurable per-agent rules
- Manual invocation

### Phase 2 (Future)
- Integration with Ralph Wiggum loop
- Automatic validation after iterations
- Feedback loop to agents
- Database storage of validation results
- MCP tools for validation

## Testing Strategy

The `iteration-example.ts` file provides:
1. QA validation example
2. Engineer validation with custom rules
3. Custom validator registration
4. Error handling demonstration

Run examples:
```bash
cd mcp-servers/task-copilot
npm run build
node dist/validation/iteration-example.js
```

## Next Steps (Phase 2)

1. **Database Integration**
   - Store validation reports in SQLite
   - Track validation history per task
   - Query validation trends

2. **MCP Tools**
   - `iteration_validate` - Run validation
   - `iteration_validate_get` - Get validation report
   - `iteration_validate_history` - Get validation history

3. **Ralph Wiggum Loop Integration**
   - Automatic validation after agent iterations
   - Feedback to agents on failures
   - Retry logic with validation context

4. **Enhanced Validators**
   - Git diff validator (check commits)
   - Database migration validator
   - Performance benchmark validator

5. **Metrics & Reporting**
   - Success rates per validator
   - Average validation duration
   - Most common failures

## Technical Decisions

### TypeScript Strict Mode
All files use strict TypeScript checking for type safety.

### Async/Await Pattern
All validators are async for consistent error handling and timeout support.

### Singleton Pattern
Engine uses singleton pattern (`getIterationEngine()`) for shared instance.

### Modular Design
Each validator is independent and can be extended/replaced.

### Error Result Pattern
Errors return structured results instead of throwing, preventing cascade failures.

## Dependencies

No new dependencies added. Uses Node.js built-ins:
- `child_process.exec` - Command execution
- `fs/promises` - File operations
- `util.promisify` - Promise wrappers

## File Locations

```
mcp-servers/task-copilot/
├── src/
│   └── validation/
│       ├── iteration-types.ts          (NEW - Type definitions)
│       ├── iteration-engine.ts         (NEW - Main engine)
│       ├── iteration-default-config.ts (NEW - Default config)
│       ├── iteration-example.ts        (NEW - Usage examples)
│       ├── ITERATION-VALIDATION.md     (NEW - Documentation)
│       ├── index.ts                    (UPDATED - Exports)
│       ├── types.ts                    (existing - work product validation)
│       ├── validator.ts                (existing - work product validation)
│       └── default-rules.ts            (existing - work product validation)
└── VALIDATION-ENGINE-SUMMARY.md        (NEW - This file)
```

## Code Statistics

- **Total new TypeScript code**: ~1,280 lines
- **Total documentation**: ~800 lines
- **Test/example code**: ~280 lines
- **Configuration**: ~200 lines

## Quality Metrics

- TypeScript strict mode: ✅
- Error handling: ✅ All validators wrapped
- Type safety: ✅ Full type coverage
- Documentation: ✅ Comprehensive docs + examples
- Extensibility: ✅ Custom validator support
- Performance: ✅ Concurrent validation, timeouts

## Conclusion

The validation rule engine provides a robust, extensible foundation for Ralph Wiggum's iteration validation. It supports multiple validator types, handles errors gracefully, and is configured per-agent with sensible defaults. The engine is ready for Phase 2 integration with the Ralph Wiggum loop and Task Copilot database.
