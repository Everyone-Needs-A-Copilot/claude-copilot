# Lifecycle Hooks

Lifecycle hooks provide interception points throughout the Claude Copilot workflow, enabling validation, transformation, and monitoring at critical execution phases.

## Overview

The lifecycle hooks system consists of three primary hook types:

| Hook Type | When It Fires | Primary Use Cases |
|-----------|---------------|-------------------|
| **PreToolUse** | Before any tool executes | Security validation, argument preprocessing, permission checks |
| **PostToolUse** | After tool completes | Result transformation, logging, error enrichment |
| **UserPromptSubmit** | Before prompt processing | Context injection, skill detection, prompt preprocessing |

## Hook Architecture

```
User Prompt
    │
    ▼
┌─────────────────────┐
│ UserPromptSubmit    │ → Context injection, skill signals
└─────────────────────┘
    │
    ▼
┌─────────────────────┐
│ Tool Selection      │
└─────────────────────┘
    │
    ▼
┌─────────────────────┐
│ PreToolUse          │ → Security checks, preprocessing
└─────────────────────┘
    │
    ▼
┌─────────────────────┐
│ Tool Execution      │
└─────────────────────┘
    │
    ▼
┌─────────────────────┐
│ PostToolUse         │ → Logging, result transformation
└─────────────────────┘
    │
    ▼
Response
```

## PreToolUse Hook

Intercepts tool calls before execution for security validation and preprocessing.

### Actions

| Action | Effect |
|--------|--------|
| `ALLOW` | Tool call proceeds normally |
| `WARN` | Proceed with warning logged |
| `BLOCK` | Tool call rejected with reason |
| `TRANSFORM` | Modify tool arguments before execution |

### Built-in Rules

| Rule ID | Category | Purpose |
|---------|----------|---------|
| `secret-detection` | security | Block hardcoded secrets (API keys, tokens) |
| `destructive-command` | security | Block dangerous commands (rm -rf /, DROP DATABASE) |
| `sensitive-file-protection` | security | Block edits to .env, credentials files |
| `credential-url` | security | Block URLs with embedded credentials |
| `git-secret-commit` | security | Prevent committing secrets to git |
| `path-normalization` | preprocessing | Normalize file paths |
| `metadata-enrichment` | preprocessing | Add timestamp and context metadata |

### API

```typescript
import {
  registerSecurityRule,
  evaluatePreToolUse,
  SecurityAction
} from 'task-copilot/hooks';

// Register a custom rule
registerSecurityRule({
  id: 'custom-rule',
  name: 'Custom Security Rule',
  description: 'Block specific patterns',
  enabled: true,
  priority: 75,  // Higher priority runs first (1-100)
  evaluate: (context) => {
    if (context.toolInput.content?.includes('UNSAFE')) {
      return {
        action: SecurityAction.BLOCK,
        ruleName: 'custom-rule',
        reason: 'Unsafe pattern detected',
        severity: 'high'
      };
    }
    return null;  // No violation
  }
});

// Evaluate a tool call
const result = await evaluatePreToolUse('Write', {
  file_path: 'config.ts',
  content: 'const key = "secret";'
});

if (!result.allowed) {
  console.log('Blocked:', result.violations);
}
```

### Configuration

Rules can be registered, toggled, and removed at runtime:

```typescript
import {
  toggleSecurityRule,
  unregisterSecurityRule,
  getSecurityRules
} from 'task-copilot/hooks';

// Disable a rule
toggleSecurityRule('secret-detection', false);

// Remove a rule
unregisterSecurityRule('custom-rule');

// List all active rules
const rules = getSecurityRules();
```

## PostToolUse Hook

Processes tool results after execution for logging, transformation, and error handling.

### Actions

| Action | Effect |
|--------|--------|
| `PASSTHROUGH` | Result unchanged |
| `TRANSFORM` | Modify result before returning |
| `ENRICH` | Add metadata to result |
| `SUPPRESS` | Suppress result (for logging-only rules) |

### Built-in Rules

| Rule ID | Purpose |
|---------|---------|
| `basic-logging` | Log tool calls with timing |
| `error-enrichment` | Add context to error messages |
| `slow-execution` | Warn on slow tool calls (>5s) |
| `result-sanitization` | Redact sensitive data from results |
| `activity-tracking` | Track tool usage patterns |

### API

```typescript
import {
  registerPostToolUseRule,
  evaluatePostToolUse,
  PostToolAction
} from 'task-copilot/hooks';

// Register a logging rule
registerPostToolUseRule({
  id: 'custom-logger',
  name: 'Custom Logger',
  description: 'Log all file operations',
  enabled: true,
  priority: 50,
  evaluate: (context) => {
    if (context.toolName === 'Write' || context.toolName === 'Edit') {
      console.log(`File operation: ${context.toolName}`, context.duration);
    }
    return {
      action: PostToolAction.PASSTHROUGH
    };
  }
});
```

## UserPromptSubmit Hook

Preprocesses user prompts before they reach the agent, enabling context injection and skill detection.

### Actions

| Action | Effect |
|--------|--------|
| `CONTINUE` | Process prompt normally |
| `TRANSFORM` | Modify prompt content |
| `INJECT_CONTEXT` | Add context to prompt |
| `SIGNAL_SKILL` | Trigger skill loading |
| `BLOCK` | Reject prompt with message |

### Built-in Rules

| Rule ID | Purpose |
|---------|---------|
| `whitespace-normalization` | Clean up prompt formatting |
| `file-pattern-detection` | Detect file references for skill matching |
| `keyword-detection` | Detect keywords for skill signals |
| `task-context-injection` | Add current task context |
| `explicit-skill-request` | Detect `/skill-name` requests |

### API

```typescript
import {
  registerUserPromptSubmitRule,
  evaluateUserPromptSubmit,
  PromptAction
} from 'task-copilot/hooks';

// Register a context injection rule
registerUserPromptSubmitRule({
  id: 'project-context',
  name: 'Project Context',
  description: 'Inject project-specific context',
  enabled: true,
  priority: 60,
  evaluate: (context) => {
    if (context.prompt.includes('deploy')) {
      return {
        action: PromptAction.INJECT_CONTEXT,
        context: 'Note: This project uses Kubernetes for deployment.',
        reason: 'Deployment context detected'
      };
    }
    return { action: PromptAction.CONTINUE };
  }
});
```

### Skill Signals

The UserPromptSubmit hook can signal that specific skills should be loaded:

```typescript
{
  action: PromptAction.SIGNAL_SKILL,
  skills: [
    { name: 'kubernetes', confidence: 0.85 },
    { name: 'deployment', confidence: 0.7 }
  ]
}
```

## Initialization

Hooks are automatically initialized on server startup. For manual initialization:

```typescript
import { initializeAllHooks } from 'task-copilot/hooks';

// Initialize all hook systems
initializeAllHooks();
```

To get a summary of registered hooks:

```typescript
import { getHooksSummary } from 'task-copilot/hooks';

const summary = getHooksSummary();
console.log('PreToolUse rules:', summary.preToolUse.total);
console.log('PostToolUse rules:', summary.postToolUse.total);
console.log('UserPromptSubmit rules:', summary.userPromptSubmit.total);
```

## Best Practices

1. **Priority Ordering**: Security rules should have higher priority (70-100) than preprocessing rules (30-50)
2. **Fail-Safe**: Rules that throw errors are caught and logged; they don't block execution
3. **Performance**: Keep rule evaluation fast (<10ms) to avoid latency
4. **Idempotency**: Rules should be safe to run multiple times
5. **Logging**: Use the built-in logging rules rather than custom console.log

## Troubleshooting

### Hook Not Firing

1. Verify the hook is registered: `getSecurityRules()` / `getPostToolUseRules()`
2. Check if the hook is enabled: `rule.enabled === true`
3. Verify priority ordering (higher priority runs first)

### Rule Blocking Incorrectly

1. Use `testSecurityRules()` for dry-run testing
2. Check the `matchedPattern` in the violation result
3. Adjust pattern specificity or add exceptions

### Performance Issues

1. Check rule evaluation time in logs
2. Simplify regex patterns
3. Use early returns for non-matching cases

## Related Documentation

- [Security Hooks Guide](../security-hooks-guide.md)
- [Auto-Checkpoint Hooks](./03-auto-checkpoint-hooks.md)
- [Task Copilot API Reference](./02-api-reference.md)
