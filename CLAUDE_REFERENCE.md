# CLAUDE_REFERENCE.md

Extended reference documentation for Claude Copilot framework components.

---

## Quick Decision Guide (Full Details)

### Feature Comparison

| Feature | Invocation | Persistence | Best For |
|---------|------------|-------------|----------|
| **Memory** | Auto | Cross-session | Context preservation, decisions, lessons |
| **Agents** | Protocol | Session | Expert tasks, complex work |
| **Skills (Native)** | Manual (@include) | Session | Local reusable patterns, workflows |
| **Skills (MCP)** | Auto/Manual | On-demand | Marketplace access, cross-source search |
| **Tasks** | CLI (`tc`) | Per-initiative | PRDs, task tracking, work products |
| **Commands** | Manual | Session | Quick shortcuts, workflows |
| **Extensions** | Auto | Permanent | Team standards, custom methodologies |

### Protocol Flow System

The `/protocol` command uses intent detection to route work through the appropriate agent chain. There are four flows:

**Flow A: Experience-First (DEFAULT)**
- **Triggers:** Building features, adding functionality, creating UI, or no strong keywords
- **Chain:** sd → uxd → uids → ta → me
- **Checkpoints:** After sd, uxd, uids (user approves each stage)
- **Philosophy:** Design before code, think about user journey first

**Flow B: Defect**
- **Triggers:** Keywords like bug, broken, fix, error, not working, crash
- **Chain:** qa → me → qa
- **Checkpoints:** After qa diagnosis, after me fix
- **Philosophy:** Diagnose thoroughly, fix with tests, verify resolution

**Flow C: Technical-Only**
- **Triggers:** Keywords like refactor, optimize, architecture, performance, or `--technical` flag
- **Chain:** ta → me
- **Checkpoints:** After ta planning
- **Philosophy:** Plan architecture first, then implement cleanly

**Flow D: Clarification**
- **Triggers:** Ambiguous keywords like improve, enhance, update, change
- **Behavior:** Ask user to clarify intent (experience/technical/defect) before routing
- **Philosophy:** Never assume - get explicit direction when unclear

**Escape Hatches:**
- Use `--technical`, `--defect`, or `--experience` flags to force a specific flow
- Use `--skip-sd`, `--skip-uxd`, `--skip-uids` to bypass design stages
- Use `--no-checkpoints` to run full chain without pausing
- Use `--verbose` or `--minimal` to control checkpoint verbosity

### Agent Selection Matrix

| Scenario | Start With | Agent Chain | Why |
|----------|------------|-------------|-----|
| Bug reported | `/protocol fix [issue]` | qa → me → qa | Diagnose → fix → verify |
| New feature | `/protocol add [feature]` | sd → uxd → uids → ta → me | Experience-first design |
| Architecture question | `/protocol [technical work]` | ta → me | System design expertise |
| Refactor/optimize | `/protocol refactor [component]` | ta → me | Technical improvements |
| Security concern | Any agent | Route to `@agent-sec` | Vulnerability analysis |
| API documentation | Any agent | Route to `@agent-doc` | Technical writing |
| CI/CD pipeline | `/protocol` + technical keywords | ta → do → me | Infrastructure automation |
| Ambiguous request | `/protocol [vague description]` | Clarification flow | Ask user intent first |

### Extension Type Guide

| Goal | Extension Type | File Pattern | Behavior |
|------|----------------|--------------|----------|
| Replace agent entirely | `override` | `agent-name.override.md` | Full replacement |
| Add to agent sections | `extension` | `agent-name.extension.md` | Section-level merge |
| Inject skills only | `skills` | `agent-name.skills.json` | Skill injection |
| Company methodology | `override` | Multiple agents | Custom processes |
| Add checklists/templates | `extension` | Specific sections | Enhance existing |

### Memory vs Skills vs Extensions

| When to Use | Memory | Skills (Native) | Skills (MCP) | Extensions |
|-------------|--------|-----------------|--------------|------------|
| Project context | ✓ | | | |
| Team decisions | ✓ | | | |
| Reusable workflows | | ✓ (@include) | ✓ (skill_get) | |
| Company standards | | | | ✓ |
| Past lessons | ✓ | | | |
| Custom methodologies | | | | ✓ |
| Tool integrations | | ✓ (@include) | ✓ (skill_get) | |
| Local patterns | | ✓ (@include) | | |
| Marketplace skills | | | ✓ (SkillsMP) | |
| Cross-project patterns | | ✓ (~/skills) | ✓ (Private DB) | ✓ |

---

## The Five Pillars (Detailed)

### 1. Memory Copilot (Full Details)

MCP server providing persistent memory across sessions.

**Location:** `mcp-servers/copilot-memory/`

| Tool | Purpose |
|------|---------|
| `initiative_get` | Retrieve current initiative (supports `mode: "lean"` for ~150 tokens or `mode: "full"` for ~370 tokens) |
| `initiative_start` | Begin new initiative |
| `initiative_update` | Update progress, decisions, lessons |
| `initiative_complete` | Archive completed initiative |
| `memory_store` | Store decisions, lessons, context |
| `memory_search` | Semantic search across memories |

**Two-Tier Resume System:**
- **Lean mode** (default): Returns ~150 tokens - status, currentFocus, nextAction only
- **Full mode**: Returns ~370 tokens - includes decisions, lessons, keyFiles

**Configuration:**

| Env Variable | Default | Purpose |
|--------------|---------|---------|
| `MEMORY_PATH` | `~/.claude/memory` | Base storage path |
| `WORKSPACE_ID` | (auto-hash) | Explicit workspace identifier |

**Important:** By default, each project gets a unique database based on its path hash. Set `WORKSPACE_ID` explicitly to preserve memories when renaming/moving projects. See `mcp-servers/copilot-memory/README.md` for details.

### 2. Agents (Full Details)

14 specialized agents for complex development tasks using the **lean agent model**.

**Location:** `.claude/agents/`

| Agent | Name | Domain |
|-------|------|--------|
| `me` | Engineer | Code implementation |
| `ta` | Tech Architect | System design |
| `qa` | QA Engineer | Testing |
| `sec` | Security | Security review |
| `doc` | Documentation | Technical writing |
| `do` | DevOps | CI/CD, infrastructure |
| `sd` | Service Designer | Experience strategy |
| `uxd` | UX Designer | Interaction design |
| `uids` | UI Designer | Visual design |
| `uid` | UI Developer | UI implementation |
| `cw` | Copywriter | Content/copy |
| `cco` | Creative Chief Officer | Creative direction |
| `kc` | Knowledge Copilot | Shared knowledge setup |

**Lean Agent Model:**

Agents are 60-120 lines each. Shared boilerplate (skill loading, Task Copilot pattern, iteration loop, return format, context compaction, knowledge pull-based, specification workflow, multi-agent handoff, protocol integration) is extracted to the "Agent Shared Behaviors" section in CLAUDE.md. Individual agent files contain only domain-specific logic, core behaviors, output format, and routing tables.

**Required Agent Tools/Commands:**

| Tool/Command | Purpose |
|--------------|---------|
| `tc task get <id> --json` | Verify task exists and retrieve details before work |
| `skill_evaluate` | Auto-detect and load skills (Skills Copilot MCP) |
| `tc task update <id> --status <s> --json` | Update task status |
| `tc wp store --task <id> --type <t> --title "..." --content "..." --json` | Store output (not in response) |

### 3. Skills (Full Details)

Skills can be loaded via **native @include directive** or **Skills Copilot MCP server**.

#### Native @include (Recommended for Local Skills)

Load local skills directly without MCP overhead:

```markdown
## Context
When working with Laravel:
@include ~/.claude/skills/laravel/SKILL.md

When writing tests:
@include .claude/skills/testing/SKILL.md
```

**Benefits:**
- Zero MCP overhead (~500 tokens saved per skill)
- Instant loading, no network/database
- Simpler setup (no MCP configuration)
- Full control over skill content

**Use for:**
- Project-specific skills (`.claude/skills/`)
- User-level skills (`~/.claude/skills/`)
- Simple, direct loading

#### Auto-Detection with skill_evaluate

Agents use `skill_evaluate` to automatically detect relevant skills based on file patterns and keywords:

```typescript
const skills = await skill_evaluate({
  files: ['src/Button.test.tsx'],     // Match against trigger_files
  text: 'Help with React testing',    // Match against trigger_keywords
  threshold: 0.5                      // Minimum confidence (0-1)
});
// Returns ranked list: { skillName, confidence, path }
```

See [Skill Evaluation Quick Reference](#skill-evaluation-quick-reference) for details.

#### Skills Copilot MCP (OPTIONAL)

MCP server for advanced skill management and marketplace access.

**Location:** `mcp-servers/skills-copilot/`

**Skill Tools:**

| Tool | Purpose |
|------|---------|
| `skill_get` | Load specific skill by name |
| `skill_search` | Search skills across sources |
| `skill_list` | List available skills |
| `skill_save` | Save skill to private DB |
| `skill_evaluate` | Auto-detect skills from context |

**Knowledge Tools:**

| Tool | Purpose |
|------|---------|
| `knowledge_search` | Search knowledge files (project → global) |
| `knowledge_get` | Get specific knowledge file by path |

**Use when you need:**
- SkillsMP marketplace access (25K+ public skills)
- Private skill storage in Postgres database
- Cross-source skill search (DB + marketplace + local)
- Usage analytics and caching
- Knowledge repository extensions

Knowledge is searched in two-tier resolution: project-level first (`KNOWLEDGE_REPO_PATH`), then machine-level (`~/.claude/knowledge`).

### 4. Task Copilot (Full Details)

CLI tool for ephemeral PRD, task, and work product storage. Task Copilot operations use the `tc` CLI tool (installed at `tools/tc/`). Agents call `tc` commands via Bash instead of MCP tool calls.

**Location:** `tools/tc/`

**Purpose:** Agents store detailed work products here instead of returning them to the main session, reducing context bloat by ~94% on average (up to 96% for single-agent tasks, 85%+ for session resume, 92%+ for multi-agent collaboration).

**Core Commands:**

| Command | Purpose |
|---------|---------|
| `tc prd create --title "..." --json` | Create product requirements document |
| `tc prd get <id> --json` | Retrieve PRD details |
| `tc prd list --json` | List PRDs for initiative |
| `tc task create --title "..." --prd <id> --json` | Create task or subtask |
| `tc task update <id> --status <s> --json` | Update task status and notes |
| `tc task get <id> --json` | Retrieve task details |
| `tc task list [--stream N] --json` | List tasks with filters |
| `tc wp store --task <id> --type <t> --title "..." --content "..." --json` | Store agent output |
| `tc wp get <id> --json` | Retrieve full work product |
| `tc wp list --json` | List work products for task |
| `tc progress --json` | Get compact progress overview (~200 tokens) |

**Stream Management:**

| Command | Purpose |
|---------|---------|
| `tc stream list --json` | List all independent work streams in initiative |
| `tc stream get <id> --json` | Get detailed info for specific stream (~200 tokens) |

**Note:** Stream conflict checking, unarchiving, and bulk archival have been removed. Use `git diff` for conflict detection between streams.

**Agent Collaboration (Hierarchical Handoffs):**

| Command | Purpose |
|---------|---------|
| `tc handoff --from <a> --to <b> --task <id> --context "..." --json` | Record handoff between agents (intermediate agents only) |
| `tc log --task <id> --json` | Retrieve full collaboration chain (final agent uses to consolidate) |

**Configuration:**

| Env Variable | Default | Purpose |
|--------------|---------|---------|
| `TASK_DB_PATH` | `~/.claude/tasks` | Database storage path |
| `WORKSPACE_ID` | (auto) | Links to Memory Copilot workspace |

**Work Product Types:**

| Type | Agent |
|------|-------|
| `architecture` | @agent-ta |
| `technical_design` | @agent-ta, @agent-do |
| `implementation` | @agent-me |
| `test_plan` | @agent-qa |
| `security_review` | @agent-sec |
| `documentation` | @agent-doc |
| `specification` | @agent-sd, @agent-uxd, @agent-uids, @agent-cw, @agent-cco |
| `other` | @agent-uid, misc. agents |

**Key Features:**

- **Hierarchical Handoffs**: Multi-agent chains pass context between agents via `tc handoff`; only final agent returns to main (~100 tokens vs ~900)
- **Token Efficiency**: Agents store detailed output via `tc wp store` instead of returning to session context
- **Independent Streams**: Parallel work streams with dependency management (foundation → parallel → integration); use `git diff` for conflict detection
- **Progress Visibility**: Compact progress overview via `tc progress --json`
- **Specification Workflow**: Domain agents (sd, uxd, uids, cw, cco) create specifications → @agent-ta reviews and creates tasks with traceability

### 5. Protocol (Full Details)

Commands enforcing battle-tested workflows.

**Location:** `.claude/commands/`

| Command | Level | Purpose |
|---------|-------|---------|
| `/setup` | Machine | One-time machine setup (run from `~/.claude/copilot`) |
| `/setup-project` | User | Initialize a new project |
| `/update-project` | User | Update existing project with latest Claude Copilot |
| `/update-copilot` | User | Update Claude Copilot itself (pull + rebuild) |
| `/knowledge-copilot` | User | Build or link shared knowledge repository |
| `/protocol [task]` | Project | Start fresh work with Agent-First Protocol |
| `/continue [stream]` | Project | Resume previous work (checks pause checkpoints first, then Memory Copilot) |
| `/pause [reason]` | Project | Create named checkpoint with extended expiry for context switching |
| `/map` | Project | Generate PROJECT_MAP.md with codebase analysis |
| `/memory` | Project | View current memory state and recent activity |
| `/orchestrate` | Project | Scaffolding for parallel streams (PRD, tasks, worktrees, conflict check); native `Task` tool handles agent execution |

**Quick Start Examples:**
```
/protocol fix login authentication bug        → Auto-routes to @agent-qa
/protocol add dark mode to dashboard          → Auto-routes to @agent-sd
/continue Stream-B                            → Resume parallel stream work
/pause switching to urgent bug                → Create checkpoint with reason
/map                                          → Generate project structure map
/orchestrate generate                         → Create PRD + stream tasks via @agent-ta
/orchestrate start                            → Set up worktrees, print launch instructions
/orchestrate status                           → Check progress of all streams
/orchestrate merge                            → Merge completed worktrees back to main
```

---

## OMC Features

Five productivity enhancements inspired by [Oh My Claude Code](https://github.com/code-yeongyu/oh-my-opencode):

### 1. Ecomode - Smart Model Routing

Automatically routes tasks to appropriate Claude model (haiku/sonnet/opus) based on complexity scoring.

**Usage in task titles (BREAKING CHANGE v2.8.0):**
```
eco: Fix the login bug                    → Auto-selects model, low effort
fast: Refactor authentication module      → Auto-selects model, medium effort ⚠️ BREAKING
max: Design microservices architecture    → Auto-selects model, max effort ✨ NEW
opus: Update README typo                  → Forces Opus (effort from complexity)
sonnet: Implement feature                 → Forces Sonnet (effort from complexity)
haiku: Fix typo                           → Forces Haiku (effort from complexity)
```

**How it works:**
- Analyzes task title, description, file count, and agent type
- Calculates complexity score (0.0 to 1.0)
- Routes model: < 0.3 = haiku, 0.3-0.7 = sonnet, > 0.7 = opus
- Determines effort: < 0.3 = low, 0.3-0.7 = high, > 0.7 = max
- Keywords can override model (opus:, sonnet:, haiku:) or effort (eco:, fast:, max:)

**Benefits:**
- Cost optimization for simple tasks
- Performance boost with haiku for quick fixes
- Automatic scaling to opus for complex work

### 2. Magic Keywords - Quick Action Routing

Action keywords at message start suggest agent routing and task type.

**Supported keywords:**
```
fix: Authentication not working           → Routes to @agent-qa
add: Dark mode to dashboard              → Routes to @agent-me
refactor: Database connection pool       → Routes to @agent-ta
optimize: API response time              → Routes to @agent-ta
test: Login flow edge cases              → Routes to @agent-qa
doc: API endpoints                       → Routes to @agent-doc
deploy: Production environment           → Routes to @agent-do
```

**Combine with modifiers:**
```
eco: fix: login bug                      → QA agent + auto-model + low effort
fast: doc: quick API reference           → Doc agent + auto-model + medium effort
max: add: complex feature                → Engineer + auto-model + max effort
opus: refactor: auth module              → Engineer + opus + complexity-based effort
```

**Rules:**
- Keywords must be at message start
- Case-insensitive matching
- Max 1 modifier + 1 action keyword
- False positive prevention (e.g., "economics:" ignored)

### 3. Progress HUD - Live Status Display

Real-time statusline showing task progress, model in use, and token estimates.

**Format:**
```
[Stream-A] ▶ 50% | sonnet | ~1.2k tokens
[Stream-B] ✓ 100% | haiku | ~500 tokens
```

**Components:**
- Stream/task identifier
- Progress indicator with unicode symbols (⏸ ▶ ⚠ ✓)
- Model indicator with color coding
- Token usage estimate
- Optional: Active file tracking

**Usage:**
```typescript
const hud = createStatusline('TASK-123', 'Fix auth bug', 'Stream-A');
hud.updateState({ status: 'in_progress', progressPercent: 50 });
hud.updateModel('sonnet');
const rendered = hud.render(); // → "[Stream-A] ▶ 50% | sonnet | ~1.2k"
```

### 4. Skill Extraction - Auto-Detect Patterns

Automatically detects repeated patterns in work and suggests skill extractions.

**Detection:**
- File patterns (e.g., "always use X pattern in src/auth/**/*.ts")
- Keyword patterns (e.g., "error handling", "validation", "testing")
- Workflow patterns (e.g., "run tests before commit")
- Best practices (e.g., "use async/await, not callbacks")

**Workflow:**
1. Pattern detection runs after task completion
2. Suggests skill creation with confidence score
3. Review and approve via `/skills-approve` command
4. Auto-generates skill file with:
   - Pattern description
   - Usage examples
   - Trigger conditions (files/keywords)
   - Quality checklist

**Benefits:**
- Builds team knowledge automatically
- Reduces repetitive explanations
- Improves consistency across sessions

### 5. Zero-Config Install - One Command Setup

Simple installer with automatic dependency checking and fixing.

**Primary method:**
```bash
# Install globally with auto-fix
npx claude-copilot install --global --auto-fix

# Install to project
npx claude-copilot install --project .
```

**Features:**
- Auto-detects missing dependencies (Node.js, Git, build tools)
- Platform-specific fixes (Homebrew on macOS, apt/dnf/pacman on Linux)
- Validates installation after completion
- Clear error messages with recovery instructions

**Commands:**
```bash
npx claude-copilot check         # Check dependencies
npx claude-copilot validate      # Validate installation
npx claude-copilot install       # Install with options
```

**What it replaces:**
- Manual dependency installation
- Manual MCP server builds
- Manual directory creation
- Manual configuration setup

See `packages/installer/README.md` for full documentation.

---

## Extension System (Full Details)

This framework supports extensions via knowledge repositories. Extensions allow company-specific methodologies to override or enhance base agents.

### Two-Tier Resolution

Extensions are resolved in priority order:

| Tier | Path | Configuration |
|------|------|---------------|
| 1. Project | `$KNOWLEDGE_REPO_PATH` | Set in `.mcp.json` (optional) |
| 2. Global | `~/.claude/knowledge` | Auto-detected (no config needed) |
| 3. Base | Framework agents | Always available |

**Key benefit:** Set up your company knowledge once in `~/.claude/knowledge` and it's automatically available in every project.

### Extension Types

| Type | Behavior |
|------|----------|
| `override` | Replaces base agent entirely |
| `extension` | Adds to base agent (section-level merge) |
| `skills` | Injects additional skills into agent |

### Setting Up Global Knowledge Repository

Create a knowledge repository at `~/.claude/knowledge/`:

```
~/.claude/knowledge/
├── knowledge-manifest.json    # Required
└── .claude/
    └── extensions/
        ├── sd.override.md     # Your agent extensions
        └── uxd.extension.md
```

**Minimal manifest:**
```json
{
  "version": "1.0",
  "name": "my-company",
  "description": "Company-specific agent extensions"
}
```

No `.mcp.json` changes needed - global repository is auto-detected.

### Project-Specific Overrides (Optional)

Only needed when a project requires different extensions than global:

```json
{
  "mcpServers": {
    "skills-copilot": {
      "env": {
        "KNOWLEDGE_REPO_PATH": "/path/to/project-specific/knowledge"
      }
    }
  }
}
```

### Extension Tools

| Tool | Purpose |
|------|---------|
| `extension_get` | Get extension for specific agent |
| `extension_list` | List all extensions (shows source: global/project) |
| `manifest_status` | Check both global and project repo status |

### Documentation

See [extension-spec.md](docs/40-extensions/00-extension-spec.md) for full documentation on:
- Creating knowledge repositories
- Extension file formats
- Fallback behaviors
- Required skills validation

---

## Session Boundary Protocol

The Session Boundary Protocol ensures agents start work in a healthy environment by running preflight checks before substantive work.

### Overview

Agents should verify the task exists via `tc task get <id> --json` and check git/environment state before beginning implementation, planning, or testing to surface environment issues early and prevent wasted work.

### When to Use

| Agent | When to Check | Why |
|-------|---------------|-----|
| `@agent-me` | Before implementation | Verify environment, git state, dependencies satisfied |
| `@agent-ta` | Before planning/PRD creation | Understand current context, check for blockers |
| `@agent-qa` | Before running tests | Ensure test environment configured, no false failures |

### Preflight Check

Verify the task exists and review its current state:

```bash
tc task get TASK-123 --json
```

Additionally, check git and environment health:

```bash
git status --short
git diff --stat
```

### Decision Matrix

| Condition | Action |
|-----------|--------|
| Task exists and is assignable | Proceed with work |
| Git working directory dirty (unrelated changes) | Warn user, suggest commit/stash |
| Git working directory dirty (related changes) | Proceed, note in context |
| Multiple blocked tasks | Suggest unblocking before new work |
| Environment issues (missing deps, config errors) | Fix critical issues before proceeding |

### Agent-Specific Guidance

**@agent-me:**
- Must verify environment before implementation
- Git dirty with unrelated changes: warn but can continue if acknowledged
- Environment issues: STOP and fix (missing deps, config errors)
- Blocked dependencies: wait for prerequisites

**@agent-ta:**
- Check before creating PRDs/tasks
- Git dirty: note current work, ensure new plan doesn't conflict
- Many blocked tasks: identify patterns, address in plan
- Use `git diff` to check for file conflicts across parallel work streams

**@agent-qa:**
- Check before running tests
- Environment issues: fix before test execution to prevent false failures
- Git dirty with failing tests: determine if failures from current changes
- Missing test dependencies: install before proceeding

### Benefits

- **Early issue detection**: Surface problems before wasted work
- **Context awareness**: Understand current state before planning
- **Better decisions**: Know git state, blockers, environment status
- **Prevent false failures**: Ensure healthy environment for tests
- **Stream coordination**: Use `git diff` to avoid file conflicts in parallel work

### Example Usage

```bash
# @agent-me starting implementation

# 1. Verify the task exists
tc task get TASK-123 --json

# 2. Check git state
git status --short

# 3. If working directory is dirty with unrelated changes:
#    Warn user and suggest: git stash or git commit

# 4. If environment issues (missing deps, etc.):
#    STOP and fix before proceeding

# 5. Proceed with implementation
```

---

## Lifecycle Hooks Quick Reference

**Note:** Lifecycle hooks (hook_register, hook_clear, hook_evaluate, hook_list) have been removed from Task Copilot. The security rules below are maintained by the development environment directly.

### Security Rules (Built-in)

| Rule | Action | Detects |
|------|--------|---------|
| `secret-detection` | Block | AWS keys, GitHub tokens, JWTs, private keys |
| `destructive-command` | Block | `rm -rf /`, `DROP DATABASE`, etc. |
| `sensitive-file-protection` | Block | `.env`, credentials, SSH keys |
| `credential-url` | Block | URLs with embedded passwords |

**Full documentation:** [docs/50-features/lifecycle-hooks.md](docs/50-features/lifecycle-hooks.md)

---

## Skill Evaluation Quick Reference

Automatically detect relevant skills from file patterns and text keywords.

### Evaluation Methods

| Method | Analyzes | Weight |
|--------|----------|--------|
| Pattern matching | File paths (glob patterns) | 0.5 |
| Keyword detection | Text content (TF-IDF) | 0.5 |

### skill_evaluate Tool

```typescript
// Evaluate context for relevant skills
const result = await skill_evaluate({
  files: ['src/Button.test.tsx'],     // File patterns to match
  text: 'Help with React testing',    // Keywords to detect
  recentActivity: ['testing'],        // Boost matching skills
  threshold: 0.3,                     // Min confidence (0-1)
  limit: 5                            // Max results
});

// Returns ranked skills:
// { skillName: 'react-testing', confidence: 0.78, level: 'high', reason: '...' }
```

### Confidence Levels

| Level | Threshold | Meaning |
|-------|-----------|---------|
| High | >= 0.7 | Strong match, likely relevant |
| Medium | >= 0.4 | Moderate match, possibly relevant |
| Low | < 0.4 | Weak match |

**Full documentation:** [docs/50-features/skill-evaluation.md](docs/50-features/skill-evaluation.md)

---

## Correction Detection Quick Reference

Auto-capture user corrections for continuous agent/skill improvement.

### Detection Patterns

| Pattern Type | Example | Weight |
|--------------|---------|--------|
| Explicit | "Correction: use X" | 0.95 |
| Negation | "No, that's wrong" | 0.90 |
| Replacement | "Use X instead of Y" | 0.90 |
| Preference | "I prefer X over Y" | 0.75 |

### Correction Tools

| Tool | Purpose |
|------|---------|
| `correction_detect` | Detect patterns in user message |
| `correction_list` | List pending/approved corrections |
| `correction_update` | Approve or reject a correction |
| `correction_route` | Get routing info (skill/agent/memory) |

### /reflect Command

Review and manage pending corrections:

```bash
/reflect                    # Review all pending
/reflect --agent me         # Filter by agent
/reflect --status approved  # Filter by status
```

### Example Detection

```typescript
import { detectCorrections } from 'copilot-memory/tools/correction-tools';

const result = detectCorrections({
  userMessage: 'Actually, use async/await instead of callbacks',
  previousAgentOutput: '...',
  agentId: 'me',
  threshold: 0.5
}, 'project-id');

// result.detected: true
// result.maxConfidence: 0.85
// result.suggestedAction: 'auto_capture'
```

**Full documentation:** [docs/50-features/correction-detection.md](docs/50-features/correction-detection.md)
