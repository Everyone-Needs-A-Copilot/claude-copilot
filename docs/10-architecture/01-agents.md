# Meet Your Team

Claude Copilot provides **8 specialized agents** plus a setup agent — each an expert in their domain, built using the lean agent model with on-demand skill loading.

## Architecture: Lean Agents + Deep Skills

Agents are kept minimal (under 120 lines) and load domain expertise on demand. Shared boilerplate (skill loading, Task Copilot pattern, iteration loop, return format, handoffs) is extracted to the "Agent Shared Behaviors" section in CLAUDE.md so individual agent files contain only domain-specific logic.

| Component | Size | Purpose |
|-----------|------|---------|
| Agent file | Under 120 lines | Core workflow, routing, behaviors |
| Shared behaviors | In CLAUDE.md | Skill loading, Task Copilot, iteration, handoffs |
| Skills | ~200-500 lines each | Domain patterns, anti-patterns, examples |
| Total context | ~1,000 tokens | Agent + relevant skills only |

**How it works:**
1. Agent discovers relevant skills via `cc skill search "<query>"`
2. Agent loads skill content via `cc skill get <name>` or native `@include`
3. Work executes with specialized knowledge
4. ~70% less context per agent vs. monolithic agents

### Required Tools

All lean agents include these tools:

| Tool / Command | Purpose |
|------|---------|
| `cc skill search "<query>"` | Discover relevant skills by keyword |
| `cc skill get <name>` | Load a specific skill |
| `tc task get <id> --json` | Retrieve task details |
| `tc task update <id> --status <s> --json` | Update task status |
| `tc wp store --task <id> ...` | Store agent output |

### Extension Compatibility

Extensions continue to work with lean agents:

| Extension Type | Behavior |
|----------------|----------|
| `override` | Replaces the lean agent entirely |
| `extension` | Adds sections to the lean agent |
| `skills` | Injects additional skills |

---

## Quick Reference

| Agent | Domain | When to Use |
|-------|--------|-------------|
| `ta` | Technical architecture — ADR/fitness functions | "Design the auth system", "Break down this PRD" |
| `me` | Engineering — Kent Beck simple design | "Implement the login endpoint", "Fix this bug" |
| `qa` | QA — Meszaros patterns | "Write tests for this feature", "What edge cases?" |
| `do` | DevOps/infra — 12-Factor/SRE | "Set up the CI pipeline", "Configure Docker" |
| `doc` | Documentation — Diátaxis | "Document this API", "Update the README" |
| `sd` | Service design — IDEO methodology | "Map the onboarding journey", "Where are users dropping off?" |
| `design` | Interaction/visual design — Nielsen + Rams + Atomic Design | "Design the checkout flow", "Create the component library" |
| `kc` | Knowledge copilot setup | Run `/knowledge-copilot` |

> **Security:** Security concerns are handled via the `security/stride-dread` skill rather than a dedicated agent. Load it with `cc skill get stride-dread` or `@include .claude/skills/security/stride-dread/SKILL.md`.

---

## Development Team

### `@agent-ta` — Tech Architect

**Your systems thinker who designs before building.**

- Converts requirements into actionable task breakdowns
- Designs scalable, maintainable architectures
- Evaluates technology choices with documented trade-offs
- Creates Architecture Decision Records (ADRs)

**Value:** Clear plans that developers can execute. Decisions documented so you remember *why* six months later.

**When to use:**
- "Design the auth system"
- "Break down this PRD into tasks"
- "Should we use GraphQL or REST?"

---

### `@agent-me` — Engineer

**Your implementer who writes clean, working code.**

- Implements features across any tech stack
- Fixes bugs with proper error handling
- Writes tests alongside implementation
- Refactors while maintaining functionality

**Value:** Code that works, handles edge cases, and other developers can maintain.

**When to use:**
- "Implement the login endpoint"
- "Fix this null pointer bug"
- "Add validation to this form"

---

### `@agent-qa` — QA Engineer

**Your quality guardian who catches bugs before users do.**

- Designs test strategies (unit, integration, E2E)
- Identifies edge cases you didn't think of
- Creates meaningful test coverage (not just high numbers)
- Verifies bug fixes actually work

**Value:** Confidence that your code works. Regression prevention. Clear bug reports with reproduction steps.

**When to use:**
- "Write tests for this feature"
- "Is this bug actually fixed?"
- "What edge cases am I missing?"

---

### `@agent-do` — DevOps Engineer

**Your infrastructure expert who makes deployment reliable.**

- Configures CI/CD pipelines
- Sets up monitoring and alerting
- Manages containers and orchestration
- Automates infrastructure with IaC

**Value:** Reliable deployments. Reproducible environments. Fast recovery from failures. Ship with confidence.

**When to use:**
- "Set up the CI pipeline"
- "Why is production slow?"
- "Configure the Docker setup"

---

### `@agent-doc` — Documentation

**Your technical writer who makes complex things clear.**

- Creates accurate, useful documentation using the Diátaxis framework
- Structures information for findability
- Maintains API documentation
- Keeps READMEs current

**Value:** Users find what they need. New team members onboard faster. Less "how does this work?" questions.

**When to use:**
- "Document this API"
- "Update the README"
- "Create a getting started guide"

---

## Human Advocates

These agents ensure your software serves real human needs — not just technical requirements.

### `@agent-sd` — Service Designer

**Your experience strategist who sees the whole journey.**

- Maps complete customer journeys across touchpoints
- Creates service blueprints (frontstage + backstage)
- Identifies pain points and opportunities
- Orchestrates coherent experiences

**Value:** Designs grounded in user evidence. All touchpoints working together. Clear implementation priorities.

**When to use:**
- "Map the onboarding journey"
- "Where are users dropping off?"
- "How do all these features connect?"

---

### `@agent-design` — Design

**Your interaction and visual designer who makes interfaces intuitive and beautiful.**

Consolidates interaction design (flows, wireframes, usability), visual design (tokens, color, typography), and UI implementation patterns.

- Designs task flows that users can follow
- Creates wireframes and interaction specifications
- Ensures accessibility (WCAG 2.1 AA)
- Creates design systems and tokens
- Designs color palettes (WCAG compliant)
- Establishes typography hierarchies

**Value:** Users complete tasks without confusion. Visual design reinforces usability. Scalable design systems. WCAG compliance. Designs validated before code.

**When to use:**
- "Design the checkout flow"
- "Is this form usable?"
- "Create a color palette"
- "Design the component library"
- "Is this visually consistent?"

---

## Knowledge & Setup

### `@agent-kc` — Knowledge Copilot

**Your guide to building shared knowledge that works across all projects.**

- Guides structured discovery of company identity, voice, and standards
- Creates Git-managed knowledge repositories
- Helps push to GitHub for team sharing
- Links knowledge to `~/.claude/knowledge` for automatic access

**Value:** Company knowledge documented once, available everywhere. Team alignment without repeated explanations. Onboarding accelerated.

**When to use:** Run `/knowledge-copilot` to create or extend your shared knowledge repository.

---

## How Agents Collaborate

Agents don't work in isolation — they route to each other based on expertise.

### Technical Flow

```
User Request: "Add user authentication"
         │
         ▼
    @agent-ta ──────────────────────────────────────────────┐
    (designs architecture)                                   │
         │                                                   │
         │   [security/stride-dread skill loaded inline]     │
         │                                                   │
         └──→ @agent-me (implementation) ◄──────────────────┘
                   │
                   ├──→ @agent-qa (tests)
                   │
                   └──→ @agent-doc (documentation)
```

### Experience Flow

```
User Request: "Redesign our onboarding experience"
         │
         ▼
    @agent-sd ─────────────────────────────────────────────────────┐
    (maps customer journey, identifies pain points)                 │
         │                                                          │
         └──→ @agent-design (interaction + visual design)          │
                   │                                                │
                   └──→ @agent-ta (spec to architecture) ◄─────────┘
                             │
                             └──→ @agent-me (implementation)
                                       │
                                       └──→ @agent-qa (accessibility + regression)
```

### Routing Table

| From | Routes To | When |
|------|-----------|------|
| Any | `ta` | Architecture decisions needed |
| `sd` | `design` | Interaction/visual design needed |
| `design` | `ta` | Specification ready for architecture |
| Any | `me` | Code implementation needed |
| Any | `qa` | Testing needed |
| Any | `doc` | Documentation needed |
| Any | `do` | CI/CD or infrastructure needed |

For security reviews: load the `security/stride-dread` skill rather than routing to a separate agent.

---

## Task Copilot Integration

Lean agents store detailed work products in Task Copilot instead of returning them to the main session. This reduces context usage by ~96%.

### Work Product Types

| Agent | Work Product Type | What's Stored |
|-------|------------------|---------------|
| `ta` | `architecture`, `technical_design` | System designs, ADRs, task breakdowns |
| `me` | `implementation` | Code changes, refactoring notes |
| `qa` | `test_plan` | Test strategies, coverage reports |
| `doc` | `documentation` | API docs, guides, READMEs |
| `do` | `technical_design` | Pipeline configs, infrastructure designs |
| `sd`, `design` | `specification` | Journey maps, wireframes, design specs |

---

## Custom Agents

Teams can add domain-specific agents by creating `.md` files in `.claude/agents/`. Custom agents can reference any of the 8 base agents for handoffs.

See [Customization](../20-configuration/02-customization.md) for how to create custom agents.

---

## Invoking Agents

Agents are automatically routed when you use `/protocol`. You can also invoke them directly:

| Method | Example |
|--------|---------|
| Via protocol | `/protocol` then describe your task |
| Direct mention | `@agent-ta design the auth system` |

---

## Next Steps

- [User Journey](../01-getting-started/01-user-journey.md) - Complete setup walkthrough
- [Configuration](../20-configuration/01-configuration.md) - Detailed setup options
- [Customization](../20-configuration/02-customization.md) - Create custom agents and extensions
