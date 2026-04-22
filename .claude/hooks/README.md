# Hooks System for Claude Copilot

## Overview

The hooks system provides lifecycle-based injection and enforcement for the main-session guardrails. Rules marked **Mandatory** are mechanically enforced (tool call blocked or session-capped). Rules marked **Advisory** emit a warning but do not block.

| Hook File | Claude Lifecycle Event | Rule | Enforcement |
|-----------|----------------------|------|-------------|
| `pretool-check.sh` | PreToolUse | Force-delegate (5 consecutive same-tool calls) | Mandatory — exit 2 |
| `pretool-check.sh` | PreToolUse | QA gate (after @agent-me, before @agent-qa) | Mandatory — exit 2 |
| `subagent-stop.sh` | SubagentStop | QA gate state manager | Mandatory state write |
| `user-prompt-submit.sh` | UserPromptSubmit | Session length cap (500 / 750 turns) | Advisory — systemMessage |
| `session-start.json` | SessionStart | Protocol injection | Advisory |

### Escape Hatches

| Variable | Disables |
|----------|----------|
| `COPILOT_FORCE_DELEGATE=off` | Force-delegate rule |
| `COPILOT_QA_GATE=off` | QA gate rule + state management |
| `COPILOT_SESSION_CAP=off` | Session length advisories |

### State Directory

`.claude/hooks/state/` (gitignored, ephemeral)

All state files use atomic writes (`.tmp` → `mv`) to prevent corruption under concurrent hook invocations.

### Debug

```bash
.claude/hooks/bin/qa-gate-status.sh              # current session
.claude/hooks/bin/qa-gate-status.sh <session_id>  # specific session
```

---

There are five hook types:

1. **SessionStart Hook** - Injects protocol guardrails at session initialization
2. **PreToolUse Hook** - Stateful dispatcher for enforcement rules (force-delegate, QA gate)
3. **Security Hooks** - PreToolUse validation to prevent security issues
4. **Auto-Checkpoint Hooks** - Automatic checkpoint creation during iteration loops
5. **UserPromptSubmit Hook** - Session length cap advisory at 500/750 turns

---

## UserPromptSubmit Hook — Session Length Cap

**File:** `.claude/hooks/user-prompt-submit.sh`
**Config:** `.claude/settings.json` → `hooks.UserPromptSubmit`

### Purpose

Tracks user prompt count per session. When a session exceeds 500 turns, surfaces a non-blocking advisory suggesting `/pause` + fresh `/continue` to prevent context bloat and prompt-cache thrash (the "22-hour session" pattern).

### Thresholds

| Turns | Action |
|-------|--------|
| < 500 | No action |
| 500 (first time) | Soft advisory via `systemMessage` |
| 501–749 | No repeat (warned flag set) |
| 750 (first time) | Stronger advisory via `systemMessage` |
| 751+ | No repeat (warnedStrong flag set) |

### State File

`.claude/hooks/state/session-turns.json`

```json
{
  "<session_id>": {
    "turns": 487,
    "firstSeen": "2026-04-22T10:00:00Z",
    "lastSeen": "2026-04-22T18:00:00Z",
    "warned": false,
    "warnedStrong": false
  }
}
```

Sessions with `lastSeen` older than 72 hours are pruned automatically on each state write.

### Escape Hatch

```bash
export COPILOT_SESSION_CAP=off  # Disables all session length advisories
```

This lets you opt out when running automated workflows or extended scripted sessions.

### Advisory Text (500 turns)

```
Session length: 500+ turns. The Copilot diagnostic showed sessions past this
threshold correlate with prompt-cache thrashing and context bloat.

Consider:
1. Run /pause to save a handoff work product
2. Start fresh: /continue will reload just the essentials
3. If you must continue, be aware that further work will consume tokens at
   reduced efficiency
```

### Advisory Text (750 turns)

Stronger language noting that the force-delegate hook and QA gate may receive incomplete context in very long sessions.

---

## PreToolUse Hook — Dispatcher Architecture

**File:** `.claude/hooks/pretool-check.sh`
**Config:** `.claude/settings.json` → `hooks.PreToolUse`

### Purpose

The PreToolUse hook intercepts every tool call before execution. It dispatches through a set of rule functions in priority order. The first rule to deny short-circuits the chain.

### State Files

Runtime state is written to `.claude/hooks/state/` (gitignored, contents ephemeral).

| File | Shape | Purpose |
|------|-------|---------|
| `streak-<session_id>.json` | `{ session_id, lastTool, streak, updatedAt }` | Consecutive tool call counter per session |
| `qa-gate.json` | See below | QA gate pending-tasks and retry state |

State files are written atomically (write to `.tmp` file then `mv`) to prevent corruption if the hook is interrupted. Stale sessions (>24h streak / >72h qa-gate) are auto-cleaned on next write.

### Rule Sets

| Rule | Owner Task | Trigger | Action |
|------|-----------|---------|--------|
| `rule_force_delegate` | P4.2 (task 17) | 5+ consecutive Bash/Read/Edit calls | Deny with agent delegation suggestion |
| `rule_qa_gate` | P4.1 (task 16) | Any task in pending-qa state for this session | Deny all except Agent(qa) and safe tc reads |

### Extending with a New Rule Set

To add a rule (e.g., task 16's QA gate):
1. Add `rule_<name>()` function in `pretool-check.sh`
2. Call it in the dispatch section near the bottom of the file
3. Rules return 0 (allow) or call `deny "<reason>"` (which writes JSON and exits 2)
4. No new hook registration needed — one dispatcher, multiple rule sets

### Force-Delegate Rule

Tracks consecutive calls to the same tool (`Bash`, `Read`, `Edit`). On the 5th consecutive same-tool call, the hook denies and suggests delegating to a framework agent.

- `Agent` tool calls are **never blocked** at any streak length
- Streak resets when a different tool is called
- Streak resets to 0 after a deny (clean slate for retry)
- **Escape hatch:** Set `COPILOT_FORCE_DELEGATE=off` to disable for a shell session

### QA-Gate Rule

Enforces the mandatory QA checkpoint after `@agent-me` completes. When `subagent-stop.sh` writes a task to `qa-gate.json`'s `pending_tasks`, PreToolUse denies all tool calls in the main session except:

- `Agent` with `subagent_type == "qa"` — always allowed (lets QA proceed)
- `Bash` with a safe read-only `tc` command prefix: `tc task get`, `tc task list`, `tc wp get`, `tc wp list`, `tc progress`, `tc log`

When `@agent-qa` completes and the verdict is parsed as a pass, the task is removed from `pending_tasks` and subsequent tool calls flow normally.

**State file:** `.claude/hooks/state/qa-gate.json`

```json
{
  "<session_id>": {
    "pending_tasks": ["TASK-5"],
    "retries": { "TASK-5": 1 },
    "history": [
      { "taskId": "TASK-5", "event": "me_completed", "ts": "2026-04-22T..." },
      { "taskId": "TASK-5", "event": "qa_failed_retry_1", "ts": "2026-04-22T..." }
    ],
    "lastSeen": "2026-04-22T..."
  }
}
```

**Retry / fallback:** After 3 consecutive QA failures, the task is auto-unblocked and an advisory `systemMessage` is emitted to the main session (human review recommended).

**Debug:** `.claude/hooks/bin/qa-gate-status.sh [session_id]`

**Escape hatch:** Set `COPILOT_QA_GATE=off` to disable for a shell session.

### Exit Codes

| Exit Code | Meaning |
|-----------|---------|
| 0 | Allow tool call |
| 2 | Deny tool call (JSON reason written to stdout) |

### Performance

Target: <50ms per invocation. The script uses `jq` for JSON parsing and a `mkdir`-based lock for atomic state updates.

### Escape Hatch

```bash
export COPILOT_FORCE_DELEGATE=off  # Disables force-delegate rule for this session
```

This lets you opt out temporarily (e.g., for bulk file reading in a focused agent task) without removing the hook configuration.

---

## SubagentStop Hook — QA Gate State Manager

**File:** `.claude/hooks/subagent-stop.sh`
**Config:** `.claude/settings.json` → `hooks.SubagentStop` (matcher: `me|qa`)

### Purpose

Manages QA-gate state in response to `@agent-me` and `@agent-qa` subagent completions.

### Flow

| Event | Action |
|-------|--------|
| `agent_type == "me"` | Extract `TASK-N` from final message, add to `pending_tasks` |
| `agent_type == "qa"` with pass verdict | Remove task from `pending_tasks`, clear retry counter |
| `agent_type == "qa"` with fail verdict | Increment retry counter; after 3 failures, auto-unblock + advisory |
| Any other agent type | No action |

### Verdict Parsing

The hook parses the QA agent's final message in priority order:

1. `VERDICT: APPROVED` or `VERDICT: APPROVED-WITH-MINOR-FIXES` → **pass**
2. `VERDICT: REJECTED` → **fail**
3. `<promise>COMPLETE</promise>` with no `REJECTED` → implicit **pass**
4. Otherwise → **fail** (safe default)

### Advisory on Auto-Unblock

After 3 consecutive QA failures, the hook emits:
```json
{ "systemMessage": "QA gate degraded to advisory: TASK-N failed QA 3 consecutive times. Main session is unblocked, but human review is strongly recommended..." }
```

### Escape Hatch

```bash
export COPILOT_QA_GATE=off  # Disables all QA gate state management
```

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
