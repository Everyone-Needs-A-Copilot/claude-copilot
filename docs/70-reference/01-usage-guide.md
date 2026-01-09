# Usage Guide

**How to actually use Claude Copilot to build software.**

This guide shows real workflows, not feature lists. After setup, this is how you work.

---

## The 30-Second Version

```bash
# Starting fresh work
/protocol fix the authentication bug

# Resuming previous work
/continue

# That's it. The framework handles the rest.
```

---

## Three Ways to Work

### 1. Quick Tasks (Minutes)

For typos, small fixes, simple questions:

```bash
/protocol quick fix the typo in README
```

**What happens:**
- Agent starts immediately (no planning overhead)
- No PRD created
- Minimal verification
- Fast completion

**Use when:** Task is obvious and small.

---

### 2. Standard Tasks (Hours)

For features, bug fixes, refactoring:

```bash
/protocol fix the login authentication bug
```

**What happens:**
1. Protocol classifies as DEFECT → routes to `@agent-qa`
2. QA agent runs **preflight check** (verifies environment healthy)
3. Agent investigates, creates tasks in Task Copilot
4. Routes to `@agent-me` for implementation
5. **Verification required** for completion (must show proof)
6. **Auto-commits** on task completion

**Use when:** Most normal development work.

---

### 3. Deep Work (Days)

For complex features, architecture changes:

```bash
/protocol ultrawork implement the payment processing system
```

**What happens:**
1. Protocol detects "ultrawork" → maximum depth mode
2. Routes to `@agent-ta` for architecture
3. Creates **scope-locked PRD** (prevents scope creep)
4. Breaks into phased tasks with dependencies
5. Can use **worktree isolation** for risky changes
6. Full verification at every step
7. Progress tracked across sessions via Memory Copilot

**Use when:** Multi-day features, risky refactors, new systems.

---

## Daily Workflow

### Starting Your Day

```bash
cd your-project
claude
/continue
```

**What happens:**
1. Memory Copilot loads your last session
2. Shows current initiative, focus, next action
3. Task Copilot shows progress, blocked items
4. Preflight check verifies environment ready
5. You're back where you left off

### Mid-Session

Work naturally. The framework handles:
- **Task tracking** - progress saved automatically
- **Auto-commit** - completed tasks create git commits
- **Verification** - complex tasks require proof of completion
- **Agent routing** - specialists called when needed

### Ending Your Day

```bash
/pause wrapping up for today
```

**What happens:**
1. Creates checkpoint with extended expiry
2. Saves current focus and next action to Memory
3. Tomorrow's `/continue` picks up exactly here

### Context Switching

Need to handle an urgent bug mid-feature?

```bash
/pause switching to urgent bug
```

Then start the bug work. When done:

```bash
/continue Stream-A   # Resume your feature work
```

---

## Common Scenarios

### Scenario 1: "I Found a Bug"

```bash
/protocol the login form crashes on empty email
```

**Flow:**
```
You: /protocol the login form crashes on empty email

[PROTOCOL: DEFECT | Agent: @agent-qa | Action: INVOKING]

QA Agent:
  1. Runs preflight_check() - environment healthy ✓
  2. Reproduces the bug
  3. Creates task: "Fix empty email crash"
  4. Routes to @agent-me for fix

Engineer Agent:
  1. Runs preflight_check() - git clean ✓
  2. Implements fix
  3. Provides proof: "Test added, all 47 tests pass"
  4. Auto-commits: "fix(TASK-xxx): Handle empty email validation"

You: Done. Git history shows the fix.
```

---

### Scenario 2: "Build a New Feature"

```bash
/protocol add dark mode to the dashboard
```

**Flow:**
```
You: /protocol add dark mode to the dashboard

[PROTOCOL: EXPERIENCE | Agent: @agent-sd | Action: INVOKING]

Service Designer:
  1. Creates journey map for dark mode toggle
  2. Routes to @agent-uxd

UX Designer:
  1. Designs interaction patterns
  2. Routes to @agent-uids

UI Designer:
  1. Creates color tokens for dark theme
  2. Routes to @agent-uid

UI Developer:
  1. Implements theme toggle
  2. Creates components
  3. Routes to @agent-me for integration

Engineer:
  1. Integrates with app
  2. Verification: Shows toggle working, tests passing
  3. Auto-commits all changes

You: Full feature, designed and built by specialists.
```

---

### Scenario 3: "I Need to Resume Yesterday's Work"

```bash
/continue
```

**Flow:**
```
You: /continue

Memory Copilot loads:
  Initiative: "Dashboard Redesign"
  Focus: "Phase 2 - Component migration"
  Next: "Continue with TASK-abc123"

Task Copilot shows:
  Progress: [████████░░░░] 65%
  Blocked: 2 tasks (waiting on API)
  In Progress: TASK-abc123

Preflight check:
  ✓ Git: clean, on branch feature/dashboard
  ✓ No critical blockers
  ✓ Environment healthy

Agent: Resuming TASK-abc123: "Migrate sidebar component"
```

---

### Scenario 4: "Risky Refactor"

```bash
/protocol ultrawork refactor the entire auth system
```

**With worktree isolation enabled:**

```
You: /protocol ultrawork refactor auth system

Architect Agent:
  1. Creates PRD with scopeLocked: true
  2. Breaks into 5 phases
  3. Each task marked: isolatedWorktree: true

Engineer Agent (Task 1):
  1. Creates git worktree: .worktrees/TASK-001
  2. Works on branch: task/task-001
  3. All changes isolated from main
  4. On completion: auto-merges to main
  5. Worktree cleaned up

  If merge conflicts:
  - Task auto-blocked
  - You resolve manually
  - Run: worktree_conflict_resolve({ taskId: "TASK-001" })

Result: Safe incremental refactor, main never broken.
```

---

### Scenario 5: "Working on Multiple Things"

Parallel streams let you context-switch safely:

```bash
# Start feature work
/protocol add user profiles
# ... creates Stream-A

# Urgent bug comes in
/pause switching to bug
/protocol fix the crash on logout
# ... creates Stream-B

# Bug fixed, back to feature
/continue Stream-A
# ... resumes exactly where you left off

# Check what streams exist
stream_list()
# Shows: Stream-A (profiles), Stream-B (complete)
```

---

## Feature Integration Guide

### Automatic Features (No Action Needed)

| Feature | When It Activates | What It Does |
|---------|-------------------|--------------|
| **Preflight Check** | Agent starts work | Verifies environment healthy |
| **Verification** | Complex task completes | Requires proof before marking done |
| **Auto-Commit** | Task completes with files | Creates structured git commit |
| **Scope Lock** | Feature/Experience PRD | Only architect can add tasks |
| **Auto-Detection** | PRD creation | Detects type from keywords |

### Opt-In Features (You Enable)

| Feature | How to Enable | Use Case |
|---------|---------------|----------|
| **Worktree Isolation** | `metadata: { isolatedWorktree: true }` | Risky refactors |
| **Skip Verification** | `metadata: { verificationRequired: false }` | Trusted quick fixes |
| **Skip Auto-Commit** | `metadata: { autoCommit: false }` | Manual commit control |
| **WebSocket Bridge** | Start the service | Real-time monitoring UI |

### Activation Modes

Control work intensity with keywords:

| Keyword | Behavior |
|---------|----------|
| `quick` | Minimal overhead, fast completion |
| `analyze` | Investigation focus, no implementation |
| `thorough` | Full validation, comprehensive testing |
| `ultrawork` | Maximum depth, warns if >3 subtasks |

```bash
/protocol quick fix typo              # Fast
/protocol analyze why tests fail      # Investigate only
/protocol thorough review auth code   # Deep review
/protocol ultrawork new payment API   # Full rigor
```

---

## Session Management

### Memory Copilot Stores

- **Decisions** - Architecture choices, tech selections
- **Lessons** - What worked, what didn't
- **Key Files** - Important files in this project
- **Current Focus** - What you're working on
- **Next Action** - What to do next

### Task Copilot Stores

- **PRDs** - Requirements documents
- **Tasks** - Work items with status
- **Work Products** - Agent outputs (designs, code, plans)
- **Checkpoints** - Recovery points for pause/resume
- **Streams** - Parallel work contexts

### What Survives Sessions

| Survives | Stored In |
|----------|-----------|
| Your decisions | Memory Copilot |
| Task progress | Task Copilot |
| Code changes | Git (via auto-commit) |
| Work products | Task Copilot |
| Conversation | Lost (by design) |

---

## Troubleshooting

### "Agent started on broken code"

The preflight check should catch this. If not:

```bash
preflight_check({})
```

Review the health report. Fix issues before continuing.

### "Task completed but no commit"

Check if `filesModified` was set:

```bash
task_update({
  id: "TASK-xxx",
  metadata: { filesModified: ["src/file.ts"] }
})
```

### "Can't add tasks to PRD"

PRD is scope-locked. Either:
1. Ask `@agent-ta` to add the task
2. Use `scope_change_request()` to request the change

### "Merge conflicts on completion"

With worktree isolation:

```bash
# Check conflict status
worktree_conflict_status({ taskId: "TASK-xxx" })

# Resolve conflicts manually in .worktrees/TASK-xxx

# Then retry
worktree_conflict_resolve({ taskId: "TASK-xxx" })
```

### "Lost my context"

```bash
/continue
```

If that doesn't help, check Memory Copilot directly:

```bash
initiative_get({ mode: "full" })
progress_summary()
```

---

## Quick Reference

### Commands

| Command | Purpose |
|---------|---------|
| `/protocol [task]` | Start fresh work |
| `/continue [stream]` | Resume previous work |
| `/pause [reason]` | Save checkpoint, switch context |
| `/map` | Generate project structure map |
| `/memory` | View memory state |
| `/orchestrate` | Set up and run parallel streams |

### Key Tools

| Tool | Purpose |
|------|---------|
| `preflight_check()` | Verify environment healthy |
| `progress_summary()` | See overall progress |
| `stream_list()` | See parallel work streams |
| `initiative_get()` | Get current initiative state |

### Workflow Cheat Sheet

```
Morning:     /continue
New task:    /protocol [description]
Context sw:  /pause [reason] → /protocol [new task]
Resume:      /continue [stream-name]
End of day:  /pause [notes]
```

---

## Next Steps

- [Agent Details](AGENTS.md) - Learn each specialist
- [Decision Guide](DECISION-GUIDE.md) - When to use what
- [Customization](CUSTOMIZATION.md) - Extensions and knowledge repos
- [Enhancement Features](ENHANCEMENT-FEATURES.md) - Advanced context engineering
