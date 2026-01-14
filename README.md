<p align="center">
  <a href="https://ineedacopilot.com">
    <img src="assets/copilot-co-logo.svg" alt="Claude Copilot" width="100">
  </a>
</p>

<h1 align="center">Claude Copilot</h1>

<p align="center">
  <strong>An instruction layer for Claude Code that gives every developer access to a full team of specialists.</strong>
</p>

<p align="center">
  <a href="https://github.com/Everyone-Needs-A-Copilot/claude-copilot/releases/latest"><img src="https://img.shields.io/github/v/release/Everyone-Needs-A-Copilot/claude-copilot?color=green" alt="Version"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/github/license/Everyone-Needs-A-Copilot/claude-copilot" alt="License"></a>
  <a href="https://github.com/Everyone-Needs-A-Copilot/claude-copilot"><img src="https://img.shields.io/github/stars/Everyone-Needs-A-Copilot/claude-copilot?style=social" alt="GitHub stars"></a>
  <a href="https://nodejs.org"><img src="https://img.shields.io/badge/Node.js-18%2B-339933?logo=node.js" alt="Node.js"></a>
  <a href="https://claude.com/claude-code"><img src="https://img.shields.io/badge/Claude_Code-Compatible-7C3AED" alt="Claude Code"></a>
</p>

---

## What Is Claude Copilot?

**Claude Copilot is a set of instructions that sit on top of Claude Code.** This is an independent, community-driven framework for Claude Code, unaffiliated with Microsoft Copilot or GitHub Copilot.

It's not separate software—it's markdown files (agents, commands, project instructions) and three MCP servers that give Claude Code new capabilities:

| You Get | What It Does |
|---------|--------------|
| **Persistent Memory** | Decisions, lessons, and progress survive across sessions |
| **13 Lean Agents** | Specialist agents (~60-100 lines) with on-demand skill loading |
| **Auto-Load Skills** | Agents detect and load relevant skills based on context (file patterns + keywords) |
| **Parallel Orchestration** | Headless workers execute streams concurrently with `/orchestrate` |
| **Pause & Resume** | Context switch mid-task with `/pause`, return with `/continue` |
| **Task Management** | PRDs, tasks, and work products with minimal context usage |
| **Stream Management** | Parallel work streams with conflict detection and dependencies |
| **Knowledge Search** | Your company docs, available in every project |
| **Extensions System** | Override or extend agents with your company methodologies |
| **Skills on Demand** | 25K+ patterns and best practices, loaded when needed |
| **Context Engineering** | Auto-compaction, continuation enforcement, activation modes |

When Claude Code reads these instructions, it transforms from a generic assistant into a full development team that remembers your work.

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
│   │   ta    │ │   me    │ │   qa    │ │   sec   │ │   doc   │ │   do    │  │
│   │Architect│ │Engineer │ │   QA    │ │Security │ │  Docs   │ │ DevOps  │  │
│   └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘  │
│   ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐  │
│   │   sd    │ │   uxd   │ │  uids   │ │   uid   │ │   cw    │ │   cco   │  │
│   │ Service │ │   UX    │ │   UI    │ │   UI    │ │  Copy   │ │Creative │  │
│   │Designer │ │Designer │ │Designer │ │Developer│ │ Writer  │ │  Chief  │  │
│   └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘  │
│                              ┌─────────┐                                    │
│                              │   kc    │  Knowledge Copilot (utility)       │
│                              └─────────┘                                    │
└───────────────────────────────┼─────────────────────────────────────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
              ▼                 ▼                 ▼
┌────────────────────┐ ┌────────────────────┐ ┌────────────────────────────────┐
│   MEMORY COPILOT   │ │   TASK COPILOT     │ │       SKILLS COPILOT           │
│                    │ │                    │ │                                │
│ • Decisions made   │ │ • PRDs & tasks     │ │ • 25,000+ public skills        │
│ • Lessons learned  │ │ • Work products    │ │ • Your private skills          │
│ • Enables /continue│ │ • 96% less context │ │ • Knowledge search             │
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
Read @~/.claude/copilot/SETUP.md and set up Claude Copilot on this machine
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

**Total time: 6-12 minutes from report to commit.**

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

**Step 2: Start parallel workers**

```bash
/orchestrate start
```

```
Starting workers:
  Stream-A (Foundation)... ✓ Worker spawned

Waiting for dependencies:
  Stream-B (blocked by Stream-A)
  Stream-C (blocked by Stream-A)
  Stream-Z (blocked by Stream-B, Stream-C)

To monitor progress, open a second terminal:
  ./watch-status
```

**Step 3: Monitor in second terminal**

```bash
./watch-status
```

```
MY-APP                                                62% ✓11 ⚙4 ○3
═════════════════════════════════════════════════════════════════════
Stream-A [===============] 100%  ✓  4        DONE  Database & Config
Stream-B [==========-----]  60%  ✓  3  ⚙ 2  RUN   Google OAuth
Stream-C [=======--------]  40%  ✓  2  ⚙ 2  RUN   GitHub OAuth
Stream-Z [---------------]   0%       ○ 4  ---   Integration & Docs
═════════════════════════════════════════════════════════════════════
Workers: 2 | Press Ctrl-C to stop
```

**Step 4: Completion**

When all streams finish:

```
🎉 INITIATIVE COMPLETE 🎉

All streams completed. 18 git commits created.
```

---

### Quick Commands

| Command | Use For |
|---------|---------|
| `/protocol [task]` | Start any work |
| `/continue` | Resume yesterday's work |
| `/pause [reason]` | Context switch, save state |
| `/orchestrate start` | Run parallel workers |
| `./watch-status` | Monitor progress (second terminal) |

### Work Intensity Keywords

| Keyword | Use For | Example |
|---------|---------|---------|
| `quick` | Typos, obvious fixes | `/protocol quick fix the typo` |
| `thorough` | Deep review, full testing | `/protocol thorough review auth` |
| `ultrawork` | Multi-day features | `/protocol ultrawork redesign auth` |

→ [Full usage guide with more scenarios](docs/70-reference/01-usage-guide.md)

---

## (Optional) Shared Knowledge

```
/knowledge-copilot
```

Creates a Git-managed knowledge repository for company information, shareable via GitHub

---

## Your Team

| Agent | Role | When to Use |
|-------|------|-------------|
| `ta` | Tech Architect | System design, task breakdown, ADRs |
| `me` | Engineer | Implementation, bug fixes, refactoring |
| `qa` | QA Engineer | Testing strategy, edge cases, verification |
| `sec` | Security | Vulnerabilities, threat modeling, OWASP |
| `doc` | Documentation | READMEs, API docs, technical writing |
| `do` | DevOps | CI/CD, infrastructure, containers |
| `sd` | Service Designer | Customer journeys, experience strategy |
| `uxd` | UX Designer | Task flows, wireframes, accessibility |
| `uids` | UI Designer | Visual design, design systems, tokens |
| `uid` | UI Developer | Component implementation, responsive UI |
| `cw` | Copywriter | Microcopy, error messages, voice |
| `cco` | Creative Chief | Creative direction, brand strategy |
| `kc` | Knowledge Copilot | Shared knowledge setup |

→ [Meet your full team](docs/10-architecture/01-agents.md)

---

## All Commands

| Command | Purpose |
|---------|---------|
| `/protocol [task]` | Start work (auto-routes to right agent) |
| `/continue [stream]` | Resume from memory or specific stream |
| `/pause [reason]` | Save checkpoint for context switch |
| `/orchestrate start` | Launch parallel workers |
| `/orchestrate status` | Check stream progress |
| `/map` | Generate project structure analysis |
| `/setup-project` | Initialize a new project |
| `/setup-knowledge-sync` | Enable auto-updates on releases |
| `/knowledge-copilot` | Build shared knowledge repo |

→ [Orchestration Guide](docs/50-features/01-orchestration-guide.md) | [Knowledge Sync](docs/50-features/03-knowledge-sync.md)

---

## Works Alone, Grows With Teams

| Level | What You Get |
|-------|--------------|
| **Solo** | 13 agents, persistent memory, local skills |
| **Team** | + shared knowledge, private skills via PostgreSQL |
| **Enterprise** | + Skill Marketplace (25K+ skills), full customization |

→ [Customization guide](docs/20-configuration/02-customization.md) | [Extension Spec](docs/40-extensions/00-extension-spec.md)

---

## Requirements

| Requirement | Version |
|-------------|---------|
| Node.js | 18+ |
| Claude Code | Latest |
| Disk space | ~300MB |

**Build tools:**
- macOS: `xcode-select --install`
- Linux: `sudo apt-get install build-essential python3`

---

## Documentation

**Start here:**
| Guide | Purpose |
|-------|---------|
| [Usage Guide](docs/70-reference/01-usage-guide.md) | **How to actually use this** - real workflows and scenarios |
| [Decision Guide](docs/10-architecture/03-decision-guide.md) | When to use what - quick reference matrices |
| [Agents](docs/10-architecture/01-agents.md) | All 13 specialists in detail |

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
