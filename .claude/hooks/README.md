# Hooks System for Claude Copilot

## Overview

The hooks system provides lifecycle-based injection and validation capabilities. There are three types of hooks:

1. **SessionStart Hook** - Injects protocol guardrails at session initialization
2. **Security Hooks** - PreToolUse validation to prevent security issues
3. **Auto-Checkpoint Hooks** - Automatic checkpoint creation during iteration loops

---

## SessionStart Hook (Protocol Injection)

**Purpose:** Inject protocol guardrails directly into session context to ensure main session compliance.

**Configuration:** `.claude/hooks/session-start.json`
**Content:** `.claude/hooks/protocol-injection.md`

### Protocol Guardrails

Enforces mandatory rules for main session behavior:

| Rule | Limit | Severity | Action |
|------|-------|----------|--------|
| File Reading | Max 3 files | High | Delegate to agent |
| Code Writing | No direct code | Critical | Delegate to @agent-me |
| Planning | No direct plans | Critical | Delegate to @agent-ta |
| Agent Selection | Framework only | Critical | No Explore/Plan/general |
| Response Size | <500 tokens | Medium | Store in work product |
| Work Products | Store details | Medium | Return summary only |

### Violation Tracking

All violations are logged to Task Copilot's `protocol_violations` table.

**MCP Tools:**
- `protocol_violation_log()` - Log a guardrail violation
- `protocol_violations_get()` - Query violations with filters

**View Violations:**
```bash
/memory  # Shows violation count and recent violations
```

### Compliance Metrics

Tracked by initiative:
- Total violations
- By type (files_read_exceeded, code_written_directly, etc.)
- By severity (critical, high, medium, low)
- Trend analysis (improving/stable/declining)

---

## Security Hooks (PreToolUse)

PreToolUse security hooks provide proactive security validation by intercepting and analyzing tool calls before execution. This prevents accidental exposure of secrets, destructive commands, and unauthorized access to sensitive files.

### Overview

Security hooks operate at the MCP layer, evaluating tool calls against a set of configurable rules. Each rule can:

- **Block** execution (SecurityAction.BLOCK)
- **Warn** but allow (SecurityAction.WARN)
- **Allow** silently (SecurityAction.ALLOW)

## Default Rules

The system includes five default security rules:

### 1. Secret Detection (`secret-detection`)

**Priority:** 90 | **Action:** Block | **Severity:** Critical

Detects and blocks writes containing:
- AWS Access Keys (`AKIA...`)
- Google API Keys (`AIza...`)
- GitHub Tokens (`ghp_...`, `gh[pousr]_...`)
- Stripe API Keys (`sk_live_...`)
- JWT Tokens
- Database connection strings with credentials
- Private keys (RSA, DSA, EC, OpenSSH)
- Generic password assignments

**Example:**
```typescript
// BLOCKED: Writing AWS credentials
Write({
  file_path: "config.ts",
  content: "const AWS_KEY = 'AKIAIOSFODNN7EXAMPLE';"
})
```

### 2. Destructive Command Detection (`destructive-command`)

**Priority:** 85 | **Action:** Warn/Block | **Severity:** High-Critical

Detects destructive commands:
- `rm -rf /` (BLOCK - Critical)
- `rm -rf ~` (BLOCK - Critical)
- `rm -rf *` (WARN - High)
- `DROP DATABASE/TABLE` (BLOCK - Critical)
- `TRUNCATE TABLE` (WARN - High)
- System shutdown commands (BLOCK - Critical)
- Overly permissive chmod (WARN - Medium)

**Example:**
```bash
# BLOCKED: Recursive delete from root
Bash({ command: "rm -rf /" })

# WARNED: Recursive delete in directory
Bash({ command: "rm -rf ./temp/*" })
```

### 3. Sensitive File Protection (`sensitive-file-protection`)

**Priority:** 80 | **Action:** Block/Warn | **Severity:** Critical-Medium

Protects sensitive files from modification:
- `.env` files (BLOCK - Critical)
- Credential files (BLOCK - Critical)
- SSH/SSL private keys (BLOCK - Critical)
- Cloud provider configs (BLOCK - Critical)
- Database files (WARN - Medium)

**Example:**
```typescript
// BLOCKED: Editing .env file
Edit({
  file_path: ".env",
  old_string: "API_KEY=old",
  new_string: "API_KEY=new"
})
```

### 4. Credential URL Detection (`credential-url`)

**Priority:** 88 | **Action:** Block | **Severity:** Critical

Blocks URLs with embedded credentials:
```
http://user:password@example.com
postgres://admin:secret@db.example.com
```

**Example:**
```typescript
// BLOCKED: Database URL with credentials
Write({
  file_path: "database.ts",
  content: "const DB_URL = 'postgres://admin:password@localhost';"
})
```

### 5. Git Secret Commit Prevention (`git-secret-commit`)

**Priority:** 75 | **Action:** Warn | **Severity:** High

Placeholder for future git integration to prevent committing ignored secret files.

## MCP Tools

### `hook_register_security`

Register custom security rules or reset to defaults.

**Input:**
```typescript
{
  rules?: Array<{
    id: string;              // Unique rule ID (lowercase-hyphenated)
    name: string;            // Human-readable name
    description: string;     // What this rule detects
    enabled?: boolean;       // Active status (default: true)
    priority?: number;       // 1-100, higher runs first (default: 50)
    patterns: string[];      // Regex patterns to match
    severity: 'low' | 'medium' | 'high' | 'critical';
    action: 'allow' | 'warn' | 'block';
  }>;
  resetToDefaults?: boolean; // Reset to default rules
}
```

**Example:**
```typescript
hook_register_security({
  rules: [{
    id: "internal-api-key",
    name: "Internal API Key Detection",
    description: "Detects internal API key patterns",
    priority: 85,
    patterns: ["INTERNAL_[A-Z0-9]{32}"],
    severity: "critical",
    action: "block"
  }]
})
```

### `hook_list_security`

List active security rules.

**Input:**
```typescript
{
  includeDisabled?: boolean; // Include disabled rules (default: false)
  ruleId?: string;           // Get specific rule by ID
}
```

**Output:**
```typescript
{
  rules: Array<{
    id: string;
    name: string;
    description: string;
    enabled: boolean;
    priority: number;
  }>;
  totalCount: number;
  enabledCount: number;
}
```

### `hook_test_security`

Test security rules without executing the tool (dry-run).

**Input:**
```typescript
{
  toolName: string;              // Tool to test (e.g., "Edit", "Write")
  toolInput: Record<string, unknown>; // Tool parameters
  metadata?: Record<string, unknown>; // Optional metadata
}
```

**Output:**
```typescript
{
  toolName: string;
  allowed: boolean;           // Whether execution would be allowed
  action: 'allow' | 'warn' | 'block';
  violations: Array<{
    ruleName: string;
    reason: string;
    severity: string;
    recommendation?: string;
  }>;
  warnings: Array<{
    ruleName: string;
    reason: string;
    severity: string;
    recommendation?: string;
  }>;
  executionTime: number; // milliseconds
}
```

**Example:**
```typescript
hook_test_security({
  toolName: "Write",
  toolInput: {
    file_path: "config.ts",
    content: "const API_KEY = 'ghp_abcd1234';"
  }
})

// Output:
// {
//   allowed: false,
//   action: "block",
//   violations: [{
//     ruleName: "secret-detection",
//     reason: "Detected potential GitHub Token in file write",
//     severity: "critical",
//     recommendation: "Use environment variables..."
//   }]
// }
```

### `hook_toggle_security`

Enable or disable a security rule.

**Input:**
```typescript
{
  ruleId: string;   // Rule ID to toggle
  enabled: boolean; // Enable (true) or disable (false)
}
```

**Example:**
```typescript
// Temporarily disable JWT detection for testing
hook_toggle_security({
  ruleId: "secret-detection",
  enabled: false
})
```

## Configuration File

Custom rules can be defined in `security-rules.json`:

```json
{
  "version": "1.0.0",
  "description": "Project-specific security rules",
  "rules": [
    {
      "id": "custom-api-pattern",
      "name": "Custom API Pattern",
      "description": "Detects custom API key format",
      "enabled": true,
      "priority": 85,
      "patterns": [
        "MYAPP_[A-Z0-9]{40}"
      ],
      "action": "block",
      "severity": "critical"
    }
  ]
}
```

## Use Cases

### 1. Prevent Secret Leaks

```typescript
// Agent attempts to write credentials
Write({
  file_path: "setup.sh",
  content: "export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
})

// BLOCKED by secret-detection rule
// Agent receives:
// {
//   allowed: false,
//   violations: [{
//     ruleName: "secret-detection",
//     reason: "Detected potential AWS Access Key in file write",
//     recommendation: "Use environment variables or AWS credentials file"
//   }]
// }
```

### 2. Warn on Destructive Operations

```typescript
// Agent attempts destructive command
Bash({ command: "rm -rf ./node_modules" })

// WARNED by destructive-command rule
// Agent receives warning but execution proceeds
```

### 3. Protect Configuration Files

```typescript
// Agent attempts to edit .env
Edit({
  file_path: ".env",
  old_string: "DB_HOST=localhost",
  new_string: "DB_HOST=production.db"
})

// BLOCKED by sensitive-file-protection rule
```

## Custom Rule Examples

### Block Hardcoded IPs

```typescript
hook_register_security({
  rules: [{
    id: "hardcoded-ip",
    name: "Hardcoded IP Detection",
    description: "Prevents hardcoding production IPs",
    priority: 70,
    patterns: [
      "192\\.168\\.1\\.(1|2|3)", // Production IPs
      "10\\.0\\.0\\.(10|20|30)"
    ],
    severity: "high",
    action: "warn"
  }]
})
```

### Block Specific File Extensions

```typescript
hook_register_security({
  rules: [{
    id: "binary-file-block",
    name: "Binary File Protection",
    description: "Prevents editing binary files",
    priority: 75,
    patterns: [
      "\\.(exe|dll|so|dylib)$"
    ],
    severity: "medium",
    action: "block"
  }]
})
```

### Warn on Large Data Deletions

```typescript
hook_register_security({
  rules: [{
    id: "bulk-delete-warning",
    name: "Bulk Delete Warning",
    description: "Warns on large-scale delete operations",
    priority: 60,
    patterns: [
      "DELETE FROM \\w+ WHERE",
      "DROP INDEX",
      "TRUNCATE"
    ],
    severity: "high",
    action: "warn"
  }]
})
```

## Performance

- **Evaluation time:** <5ms per tool call (typical)
- **Pattern matching:** Optimized regex with early exit
- **No blocking:** Async evaluation doesn't block MCP server
- **Minimal overhead:** Only enabled rules are evaluated

## Best Practices

1. **Start with defaults:** Default rules cover 90% of common security issues
2. **Test before deploying:** Use `hook_test_security` to validate rules
3. **Tune priority:** Higher priority (80-100) for critical rules
4. **Use specific patterns:** More specific regex = fewer false positives
5. **Document custom rules:** Add clear descriptions for team understanding
6. **Review regularly:** Audit rules quarterly and remove obsolete ones
7. **Don't over-block:** Use WARN for non-critical issues to avoid frustration

## Troubleshooting

### False Positives

**Problem:** Legitimate code triggers security rules

**Solution:**
1. Review the matched pattern with `hook_test_security`
2. Refine the regex pattern to be more specific
3. Consider lowering severity to WARN instead of BLOCK
4. Temporarily disable rule: `hook_toggle_security({ ruleId: "...", enabled: false })`

### Performance Issues

**Problem:** Hook evaluation is slow

**Solution:**
1. Check `executionTime` in `hook_test_security` output
2. Simplify complex regex patterns
3. Reduce number of enabled rules
4. Increase priority of frequently-matched rules (evaluated first)

### Missing Detections

**Problem:** Security issues not being caught

**Solution:**
1. Review default rules: `hook_list_security({})`
2. Add custom rule for specific pattern
3. Test rule: `hook_test_security({ ... })`
4. Verify rule is enabled and priority is appropriate

## Limitations

- **Pattern-based:** Only detects known patterns, not semantic issues
- **Post-hoc validation:** Cannot prevent manual tool use outside MCP
- **No execution context:** Cannot analyze runtime behavior, only static content
- **Regex limitations:** Complex obfuscation may bypass detection

## Future Enhancements

- [ ] Semantic secret detection (ML-based)
- [ ] Integration with git pre-commit hooks
- [ ] Real-time security dashboard
- [ ] Automatic rule learning from blocked patterns
- [ ] Integration with secret scanning services (GitHub, GitLab)
- [ ] Context-aware rules (different rules per project/environment)

## Contributing

To add new default rules:

1. Add pattern to `src/hooks/security-rules.ts`
2. Create SecurityRule implementation
3. Register in `initializeDefaultSecurityRules()`
4. Add tests in `src/hooks/__tests__/security-rules.test.ts`
5. Document in this README

## License

MIT License - See LICENSE file for details

---

## Auto-Checkpoint Hooks

**Purpose:** Automatically create checkpoints during iteration loops without requiring manual `checkpoint_create()` calls from agents.

### How It Works

The auto-checkpoint system hooks into the iteration lifecycle to create checkpoints at strategic moments:

1. **Iteration Start**: When `iteration_start()` is called (iteration 1)
2. **Iteration Next**: When `iteration_next()` is called (subsequent iterations)
3. **Iteration Failure** (optional): When validation fails (disabled by default)

### Configuration

Auto-checkpoint hooks are initialized in the `tc` CLI with default settings:

```
Triggers:
  iterationStart: true       # Create checkpoint at start of each iteration
  iterationFailure: true     # Create checkpoint after validation failures
  taskStatusChange: false    # Too noisy for most workflows
  workProductStore: false    # Work products serve as checkpoints
```

### Checkpoint Triggers

| Trigger | When | Use Case |
|---------|------|----------|
| `iterationStart` | Start of each iteration | Recovery point if agent crashes mid-iteration |
| `iterationFailure` | Validation fails | Debug failed validation attempts |
| `taskStatusChange` | Task status changes | Track significant state transitions |
| `workProductStore` | Work product stored | Link checkpoints to deliverables |

### Benefits

**For Agents:**
- Simplified prompts - no manual checkpoint calls needed
- Automatic recovery points in TDD/iteration loops
- Consistent checkpoint creation across all iteration workflows

**For Users:**
- Transparent checkpointing - works automatically
- Resume from any iteration using `checkpoint_resume()`
- Better debugging with automatic failure checkpoints

### Agent Prompt Updates

With auto-checkpoint hooks, agents no longer need to manually call `checkpoint_create()` in iteration loops:

**Before (manual):**
```
FOR EACH iteration:
  checkpoint_create({ taskId, trigger: 'auto_iteration', ... })
  # Do work
  iteration_validate({ taskId })
  iteration_next({ taskId })
```

**After (automatic):**
```
FOR EACH iteration:
  # Do work (checkpoint created automatically)
  iteration_validate({ taskId })
  iteration_next({ taskId })
```

### Backwards Compatibility

- Manual `checkpoint_create()` calls still work for non-iteration checkpoints
- Existing `checkpoint_resume()` unchanged - works with both manual and auto checkpoints
- All existing checkpoints remain valid and accessible
- Agents can still create manual checkpoints outside iteration loops for risky operations

### Recovery

Resume from any iteration checkpoint:

```typescript
// Resume from latest checkpoint
checkpoint_resume({ taskId: 'TASK-123' })

// Resume from specific iteration checkpoint
checkpoint_resume({
  taskId: 'TASK-123',
  checkpointId: 'IT-1234567890-abc123'
})
```

The resume provides:
- `iterationNumber`: Current iteration
- `iterationConfig`: Max iterations, validation rules
- `iterationHistory`: Past iteration results
- `agentContext`: Preserved agent state

### Performance

- Minimal overhead: <1ms per checkpoint
- Automatic cleanup: Old checkpoints pruned (keeps last 5 per task)
- No blocking: Checkpoint creation doesn't block iteration execution

### Disabling Auto-Checkpoints

To disable auto-checkpoint hooks, set environment variable:

```bash
export AUTO_CHECKPOINT_ENABLED=false
```

Or configure via `tc` CLI settings:

```bash
tc config set auto-checkpoint.enabled false
```
