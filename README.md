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
| **12 Specialist Agents** | Expert guidance for architecture, security, UX, and more |
| **Task Management** | PRDs, tasks, and work products with minimal context usage |
| **Knowledge Search** | Your company docs, available in every project |
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
│   │   sd    │ │   uxd   │ │  uids   │ │   uid   │ │   cw    │ │   kc    │  │
│   │ Service │ │   UX    │ │   UI    │ │   UI    │ │  Copy   │ │Knowledge│  │
│   │Designer │ │Designer │ │Designer │ │Developer│ │ Writer  │ │ Copilot │  │
│   └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘  │
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

### The Basic Pattern

```bash
# New work
/protocol [describe what you want to do]

# Resume
/continue
```

That's it. The framework classifies your request, routes to the right specialist, tracks progress, and remembers everything.

### Real Workflows

**Bug fix:**
```bash
/protocol the checkout crashes on empty cart
```
→ Routes to QA → reproduces → routes to Engineer → fixes → verifies → auto-commits

**New feature:**
```bash
/protocol add dark mode to settings
```
→ Routes through Service Design → UX → UI Design → Implementation → verified and committed

**Resume yesterday:**
```bash
/continue
```
→ Loads memory → shows progress → picks up exactly where you left off

### Work Intensity

Control depth with keywords:

| Keyword | Use For |
|---------|---------|
| `quick` | Typos, obvious fixes |
| `analyze` | Investigation only |
| `thorough` | Deep review, full testing |
| `ultrawork` | Multi-day features, architecture |

```bash
/protocol quick fix the typo
/protocol ultrawork redesign the auth system
```

### What Happens Automatically

| Feature | What It Does |
|---------|--------------|
| **Preflight Check** | Agents verify environment before starting |
| **Verification** | Complex tasks require proof of completion |
| **Auto-Commit** | Completed tasks create git commits |
| **Scope Lock** | Feature PRDs prevent scope creep |
| **Memory** | Progress survives across sessions |

### Context Switching

```bash
/pause switching to urgent bug    # Save current work
/protocol fix the crash           # Handle urgent work
/continue Stream-A                # Resume previous work
```

→ [Full usage guide with scenarios](docs/70-reference/01-usage-guide.md)

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
| `kc` | Knowledge Copilot | Shared knowledge setup |

→ [Meet your full team](docs/10-architecture/01-agents.md)

---

## Commands

| Command | Purpose | Example |
|---------|---------|---------|
| `/protocol [task]` | Start work with Agent-First Protocol | `/protocol add dark mode` |
| `/continue [stream]` | Resume from memory | `/continue Stream-B` |
| `/orchestrate` | Run parallel work streams | `/orchestrate start` |
| `/setup-project` | Initialize a new project | |
| `/knowledge-copilot` | Build shared knowledge | |

---

## Works Alone, Grows With Teams

| Level | What You Get |
|-------|--------------|
| **Solo** | 12 agents, persistent memory, local skills |
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
| [Agents](docs/10-architecture/01-agents.md) | All 12 specialists in detail |

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
