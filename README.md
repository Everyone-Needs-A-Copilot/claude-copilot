<p align="center">
  <a href="https://ineedacopilot.com">
    <img src="assets/copilot-co-logo.svg" alt="Claude Copilot" width="100">
  </a>
</p>

<h1 align="center">Claude Copilot</h1>

<p align="center">
  <strong>An instruction layer for Claude Code — 15 framework agents with strict points of view, a design-led process enforced by mechanical hooks, persistent memory across sessions, and real task/worker orchestration. It makes Claude Code's process repeatable, inspectable, and stateful.</strong>
</p>

<p align="center">
  <a href="https://github.com/Everyone-Needs-A-Copilot/claude-copilot/releases/latest"><img src="https://img.shields.io/github/v/release/Everyone-Needs-A-Copilot/claude-copilot?color=green" alt="Version"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/github/license/Everyone-Needs-A-Copilot/claude-copilot" alt="License"></a>
  <a href="https://github.com/Everyone-Needs-A-Copilot/claude-copilot"><img src="https://img.shields.io/github/stars/Everyone-Needs-A-Copilot/claude-copilot?style=social" alt="GitHub stars"></a>
  <a href="https://claude.com/claude-code"><img src="https://img.shields.io/badge/Claude_Code-Compatible-7C3AED" alt="Claude Code"></a>
</p>

---

## What Is Claude Copilot?

**Claude Copilot is a set of instructions that sit on top of Claude Code.** This is an independent, community-driven framework for Claude Code, unaffiliated with Microsoft Copilot or GitHub Copilot.

It's not separate software—it's markdown files (agents, commands, project instructions) and two CLI tools (`cc` and `tc`) that give Claude Code new capabilities:

| You Get                    | What It Does                                                                         |
| -------------------------- | ------------------------------------------------------------------------------------ |
| **Persistent Memory**      | Decisions, lessons, and progress survive across sessions ([FTS5](docs/70-reference/05-glossary.md#fts5) keyword search)       |
| **Memory Drift Detection** | `cc memory check` — token-free deterministic checkers (path-exists, command-resolves, version-conflict, staleness); 0–100 score; exits 1 on any fail-severity finding |
| **Usage Observability**    | `cc usage` — idle-gated quota probe via Keychain OAuth + `anthropic-ratelimit-unified-*` headers; producer/consumer split so consumers never corrupt the quota window |
| **15 Framework Agents**    | Lean agents with on-demand skill loading; methodology-embedded from IDEO to Kent Beck; `kc` is setup-only (not in the build chain). Authoritative roster: `.claude/agents/manifest.json` |
| **Auto-Firing Skills**     | Skills surface automatically from trigger-rich descriptions; code-bearing skills run executable scripts |
| **Parallel Orchestration** | Headless workers execute streams concurrently with `/orchestrate` _(works; unproven at large scale — no proven >5-stream run; tests are mock-only)_ |
| **Pause & Resume**         | Context switch mid-task with `/pause`, return with `/continue`                       |
| **Task Management**        | [PRD](docs/70-reference/05-glossary.md#prd)s, tasks, and work products ([WP](docs/70-reference/05-glossary.md#wp-work-product)) via `tc` CLI with minimal context usage               |
| **Stream Management**      | Parallel work streams with conflict detection and dependencies                       |
| **Known References**       | Configured paths and refs surface into every session via the Known References registry (`cc config set refs.*`); `cc memory` search is available manually — agents do not yet auto-search a company knowledge repo _(roadmap: agent auto-pull)_ |
| **Extensions System**      | Override or extend agents with your company methodologies                            |
| **Code-Execution Path**    | `tc.api` / `cc.api` facades for multi-step ops without CLI round-trip token cost     |
| **Live Docs**              | `cc docs get <pkg>` — version-exact package documentation; agents code against the real installed API, not stale training memory; local-first, offline-safe |
| **Context Engineering**    | Auto-compaction, continuation enforcement, activation modes                          |

When Claude Code reads these instructions, it gains persistent memory, 15 framework agents (plus `kc`, setup-only), and a structured process — the design goal being more disciplined, resumable work built from the practices that tend to produce better software. We measure process and context efficiency, not output quality; there is no defect/rework data yet.

→ [Why we built this](docs/10-architecture/02-philosophy.md)

---

## The Problem

Solo developers are expected to be experts in everything. AI assistants help, but they:

- **Forget everything** between sessions
- **Give generic advice** without context
- **Lack proven processes** for complex work

Teams face the same challenges at scale—plus knowledge silos, inconsistent standards, and AI that amplifies inconsistency.

→ [Read the full problem statement](docs/10-architecture/02-philosophy.md#the-problems-we-solve)

---

## April 2026 Restructure

A diagnostic of 15 sessions (Apr 17-22 2026) found a 6% delegation rate — 94% of work stayed in the main session despite a 14-agent roster. A 5-day staging deployment saga (57 manual bash polling calls, 26 loops) exposed missing primitives. The April 2026 restructure introduced mechanical hook enforcement, the `tc deploy wait` primitive, and model pinning. The roster was consolidated to 8 agents as an interim step to reduce complexity during the hook rollout; it has since been restored and expanded to the current 15 framework agents + `kc` (setup-only).

**Correction (2026-07, TASK-106/C-6):** the hook enforcement shipped April 22 was narrowed to a `Bash`-only `PreToolUse` matcher the same day ("resolve hook deadlock") and stayed that way for over two months — it never fired on `Read`, `Edit`, or `Agent`, the exact tools it was built to police. The root cause (Claude Code shares one `session_id` between a main session and any subagent it spawns, so a subagent's own tool calls could trip and then get denied by the parent's same enforcement state, with no escape since framework agents don't carry the Agent/Task tool) is fixed and proven in this repo (`.claude/hooks/pretool-check.sh`, matcher now `Bash|Read|Edit|Agent`) — see [the root-cause writeup](docs/10-architecture/06-hook-deadlock-root-cause-2026-07.md). Rollout to consumer repos beyond `claude-copilot` itself is a separate, staged effort (C-3), not implied by this fix.

→ [Full diagnostic and rationale](docs/10-architecture/04-framework-restructure-2026-04.md)

---

## How It Works

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              YOU                                             │
│                               │                                              │
│                    "Fix the login bug" or "/continue"                        │
└───────────────────────────────┼─────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PROTOCOL LAYER                                       │
│                                                                              │
│   /protocol  →  Classifies request, routes to right agent                   │
│   /continue  →  Loads your previous session from memory                     │
└───────────────────────────────┼─────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          AGENT LAYER                                         │
│                                                                              │
│   ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐  │
│   │   ta    │ │   me    │ │   qa    │ │   doc   │ │   do    │ │   sd    │  │
│   │Architect│ │Engineer │ │   QA    │ │  Docs   │ │ DevOps  │ │ Service │  │
│   │         │ │         │ │         │ │         │ │         │ │Designer │  │
│   └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘  │
│   ┌─────────┐ ┌─────────┐ ┌─────────┐  ┌─────────┐                          │
│   │   uxd   │ │  uids   │ │   uid   │  │   kc    │  Knowledge Copilot       │
│   │UX Design│ │UI Design│ │UI Dev   │  │ (util)  │                          │
│   │         │ │ System  │ │         │  └─────────┘                          │
│   └─────────┘ └─────────┘ └─────────┘                                      │
└───────────────────────────────┼─────────────────────────────────────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
              ▼                 ▼                 ▼
┌────────────────────┐ ┌────────────────────┐ ┌────────────────────────────────┐
│   MEMORY COPILOT   │ │   TASK COPILOT     │ │          cc SKILLS             │
│   (cc memory)      │ │   (tc CLI)         │ │                                │
│ • Decisions made   │ │ • PRDs & tasks     │ │ • Auto-fires from description  │
│ • Lessons learned  │ │ • Work products    │ │ • Code-bearing: L1/L2/L3      │
│ • FTS5 keyword     │ │ • Externalizes WPs │ │ • Known References registry    │
│                    │ │   out of the main  │ │   (configured paths/refs only) │
│                    │ │   session context  │ │ • Agent auto-pull: roadmap     │
│                    │ │                    │ │                                │
│ • Enables /continue│ │ • tc.api facade    │ │ • cc.api facade                │
└────────────────────┘ └────────────────────┘ └────────────────────────────────┘
```

---

## Quick Start

### 1. Clone

```bash
mkdir -p ~/.claude && cd ~/.claude
git clone https://github.com/Everyone-Needs-A-Copilot/claude-copilot.git copilot
```

### 2. Machine Setup (once)

```bash
cd ~/.claude/copilot && claude
```

Then say:

```
Read @SETUP.md and set up Claude Copilot on this machine
```

### 3. Project Setup (each project)

```bash
cd ~/your-project && claude
```

Then run:

```
/setup-project
```

### 4. Start Working

```bash
/protocol fix the login bug          # Start fresh work
/continue                            # Resume where you left off
```

→ [Complete setup guide](docs/01-getting-started/01-user-journey.md)

---

## How to Use This Framework

Two patterns cover most development work:

### Pattern 1: Fix a Bug

_Illustrative (not a captured transcript)._

```bash
/protocol the checkout form submits twice on Enter key
```

**What happens step-by-step:**

1. **Protocol classifies your request:**

   ```
   [PROTOCOL: DEFECT | Agent: @agent-qa | Action: INVOKING]
   Detected: Bug fix → Routing to QA Engineer...
   ```

2. **@agent-qa diagnoses:**

   ```
   Bug reproduced. Root cause: Missing preventDefault() on keyDown handler.
   Routing to @agent-me for fix...
   ```

3. **@agent-me implements:**

   ```
   Fix implemented:
   - Added e.preventDefault() to handleKeyDown
   - Added test: "prevents double submission on Enter"

   Routing back to @agent-qa for verification...
   ```

4. **@agent-qa verifies and commits:**
   ```
   Verification: PASS ✓
   Git commit: fix(TASK-abc): Prevent double submission on Enter key
   ```

---

### Pattern 2: Build a Feature (with Orchestration)

For substantial features, use parallel work streams:

```bash
/protocol ultrawork add OAuth authentication with Google and GitHub
```

**Step 1: Planning**

The Tech Architect creates a plan with parallel streams:

```
✓ PRD Created: PRD-xyz789
✓ 4 streams identified with 18 tasks

Stream Structure:
  Depth 0 (Foundation):
    • Stream-A (Database & Config) - 4 tasks

  Depth 1 (Parallel):
    • Stream-B (Google OAuth) - 5 tasks → depends on: Stream-A
    • Stream-C (GitHub OAuth) - 5 tasks → depends on: Stream-A

  Depth 2 (Integration):
    • Stream-Z (Integration & Docs) - 4 tasks → depends on: Stream-B, Stream-C

Next: Run /orchestrate start to begin parallel execution
```

**Step 2: Set up worktrees and launch agents**

```bash
/orchestrate start
```

```
Scaffolding ready. Each stream has an isolated worktree.

Launching Task agents for each stream...
  Stream-A (Foundation)... ✓ Agent launched
  Stream-B (blocked by Stream-A) - will start when ready
  Stream-C (blocked by Stream-A) - will start when ready
  Stream-Z (blocked by Stream-B, Stream-C) - will start when ready
```

**Step 3: Monitor progress**

```bash
/orchestrate status
```

```
Stream     | Status      | Progress
-----------|-------------|----------
Stream-A   | completed   | 100%
Stream-B   | in_progress | 60%
Stream-C   | in_progress | 40%
Stream-Z   | pending     | 0%
```

**Step 4: Completion**

When all streams finish:

```
🎉 INITIATIVE COMPLETE 🎉

All streams completed. 18 git commits created.
```

---

### Quick Commands

| Command              | Use For                            |
| -------------------- | ---------------------------------- |
| `/protocol [task]`   | Start any work                     |
| `/continue`          | Resume yesterday's work            |
| `/pause [reason]`    | Context switch, save state         |
| `/orchestrate start` | Set up worktrees, launch agents    |
| `/orchestrate status`| Check stream progress              |

### Work Intensity Keywords

| Keyword     | Use For                   | Example                             |
| ----------- | ------------------------- | ----------------------------------- |
| `quick`     | Typos, obvious fixes      | `/protocol quick fix the typo`      |
| `thorough`  | Deep review, full testing | `/protocol thorough review auth`    |
| `ultrawork` | Large multi-stream features | `/protocol ultrawork redesign auth` |

→ [Full usage guide with more scenarios](docs/70-reference/01-usage-guide.md)

---

## (Optional) Shared Knowledge

```
/knowledge-copilot
```

Creates a Git-managed knowledge repository for company information, shareable via GitHub

---

## Your Team

**Core agents (always available):**

| Agent | Role              | When to Use                                |
| ----- | ----------------- | ------------------------------------------ |
| `ta`  | Tech Architect    | System design, task breakdown, [ADR](docs/70-reference/05-glossary.md#adr)s        |
| `me`  | Engineer          | Implementation, bug fixes, refactoring     |
| `qa`  | QA Engineer       | Testing strategy, edge cases, verification |
| `doc` | Documentation     | READMEs, API docs, technical writing       |
| `do`  | DevOps            | CI/CD, infrastructure, deploy, containers  |
| `sd`  | Service Designer  | Customer journeys, experience strategy     |
| `kc`  | Knowledge Copilot | Shared knowledge setup (utility)           |

**Design chain (sd → uxd → uids → uid → ta → me):**

| Agent  | Role                           | When to Use                             |
| ------ | ------------------------------ | --------------------------------------- |
| `uxd`  | UX Designer                    | Interaction flows, task design          |
| `uids` | UI Design System               | Visual tokens, color, typography        |
| `uid`  | UI Developer                   | Component implementation specs          |

**Specialist branches:**

| Agent | Role                    | When to Use                                      |
| ----- | ----------------------- | ------------------------------------------------ |
| `sec` | Security                | Threat modeling, STRIDE/DREAD analysis           |
| `ind` | Industrial Designer     | Object-level essentialism review (upstream of uxd) |
| `cco` | Creative Director       | Brand strategy, creative direction               |
| `cw`  | Copywriter              | Copy execution, messaging, microcopy             |

**Business advisory (optional — outside the software build chain):**

> `cs` and `cpa` are standalone advisory agents for founder/agency business needs. They do not route into the build chain (sd → uxd → uids → uid → ta → me). Invoke them directly.

| Agent | Role                    | When to Use                                      |
| ----- | ----------------------- | ------------------------------------------------ |
| `cs`  | Customer Success        | Support patterns, retention strategy             |
| `cpa` | CPA / Financial         | Tax implications, financial modeling             |

→ [Meet your full team](docs/10-architecture/01-agents.md) | [Agent roster history](docs/10-architecture/04-framework-restructure-2026-04.md)

---

## All Commands

| Command                 | Purpose                                 |
| ----------------------- | --------------------------------------- |
| `/protocol [task]`      | Start work (auto-routes to right agent) |
| `/continue [stream]`    | Resume from memory or specific stream   |
| `/pause [reason]`       | Save checkpoint for context switch      |
| `/orchestrate start`    | Set up worktrees, launch stream agents  |
| `/orchestrate status`   | Check stream progress                   |
| `/map`                  | Generate project structure analysis     |
| `/setup-project`        | Initialize a new project                |
| `/setup-knowledge-sync` | Enable auto-updates on releases         |
| `/knowledge-copilot`    | Build shared knowledge repo             |

→ [Orchestration Guide](docs/50-features/01-orchestration-workflow.md) | [Knowledge Sync](docs/50-features/03-knowledge-sync.md)

---

## Works Alone, Grows With Teams

| Level          | What You Get                                          |
| -------------- | ----------------------------------------------------- |
| **Solo**       | 15 framework agents + kc (setup-only), persistent memory, local skills |
| **Team**       | + shared knowledge repo, Known References registry    |
| **Enterprise** | + Extensions system, company-specific agent overrides |

→ [Customization guide](docs/20-configuration/02-customization.md) | [Extension Spec](docs/40-extensions/00-extension-spec.md)

---

## Requirements

| Requirement | Version |
| ----------- | ------- |
| Python      | 3.10+   |
| Claude Code | Latest  |
| Disk space  | ~100MB  |

**Build tools (for Python packages):**

- macOS: `xcode-select --install`
- Linux: `sudo apt-get install build-essential`

---

## Documentation

**Start here:**
| Guide | Purpose |
|-------|---------|
| [Usage Guide](docs/70-reference/01-usage-guide.md) | **How to actually use this** - real workflows and scenarios |
| [Decision Guide](docs/10-architecture/03-decision-guide.md) | When to use what - quick reference matrices |
| [Agents](docs/10-architecture/01-agents.md) | All 15 framework agents + kc in detail |

**Setup & Configuration:**
| Guide | Purpose |
|-------|---------|
| [User Journey](docs/01-getting-started/01-user-journey.md) | Complete setup walkthrough |
| [Configuration](docs/20-configuration/01-configuration.md) | .mcp.json, environment variables |
| [Customization](docs/20-configuration/02-customization.md) | Extensions, knowledge repos, private skills |

**Advanced:**
| Guide | Purpose |
|-------|---------|
| [Enhancement Features](docs/50-features/00-enhancement-features.md) | Verification, auto-commit, preflight, worktrees |
| [Extension Spec](docs/40-extensions/00-extension-spec.md) | Creating extensions |
| [Architecture](docs/10-architecture/00-overview.md) | Technical deep dive |
| [Philosophy](docs/10-architecture/02-philosophy.md) | Why we built it this way |

**Operations:**
| Document | Purpose |
|----------|---------|
| [Working Protocol](docs/30-operations/01-working-protocol.md) | Agent-First Protocol details |
| [Documentation Guide](docs/30-operations/02-documentation-guide.md) | Doc standards, token budgets |

**Reference:**
| Document | Purpose |
|----------|---------|
| [Quick Reference](docs/70-reference/00-quick-reference.md) | Command cheatsheet |
| [Glossary](docs/70-reference/05-glossary.md) | FTS5, BM25, ADR, PRD, WP, L1/L2/L3, all 15 framework agent codes + kc |

---

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md).

When modifying agents:

- Keep base agents generic (no company-specific content)
- Use industry-standard methodologies
- Include routing to other agents

---

## License

MIT License - see [LICENSE](LICENSE)

---

## Acknowledgements

This project builds on the work of many contributors and open source projects. See [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md) for credits.

---

<p align="center">
  <a href="https://ineedacopilot.com">
    <img src="assets/ENAC-Tagline-MID.svg" alt="...because Everyone Needs a Copilot" width="400">
  </a>
</p>

<p align="center">
  Built by <a href="https://ineedacopilot.com">Everyone Needs a Copilot</a>
</p>
