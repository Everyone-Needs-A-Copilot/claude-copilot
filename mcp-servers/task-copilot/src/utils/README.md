# Task Copilot Utilities

This directory contains utility functions for the Task Copilot MCP Server.

## Mode Detection

**File**: `mode-detection.ts`

### Purpose

Automatically detects agent execution modes from task titles and descriptions using keyword matching.

### Supported Modes

| Mode | Keywords | Use Case |
|------|----------|----------|
| `ultrawork` | ultrawork | Maximum effort, comprehensive implementation |
| `analyze` | analyze, analysis, analyse | Analysis and investigation tasks |
| `quick` | quick, fast, rapid | Fast fixes and rapid prototyping |
| `thorough` | thorough, comprehensive, detailed, in-depth | Comprehensive reviews and detailed work |

### API

#### `detectActivationMode(title: string, description?: string): ActivationMode | null`

Detects activation mode from task title and optional description.

**Parameters**:
- `title` (string): Task title
- `description` (string, optional): Task description

**Returns**: Detected mode or `null` if no keywords found

**Examples**:

```typescript
import { detectActivationMode } from './mode-detection.js';

// Single keyword detection
detectActivationMode('Quick bug fix');
// Returns: 'quick'

detectActivationMode('Analyze the code');
// Returns: 'analyze'

// Title + description
detectActivationMode('Code review', 'Do a thorough check');
// Returns: 'thorough'

// No keywords
detectActivationMode('Implement feature');
// Returns: null

// Multiple keywords (last wins)
detectActivationMode('Quick analysis needed');
// Returns: 'analyze' (appears after 'quick')
```

#### `isValidActivationMode(mode: string): mode is ActivationMode`

Type guard to validate activation mode strings.

**Parameters**:
- `mode` (string): String to validate

**Returns**: `true` if valid activation mode, `false` otherwise

**Examples**:

```typescript
import { isValidActivationMode } from './mode-detection.js';

isValidActivationMode('quick');     // true
isValidActivationMode('analyze');   // true
isValidActivationMode('invalid');   // false
isValidActivationMode('QUICK');     // false (case-sensitive)
```

### Detection Rules

1. **Case-insensitive**: Keywords match regardless of case (QUICK, Quick, quick)
2. **Whole-word matching**: Won't match partial words (e.g., "quarterback" won't match "quick")
3. **Last-wins conflict resolution**: When multiple keywords present, last one wins
4. **Synonym support**: Multiple keywords map to same mode (e.g., "analyse" and "analyze" both map to "analyze")

### Integration with Task Creation

The mode detection is automatically invoked during task creation:

```typescript
// Auto-detection from title/description
task_create({
  title: "Quick bug fix"
  // activationMode will be auto-detected as "quick"
})

// Explicit override
task_create({
  title: "Quick task",
  metadata: {
    activationMode: "thorough"  // Overrides auto-detection
  }
})

// Explicit null
task_create({
  title: "Analyze this",
  metadata: {
    activationMode: null  // Disables auto-detection
  }
})
```

### Testing

Unit tests: `__tests__/mode-detection.test.ts`
Integration tests: `../tools/__tests__/activation-mode.integration.test.ts`

Run tests:
```bash
npm test
```

### Performance

- **Complexity**: O(1) - constant time (4 regex checks)
- **Overhead**: Minimal (~1-2ms for typical task titles)
- **Memory**: No allocations beyond pattern matching
- **Dependencies**: None (uses built-in RegExp)

### Future Enhancements

Potential improvements (not currently implemented):

1. Configurable keyword patterns
2. Weighted keyword scoring
3. ML-based mode prediction
4. Context-aware detection (project type, agent history)
5. Localization support for non-English keywords
