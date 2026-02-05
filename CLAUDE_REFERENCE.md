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
| **Tasks** | Auto | Per-initiative | PRDs, task tracking, work products |
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

13 specialized agents for complex development tasks using the **lean agent model**.

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

Agents are ~60-100 lines and auto-load domain skills using `skill_evaluate`:

```typescript
// Agents auto-detect relevant skills
const skills = await skill_evaluate({
  files: ['src/auth/login.ts'],     // Files being worked on
  text: task.description,            // Task context
  threshold: 0.5                     // Minimum confidence
});
// Then load matching skills via @include
```

**Required Agent Tools:**

| Tool | Purpose |
|------|---------|
| `preflight_check` | Verify environment before work |
| `skill_evaluate` | Auto-detect and load skills |
| `task_get`, `task_update` | Task management |
| `work_product_store` | Store output (not in response) |

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

MCP server for ephemeral PRD, task, and work product storage.

**Location:** `mcp-servers/task-copilot/`

**Purpose:** Agents store detailed work products here instead of returning them to the main session, reducing context bloat by ~94% on average (up to 96% for single-agent tasks, 85%+ for session resume, 92%+ for multi-agent collaboration).

**Core Tools:**

| Tool | Purpose |
|------|---------|
| `prd_create` | Create product requirements document |
| `prd_get` | Retrieve PRD details |
| `prd_list` | List PRDs for initiative |
| `task_create` | Create task or subtask |
| `task_update` | Update task status and notes |
| `task_get` | Retrieve task details |
| `task_list` | List tasks with filters |
| `work_product_store` | Store agent output |
| `work_product_get` | Retrieve full work product |
| `work_product_list` | List work products for task |
| `progress_summary` | Get compact progress overview (~200 tokens) |
| `initiative_link` | Link Memory Copilot initiative to Task Copilot |

**Stream Management:**

| Tool | Purpose |
|------|---------|
| `stream_list` | List all independent work streams in initiative (use `includeArchived: true` to show archived) |
| `stream_get` | Get detailed info for specific stream (~200 tokens) |
| `stream_conflict_check` | Check if files conflict with other streams |
| `stream_unarchive` | Recover an archived stream to make it active again |
| `stream_archive_all` | One-time cleanup to archive all legacy streams (requires `confirm: true`) |

**Stream Archival:**

Streams are automatically archived when switching initiatives via `initiative_link()`. This prevents stream pollution when using `/continue` across different initiatives.

| Scenario | Behavior |
|----------|----------|
| Switch to new initiative | Old streams auto-archived |
| Re-link same initiative | No archival (streams preserved) |
| `/continue Stream-A` | Only shows current initiative's streams |
| `/orchestrate generate` | Calls `initiative_link()` → archives old streams before creating new ones |
| `/orchestrate start` | Only spawns workers for current initiative's streams |
| `watch-status` | Only displays streams from active initiative |
| Need old stream back | Use `stream_unarchive({ streamId: "Stream-A" })` |

**After Updating from Pre-1.7.1:** Run `stream_archive_all({ confirm: true })` once to clean up legacy streams from before the auto-archive feature.

**Agent Collaboration (Hierarchical Handoffs):**

| Tool | Purpose |
|------|---------|
| `agent_handoff` | Record handoff between agents (50-char context, intermediate agents only) |
| `agent_chain_get` | Retrieve full collaboration chain (final agent uses to consolidate) |

**Performance Tracking:**

| Tool | Purpose |
|------|---------|
| `agent_performance_get` | Get agent success rates, completion rates by task type, complexity |

**Checkpoint System:**

| Tool | Purpose |
|------|---------|
| `checkpoint_create` | (Optional) Manually create checkpoint outside iteration loops |
| `checkpoint_resume` | Resume task from last checkpoint with full state |
| `checkpoint_get` | Get specific checkpoint details |
| `checkpoint_list` | List available checkpoints for task |
| `checkpoint_cleanup` | Clean up old or expired checkpoints |

**Note:** Checkpoints are automatically created during iteration loops. Manual `checkpoint_create()` calls are only needed for recovery points outside TDD/iteration workflows.

**Validation System:**

| Tool | Purpose |
|------|---------|
| `validation_config_get` | Get current validation configuration and rules |
| `validation_rules_list` | List validation rules for work product types |

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

- **Hierarchical Handoffs**: Multi-agent chains pass 50-char context between agents; only final agent returns to main (~100 tokens vs ~900)
- **Performance Tracking**: Automatically tracks agent success rates, completion rates by task type and complexity
- **Checkpoint System**: Create recovery points during long-running tasks; auto-expires (extended for manual pauses)
- **Validation System**: Validates work products for size limits, required structure, completeness before storage
- **Token Efficiency**: Validation enforces character/token limits to prevent context bloat (warn/reject modes)
- **Independent Streams**: Parallel work streams with file conflict detection and dependency management (foundation → parallel → integration)
- **Verification Enforcement**: Opt-in blocking of task completion without acceptance criteria and proof (set `metadata.verificationRequired: true`)
- **Activation Modes**: Auto-detected from keywords (ultrawork, analyze, quick, thorough); ultrawork warns when >3 subtasks
- **Progress Visibility**: ASCII progress bars, milestone tracking in PRDs, velocity trends (7d/14d/30d with ↗↘→ indicators)
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
| `/orchestrate` | Project | Set up and manage parallel stream orchestration |

**Quick Start Examples:**
```
/protocol fix login authentication bug        → Auto-routes to @agent-qa
/protocol add dark mode to dashboard          → Auto-routes to @agent-sd
/continue Stream-B                            → Resume parallel stream work
/pause switching to urgent bug                → Create checkpoint with reason
/map                                          → Generate project structure map
/orchestrate start                            → Start parallel workers for all streams
/orchestrate status                           → Check progress of all streams
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

Agents should call `preflight_check()` before beginning implementation, planning, or testing to surface environment issues early and prevent wasted work.

### When to Use

| Agent | When to Check | Why |
|-------|---------------|-----|
| `@agent-me` | Before implementation | Verify environment, git state, dependencies satisfied |
| `@agent-ta` | Before planning/PRD creation | Understand current context, check for blockers |
| `@agent-qa` | Before running tests | Ensure test environment configured, no false failures |

### Preflight Check Tool

**Tool:** `preflight_check({ taskId: "TASK-xxx" })`

**Returns health report with:**

| Field | Description |
|-------|-------------|
| `healthy` | Overall health status (boolean) |
| `git.clean` | Whether working directory is clean |
| `progress.blockedTasks` | Number of blocked tasks |
| `environment` | Environment issues detected |
| `recommendations` | Suggested actions if unhealthy |

### Decision Matrix

| Condition | Action |
|-----------|--------|
| `healthy: true` | Proceed with work |
| `git.clean: false` (unrelated changes) | Warn user, suggest commit/stash |
| `git.clean: false` (related changes) | Proceed, note in context |
| `blockedTasks > 3` | Suggest unblocking before new work |
| `environment` issues | Fix critical issues before proceeding |

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
- Use `stream_conflict_check()` for parallel work planning

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
- **Stream coordination**: Avoid file conflicts in parallel work

### Example Usage

```typescript
// @agent-me starting implementation
const health = await preflight_check({ taskId: "TASK-123" });

if (!health.healthy) {
  // Review recommendations
  if (health.git.clean === false) {
    console.log("Warning: Uncommitted changes detected");
    console.log("Recommendation:", health.recommendations);
    // Proceed if changes are related to current task
  }

  if (health.environment.length > 0) {
    console.log("Environment issues:", health.environment);
    // STOP and fix critical issues
    return;
  }
}

// Proceed with implementation
```

---

## Lifecycle Hooks Quick Reference

Lifecycle hooks intercept execution at critical phases for security, transformation, and monitoring.

### Hook Types

| Hook | Fires | Primary Use |
|------|-------|-------------|
| `PreToolUse` | Before tool executes | Security validation, preprocessing |
| `PostToolUse` | After tool completes | Logging, result transformation |
| `UserPromptSubmit` | Before prompt processing | Context injection, skill detection |

### PreToolUse Security Rules (Built-in)

| Rule | Action | Detects |
|------|--------|---------|
| `secret-detection` | Block | AWS keys, GitHub tokens, JWTs, private keys |
| `destructive-command` | Block | `rm -rf /`, `DROP DATABASE`, etc. |
| `sensitive-file-protection` | Block | `.env`, credentials, SSH keys |
| `credential-url` | Block | URLs with embedded passwords |

### Hook API Examples

```typescript
// Test if a tool call would be blocked
import { testSecurityRules } from 'task-copilot/hooks';
const result = await testSecurityRules('Write', { file_path: '.env', content: '...' });
if (!result.allowed) console.log('Would be blocked:', result.violations);

// Register custom rule
import { registerSecurityRule, SecurityAction } from 'task-copilot/hooks';
registerSecurityRule({
  id: 'my-rule', name: 'Custom', description: '...', enabled: true, priority: 75,
  evaluate: (ctx) => ctx.toolInput.content?.includes('UNSAFE')
    ? { action: SecurityAction.BLOCK, ruleName: 'my-rule', reason: 'Unsafe', severity: 'high' }
    : null
});
```

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
