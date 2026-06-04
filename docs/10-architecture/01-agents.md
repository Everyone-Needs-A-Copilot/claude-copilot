# Meet Your Team

Claude Copilot provides **16 specialized agents** plus a setup agent — each an expert in their domain, built using the lean agent model with on-demand skill loading.

## Architecture: Lean Agents + Deep Skills

Agents are kept minimal (under 120 lines) and load domain expertise on demand. Shared boilerplate (skill loading, Task Copilot pattern, iteration loop, return format, handoffs) is extracted to the "Agent Shared Behaviors" section in CLAUDE.md so individual agent files contain only domain-specific logic.

| Component | Size | Purpose |
|-----------|------|---------|
| Agent file | Under 120 lines | Core workflow, routing, behaviors |
| Shared behaviors | In CLAUDE.md | Skill loading, Task Copilot, iteration, handoffs |
| Skills | ~200-500 lines each | Domain patterns, anti-patterns, examples |
| Total context | ~1,000 tokens | Agent + relevant skills only |

**How it works:**
1. Skills auto-fire from their trigger-rich `description` field when the model recognizes a prompt match (primary path)
2. Agent uses `cc skill search "<query>"` as a fallback for explicit discovery (case-insensitive substring match — not FTS5)
3. Agent loads skill content via `cc skill get <name>` or native `@include`
4. Work executes with specialized knowledge
5. ~70% less context per agent vs. monolithic agents

### Required Tools

All lean agents include these tools:

| Tool / Command | Purpose |
|------|---------|
| `cc skill search "<query>"` | Fallback skill discovery by keyword (substring match) |
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

**Core agents:**

| Agent | Domain | When to Use |
|-------|--------|-------------|
| `ta` | Technical architecture — ADR/fitness functions | "Design the auth system", "Break down this PRD" |
| `me` | Engineering — Kent Beck simple design | "Implement the login endpoint", "Fix this bug" |
| `qa` | QA — Meszaros patterns | "Write tests for this feature", "What edge cases?" |
| `do` | DevOps/infra — 12-Factor/SRE | "Set up the CI pipeline", "Configure Docker" |
| `doc` | Documentation — Diátaxis | "Document this API", "Update the README" |
| `sd` | Service design — IDEO methodology | "Map the onboarding journey", "Where are users dropping off?" |
| `kc` | Knowledge copilot setup | Run `/knowledge-copilot` |

**Design chain (sd → uxd → uids → uid → ta → me):**

| Agent | Domain | When to Use |
|-------|--------|-------------|
| `uxd` | UX Designer — interaction flows, task design | "Design the checkout task flow", "Map the error recovery flow" |
| `uids` | UI Design System — visual tokens, color, typography | "Create the design tokens", "Define color palette" |
| `uid` | UI Developer — component implementation specs | "Spec the button component", "Create the form component library" |

**Specialist branches:**

| Agent | Domain | When to Use |
|-------|--------|-------------|
| `sec` | Security — STRIDE/DREAD threat modeling | "Review auth for vulnerabilities", "Threat model the payment flow" |
| `ind` | Industrial Designer — object-level essentialism | "Review what's essential in this feature" (upstream of uxd) |
| `cco` | Creative Director — brand strategy | "Review brand alignment", "Creative direction for campaign" |
| `cw` | Copywriter — messaging and microcopy | "Write the error messages", "Copy for onboarding" |

**Business advisory (optional — outside the software build chain):**

> `cs` and `cpa` are standalone advisory agents for founder/agency business needs. They do not route into or out of the build chain (sd → uxd → uids → uid → ta → me). Invoke them directly when you need business guidance.

| Agent | Domain | When to Use |
|-------|--------|-------------|
| `cs` | Customer Success — Socratic sales patterns | "Design the support escalation flow", "Sales conversation strategy" |
| `cpa` | CPA / Financial — S-Corp tax advisory | "Model the pricing implications", "Tax considerations" |

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

### `@agent-uxd` — UX Designer

**Your interaction designer who makes flows users can follow.**

- Designs task flows and interaction models
- Creates wireframes and interaction specifications
- Ensures accessibility (WCAG 2.1 AA)
- Validates usability before visual polish

**Value:** Users complete tasks without confusion. Designs validated before code is written.

**When to use:** "Design the checkout flow", "Is this form usable?", "Map the error recovery task flow"

Routes to `@agent-uids` when task flows are approved.

---

### `@agent-uids` — UI Design System

**Your visual design system specialist.**

- Creates design tokens (color, spacing, typography)
- Designs WCAG-compliant color palettes
- Establishes typography hierarchies
- Produces visual specs for components

**Value:** Scalable design systems. Visual consistency. WCAG compliance.

**When to use:** "Create design tokens", "Define the color palette", "Set the typography scale"

Routes to `@agent-uid` when tokens and specs are ready.

---

### `@agent-uid` — UI Developer

**Your component specification expert.**

- Translates design tokens into component specs
- Creates component implementation blueprints
- Ensures design-to-code fidelity

**Value:** Components built from design intent, not guesswork.

**When to use:** "Spec the button component", "Create the form component library"

Routes to `@agent-ta` when component specs are ready for task planning.

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
         └──→ @agent-uxd (interaction + task flow design)         │
                   │                                                │
                   └──→ @agent-uids (visual design system)         │
                             │                                      │
                             └──→ @agent-uid (component specs)     │
                                       │                            │
                                       └──→ @agent-ta (spec to architecture) ◄─┘
                                                 │
                                                 └──→ @agent-me (implementation)
                                                           │
                                                           └──→ @agent-qa (accessibility + regression)
```

### Routing Table

| From | Routes To | When |
|------|-----------|------|
| Any | `ta` | Architecture decisions needed |
| `sd` | `uxd` | Interaction/task flow design needed |
| `uxd` | `uids` | Task flows approved, visual design next |
| `uids` | `uid` | Design tokens ready for component specs |
| `uid` | `ta` | Component specs ready for task planning |
| `sd` | `cco` | Creative direction or brand strategy needed |
| `cco` | `cw` | Copy execution, messaging, microcopy |
| Any | `me` | Code implementation needed |
| Any | `qa` | Testing needed |
| Any | `doc` | Documentation needed |
| Any | `do` | CI/CD or infrastructure needed |
| Any | `sec` | Security review, threat modeling |

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
