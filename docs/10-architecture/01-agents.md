# Meet Your Team

Claude Copilot gives you access to **14 specialized agents**—each an expert in their domain, built using the **lean agent model** with on-demand skill loading.

## Architecture: Lean Agents + Deep Skills

Agents are kept minimal (under 120 lines) and auto-load domain expertise on demand. Shared boilerplate (skill loading, Task Copilot pattern, iteration loop, return format, etc.) is extracted to the "Agent Shared Behaviors" section in CLAUDE.md, so individual agent files contain only domain-specific logic.

| Component | Size | Purpose |
|-----------|------|---------|
| Agent file | Under 120 lines | Core workflow, routing, behaviors |
| Shared behaviors | In CLAUDE.md | Skill loading, Task Copilot, iteration, handoffs |
| Skills | ~200-500 lines each | Domain patterns, anti-patterns, examples |
| Total context | ~1,000 tokens | Agent + relevant skills only |

**How it works:**
1. Agent calls `skill_evaluate({ files, text })` to detect relevant skills
2. Skills ranked by confidence (file patterns + keyword matching)
3. Agent loads top skills via `@include` directive
4. Work executes with specialized knowledge

**Benefits:**
- ~70% less context per agent (3,000 → 1,000 tokens)
- Skills loaded only when needed
- Extensible without modifying agents
- Faster agent startup

### Required Tools

All lean agents MUST include these tools:

| Tool | Purpose |
|------|---------|
| `preflight_check` | Verify environment before work |
| `skill_evaluate` | Auto-detect and load skills |
| `task_get` | Retrieve task details |
| `task_update` | Update task status |
| `work_product_store` | Store output |

### Skill Metadata

Skills must have trigger metadata for auto-detection:

```yaml
---
skill_name: python-idioms
trigger_files: ["*.py", "**/*.py", "requirements.txt"]
trigger_keywords: [python, django, flask, pytest, pythonic]
---
```

### Extension Compatibility

Extensions continue to work with lean agents:

| Extension Type | Behavior |
|----------------|----------|
| `override` | Replaces the lean agent entirely |
| `extension` | Adds sections to the lean agent |
| `skills` | Injects additional skills |

---

## Quick Reference

| Agent | Name | Domain | When to Use |
|-------|------|--------|-------------|
| `ta` | Tech Architect | System design | "Design the auth system", "Break down this PRD" |
| `me` | Engineer | Code implementation | "Implement the login endpoint", "Fix this bug" |
| `qa` | QA Engineer | Testing | "Write tests for this feature", "What edge cases?" |
| `sec` | Security | Security review | "Review this auth code", "Is this API secure?" |
| `doc` | Documentation | Technical writing | "Document this API", "Update the README" |
| `do` | DevOps | CI/CD, infrastructure | "Set up the CI pipeline", "Configure Docker" |
| `sd` | Service Designer | Experience strategy | "Map the onboarding journey", "Where are users dropping off?" |
| `uxd` | UX Designer | Interaction design | "Design the checkout flow", "Is this form usable?" |
| `uids` | UI Designer | Visual design | "Create a color palette", "Design the component library" |
| `uid` | UI Developer | UI implementation | "Build this component", "Make this responsive" |
| `cw` | Copywriter | Content/copy | "Write the error messages", "Create onboarding copy" |
| `kc` | Knowledge Copilot | Shared knowledge | Run `/knowledge-copilot` |

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

### `@agent-sec` — Security Engineer

**Your security expert who protects users and data.**

- Reviews code for vulnerabilities (OWASP Top 10)
- Performs threat modeling (STRIDE methodology)
- Ensures authentication/authorization is solid
- Balances security with usability

**Value:** Vulnerabilities caught before exploitation. Security built in, not bolted on. Compliance requirements met.

**When to use:**
- "Review this auth code"
- "Is this API secure?"
- "What are the security risks here?"

---

### `@agent-doc` — Documentation

**Your technical writer who makes complex things clear.**

- Creates accurate, useful documentation
- Structures information for findability
- Maintains API documentation
- Keeps READMEs current

**Value:** Users find what they need. New team members onboard faster. Less "how does this work?" questions.

**When to use:**
- "Document this API"
- "Update the README"
- "Create a getting started guide"

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

## Human Advocates

These agents ensure your software serves real human needs—not just technical requirements.

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

**Your interaction designer who makes things intuitive.**

- Designs task flows that users can follow
- Creates wireframes and interaction specifications
- Ensures accessibility (WCAG 2.1 AA)
- Validates usability before development

**Value:** Users complete tasks without confusion. Interfaces accessible to everyone. Designs validated before code.

**When to use:**
- "Design the checkout flow"
- "Is this form usable?"
- "How should error states work?"

---

### `@agent-uids` — UI Designer

**Your visual designer who makes interfaces beautiful and functional.**

- Creates design systems and tokens
- Designs color palettes (WCAG compliant)
- Establishes typography hierarchies
- Ensures brand consistency

**Value:** Visual design that reinforces usability. Scalable design systems. WCAG compliance. Documented design decisions.

**When to use:**
- "Create a color palette"
- "Design the component library"
- "Is this visually consistent?"

---

### `@agent-uid` — UI Developer

**Your frontend specialist who brings designs to life.**

- Implements accessible, responsive components
- Translates designs to pixel-perfect code
- Optimizes frontend performance
- Builds reusable component libraries

**Value:** UI matches design specs. Components work on all devices. Accessible to screen readers. Maintainable code.

**When to use:**
- "Build this component"
- "Make this responsive"
- "Implement the design system"

---

### `@agent-cw` — Copywriter

**Your content designer who writes words that work.**

- Crafts clear microcopy and button labels
- Writes helpful error messages
- Creates onboarding flows that guide users
- Establishes voice and tone guidelines

**Value:** Users understand without thinking. Error messages help recovery. Consistent voice throughout.

**When to use:**
- "Write the error messages"
- "What should this button say?"
- "Create onboarding copy"

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

Agents don't work in isolation—they route to each other based on expertise.

### Technical Flow

```
User Request: "Add user authentication"
         │
         ▼
    @agent-ta ──────────────────────────────────────────────┐
    (designs architecture)                                   │
         │                                                   │
         ├──→ @agent-sec (security review)                  │
         │         │                                         │
         │         └──→ returns recommendations              │
         │                                                   │
         └──→ @agent-me (implementation) ◄──────────────────┘
                   │
                   ├──→ @agent-qa (tests)
                   │
                   └──→ @agent-doc (documentation)
```

### Human Advocate Flow

```
User Request: "Redesign our onboarding experience"
         │
         ▼
    @agent-sd ─────────────────────────────────────────────────────┐
    (maps customer journey, identifies pain points)                 │
         │                                                          │
         ├──→ @agent-uxd (designs task flows, wireframes)          │
         │         │                                                │
         │         └──→ @agent-uids (visual design, tokens)        │
         │                   │                                      │
         │                   └──→ @agent-cw (onboarding copy)      │
         │                                                          │
         └──→ @agent-uid (implements components) ◄─────────────────┘
                   │
                   └──→ @agent-qa (accessibility testing)
```

### Routing Table

| From | Routes To | When |
|------|-----------|------|
| Any | `ta` | Architecture decisions needed |
| Any | `sec` | Security concerns arise |
| `sd` | `uxd` | Interaction design needed |
| `uxd` | `uids` | Visual design needed |
| `uids` | `uid` | Implementation needed |
| Any | `me` | Code implementation needed |
| Any | `qa` | Testing needed |
| Any | `doc` | Documentation needed |

---

## Task Copilot Integration

Lean agents store their detailed work products in Task Copilot instead of returning them to the main session. This reduces context usage by ~96%.

### How It Works

```
User Request: "Design the auth system"
         │
         ▼
    @agent-ta (lean agent)
         │
         ├──→ Calls skill_evaluate() to load relevant skills
         │
         ├──→ Creates PRD, breaks down tasks
         │
         ├──→ Stores PRD in Task Copilot (prd_create)
         │
         ├──→ Creates tasks (task_create)
         │
         └──→ Returns summary to main session (~100 tokens)
              "Created PRD-001 with 5 tasks. Ready to proceed."
```

### Work Product Types

Each agent stores specific types of work:

| Agent | Work Product Type | What's Stored |
|-------|------------------|---------------|
| `ta` | `architecture`, `technical_design` | System designs, ADRs, task breakdowns |
| `me` | `implementation` | Code changes, refactoring notes |
| `qa` | `test_plan` | Test strategies, coverage reports |
| `sec` | `security_review` | Vulnerability assessments, threat models |
| `doc` | `documentation` | API docs, guides, READMEs |
| `do` | `technical_design` | Pipeline configs, infrastructure designs |
| `sd`, `uxd`, `uids`, `uid`, `cw` | `other` | Journey maps, wireframes, design specs, copy |

### Benefits

- **Reduced context**: Main session stays focused (~200 tokens vs ~8000)
- **Persistent storage**: Work products survive session restarts
- **Progress tracking**: `progress_summary()` shows compact status
- **Work retrieval**: `work_product_get(id)` retrieves full details when needed

### Agent Workflow

1. Agent receives task (with Task ID if assigned)
2. Agent stores detailed work in Task Copilot
3. Agent returns minimal summary to main session
4. Main session continues with low context overhead

---

## Custom Agents

Teams can add domain-specific agents. Example with a custom `@agent-cpa`:

```
User Request: "Add expense reporting with tax categorization"
         │
         ▼
    @agent-ta ──────────────────────────────────────────────┐
    (designs data model, API structure)                      │
         │                                                   │
         ├──→ @agent-cpa (tax categories, compliance rules) │  ← Your custom agent
         │         │                                         │
         │         └──→ returns IRS category mappings        │
         │                                                   │
         └──→ @agent-me (implementation) ◄──────────────────┘
                   │
                   ├──→ @agent-sec (financial data protection)
                   │
                   └──→ @agent-cpa (validates tax logic)
```

Your CPA agent encodes tax law expertise, IRS requirements, and accounting standards—knowledge that doesn't exist in generic AI tools.

See [Customization](CUSTOMIZATION.md) for how to create custom agents.

---

## Invoking Agents

Agents are automatically routed when you use `/protocol`. You can also invoke them directly:

| Method | Example |
|--------|---------|
| Via protocol | `/protocol` then describe your task |
| Direct mention | `@agent-ta design the auth system` |
| Task tool | `subagent_type: "ta"` |

---

## Next Steps

- [User Journey](USER-JOURNEY.md) - Complete setup walkthrough
- [Configuration](CONFIGURATION.md) - Detailed setup options
- [Customization](CUSTOMIZATION.md) - Create custom agents
