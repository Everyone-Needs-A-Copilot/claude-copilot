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

There are four hook types:

1. **SessionStart Hook** - Injects protocol guardrails at session initialization
2. **PreToolUse Hook** - Stateful dispatcher for enforcement rules (force-delegate, QA gate, security checks)
3. **SubagentStop Hook** - QA gate state manager
4. **UserPromptSubmit Hook** - Session length cap advisory at 500/750 turns

---

## UserPromptSubmit Hook — Session Length Cap + Known References

**File:** `.claude/hooks/user-prompt-submit.sh`
**Config:** `.claude/settings.json` → `hooks.UserPromptSubmit`

### Purpose

Two responsibilities:
1. **Known References injection (turn 1 only):** On the first prompt of each new session, reads stable reference values from `cc config` (`paths.shared_docs`, `paths.knowledge_repo`, and any `refs.*` keys) and `cc memory` (reference-type entries), then surfaces them as a compact `systemMessage` block. Graceful no-op when nothing is configured.
2. **Session length cap:** Tracks user prompt count per session. When a session exceeds 500 turns, surfaces a non-blocking advisory suggesting `/pause` + fresh `/continue` to prevent context bloat and prompt-cache thrash (the "22-hour session" pattern).

### Registering Known References

```bash
# Standard paths (read by cc env for agents too)
cc config set paths.shared_docs /path/to/docs
cc config set paths.knowledge_repo /path/to/knowledge

# Arbitrary named references (surfaced to main session)
cc config set refs.cli_copilot /path/to/cli-copilot
cc config set refs.project_board https://...

# Free-text reference entries (FTS5 keyword-searchable)
cc memory store --type reference "CLI Copilot is at /path/to/cli-copilot"
```

### Known References Output (turn 1)

When any references are configured, the hook emits a compact `systemMessage`:

```
Known references (this session):
- shared_docs: /path/to/docs
- knowledge_repo: /path/to/knowledge
- cli_copilot: /path/to/cli-copilot
- [memory] CLI Copilot is at /path/to/cli-copilot

Register a reference: cc config set refs.<name> <value>
```

### Escape Hatch

```bash
export COPILOT_SESSION_CAP=off  # Disables session length advisories AND known-references injection
```

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

To add a rule:
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
- `Bash` with a safe `tc` command prefix: `tc task get`, `tc task list`, `tc task create`, `tc task update`, `tc wp get`, `tc wp list`, `tc wp store`, `tc progress`, `tc log`, `tc handoff`, `tc prd`, `tc stream`
- `Bash` starting with `python3 -m pytest` or `pytest` — allowed because test runs are read-only with respect to product state (they never mutate the codebase, they only verify it). This lets QA subagents run tests while the gate is active. Note: the prefix match only allows commands that literally start with these strings, so `python3 -m pytest` does NOT widen to arbitrary `python3` commands.

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

### Pass Clear Strategy

On a **pass** verdict, the hook extracts ALL `TASK-N` IDs mentioned in the QA message (not just the first), then:

1. Computes the intersection of mentioned IDs with `pending_tasks` for the session.
2. If intersection is non-empty → **targeted clear**: removes only those tasks from `pending_tasks`.
3. If intersection is empty (QA's message mentioned unrelated task IDs) → **full clear**: empties all `pending_tasks` for the session.

This handles the common stuck-gate failure mode where QA's message references a different task than the one currently pending (e.g., QA summarizes prior context with an old task ID while a new task awaits clearance).

On a **pass** verdict, a missing task ID is no longer a hard stop — the full-clear path still unblocks the session.

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

### Compliance

Guardrail violations are handled inline by returning actionable correction guidance and the correct framework agent to route to. No external logging table is used.

---

## Security Hooks (PreToolUse)

Security validation is handled inside `pretool-check.sh` as part of the PreToolUse dispatcher. No separate MCP server or `hook_register_security` tool is involved.

### Currently Active Rules

`pretool-check.sh` currently enforces two rules only:

| Rule | Trigger | Action |
|------|---------|--------|
| `rule_force_delegate` | 5+ consecutive Bash/Read/Edit calls | Deny, suggest agent delegation |
| `rule_qa_gate` | Task in pending-qa state for this session | Deny all except Agent(qa) and safe tc reads |

`security-rules.json` is present in this directory but is **not yet wired into `pretool-check.sh`**. Secret detection, destructive-command blocking, and sensitive-file protection described in that file are aspirational — they are not currently enforced at runtime.

### Adding Security Rules (Future)

To wire in a new security check, add a `rule_<name>()` function to `pretool-check.sh` and call it in the dispatch section near the bottom of the file. Rules return 0 (allow) or call `deny "<reason>"` (which writes JSON and exits 2).
