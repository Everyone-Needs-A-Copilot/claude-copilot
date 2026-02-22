# Enhancement Features

## Overview

Claude Copilot includes 12 enhancement features developed from community research and Anthropic's long-running agent harness patterns, designed to improve agent reliability, workflow efficiency, and development velocity:

| # | Feature | Benefit | Impact |
|---|---------|---------|--------|
| 1 | **Self-improving Memory Schema** | Agents learn from mistakes | Continuous framework improvement |
| 2 | **Quality Gates Configuration** | Enforce code standards | Zero defect completions |
| 3 | **Activation Mode Detection** | Context-aware execution | Right approach for each task |
| 4 | **Git Worktree Isolation** | True parallel development | No merge conflicts |
| 5 | **Continuation Enforcement** | Prevent premature stops | Robust task completion |
| 6 | **Auto-compaction Threshold** | Manage context size | Efficient token usage |
| 7 | **Verification Enforcement** | Require proof of completion | No early victory declarations |
| 8 | **Auto-Commit on Completion** | Git commits as checkpoints | Recoverable work states |
| 9 | **Preflight Check** | Verify environment health | Catch issues before starting |
| 10 | **Scope Lock** | Separate planning from execution | Prevent scope creep |
| 11 | **Task Worktree Isolation** | Isolate risky changes | Safe refactoring |
| 12 | **WebSocket Bridge** | Stream events to UIs | Real-time visibility |

These features work together to create a robust, self-improving development system that maintains quality while maximizing efficiency.

---

## Quick Start: User Examples

Most features are automatic. Here's how to use the ones that require interaction:

### Activation Modes (Keywords in Prompts)

Control how deeply agents analyze and work by including keywords in your requests:

```bash
# Quick mode - fast iteration, minimal overhead
/protocol quick fix the typo in the login form
"Can you do a quick review of this PR?"
"Fast - just update the button color to blue"

# Thorough mode - deep analysis, comprehensive validation
/protocol thorough review the authentication module
"Do a comprehensive security audit of the API endpoints"
"I need a detailed analysis of why the tests are failing"

# Analyze mode - investigation and diagnosis focus
/protocol analyze why the database queries are slow
"Analyze the memory leak in the worker process"
"Help me analyse the error patterns in the logs"

# Ultrawork mode - maximum depth, no shortcuts
/protocol ultrawork implement the payment processing system
"This needs ultrawork attention - redesign the entire caching layer"
```

**How it works:** Keywords are detected automatically from your prompt. The agent adjusts iteration limits, validation depth, and detail level accordingly.

### Quality Gates (Project Configuration)

Create `.claude/quality-gates.json` in your project to enforce checks before task completion:

```json
{
  "version": "1.0",
  "defaultGates": ["tests_pass", "lint_clean"],
  "gates": {
    "tests_pass": {
      "name": "tests_pass",
      "description": "All tests must pass",
      "command": "npm test",
      "expectedExitCode": 0
    },
    "lint_clean": {
      "name": "lint_clean",
      "description": "No linting errors",
      "command": "npm run lint",
      "expectedExitCode": 0
    }
  }
}
```

**How it works:** When agents complete tasks, these commands run automatically. If any fail, the task is marked `blocked` instead of `completed`.

### Git Worktree Isolation (Parallel Streams)

When working on multiple independent features simultaneously:

```bash
# Set up isolated worktrees for parallel work
git worktree add ../project-stream-a feature-a
git worktree add ../project-stream-b feature-b

# Work on Stream A
cd ../project-stream-a && claude
/continue Stream-A

# Work on Stream B (separate terminal)
cd ../project-stream-b && claude
/continue Stream-B
```

**How it works:** Each worktree has its own working directory. Changes don't conflict until you're ready to merge.

### Self-Improving Memory (Review Suggestions)

View agent improvement suggestions:

```bash
/memory
```

Shows pending suggestions that agents have made about improving their own instructions. Review and approve/reject as needed.

---

## Features

### 1. Self-improving Memory Schema

**Purpose:** Enables agents to store improvement suggestions for the framework itself, creating a feedback loop for continuous enhancement.

#### What it does

Agents can identify inefficiencies, missing capabilities, or unclear instructions during their work and store structured improvement suggestions in Memory Copilot. These suggestions are categorized by agent, section, and status, allowing framework maintainers to review and implement improvements systematically.

#### Memory Type

A new memory type `agent_improvement` is available alongside existing types (`decision`, `lesson`, `discussion`, `file`, `initiative`, `context`).

#### Required Metadata Structure

```typescript
{
  agentId: string;           // Agent making suggestion (e.g., "me", "ta", "qa")
  targetSection: string;      // Section to improve (e.g., "Core Behaviors", "Output Format")
  currentContent: string;     // What currently exists
  suggestedContent: string;   // Proposed improvement
  rationale: string;          // Why this change is needed
  status: 'pending' | 'approved' | 'rejected'
}
```

#### How to use it

**Store an improvement suggestion:**

```typescript
memory_store({
  type: 'agent_improvement',
  content: 'Agent @agent-me needs better guidance on handling TypeScript compilation errors',
  metadata: {
    agentId: 'me',
    targetSection: 'Core Behaviors',
    currentContent: 'Always do: Fix compilation errors immediately',
    suggestedContent: 'Always do: Fix compilation errors immediately. When TypeScript errors occur, use tsc --noEmit to see all errors, then fix systematically from dependencies outward.',
    rationale: 'Current guidance lacks specific commands and approach. Agents waste tokens debugging incrementally.',
    status: 'pending'
  },
  tags: ['agent-improvement', 'typescript', 'compilation']
})
```

**Query improvement suggestions:**

```typescript
// Get all pending improvements for @agent-me
memory_search({
  query: 'TypeScript compilation improvements',
  type: 'agent_improvement',
  agentId: 'me'
})

// List all agent improvements
const memories = memory_list({
  type: 'agent_improvement',
  limit: 50
})
```

#### Viewing suggestions via /memory

The `/memory` command shows recent memory activity including agent improvements:

```
Recent Memories:
- [agent_improvement] Better TypeScript compilation guidance (@agent-me)
- [decision] Use streaming responses for large datasets
- [lesson] Always validate input schemas before processing
```

#### Integration with framework maintenance

Framework maintainers can:

1. Query pending suggestions: `memory_search({ type: 'agent_improvement', agentId: 'me' })`
2. Review suggestions and update agent files
3. Update suggestion status: `memory_update({ id: 'MEM-123', metadata: { ...metadata, status: 'approved' } })`
4. Track improvement history over time

#### Token efficiency

- Storing suggestion: ~150 tokens
- Querying suggestions: ~50 tokens (returns only matching suggestions)
- No impact on normal agent workflows (opt-in feature)

---

### 2. Quality Gates Configuration

**Purpose:** Enforces automated quality checks (tests, linting, builds) before allowing task completion, preventing defective work from being marked complete.

#### Configuration file: .claude/quality-gates.json

Located in project root, defines gates available to all tasks.

**Example configuration:**

```json
{
  "version": "1.0",
  "defaultGates": ["tests_pass", "lint_clean"],
  "gates": {
    "tests_pass": {
      "name": "tests_pass",
      "description": "All tests must pass",
      "command": "npm test",
      "expectedExitCode": 0,
      "timeout": 300000
    },
    "lint_clean": {
      "name": "lint_clean",
      "description": "No linting errors",
      "command": "npm run lint",
      "expectedExitCode": 0,
      "timeout": 60000
    },
    "build_success": {
      "name": "build_success",
      "description": "TypeScript compilation succeeds",
      "command": "npm run build",
      "expectedExitCode": 0,
      "timeout": 120000
    }
  }
}
```

#### Available gates

Gates are fully customizable. Common examples:

**JavaScript/TypeScript:**
- `npm test` - Jest/Mocha test suite
- `npm run lint` - ESLint validation
- `npm run build` - TypeScript compilation
- `npm run type-check` - TypeScript type checking

**Python:**
- `pytest` - Test suite
- `black --check .` - Code formatting
- `mypy .` - Type checking
- `flake8` - Linting

**Rust:**
- `cargo test` - Test suite
- `cargo clippy -- -D warnings` - Linting
- `cargo fmt --check` - Format checking

**Go:**
- `go test ./...` - Test suite
- `go vet ./...` - Static analysis
- `golangci-lint run` - Comprehensive linting

#### Gate definition fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | Yes | - | Gate identifier |
| `description` | string | Yes | - | Human-readable description |
| `command` | string | Yes | - | Shell command to execute |
| `expectedExitCode` | number | No | 0 | Expected exit code for success |
| `timeout` | number | No | 60000 | Timeout in milliseconds |
| `workingDirectory` | string | No | Project root | Override working directory |
| `env` | object | No | {} | Environment variables |

#### Custom gate example

**Security scan gate:**

```json
{
  "security_scan": {
    "name": "security_scan",
    "description": "No security vulnerabilities detected",
    "command": "npm audit --audit-level=high",
    "expectedExitCode": 0,
    "timeout": 120000
  }
}
```

**Database migration check:**

```json
{
  "migrations_valid": {
    "name": "migrations_valid",
    "description": "Database migrations can run",
    "command": "npx knex migrate:list",
    "expectedExitCode": 0,
    "workingDirectory": "./backend"
  }
}
```

#### Integration with task completion

Quality gates run automatically when tasks transition to `completed` status.

**Default behavior (uses defaultGates):**

```bash
# Create the task
tc task create --title "Implement user authentication" --prd <id> --json

# Later, agent completes task
tc task update TASK-123 --status completed --json

# System automatically runs gates from defaultGates
# If any fail, task status set to 'blocked' instead
```

**Per-task override:**

```bash
# Use specific gates -- set qualityGates in task metadata
tc task create --title "Update API documentation" --prd <id> --json
# metadata: { qualityGates: ["lint_clean"] }  -- Only run lint, skip tests

# Skip all gates -- set empty qualityGates array
tc task create --title "Add comments to code" --prd <id> --json
# metadata: { qualityGates: [] }  -- No gates
```

#### Blocking behavior

When gates fail:

1. **Task status** - Changed to `blocked` (even if agent requested `completed`)
2. **Blocked reason** - Set to summary: `"Quality gates failed: tests_pass, lint_clean. 2 of 3 gates failed."`
3. **Task notes** - Updated with detailed failure information:
   ```
   Quality Gate Failures:
   - tests_pass: Command exit code mismatch (expected 0, got 1)
     stdout: [test output]
     stderr: [error messages]
   - lint_clean: Command exit code mismatch (expected 0, got 1)
     stdout: [lint output]
   ```

#### Configuration management

**No configuration file:**
- If `.claude/quality-gates.json` doesn't exist, no gates run
- Tasks complete normally without validation

**Invalid configuration:**
- Throws error with parse details
- Prevents task update
- Task remains in previous state

**Missing gate reference:**
- If task specifies non-existent gate name
- Throws error: `"Quality gate not found in config: gate_name"`
- Task update fails

#### Token efficiency

- Gate execution: Server-side, 0 tokens
- Gate failure feedback: ~100-200 tokens (included in task notes)
- Configuration loading: Cached after first load, 0 subsequent overhead

---

### 3. Activation Mode Detection

**Purpose:** Auto-detects agent execution modes from task keywords, enabling context-aware behavior tuning without manual configuration.

#### Supported keywords

| Mode | Keywords | Typical Use Case |
|------|----------|------------------|
| `ultrawork` | ultrawork | Maximum depth analysis and implementation |
| `analyze` | analyze, analysis, analyse | Investigation and diagnosis focus |
| `quick` | quick, fast, rapid | Fast iteration, minimal overhead |
| `thorough` | thorough, comprehensive, detailed, in-depth | Deep validation and review |

**Detection rules:**
- Case-insensitive matching
- Whole-word boundaries (won't match partial words)
- Last keyword wins if multiple present
- Searches both title and description

#### How modes affect behavior

Agents can read `task.metadata.activationMode` and adjust:

**Iteration limits:**
```typescript
const maxIterations = mode === 'quick' ? 5 : mode === 'thorough' ? 20 : 10;
```

**Validation depth:**
```typescript
const validationRules = mode === 'thorough'
  ? ['tests', 'lint', 'coverage', 'security', 'performance']
  : ['tests', 'lint'];
```

**Detail level:**
```typescript
const includeMetrics = mode === 'analyze' || mode === 'thorough';
```

**Current implementation:** Mode is stored in task metadata. Future enhancements will integrate with iteration system, quality gates, and agent routing.

#### Auto-detection examples

**Example 1: Quick fix**

```bash
tc task create --title "Quick bug fix for login validation" --prd <id> --json
# Result: activationMode = "quick" (detected from title)
```

**Example 2: Thorough analysis**

```bash
tc task create --title "Code review" --prd <id> --json
# With description: "Perform comprehensive analysis of the auth module"
# Result: activationMode = "thorough" (detected from description)
```

**Example 3: Investigation**

```bash
tc task create --title "Analyze performance bottleneck" --prd <id> --json
# With description: "Quick investigation of database query speed"
# Result: activationMode = "analyze" (last keyword in combined text)
```

**Example 4: No keyword**

```bash
tc task create --title "Implement dark mode feature" --prd <id> --json
# With description: "Add theme toggle to settings page"
# Result: activationMode = null (no keywords detected)
```

#### Explicit override

Override auto-detection by setting mode explicitly in task metadata:

```bash
tc task create --title "Quick task" --prd <id> --json
# Set metadata: { activationMode: "ultrawork" }
# Result: activationMode = "ultrawork" (explicit override takes precedence)
```

**Disable auto-detection:**

```bash
tc task create --title "Analyze this code" --prd <id> --json
# Set metadata: { activationMode: null }
# Result: activationMode = null (explicitly disabled)
```

#### Edge cases

| Scenario | Result | Reason |
|----------|--------|--------|
| "quarterback quick play" | `null` | "quick" inside word boundary |
| "QUICK FIX" | `"quick"` | Case-insensitive matching |
| "Quick analysis needed" | `"analyze"` | Last keyword wins |
| "Analyse the data" (British) | `"analyze"` | British spelling supported |
| Empty title | `null` | No text to analyze |

#### Integration with other systems

**Quality gates:**
```typescript
const gates = mode === 'quick'
  ? ['tests_pass']  // Minimal gates for quick mode
  : ['tests_pass', 'lint_clean', 'build_success'];  // Full gates otherwise
```

**Continuation thresholds:**
```typescript
const maxContinuations = mode === 'ultrawork' ? 15 : mode === 'quick' ? 3 : 5;
```

**Token budgets:**
```typescript
const maxTokens = mode === 'thorough' ? 8192 : mode === 'quick' ? 2048 : 4096;
```

#### Token efficiency

- Auto-detection: 0 tokens (server-side)
- Explicit mode: ~5 tokens (`"activationMode": "quick"`)
- Retrieved in task: ~5 tokens (included in metadata)

---

### 4. Git Worktree Isolation

**Purpose:** Eliminates file conflicts during parallel stream development by giving each stream its own isolated git worktree with dedicated branch.

#### When worktrees are used

**Automatic creation triggers:**
- Resuming a parallel stream via `/continue Stream-B`
- Stream phase is `parallel`
- Stream doesn't already have worktree metadata

**Not used for:**
- Foundation streams (phase: `foundation`) - Work in main worktree
- Integration streams (phase: `integration`) - Work in main worktree
- Non-git projects - Feature gracefully skips

#### Directory structure

```
project-root/
├── .git/                          # Main repository
├── src/                           # Main worktree files
├── .claude/
│   └── worktrees/                 # Isolated worktrees
│       ├── Stream-A/              # Foundation (usually not created)
│       ├── Stream-B/              # Parallel stream B
│       │   ├── .git               # Linked to main repo
│       │   └── src/               # Isolated working files
│       └── Stream-C/              # Parallel stream C
│           ├── .git
│           └── src/
└── .gitignore                     # Excludes .claude/worktrees/
```

**Worktree location pattern:** `.claude/worktrees/{streamId}`

**Branch naming pattern:** `stream-{streamId}` (lowercase)
- Stream-A → `stream-a`
- Stream-B → `stream-b`
- Stream-C → `stream-c`

#### Creation workflow

**Manual creation (via /continue):**

```bash
/continue Stream-B
```

**What happens:**

1. Query stream details: `tc stream get Stream-B --json`
2. Check stream phase and worktree metadata
3. If parallel phase and no worktree exists:
   ```typescript
   // WorktreeManager creates:
   // - Directory: .claude/worktrees/Stream-B
   // - Branch: stream-b (from current branch)
   // - Git linkage to main repo
   ```
4. Update all stream tasks with metadata:
   ```json
   {
     "worktreePath": ".claude/worktrees/Stream-B",
     "branchName": "stream-b"
   }
   ```
5. Agent works in isolated directory
6. Changes committed to `stream-b` branch
7. No conflicts with other parallel streams

#### Stream metadata integration

Tasks in worktree-isolated streams include:

```typescript
{
  streamId: "Stream-B",
  streamName: "command-updates",
  streamPhase: "parallel",
  worktreePath: ".claude/worktrees/Stream-B",
  branchName: "stream-b",
  files: [".claude/commands/protocol.md"]
}
```

#### Conflict detection

Conflict detection recognizes worktree isolation. Streams with worktrees cannot have file conflicts because they work in isolated directories. Use `git diff` to check for conflicts between streams sharing the main worktree.

**Only streams sharing main worktree can have file conflicts.**

#### Merging completed work

**When stream completes:**

1. Switch to target branch:
   ```bash
   git checkout main
   ```

2. Merge stream branch:
   ```bash
   git merge stream-b --no-ff -m "Merge Stream-B: command updates"
   ```

3. Verify merge successful (resolve conflicts if any)

**Why manual merge?**
- Allows review before integration
- Prevents accidental loss of uncommitted work
- Gives control over merge strategy (no-ff, squash, rebase)
- Stream may need pause/resume before final merge

#### Cleanup

**Manual cleanup workflow:**

```bash
# Remove worktree directory
git worktree remove .claude/worktrees/Stream-B

# Or force removal if dirty
git worktree remove --force .claude/worktrees/Stream-B

# Clean up stale references
git worktree prune

# Optional: Delete stream branch after merge
git branch -d stream-b
```

**Why manual cleanup?**
- Prevents accidental deletion of uncommitted work
- Allows stream pause and resume
- Gives control over branch lifecycle
- Stream may need to be reopened for fixes

**Automatic pruning (safe):**
```bash
git worktree prune  # Only removes stale references, not worktrees
```

#### WorktreeManager API

The WorktreeManager handles git worktree lifecycle for streams.

**Key methods:**

```typescript
// Create worktree for stream
const info = await manager.createWorktree('Stream-B', 'main');
// Returns: { path: '.claude/worktrees/Stream-B', branch: 'stream-b', streamId: 'Stream-B' }

// Check if worktree exists
const exists = await manager.hasWorktree('Stream-B');

// Get worktree info
const info = await manager.getWorktreeInfo('Stream-B');

// List all managed worktrees
const worktrees = await manager.listWorktrees();

// Remove worktree
await manager.removeWorktree('Stream-B', force = false);

// Merge stream branch into target
const result = await manager.mergeStreamBranch('Stream-B', 'main');

// Clean up stale references
await manager.pruneWorktrees();
```

#### Error handling

**Not a git repository:**
```typescript
// manager.createWorktree() throws:
// "Not a git repository"
```

**Worktree already exists:**
```typescript
// manager.createWorktree() returns existing worktree info (idempotent)
```

**Merge conflicts:**
```typescript
// manager.mergeStreamBranch() throws with git error details
// User must resolve conflicts manually
```

#### Token efficiency

- Worktree creation: ~0 tokens (server-side operation)
- Stream metadata includes paths: ~20 tokens
- No impact on agent workflows (transparent to agents)
- Overall: Prevents context bloat from merge conflicts

---

### 5. Continuation Enforcement

**Purpose:** Automatically detects when agents stop prematurely (missing completion signals) and intelligently decides whether to auto-resume, prompt user, or block for safety.

#### How premature stops are detected

The system checks the **last 100 characters** of agent output for completion signals:

**Valid completion signals:**
- `<promise>COMPLETE</promise>` - Work finished successfully
- `<promise>BLOCKED</promise>` - Cannot proceed without intervention
- `<thinking>CONTINUATION_NEEDED</thinking>` - Explicit continuation request

**If none found:** Premature stop detected.

**Why last 100 chars only?**
- Prevents false positives from agents quoting signals in implementation
- Agents might write code that includes these strings
- Only final output matters for completion detection

#### Decision logic

```
Agent completes iteration
    ↓
Check last 100 chars for signals
    ↓
Signal found?
    ├─ Yes → Complete normally
    │
    └─ No → Premature stop detected
        ↓
    Continuation count > 10?
        ├─ Yes → BLOCKED (runaway protection)
        │
        └─ No → In active iteration loop?
            ├─ Yes → AUTO_RESUME (continue iteration)
            │
            └─ No → PROMPT_USER (ask for confirmation)
```

#### Auto-resume example (iteration loop)

**Scenario:** Agent in TDD loop completes work but does not signal completion

The system detects that the agent stopped without a completion signal and decides whether to auto-resume (if in an active iteration), prompt the user, or block. Continuation is tracked in task metadata (retrievable via `tc task get <id> --json`).

#### User prompt example (no iteration)

**Scenario:** Agent stops mid-work outside iteration loop

```typescript
const result = await checkAndDecideContinuation(
  db,
  'TASK-456',
  null,  // No iteration ID
  `
    ## Phase 1 Complete

    I've updated the schema. Next I need to update the API endpoints.
  `
  // ❌ Missing completion signal
);

// Result:
result = {
  shouldContinue: true,
  action: 'prompt_user',
  reason: 'No active iteration loop - user confirmation needed',
  prompt: 'Agent stopped without completion signal. Continue? [y/n]'
}

// User sees prompt and decides whether to continue
```

#### Promise signals (<promise>COMPLETE</promise>)

**Usage by agents:**

```typescript
// Successful completion
const output = `
## Task Complete

All tests passing, code reviewed and merged.

<promise>COMPLETE</promise>
`;

// Blocked state
const output = `
## Blocked

Cannot proceed: Database credentials not configured in environment.

<promise>BLOCKED</promise>
`;

// Explicit continuation request
const output = `
## Phase 1 Done

Schema updated successfully. Proceeding to API endpoint updates.

<thinking>CONTINUATION_NEEDED</thinking>
`;
```

**Best practices:**
- Always emit signal in last 100 characters
- Use `COMPLETE` when work fully done
- Use `BLOCKED` when stuck and need human help
- Use `CONTINUATION_NEEDED` for planned multi-phase work
- Signals are case-insensitive but use uppercase by convention

#### Runaway protection

The system prevents infinite continuation loops:

| Continuation Count | Behavior | Action |
|-------------------|----------|--------|
| 1-4 | Continue normally | No warning |
| 5-9 | Continue with warning | `"Warning: N continuations detected. Possible runaway loop."` |
| 10+ | Hard block | Task status set to `blocked`, no further continuations |

**Warning example (6th continuation):**

```typescript
const decision = decideContinuation(db, taskId, iterationId, detection);

// Result:
{
  shouldContinue: true,
  action: 'auto_resume',
  reason: 'Active iteration loop detected (6/15)',
  prompt: 'Continuing iteration 7',
  warning: 'Warning: 6 continuations detected. Possible runaway loop.'
}

// Warning automatically added to validation feedback:
validationResult.feedback = [
  'Validation rule X failed',
  'Warning: 6 continuations detected. Possible runaway loop.'
]
```

**Hard block example (11th continuation):**

```typescript
const decision = decideContinuation(db, taskId, iterationId, detection);

// Result:
{
  shouldContinue: false,
  action: 'blocked',
  reason: 'Runaway detected: 11 continuations exceed threshold of 10',
  warning: 'Task has been continued 11 times without completion. Manual intervention required.'
}

// Task automatically blocked
// No further iterations allowed
// Human must review and reset
```

#### Continuation metadata tracking

Stored in `task.metadata.continuation`:

```typescript
{
  continuationCount: 6,
  lastContinuedAt: '2026-01-04T10:35:42Z',
  continuationReasons: [
    'No completion signal detected in last 100 characters',
    'No completion signal detected in last 100 characters',
    'Agent explicitly signaled continuation needed',
    'No completion signal detected in last 100 characters',
    'No completion signal detected in last 100 characters',
    'No completion signal detected in last 100 characters'
  ]  // Last 10 reasons kept
}
```

**Reset on completion:**
```typescript
// When agent successfully emits <promise>COMPLETE</promise>:
// continuation metadata removed
// Counter reset to 0
```

#### Integration with agent workflow

The continuation guard runs as part of the agent's self-managed iteration loop. When an agent completes an iteration without signaling completion, the system tracks the continuation in task metadata and decides the next action.

#### Token efficiency

| Scenario | Without Guard | With Guard | Savings |
|----------|--------------|------------|---------|
| Premature stop in iteration | Manual detection + restart (~200 tokens) | Auto-resume (0 overhead) | 100% |
| Premature stop outside iteration | Manual restart (~300 tokens) | User prompt + decision (~50 tokens) | 83% |
| Runaway detection | No protection, wasted iterations | Hard block after 10 | Prevents waste |

**Overhead per validation:** ~50 tokens (detection + decision logic)

**Net benefit:** ~150-250 tokens saved when catching incomplete stops

---

### 6. Auto-compaction Threshold

**Purpose:** Monitors agent response size and triggers automatic compaction when approaching context limits, preventing token overflow and maintaining efficient communication.

**Note (Opus 4.6):** Default thresholds increased 4x to leverage 1M token context window. See [Opus 4.6 Capabilities](./06-opus-46-capabilities.md) for details.

#### Token estimation formula

Conservative approach to avoid underestimation:

```typescript
estimatedTokens = Math.ceil(text.length / 4)
```

**Why 1 token ≈ 4 characters?**
- Conservative estimate (actual is ~3.5-4 chars per token)
- Leaves safety buffer
- Prevents edge cases where estimation is too low

**Example:**
- 400 characters → 100 tokens
- 4,000 characters → 1,000 tokens
- 16,000 characters → 4,000 tokens

#### Threshold settings

**Default configuration (Opus 4.6):**

```typescript
const threshold = 0.85;  // 85% of max tokens
const maxTokens = 16384;  // Default agent response limit (Opus 4.6)
const thresholdTokens = 13,927;  // 85% of 16384
```

**Legacy (Opus 4):**

```typescript
const maxTokens = 4096;  // Old default
const thresholdTokens = 3,482;  // 85% of 4096
```

**Threshold trigger:**
```typescript
if (estimatedTokens >= thresholdTokens) {
  // Compact response
}
```

**Different limits by agent type:**

| Agent Type | Max Tokens | 85% Threshold | When to Compact |
|------------|-----------|---------------|-----------------|
| Standard agent | 4,096 | 3,482 | ≥ 3,482 tokens |
| Extended agent | 8,192 | 6,963 | ≥ 6,963 tokens |
| Large context | 16,384 | 13,927 | ≥ 13,927 tokens |

#### Compact summary format

When threshold exceeded, agents should return compact summaries:

**Detailed response (exceeds threshold):**

```markdown
## Implementation Complete

I've implemented the authentication system with the following components:

### 1. User Model
Created `models/User.ts` with fields:
- id: UUID primary key
- email: unique, validated
- password: bcrypt hashed
- createdAt: timestamp
- updatedAt: timestamp

[... continues for 4,000+ tokens ...]
```

**Compact summary (at threshold):**

```markdown
## Implementation Complete

Task: TASK-123 (authentication system)
Status: Completed
Work Product: WP-456 (implementation, 3,847 tokens)

Summary: Implemented authentication with User model, JWT middleware, and password hashing. All tests passing.

Files Modified:
- models/User.ts (created)
- middleware/auth.ts (created)
- routes/auth.ts (created)
- __tests__/auth.test.ts (created)

Next Steps: Review work product WP-456 for full implementation details.
```

**Token comparison:**
- Detailed: 4,200 tokens
- Compact: 180 tokens
- Savings: 96%

#### Usage in agents

**Check before responding:**

When response exceeds the threshold, agents should store the full content as a work product and return a compact summary:

```bash
# Store full details in work product
tc wp store --task TASK-123 --type implementation --title "Authentication system implementation" --content "<full response>" --json

# Return compact summary to main session (~100 tokens)
# "Task Complete: TASK-123. WP-456 stored. See work product for full details."
```

#### Context monitoring utilities

**Check threshold:**

```typescript
import { exceedsThreshold } from './utils/context-monitor';

const shouldCompact = exceedsThreshold(
  responseText,
  threshold = 0.85,
  maxTokens = 4096
);

// Returns: true if estimated tokens >= 85% of max
```

**Get usage details:**

```typescript
import { getContextUsage } from './utils/context-monitor';

const usage = getContextUsage(responseText);

// Returns:
{
  estimatedTokens: 3500,
  thresholdTokens: 3482,
  maxTokens: 4096,
  percentage: 85.4,
  exceedsThreshold: true,
  shouldCompact: true
}
```

**Extract summary:**

```typescript
import { extractSummary } from './utils/context-monitor';

const summary = extractSummary(
  fullContent,
  maxTokens = 100
);

// Returns: Truncated content at sentence boundary
// "Implemented authentication system with JWT tokens. All tests passing..."
```

#### Configuration (future)

Currently hard-coded. Future enhancement:

```json
// .claude/compaction-config.json
{
  "threshold": 0.85,
  "maxTokens": 4096,
  "summaryMaxTokens": 150,
  "enforceCompaction": true
}
```

**Per-agent overrides:**

```json
{
  "agents": {
    "ta": {
      "threshold": 0.90,
      "maxTokens": 8192
    },
    "me": {
      "threshold": 0.85,
      "maxTokens": 4096
    }
  }
}
```

#### Integration with `tc` CLI

Agents automatically use compaction when storing work products:

```bash
# Agent stores full content via tc CLI
tc wp store --task <id> --type implementation --title "..." --content "<full implementation>" --json

# Then returns compact summary to main session
```

**Benefits:**
- Full details preserved (retrievable via `tc wp get <id> --json`)
- Main session receives ~100 token summary
- Token savings: ~95% on large responses

#### Token efficiency

| Response Size | Without Compaction | With Compaction | Savings |
|---------------|-------------------|-----------------|---------|
| 4,200 tokens (exceeded) | 4,200 tokens | 180 tokens | 96% |
| 3,000 tokens (below threshold) | 3,000 tokens | 3,000 tokens | 0% |
| 8,000 tokens (way over) | 8,000 tokens | 200 tokens | 97.5% |

**Overhead:** ~10-20 tokens for threshold check and summary generation (negligible)

---

## Configuration Reference

Summary of configuration files and environment variables for all enhancement features.

### Configuration Files

| File | Feature | Location | Required |
|------|---------|----------|----------|
| `.claude/quality-gates.json` | Quality Gates | Project root | No (optional) |
| `.gitignore` | Worktree Isolation | Project root | Yes (auto-created) |

### Environment Variables

| Variable | Feature | Default | Purpose |
|----------|---------|---------|---------|
| `MEMORY_PATH` | Self-improving Memory | `~/.claude/memory` | Memory database location |
| `WORKSPACE_ID` | Self-improving Memory | (auto-hash) | Explicit workspace identifier |
| `TASK_DB_PATH` | `tc` CLI task management | `~/.claude/tasks` | Task database location |

### In-Code Configuration

| Feature | Configuration | Default | How to Change |
|---------|--------------|---------|---------------|
| Activation Mode | Keywords | `ultrawork`, `analyze`, `quick`, `thorough` | Modify `MODE_PATTERNS` in `mode-detection.ts` |
| Continuation Guard | Max continuations | 10 (hard block), 5 (warning) | Modify `RUNAWAY_THRESHOLD`, `MAX_CONTINUATIONS` in `continuation-guard.ts` |
| Continuation Guard | Check chars | 100 | Modify `COMPLETION_CHECK_CHARS` in `continuation-guard.ts` |
| Auto-compaction | Threshold | 85% | Modify `threshold` parameter in `exceedsThreshold()` calls |
| Auto-compaction | Max tokens | 4096 | Modify `maxTokens` parameter in `exceedsThreshold()` calls |

### Quality Gates Examples

**Minimal (tests only):**

```json
{
  "version": "1.0",
  "defaultGates": ["tests_pass"],
  "gates": {
    "tests_pass": {
      "name": "tests_pass",
      "description": "Tests must pass",
      "command": "npm test",
      "expectedExitCode": 0
    }
  }
}
```

**Comprehensive (tests, lint, build, security):**

```json
{
  "version": "1.0",
  "defaultGates": ["tests_pass", "lint_clean", "build_success", "security_scan"],
  "gates": {
    "tests_pass": {
      "name": "tests_pass",
      "description": "All tests pass",
      "command": "npm test",
      "expectedExitCode": 0,
      "timeout": 300000
    },
    "lint_clean": {
      "name": "lint_clean",
      "description": "No linting errors",
      "command": "npm run lint",
      "expectedExitCode": 0
    },
    "build_success": {
      "name": "build_success",
      "description": "Build succeeds",
      "command": "npm run build",
      "expectedExitCode": 0,
      "timeout": 120000
    },
    "security_scan": {
      "name": "security_scan",
      "description": "No high/critical vulnerabilities",
      "command": "npm audit --audit-level=high",
      "expectedExitCode": 0,
      "timeout": 120000
    }
  }
}
```

---

## Troubleshooting

### Self-improving Memory Schema

**Issue:** `agent_improvement type requires metadata` error

**Solution:** Ensure metadata includes all required fields:
```typescript
metadata: {
  agentId: 'me',
  targetSection: 'Core Behaviors',
  currentContent: '...',
  suggestedContent: '...',
  rationale: '...',
  status: 'pending'
}
```

**Issue:** Cannot find improvement suggestions

**Solution:** Use `agentId` filter in search:
```typescript
memory_search({
  query: 'improvements',
  type: 'agent_improvement',
  agentId: 'me'  // Filter by specific agent
})
```

---

### Quality Gates Configuration

**Issue:** `Quality gate not found in config: gate_name`

**Solution:** Check `.claude/quality-gates.json` for gate definition. Ensure gate name matches exactly:
```json
{
  "gates": {
    "tests_pass": { ... }  // Must match metadata.qualityGates array
  }
}
```

**Issue:** Gates fail but no detailed error in notes

**Solution:** Check that `command` field uses correct path and exists in project:
```bash
# Test gate command manually
npm test  # Should work from project root
```

**Issue:** Task stays blocked after fixing issues

**Solution:** Re-run task completion:
```bash
# Reset task status
tc task update TASK-123 --status in-progress --json

# Re-attempt completion (re-runs gates)
tc task update TASK-123 --status completed --json
```

---

### Activation Mode Detection

**Issue:** Mode not detected when keyword present

**Solution:** Ensure whole-word match. Keywords must not be inside other words:
```typescript
// ✅ Detected
"Quick bug fix"

// ❌ Not detected
"quarterback play"  // "quick" is inside word
```

**Issue:** Wrong mode detected

**Solution:** Last keyword wins. Check combined title + description:
```typescript
title: "Quick analysis"  // "quick" at position 0, "analysis" at position 6
// Result: "analyze" (last keyword)
```

**Issue:** Cannot override auto-detection

**Solution:** Set explicit `activationMode` in task metadata when creating the task:
```bash
tc task create --title "Quick task" --prd <id> --json
# Set metadata: { activationMode: "thorough" }  -- Explicit override
```

---

### Git Worktree Isolation

**Issue:** `Not a git repository` error

**Solution:** Worktrees only work in git projects. Initialize git:
```bash
git init
git add .
git commit -m "Initial commit"
```

**Issue:** Worktree creation fails

**Solution:** Check for existing worktree at path:
```bash
git worktree list
git worktree remove .claude/worktrees/Stream-B  # If exists
```

**Issue:** Cannot switch to worktree branch

**Solution:** Branches are local to worktrees. Use worktree path:
```bash
cd .claude/worktrees/Stream-B  # Work in worktree directory
git status  # Shows stream-b branch
```

**Issue:** Merge conflicts when integrating stream

**Solution:** Resolve conflicts manually:
```bash
git checkout main
git merge stream-b
# Resolve conflicts in editor
git add .
git commit
```

**Issue:** Stale worktree references

**Solution:** Clean up stale entries:
```bash
git worktree prune
```

---

### Continuation Enforcement

**Issue:** Agent continues indefinitely without completing

**Solution:** Check continuation count in task metadata. If >= 10, task is blocked:
```bash
tc task get TASK-xxx --json
# Check metadata.continuation.continuationCount
# If >= 10, reset by updating task status back to in_progress
tc task update TASK-xxx --status in_progress --json
```

**Issue:** Agent blocked at 10 continuations but work isn't done

**Solution:** Review agent approach. Runaway usually indicates:
- Agent stuck in loop without making progress
- Validation rules too strict
- Agent lacks necessary information

Reset counter and provide additional context:
```bash
tc task update <id> --status in_progress --json
# Add notes with additional context for the agent
```

**Issue:** Continuation prompts not appearing

**Solution:** Check that agent output lacks completion signal:
```typescript
// ❌ Missing signal
"Work is done. Files modified: src/api.ts"

// ✅ Has signal
"Work is done. Files modified: src/api.ts\n\n<promise>COMPLETE</promise>"
```

**Issue:** False positive - agent completed but detected as incomplete

**Solution:** Ensure signal is in **last 100 characters**:
```typescript
// ❌ Signal too early
`<promise>COMPLETE</promise>

Additional notes about the implementation:
[... 200+ characters of notes ...]`

// ✅ Signal at end
`Additional notes about the implementation:
[... notes ...]

<promise>COMPLETE</promise>`
```

---

### Auto-compaction Threshold

**Issue:** Responses still exceeding context limits

**Solution:** Lower threshold or reduce maxTokens:
```typescript
// More aggressive compaction
const shouldCompact = exceedsThreshold(text, 0.75, 4096);  // 75% threshold
```

**Issue:** Responses compacted unnecessarily

**Solution:** Raise threshold:
```typescript
const shouldCompact = exceedsThreshold(text, 0.90, 4096);  // 90% threshold
```

**Issue:** Summary too short / loses context

**Solution:** Increase summary max tokens:
```typescript
const summary = extractSummary(content, 200);  // 200 tokens instead of 100
```

**Issue:** Cannot retrieve full content after compaction

**Solution:** Ensure work product was stored before compacting:
```bash
# Store full content
tc wp store --task <id> --type implementation --title "..." --content "<full content>" --json

# Then return compact summary

# Later, retrieve full content:
tc wp get <wp-id> --json
```

---

---

## v1.8 Harness Features

Based on Anthropic's research on long-running agents, v1.8 adds features that improve agent reliability over multi-session work.

### 7. Verification Enforcement (Default On)

**Purpose:** Prevents "early victory declaration" - agents claiming tasks complete without proof.

**How it works:**
- Tasks with `complexity: "High"` or `"Very High"` automatically require verification
- Agent must provide proof before marking complete (test output, work products, or detailed notes ≥50 chars)
- Task completion blocked without evidence

**Automatic behavior:**
```bash
# High complexity task - verification auto-enabled
tc task create --title "Implement authentication" --prd <id> --json
# metadata: { complexity: "High" }  -- verificationRequired: true (automatic)

# Completion requires proof
tc task update TASK-xxx --status completed --json
# Notes: "All 47 tests pass. See WP-001 for implementation."  -- Sufficient proof
```

**Override if needed:** Set `verificationRequired: false` in task metadata.

---

### 8. Auto-Commit on Completion

**Purpose:** Git commits serve as checkpoints - every completed task creates a commit.

**How it works:**
- When task marked complete AND `filesModified` array exists in metadata
- Auto-stages listed files
- Creates commit: `feat(TASK-xxx): <task title>`
- Includes task ID in commit body

**Automatic behavior:**
```bash
tc task update TASK-xxx --status completed --json
# metadata: { filesModified: ["src/auth.ts", "src/types.ts"] }
# Creates: git commit -m "feat(TASK-xxx): Implement authentication"
```

**Disable for a task:** Set `autoCommit: false` in task metadata.

**Error handling:**
- Dirty directory: warns but doesn't fail
- No git: warns but doesn't fail
- No filesModified: skips commit (no files to commit)

---

### 9. Preflight Check (Session Boundary Protocol)

**Purpose:** Agents verify environment health before starting work, catching issues early.

**Command:** `tc task get <id> --json` (returns task state including environment context)

**What agents check before starting:**
- Task status and metadata via `tc task get <id> --json`
- Git status (clean/dirty, branch, uncommitted files) via `git status`
- Dev server (optional, via Bash)
- Baseline tests (optional, via Bash)

**Usage:**
```bash
# Check task state
tc task get TASK-123 --json

# Check git status
git status

# Optional: check dev server
curl -s http://localhost:3000/health

# Optional: run baseline tests
npm test
```

**Agent integration:**
Agents @agent-me, @agent-ta, and @agent-qa check task state and environment before starting work.

---

### 10. Scope Lock (Two-Agent Enforcement)

**Purpose:** Separates planning (initializer) from execution (worker) to prevent scope creep.

**How it works:**
- PRDs can be marked `scopeLocked: true`
- Only `@agent-ta` (Tech Architect) can create tasks for locked PRDs
- Other agents must route scope change requests to `@agent-ta`

**Auto-detection:**
- FEATURE and EXPERIENCE PRDs auto-lock
- DEFECT and QUESTION PRDs stay unlocked
- Detection based on keywords in title/description

**Manual control:**
```bash
# Explicitly lock
tc prd create --title "Payment system" --json
# Set metadata: { scopeLocked: true }

# Explicitly unlock
tc prd create --title "Add feature" --json
# Set metadata: { scopeLocked: false }
```

**Scope change workflow:**

Scope changes are managed through direct communication with @agent-ta. Worker agents should route scope change requests to @agent-ta, who has the authority to add or modify tasks on locked PRDs.

---

### 11. Task Worktree Isolation

**Purpose:** Isolates risky work in git worktrees - main branch never touched until merge.

**How it works:**
- Enable with `isolatedWorktree: true` in task metadata
- On task start: creates `.worktrees/TASK-xxx` with branch `task/task-xxx`
- On task complete: auto-merges to target branch, cleans up worktree
- If merge conflicts: task blocked, worktree preserved for manual resolution

**Usage:**
```bash
tc task create --title "Risky refactor" --prd <id> --json
# Set metadata: { isolatedWorktree: true }
```

**Conflict handling:**
```bash
# Check conflict status
worktree_conflict_status({ taskId: "TASK-xxx" })

# After manual resolution
worktree_conflict_resolve({ taskId: "TASK-xxx" })
```

---

### 12. WebSocket Bridge (Real-time Events)

**Purpose:** Streams task events to external consumers (UIs, dashboards).

**Architecture:**
- Standalone service polling the task activity_log
- JWT authentication per connection
- Events filtered by initiative

**Starting the bridge:**
```bash
cd mcp-servers/websocket-bridge
JWT_SECRET="secret" WORKSPACE_ID="your-workspace" npm start
```

**Event types:**
- `task.create`, `task.update`, `task.complete`
- `work_product.store`
- `prd.create`
- `checkpoint.create`

**Client connection:**
```javascript
const ws = new WebSocket('ws://localhost:8765', {
  headers: { Authorization: 'Bearer <jwt-token>' }
});

ws.on('message', (data) => {
  const event = JSON.parse(data);
  console.log(event.type, event.payload);
});
```

---

## Summary

These 12 enhancement features transform Claude Copilot into a robust, self-improving development system:

**Context Engineering (1-6):**
1. **Self-improving Memory Schema** - Framework learns from agent experiences
2. **Quality Gates Configuration** - Automated enforcement of code standards
3. **Activation Mode Detection** - Context-aware execution without manual config
4. **Git Worktree Isolation** - True parallel development without conflicts
5. **Continuation Enforcement** - Reliable task completion with runaway protection
6. **Auto-compaction Threshold** - Efficient token usage at scale

**v1.8 Harness Features (7-12):**
7. **Verification Enforcement** - Require proof before marking tasks complete
8. **Auto-Commit on Completion** - Git commits as recovery checkpoints
9. **Preflight Check** - Environment health verification before work
10. **Scope Lock** - Two-agent separation of planning and execution
11. **Task Worktree Isolation** - Isolate risky changes in git worktrees
12. **WebSocket Bridge** - Real-time event streaming for UIs

**Key Benefits:**

| Benefit | Impact |
|---------|--------|
| **Reliability** | Continuation enforcement + quality gates prevent incomplete/defective work |
| **Efficiency** | Auto-compaction + worktree isolation reduce token waste and merge conflicts |
| **Intelligence** | Activation mode + self-improving memory enable adaptive behavior |
| **Safety** | Runaway protection + quality gates prevent infinite loops and regressions |
| **Scalability** | Parallel streams + compaction support large initiatives without context bloat |

**Token Efficiency Summary:**

| Feature | Token Savings | When |
|---------|---------------|------|
| Quality Gates | 0 overhead | Server-side execution |
| Activation Mode | ~5 tokens | Per task metadata |
| Worktree Isolation | ~20 tokens | Stream metadata |
| Continuation Guard | ~150-250 tokens | When catching premature stops |
| Auto-compaction | 95-97% | Responses > threshold |
| Self-improving Memory | ~150 tokens | Per improvement suggestion |

**Combined Impact:** These features enable Claude Copilot to manage complex initiatives with hundreds of tasks while maintaining lean token budgets and high code quality.
