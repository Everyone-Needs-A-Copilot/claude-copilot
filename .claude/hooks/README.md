# Hooks System for Claude Copilot

## Overview

The hooks system provides lifecycle-based injection and enforcement for the main-session guardrails. Rules marked **Mandatory** are mechanically enforced (tool call blocked or session-capped). Rules marked **Advisory** emit a warning but do not block.

**`PreToolUse` matcher (`.claude/settings.json`): `Bash|Read|Edit|Agent`.** This repo's own `settings.json` is live for real sessions. From 2026-04-22 to 2026-07-12 this matcher was `Bash`-only (a same-day "fix" for a real deadlock that also disabled the enforcement almost entirely) — see [`docs/10-architecture/06-hook-deadlock-root-cause-2026-07.md`](../../docs/10-architecture/06-hook-deadlock-root-cause-2026-07.md) for the root cause and what changed (TASK-106/C-6). Subagent (sidechain) tool calls share `session_id` with the session that spawned them and are exempted from `rule_force_delegate`/`rule_qa_gate` by checking `agent_type` — they are the delegation these rules exist to force, not something to gate further.

| Hook File | Claude Lifecycle Event | Rule | Enforcement |
|-----------|----------------------|------|-------------|
| `pretool-check.sh` | PreToolUse | Force-delegate (5 consecutive same-tool calls) | Mandatory — exit 2 |
| `pretool-check.sh` | PreToolUse | QA gate (after @agent-me, before @agent-qa) | Mandatory — exit 2 |
| `pretool-check.sh` | PreToolUse | Destructive-command safety `/careful` | block → exit 2; warn → exit 0 + stderr |
| `pretool-check.sh` | PreToolUse | Path-scope lock `/freeze` | Mandatory — exit 2 |
| `subagent-stop.sh` | SubagentStop | QA gate state manager | Mandatory state write |
| `user-prompt-submit.sh` | UserPromptSubmit | Session length cap (500 / 750 turns) | Advisory — systemMessage |
| `session-start.json` | SessionStart | Protocol injection | Advisory |

### Escape Hatches

| Variable | Disables |
|----------|----------|
| `CC_HOOK_ENFORCE=off` | **Everything** in `pretool-check.sh` — global kill switch, checked first, before any rule or state access |
| `COPILOT_FORCE_DELEGATE=off` | Force-delegate rule |
| `COPILOT_QA_GATE=off` | QA gate rule + state management |
| `COPILOT_SESSION_CAP=off` | Session length advisories |
| `COPILOT_CAREFUL=off` | Destructive-command safety rule (`/careful`) |
| `COPILOT_FREEZE=off` | Path-scope lock rule (`/freeze`) |
| `COPILOT_SAFETY=off` | Both `/careful` and `/freeze` (convenience alias) |

Reach for `CC_HOOK_ENFORCE=off` when the widened matcher itself is suspected of misbehaving and you don't want to guess which per-rule variable applies. It bypasses `/careful` and `/freeze` too, so treat it as a real escape hatch, not a default.

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
| `rule_force_delegate` | P4.2 (task 17), TASK-106/C-6 | 5+ consecutive Bash/Read/Edit calls from the main session (subagent calls exempt) | Deny with agent delegation suggestion |
| `rule_qa_gate` | P4.1 (task 16), TASK-106/C-6 | Any task in pending-qa state for this session | Deny all main-session calls except Agent(qa) and safe tc reads; the dispatched subagent's own non-Agent calls are exempt |

### Extending with a New Rule Set

To add a rule:
1. Add `rule_<name>()` function in `pretool-check.sh`
2. Call it in the dispatch section near the bottom of the file
3. Rules return 0 (allow) or call `deny "<reason>"` (which writes JSON and exits 2)
4. No new hook registration needed — one dispatcher, multiple rule sets

### Force-Delegate Rule

Tracks consecutive calls to the same tool (`Bash`, `Read`, `Edit`) **made directly by the main session**. On the 5th consecutive same-tool call, the hook denies and suggests delegating to a framework agent.

- `Agent` tool calls are **never blocked** at any streak length
- **Subagent (sidechain) calls are exempt, not tracked at all** (TASK-106/C-6): a `PreToolUse` payload with a non-empty `agent_type` — meaning this call originated inside a Task-spawned subagent, which shares `session_id` with its parent — returns allow immediately, before reading or writing streak state. This is what makes the widened `Read|Edit|Agent` matcher safe: without it, a subagent's own tool calls would inherit and could trip the parent's streak, and the resulting deny is unsatisfiable from inside a subagent (framework agents don't carry the Agent/Task tool). See [`docs/10-architecture/06-hook-deadlock-root-cause-2026-07.md`](../../docs/10-architecture/06-hook-deadlock-root-cause-2026-07.md).
- Streak resets when a different tool is called
- Streak resets to 0 after a deny (clean slate for retry)
- **Escape hatch:** Set `COPILOT_FORCE_DELEGATE=off` to disable for a shell session

### QA-Gate Rule

Enforces the mandatory QA checkpoint after `@agent-me` completes. When `subagent-stop.sh` writes a task to `qa-gate.json`'s `pending_tasks`, PreToolUse denies all tool calls in the main session except:

- `Agent` with `subagent_type == "qa"` — always allowed (lets QA proceed)
- `Bash` with a safe `tc` command prefix: `tc task get`, `tc task list`, `tc task create`, `tc task update`, `tc wp get`, `tc wp list`, `tc wp store`, `tc progress`, `tc log`, `tc handoff`, `tc prd`, `tc stream`
- `Bash` starting with `python3 -m pytest` or `pytest` — allowed because test runs are read-only with respect to product state (they never mutate the codebase, they only verify it). This lets QA subagents run tests while the gate is active. Note: the prefix match only allows commands that literally start with these strings, so `python3 -m pytest` does NOT widen to arbitrary `python3` commands.
- **Any non-`Agent` tool call made by an already-dispatched subagent** (`agent_type` non-empty, TASK-106/C-6): once `@agent-qa` has been allowed to start, its own `Read`/`Edit`/`Bash` calls — needed to actually verify the fix — are exempt from the gate too. Without this, the qa subagent could be dispatched and then immediately blocked from doing the work it was dispatched for. The `Agent`-tool dispatch decision itself stays fully gated regardless of caller, so this does not let a subagent nest a further delegation around the gate.

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
| `agent_type == "me"` with `<promise>BLOCKED</promise>` | Skip gate — blocker surfaces to user, no `pending_tasks` entry |
| `agent_type == "me"` with `<promise>CONFUSED</promise>` | Skip gate — decision fork surfaces to user, no `pending_tasks` entry |
| `agent_type == "me"` (normal completion) | Extract `TASK-N` from final message, add to `pending_tasks` |
| `agent_type == "qa"` with pass verdict | Remove task from `pending_tasks`, clear retry counter |
| `agent_type == "qa"` with fail verdict | Increment retry counter; after 3 failures, auto-unblock + advisory |
| Any other agent type | No action |

### Verdict Parsing

The hook parses the QA agent's final message in priority order:

1. `VERDICT: APPROVED` or `VERDICT: APPROVED-WITH-MINOR-FIXES` **AND** an `ARTIFACT` marker → **pass**
2. `VERDICT: APPROVED` without an `ARTIFACT` marker → **fail** (bare pass is invalid)
3. `VERDICT: REJECTED` → **fail**
4. `<promise>COMPLETE</promise>` with no `REJECTED` **AND** an `ARTIFACT` marker → implicit **pass**
5. Otherwise → **fail** (safe default)

### Artifact Marker Requirement (WS1 / TASK-115)

A passing verdict MUST include an `ARTIFACT` marker line. A bare `VERDICT: APPROVED` with no
artifact will NOT unblock the gate. This enforces the principle: "I reviewed it and it looks
right is not a check — a model that would skip verification will also pass its own introspection."

**Artifact marker format:**
```
ARTIFACT: <type>|<detail>
```

Where `<type>` is one of:
- `test-run` — a failable test command with exit code and output excerpt
- `file-check` — a file that exists in the expected shape
- `diff-check` — a diff or comparison result against a spec
- `adversarial-run` — cross-model adversarial pass (optional/bonus; see below)

**Examples:**
```
ARTIFACT: test-run|pytest tests/test_auth.py exit=0 "5 passed, 0 failed"
ARTIFACT: file-check|.claude/agents/manifest.json exists agents=14
ARTIFACT: diff-check|expected 14 agents actual 14 agents match
ARTIFACT: adversarial-run|llm FINDINGS: none found exit=0
```

The escape hatches (`COPILOT_QA_GATE=off`) still bypass the gate entirely — including the
artifact requirement. The 3-fail auto-unblock safety also still fires even if the artifact
requirement is the reason for failure (risk R3: a tighter parser cannot permanently wedge
an in-flight session).

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

### Adversarial Pass (Optional, Availability-Gated)

An optional second-model "try to break this diff" pass that @agent-qa can run via:

```bash
artifact="$(.claude/hooks/bin/adversarial-pass.sh)"
# Include $artifact in the verdict if non-empty (it's a bonus, never required)
```

**Detection order:**
1. `COPILOT_ADVERSARIAL_CMD` env var — explicit command (may include flags/path)
2. PATH probe: `codex`, `llm`, `mods` (first found)
3. Nothing found → clean no-op (exit 0, no output, gate unaffected)

**Configuration:**

| Variable | Purpose | Default |
|----------|---------|---------|
| `COPILOT_ADVERSARIAL_CMD` | Explicit CLI command to use | (none — uses PATH probe) |
| `COPILOT_ADVERSARIAL_TIMEOUT` | Timeout in seconds | `30` |
| `COPILOT_ADVERSARIAL=off` | Disable entirely | (enabled when absent) |

**Example configuration:**
```bash
export COPILOT_ADVERSARIAL_CMD="llm"           # use Simon Willison's llm tool
export COPILOT_ADVERSARIAL_CMD="mods --no-cache" # use charm's mods tool
export COPILOT_ADVERSARIAL_CMD="/path/to/wrapper.sh"  # custom wrapper
```

**Invocation convention:** Prompt + diff are piped to the command via stdin. For CLIs requiring a separate argument, set `COPILOT_ADVERSARIAL_CMD` to a wrapper script.

**Degradation:** Any error (CLI not found, non-zero exit, timeout, empty diff) degrades cleanly to no-op. The gate is NEVER blocked by a missing or failing adversarial CLI.

**Artifact type:** `adversarial-run` — recognized by `subagent-stop.sh` alongside `test-run`, `file-check`, `diff-check`. It satisfies the artifact requirement on its own but is never a new mandatory requirement. The gate still passes on `test-run` alone.

**Test:** `.claude/hooks/bin/test-adversarial-pass.sh`

### Escape Hatch

```bash
export COPILOT_QA_GATE=off       # Disables all QA gate state management
export COPILOT_ADVERSARIAL=off   # Disables adversarial pass only
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

| Rule | Trigger | Action |
|------|---------|--------|
| `rule_force_delegate` | 5+ consecutive Bash/Read/Edit calls | Deny, suggest agent delegation |
| `rule_qa_gate` | Task in pending-qa state for this session | Deny all except Agent(qa) and safe tc reads |
| `rule_destructive_command` | Bash command matching a pattern in `security-rules.json` | `action: block` → deny (exit 2); `action: warn` → stderr warning (exit 0) |
| `rule_path_scope` | Edit/Write/Bash targeting a path outside the freeze dir | Deny (exit 2) |

### `/careful` — Destructive Command Safety (rule_destructive_command)

Reads `security-rules.json` on every Bash tool call and tests the command string against all enabled rules' patterns (case-insensitive, via jq `test()`).

- Rules with `"action": "block"` cause a deny (exit 2 + JSON reason). Example: `git push --force`.
- Rules with `"action": "warn"` emit a `[safety-warn]` message to stderr and allow (exit 0). Example: `git reset --hard`, `rm -rf /`.

**Adding a new pattern:** Edit `security-rules.json`. Add a pattern to an existing rule's `patterns` array, or add a new rule object following the same schema. The hook reads the file at runtime — no hook restart needed.

**Bypass:**
```bash
export COPILOT_CAREFUL=off   # disables /careful for this shell session
export COPILOT_SAFETY=off    # disables both /careful and /freeze
```

**Test:**
```bash
.claude/hooks/bin/test-safety-rules.sh
```

### `/freeze` — Path-Scope Lock (rule_path_scope)

Restricts Edit, Write, and Bash file-redirect operations to a declared directory. Prevents accidental out-of-scope edits when working on a focused sub-tree.

**Enable:**
```bash
.claude/hooks/bin/freeze.sh on /path/to/your/project
# or manually:
echo /path/to/your/project > .claude/hooks/state/.freeze
```

**Disable:**
```bash
.claude/hooks/bin/freeze.sh off
# or manually:
rm .claude/hooks/state/.freeze
```

**Check status:**
```bash
.claude/hooks/bin/freeze.sh status
```

**Bypass:**
```bash
export COPILOT_FREEZE=off    # disables /freeze for this shell session
export COPILOT_SAFETY=off    # disables both /careful and /freeze
```

**State file:** `.claude/hooks/state/.freeze` (gitignored, ephemeral — one absolute path per line)

**Scope per tool:**
- `Edit` / `Write`: hard block if `file_path` is not under the freeze dir (exact, reliable)
- `Bash`: best-effort — checks redirect targets (`> path` / `>> path`) for paths outside freeze dir; does not parse arbitrary command arguments

### Adding Security Rules

To wire in a new security check, add a `rule_<name>()` function to `pretool-check.sh` and call it in the dispatch section near the bottom of the file. Rules return 0 (allow) or call `deny "<reason>"` (which writes JSON and exits 2).

To add a new destructive-command pattern that fires through `rule_destructive_command`, add it to `security-rules.json` following the existing schema — no code change needed.
