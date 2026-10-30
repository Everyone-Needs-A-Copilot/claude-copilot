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

It's not separate software. It's markdown files (agents, commands, skills, project instructions), lifecycle hooks, and two CLI tools (`cc` and `tc`) that give Claude Code new capabilities:

| You Get | What It Does |
| --- | --- |
| **Persistent Memory** | Decisions, lessons, and progress survive across sessions ([FTS5](docs/70-reference/05-glossary.md#fts5) keyword search) |
| **Memory Drift Detection** | `cc memory check`: token-free deterministic checkers (path-exists, command-resolves, version-conflict, staleness); 0–100 score; exits 1 on any fail-severity finding |
| **15 Framework Agents** | Lean agents with on-demand skill loading and named methodologies from IDEO to Kent Beck; `kc` is setup-only. Authoritative roster: `.claude/agents/manifest.json` |
| **Product Definition** | `/new-product` takes an empty folder from idea to prototype in six facilitated phases, and writes a `SOUL.md` decision instrument (IS / IS-NOT, principles, anti-patterns, Feature Filter, and the walk-away test: what would make the user stop using it) |
| **Done Block And Completion Report** | Before substantial work, a five-line done block (Done means / Proven by / Not in scope / Assumptions / First example) becomes the task contract; reports close with Works / Unverified / Parked / Decision needed |
| **Mechanical Enforcement** | Hooks block main-session overreach until work is delegated, gate everything after `me` until `qa` returns a verdict with evidence, block destructive commands (`/careful`) and lock edit paths (`/freeze`) |
| **Evidence-Bound QA** | Tasks carry acceptance contracts; `tc task check-qa` requires observed results and source identity, not a bare approval |
| **Execution Limits** | `tc execution`: per-project paid-call budget, replay by default (`--live` is the only paid path), attempt and runtime ceilings |
| **Test Map And Lanes** | `tc tests map` stores a change-to-test map and selects the verification lane from a diff |
| **Rules And Priorities** | `cc rule add` rewrites a rule in place and dates it; `cc priorities` reads every project's tasks and names the week's three outcomes |
| **Auto-Firing Skills** | Skills surface automatically from trigger-rich descriptions; code-bearing skills run executable scripts |
| **Design Quality** | `cc design`: guides, templates, context, review, audit and reports for UI work |
| **Task Management** | [PRD](docs/70-reference/05-glossary.md#prd)s, tasks, streams and work products ([WP](docs/70-reference/05-glossary.md#wp-work-product)) via `tc` with minimal context usage |
| **Parallel Orchestration** | `/orchestrate` scaffolds streams, checks conflicts, creates worktrees and merges them back; the harness dispatches the agents _(unproven at large scale: no proven >5-stream run)_ |
| **Work Lifecycle** | Start, resume, pause, handoff and finish checkpoints; a PreCompact hook writes a handoff before context is summarized; `/cleanup` consolidates history and retires approved clutter; `/reflect` turns corrections into rules |
| **Live Docs** | `cc docs get <pkg>`: version-exact package documentation, local-first and offline-safe |
| **Usage Observability** | `cc usage`: idle-gated Claude quota probe; producers and consumers are split so consumers never corrupt the quota window |
| **Known References** | Configured paths and refs surface into every session (`cc config set refs.*`) |
| **Extensions** | Override or extend agents with your company's methodologies through a knowledge repo |
| **Code-Execution Path** | `tc.api` / `cc.api` facades for multi-step operations without CLI round-trip token cost |
| **Codex Too** | The [Codex Copilot](https://github.com/Everyone-Needs-A-Copilot/codex-copilot) plugin ships embedded under `plugins/codex-copilot`, so `/update-copilot` can deliver the same capabilities to Codex |

The design goal is more disciplined, resumable work built from the practices that tend to produce better software. We measure process and context efficiency, not output quality; there is no defect or rework data yet.

→ [Why we built this](docs/10-architecture/02-philosophy.md)

---

## The Problem

Solo developers are expected to be experts in everything. AI assistants help, but they:

- **Forget everything** between sessions
- **Give generic advice** without context
- **Lack proven processes** for complex work
- **Call work done** without evidence that it works

Teams face the same challenges at scale, plus knowledge silos, inconsistent standards, and AI that amplifies inconsistency.

→ [Read the full problem statement](docs/10-architecture/02-philosophy.md#the-problems-we-solve)

---

## How It Works

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              YOU                                             │
│        "/protocol fix the login bug", "/continue" or "/new-product"          │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PROTOCOL LAYER                                       │
│   /protocol  → done block, classifies the request, routes the agent chain    │
│   /continue  → loads your previous session from memory                       │
│   hooks      → delegation budget, QA gate, /careful, /freeze, handoffs       │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          AGENT LAYER                                         │
│   Build:     ta  me  qa  doc  do  sec                                        │
│   Design:    sd → (ind) → uxd → uids → uid → ta → me                         │
│   Creative:  cco  cw            Business:  cs  cpa        Setup:  kc         │
└───────────────────────────────┬─────────────────────────────────────────────┘
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                 ▼
┌────────────────────┐ ┌────────────────────┐ ┌────────────────────────────────┐
│   MEMORY (cc)      │ │   TASKS (tc)       │ │   SKILLS (cc skill)            │
│ • Decisions        │ │ • PRDs, tasks,     │ │ • Auto-fire from description   │
│ • Lessons, rules   │ │   streams, WPs     │ │ • Code-bearing: L1/L2/L3       │
│ • FTS5 search      │ │ • QA contracts     │ │ • Known References registry    │
│ • Drift checks     │ │ • Execution limits │ │ • /new-product (machine-wide)  │
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

Then run `/setup` (or say "Read @SETUP.md and set up Claude Copilot on this machine"). It installs `cc`, `tc`, the machine commands and the machine-wide `/new-product` skill from one immutable snapshot.

### 3. Project Setup (each project)

```bash
cd ~/your-project && claude
```

Then run `/setup-project`. Keep projects current with `/update-project`, and the framework itself with `/update-copilot`.

### 4. Start Working

```bash
/protocol fix the login bug          # Start fresh work
/continue                            # Resume where you left off
/new-product                         # Define a new product from an empty folder
```

→ [Complete setup guide](docs/01-getting-started/01-user-journey.md)

---

## How to Use This Framework

### Pattern 1: Fix a Bug

_Illustrative (not a captured transcript)._

```bash
/protocol the checkout form submits twice on Enter key
```

1. **Protocol posts a done block** and waits for one word from you. The confirmed block becomes the task contract.
2. **Protocol classifies and routes:** a defect goes `qa → me → qa`.
3. **@agent-qa reproduces** the bug and names the root cause.
4. **@agent-me fixes** it and adds a test. Main-session tools stay gated until QA answers.
5. **@agent-qa verifies** against the contract and records a verdict with an `ARTIFACT:` line (for example a test run). A bare approval does not unblock the gate.
6. **You get a four-line report:** Works / Unverified / Parked / Decision needed.

### Pattern 2: Build a Feature

```bash
/protocol add dark mode to the dashboard
```

Experience-first is the default flow: `sd → uxd → uids → uid → ta → me → qa`, pausing for your approval at each design checkpoint. Flags override the route:

| Flag | Effect |
| --- | --- |
| `--technical` | Technical flow (`ta → me → qa`) |
| `--defect` | Defect flow (`qa → me → qa`) |
| `--experience` | Experience flow |
| `--infra` | Infrastructure flow (`do → me → qa`) |
| `--skip-sd`, `--skip-ind`, `--skip-uxd`, `--skip-uids`, `--skip-uid` | Skip a design stage |
| `--design-only` | Stop after design (no `ta`/`me`) |
| `--no-checkpoints` | Run the chain without pausing |
| `--verbose` / `--minimal` | Longer or shorter checkpoint summaries |

### Pattern 3: Parallel Streams

For large work, split it into streams that run in isolated worktrees:

```bash
/orchestrate generate   # @agent-ta creates the PRD and stream tasks
/orchestrate start      # validate streams, check conflicts, create worktrees, print dispatch commands
/orchestrate status     # stream progress and live sessions
/orchestrate merge      # merge completed worktrees back
```

### Pattern 4: Define a New Product

```bash
mkdir my-product && cd my-product && claude
/new-product
```

A facilitated interview across six phases (discovery, research and service design, requirements, experience design, design challenge, prototype) writes the design package into `docs/` and a root `SOUL.md`. The soul is drafted after Phase 2, ratified before the prototype, and can't be ratified until the user has answered what would make them stop using the product. It resumes from `docs/TODO-DESIGN-PACKAGE.md`.

→ [Full usage guide with more scenarios](docs/70-reference/01-usage-guide.md)

---

## (Optional) Shared Knowledge

```
/knowledge-copilot
```

Creates a Git-managed knowledge repository for company information, shareable via GitHub. `/setup-knowledge-sync` installs a hook that updates product knowledge after release tags.

---

## Your Team

**Build agents:**

| Agent | Role | When to Use |
| --- | --- | --- |
| `ta` | Tech Architect | System design, task breakdown, [ADR](docs/70-reference/05-glossary.md#adr)s |
| `me` | Engineer | Implementation, bug fixes, refactoring |
| `qa` | QA Engineer | Testing strategy, edge cases, verification |
| `doc` | Documentation | READMEs, API docs, technical writing |
| `do` | DevOps | CI/CD, infrastructure, deploy, containers |
| `sec` | Security | Threat modeling, STRIDE/DREAD analysis |

**Design chain (sd → uxd → uids → uid → ta → me):**

| Agent | Role | When to Use |
| --- | --- | --- |
| `sd` | Service Designer | Customer journeys, experience strategy |
| `ind` | Industrial Designer | Object-level essentialism review (optional, upstream of uxd) |
| `uxd` | UX Designer | Interaction flows, task design |
| `uids` | UI Design System | Visual tokens, color, typography |
| `uid` | UI Developer | Component implementation |

**Creative branches:**

| Agent | Role | When to Use |
| --- | --- | --- |
| `cco` | Creative Director | Brand strategy, creative direction |
| `cw` | Copywriter | Copy execution, messaging, microcopy |

**Business advisory (outside the build chain; invoke directly):**

| Agent | Role | When to Use |
| --- | --- | --- |
| `cs` | Sales | Sales strategy, discovery call prep, objection handling, deal diagnosis |
| `cpa` | CPA / Financial | Tax strategy, owner compensation, cash flow, pricing economics |

**Setup only:** `kc` (Knowledge Copilot) builds the shared knowledge repo through `/knowledge-copilot`.

→ [Meet your full team](docs/10-architecture/01-agents.md) | [Agent roster history](docs/10-architecture/04-framework-restructure-2026-04.md)

---

## All Commands

**In a project:**

| Command | Purpose |
| --- | --- |
| `/protocol [task]` | Start work (done block, then routes to the right agents) |
| `/continue [stream]` | Resume from memory or a specific stream |
| `/pause [reason]` | Save a checkpoint for a context switch |
| `/orchestrate generate\|start\|status\|merge` | Parallel streams in worktrees |
| `/cleanup [scope]` | Consolidate history and retire approved clutter |
| `/reflect` | Review the session for mistakes and turn corrections into rules |
| `/memory` | Show memory state |
| `/map` | Generate `PROJECT_MAP.md` |
| `/extensions` | Show the knowledge ladder, skills and active agent extensions |
| `/config` | Show and change framework settings |
| `/skills-approve` | Browse, search and manage skills |
| `/new-product` | Facilitated product definition from an empty folder (machine-wide skill) |

**On the machine:**

| Command | Purpose |
| --- | --- |
| `/setup` | First-time machine setup |
| `/setup-copilot` | Detects context and routes to the right setup command |
| `/setup-project` | Initialize a project |
| `/update-project` | Sync a project with the installed framework |
| `/update-copilot` | Update the framework, CLIs, machine commands and skills |
| `/knowledge-copilot` | Build a shared knowledge repo |
| `/setup-knowledge-sync` | Update product knowledge after release tags |

**CLIs:** `cc` covers memory, skills, config, Live Docs, design, rules, priorities, usage, journeys and environment health (`cc doctor`); `tc` covers PRDs, tasks, streams, work products, handoffs, QA contracts, execution limits, test maps and deploy waits. Run `cc --help` or `tc --help` for the full list.

→ [Orchestration Guide](docs/50-features/01-orchestration-workflow.md) | [Knowledge Sync](docs/50-features/03-knowledge-sync.md) | [Quick Reference](docs/70-reference/00-quick-reference.md)

---

## Works Alone, Grows With Teams

| Level | What You Get |
| --- | --- |
| **Solo** | 15 framework agents, persistent memory, local skills, `/new-product` |
| **Team** | + shared knowledge repo, Known References registry |
| **Enterprise** | + Extensions system, company-specific agent overrides |

→ [Customization guide](docs/20-configuration/02-customization.md) | [Extension Spec](docs/40-extensions/00-extension-spec.md)

---

## Requirements

| Requirement | Version |
| --- | --- |
| Python | 3.10+ |
| Claude Code | Latest |
| Git | Any recent version |
| Disk space | ~100MB |

**Build tools (for Python packages):**

- macOS: `xcode-select --install`
- Linux: `sudo apt-get install build-essential`

Model pinning is optional: `.claude/claude-launcher` reads `.claude/.model` and passes `--model` for you. See [SETUP.md](SETUP.md).

---

## Documentation

**Start here:**
| Guide | Purpose |
|-------|---------|
| [Usage Guide](docs/70-reference/01-usage-guide.md) | **How to actually use this**: real workflows and scenarios |
| [Decision Guide](docs/10-architecture/03-decision-guide.md) | When to use what: quick reference matrices |
| [Agents](docs/10-architecture/01-agents.md) | All 15 framework agents + kc in detail |

**Setup & Configuration:**
| Guide | Purpose |
|-------|---------|
| [User Journey](docs/01-getting-started/01-user-journey.md) | Complete setup walkthrough |
| [Configuration](docs/20-configuration/01-configuration.md) | Every configuration option |
| [Customization](docs/20-configuration/02-customization.md) | Extensions, knowledge repos, private skills |

**Advanced:**
| Guide | Purpose |
|-------|---------|
| [Enhancement Features](docs/50-features/00-enhancement-features.md) | Verification, auto-commit, preflight, worktrees |
| [Extension Spec](docs/40-extensions/00-extension-spec.md) | Creating extensions |
| [Architecture](docs/10-architecture/00-overview.md) | Technical deep dive |
| [Philosophy](docs/10-architecture/02-philosophy.md) | Why we built it this way |
| [Framework Restructure](docs/10-architecture/04-framework-restructure-2026-04.md) | Why hooks enforce delegation (April 2026 diagnostic) |

**Operations:**
| Document | Purpose |
|----------|---------|
| [Working Protocol](docs/30-operations/01-working-protocol.md) | Agent-First Protocol details |
| [Documentation Guide](docs/30-operations/02-documentation-guide.md) | Doc standards, token budgets |
| [Hooks](.claude/hooks/README.md) | What each hook enforces, escape hatches and debug tools |

**Reference:**
| Document | Purpose |
|----------|---------|
| [Quick Reference](docs/70-reference/00-quick-reference.md) | Command cheatsheet |
| [Glossary](docs/70-reference/05-glossary.md) | FTS5, BM25, ADR, PRD, WP, L1/L2/L3, all 15 framework agent codes + kc |
| [Changelog](CHANGELOG.md) | Every release |

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
