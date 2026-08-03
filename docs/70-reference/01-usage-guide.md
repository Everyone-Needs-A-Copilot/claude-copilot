# Usage Guide

**How to actually use Claude Copilot to build software.**

This guide shows real workflows, not feature lists. After setup, this is how you work.

---

## The 30-Second Version

```bash
# Starting fresh work
/protocol fix the authentication bug

# With magic keywords for model control
/protocol eco: fix: the login bug      # Cost-optimized bug fix
/protocol opus: add: new feature       # High-quality feature work
/protocol fast: doc: API reference     # Quick documentation

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
  1. Checks task state via tc task get - environment healthy
  2. Reproduces the bug
  3. Creates task: "Fix empty email crash"
  4. Routes to @agent-me for fix

Engineer Agent:
  1. Checks task state and git status - clean
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
  1. Designs interaction patterns for dark mode toggle
  2. Routes to @agent-uids for visual design tokens

UI Design System:
  1. Creates color tokens for dark theme
  2. Routes to @agent-me for implementation

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

### Scenario 4: "Am I About to Hit My Rate Limit?"

```bash
cc usage
```

**What you get:**

```
Claude Usage (5h window)
  Requests:  42 / 100    [████░░░░░░] 42%
  Tokens:    3.1M / 7M   [████░░░░░░] 44%

7-day window
  Requests:  310 / 1000  [███░░░░░░░] 31%
```

Run this before starting a long agent task to confirm quota headroom. The counters come from Anthropic's server-side rate-limit response headers — not estimates. `cc usage` is **idle-gated**: it only probes the server when Claude Code is actively in use, so running it between sessions won't consume quota.

**Flags:**
- `cc usage --json` — machine-readable cache (zero overhead, no probe)
- `cc usage --refresh` — force a fresh probe even if idle gate fires
- `cc usage --no-probe` — read the last cached values without touching the server

Full reference: [`tools/cc/README.md`](../../tools/cc/README.md)

---

### Scenario 5: "My Memory Might Be Stale"

After a project restructure, renamed commands, or a framework update, stored memory entries can develop broken references — pointing at deleted paths, renamed commands, or outdated version strings. Run this to find them before an agent acts on bad information:

```bash
cc memory check
```

**What you get:**

```
Memory Health Check
  Entries checked: 47
  Score: 82/100

WARN  [2026-01-15] path /old/path/to/project not found
WARN  [2026-05-03] command 'mcp-server' not found in PATH
FAIL  [2026-03-20] version "5.1.0" conflicts with installed "5.9.0"

  2 warnings · 1 failure
```

Exits 1 if any `FAIL`-severity finding exists, so it integrates cleanly with CI or a shell alias. Use the flags to narrow scope:

| Flag | What it skips |
|------|--------------|
| `--no-paths` | Path-existence checks |
| `--no-commands` | Command-resolves checks |
| `--no-stale` | Staleness-by-age checks |
| `--staleness-days N` | Change the staleness cutoff (default: 90 days) |
| `--json` | Machine-readable output |

**When to run it:** Before a long `/protocol` session; after renaming directories; after a major framework update; when `/continue` gives you context that feels wrong.

Full reference: [`tools/cc/README.md`](../../tools/cc/README.md)

---

### Scenario 6: "Risky Refactor"

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
  - Check conflicts: git status / git diff --name-only --diff-filter=U
  - Resolve manually in .worktrees/TASK-001 (remove conflict markers, git add, git commit)

Result: Safe incremental refactor, main never broken.
```

---

### Scenario 7: "Working on Multiple Things"

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
tc stream list --json
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

### Task Copilot Stores (via `tc` CLI)

- **PRDs** - Requirements documents
- **Tasks** - Work items with status
- **Work Products** - Agent outputs (designs, code, plans)
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

Check the environment before continuing:

```bash
tc task get <id> --json
git status
```

Review the task state and git status. Fix issues before continuing.

### "Task completed but no commit"

Check if `filesModified` was set:

```bash
tc task update TASK-xxx --status completed --json
# Ensure metadata includes: { filesModified: ["src/file.ts"] }
```

### "Can't add tasks to PRD"

PRD is scope-locked. Either:
1. Ask `@agent-ta` to add the task (TA has scope authority on locked PRDs)

### "Merge conflicts on completion"

With worktree isolation:

```bash
# Check conflict status
git status
git diff --name-only --diff-filter=U

# Navigate to the worktree and resolve conflicts manually
# (edit files to remove <<<<<<<, =======, >>>>>>> markers)
cd .worktrees/TASK-xxx
# ... edit conflicting files ...

# Stage resolved files and complete the merge
git add <resolved-files>
git commit

# Then update task status
tc task update TASK-xxx --status completed --json
```

### "Lost my context"

```bash
/continue
```

If that doesn't help, check Memory Copilot directly:

```bash
# Check Memory Copilot
cc memory list --json

# Check Task Copilot
tc progress --json
```

### "Memory feels wrong — context from an old project layout"

Your memory entries may reference deleted paths or outdated commands:

```bash
cc memory check
```

Review the flagged entries (`cc memory get <id>`) and delete or update those that are no longer accurate.

### "Not sure if I have quota for a long task"

```bash
cc usage
```

Check the 5h window utilization. If you're near the limit, use `/pause` to checkpoint and come back later, or use `eco:` prefix to minimize token usage.

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

### Key Tools / Commands

| Tool / Command | Purpose |
|------|---------|
| `tc task get <id> --json` | Retrieve task state |
| `tc progress --json` | See overall progress |
| `tc stream list --json` | See parallel work streams |
| `cc memory list --json` | Review stored memory (decisions, lessons, context) |
| `cc memory check` | Drift detection — find stale/broken references before they mislead an agent (exits 1 on fail) |
| `cc usage` | Show current quota utilization from server-side counters; use before long tasks |

### Magic Keywords

Prefix your `/protocol` commands for model and routing control:

**Model Selection & Effort:**
| Keyword | Model | Effort | Use When |
|---------|-------|--------|----------|
| `eco:` | Auto-select | low | Cost optimization, simple tasks |
| `fast:` | Auto-select | medium | Balanced reasoning ⚠️ BREAKING: was haiku |
| `max:` | Auto-select | max | Maximum reasoning depth ✨ NEW |
| `opus:` | Opus | (auto) | Force Opus model |
| `sonnet:` | Sonnet | (auto) | Force Sonnet model |
| `haiku:` | Haiku | (auto) | Force Haiku model |

**Action Routing:**
| Keyword | Flow | Agent Chain |
|---------|------|-------------|
| `fix:` | Defect | qa → me → qa |
| `add:` | Experience | sd → design → ta → me → qa |
| `refactor:` | Technical | ta → me → qa |
| `test:` | QA | qa |
| `doc:` | Documentation | doc |

**Combine them:** `/protocol eco: fix: the login bug`

See [Magic Keywords](../50-features/09-magic-keywords.md) for full documentation.

### Workflow Cheat Sheet

```
Morning:       /continue
Check quota:   cc usage
Check memory:  cc memory check
New task:      /protocol [description]
Quick fix:     /protocol eco: fix: [description]
Quality:       /protocol max: add: [description]
Force model:   /protocol opus: [description]
Context sw:    /pause [reason] → /protocol [new task]
Resume:        /continue [stream-name]
End of day:    /pause [notes]
```

---

## Next Steps

- [Magic Keywords](../50-features/09-magic-keywords.md) - Model selection and action routing
- [Ecomode](../50-features/08-ecomode.md) - Smart model routing based on complexity
- [Agent Details](../10-architecture/01-agents.md) - Learn each specialist
- [Decision Guide](../10-architecture/03-decision-guide.md) - When to use what
- [Customization](../20-configuration/02-customization.md) - Extensions and knowledge repos
- [Enhancement Features](../50-features/00-enhancement-features.md) - Advanced context engineering
- [Token Efficiency Playbook](../30-operations/04-token-efficiency-playbook.md) - Keep usage low without losing rigor
