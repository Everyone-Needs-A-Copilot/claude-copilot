# Claude Copilot Learning Roadmap

**New to Claude Copilot?** This comprehensive guide will help you master the framework progressively, from basic memory persistence to advanced team customization.

---

## Learning Philosophy

This roadmap follows three key principles:

1. **Dependencies** - Build foundational capabilities before advanced features
2. **Value First** - Get immediate productivity wins at each stage
3. **Practical Application** - Learn by doing with copy-paste ready commands

Each milestone delivers tangible value. You can stop at any stage and already have a dramatically improved workflow.

---

## Your Learning Path

```mermaid
graph TD
    A[Milestone 1: Memory<br/>Persistent Context] --> B[Milestone 2: Protocol<br/>Structured Workflow]
    B --> C[Milestone 3: Agents<br/>Specialist Team]
    C --> D[Milestone 4: Extensions<br/>Team Knowledge]
    D --> E[Milestone 5: Mastery<br/>Custom Solutions]

    style A fill:#90EE90
    style B fill:#87CEEB
    style C fill:#FFD700
    style D fill:#FFA500
    style E fill:#FF6347
```

**Color Legend:**
- Green: Essential - Memory that survives sessions
- Light Blue: Core - Structured workflows
- Gold: Power User - Full specialist team
- Orange: Team - Shared knowledge
- Red: Advanced - Custom solutions

---

## Complete Roadmap Table

| Milestone | Focus | Complexity | Dependencies | Why Learn This | Key Capabilities |
|-----------|-------|------------|--------------|----------------|------------------|
| **1** | [Memory](#milestone-1-persistent-memory) | Beginner | None | Never lose context again | /continue, decisions persist |
| **2** | [Protocol](#milestone-2-agent-workflow) | Beginner+ | Memory | Structured work sessions | Task breakdown, routing |
| **3** | [Agents](#milestone-3-full-framework) | Intermediate | Protocol | Expert guidance | 15 framework agents + kc, auto-routing |
| **4** | [Extensions](#milestone-4-team-setup) | Intermediate+ | Agents | Company knowledge | Shared standards, custom agents |
| **5** | [Mastery](#milestone-5-power-user) | Advanced | All previous | Complete customization | Private skills, workflows |

---

## Quick Start Paths

### If You Only Have 15 Minutes
**Goal**: Get memory working so /continue actually works

```bash
# 1. Clone to standard location
mkdir -p ~/.claude && cd ~/.claude
git clone https://github.com/Everyone-Needs-A-Copilot/claude-copilot.git copilot

# 2. Machine setup
cd ~/.claude/copilot && claude
```

Then say:
```
Read @~/.claude/copilot/SETUP.md and set up Claude Copilot on this machine
```

**What you get**: Memory Copilot running - your work persists between sessions.

---

### If You Have 1 Hour
**Goal**: Memory + Protocol + core agents (ta, me, qa)

Follow the 15-minute path, then:

```bash
# Set up a project
cd ~/your-project && claude
```

Run:
```
/setup-project
```

Then try:
```
/protocol
# Say: "I need to add user authentication"
# Watch as ta (Tech Architect) breaks it down
```

**What you get**: Structured workflows with expert guidance.

---

### If You Have a Weekend
**Goal**: Full framework + team knowledge repository

**Phase 1** - Complete Milestones 1-3
**Phase 2** - Set up knowledge repository
**Phase 3** - Create custom extensions for your domain

**What you get**: Complete development team + company knowledge accessible everywhere.

---

## Milestone 1: Persistent Memory

**Complexity**: Beginner
**Prerequisites**: None
**Goal**: Work survives sessions - decisions, context, and progress persist

### What You'll Achieve

- Memory Copilot installed and running
- /continue loads your previous session
- Decisions and lessons automatically stored
- Never start from zero again

### The Problem This Solves

Claude Code normally forgets everything when you close it. You repeat context, explain decisions, and lose progress. Memory Copilot fixes this.

### Hands-on Exercise

```bash
# 1. Clone repository
mkdir -p ~/.claude && cd ~/.claude
git clone https://github.com/Everyone-Needs-A-Copilot/claude-copilot.git copilot

# 2. Open in Claude Code
cd ~/.claude/copilot && claude
```

Then say:
```
Read @~/.claude/copilot/SETUP.md and set up Claude Copilot on this machine
```

This installs:
- `cc` CLI — memory search, skill discovery, env hydration
- `tc` CLI — task and work product storage (Task Copilot)
- Global commands (/setup-project, /knowledge-copilot, etc.)

### Verification

In your terminal, run:
```bash
cc --version
tc version
```

Both should print their version numbers. No MCP servers or Node.js required.

### What You Can Do Now

| Capability | How |
|------------|-----|
| **Store decisions** | `cc memory store --type decision "<content>"` |
| **Resume work** | `/continue` loads your last session |
| **Search history** | `cc memory search "<query>"` finds past decisions |
| **Detect stale memory** | `cc memory check` — finds broken paths, commands, version conflicts |
| **Check quota** | `cc usage` — real server-side counters for your 5h and 7d windows |
| **Track tasks** | `tc task create`, `tc wp store` for work products |

### Understanding Memory CLI

Claude Copilot uses the `cc` CLI for memory and `tc` CLI for tasks:

| Command | Purpose | When Used |
|---------|---------|-----------|
| `cc memory store` | Store decision/lesson | After meaningful work |
| `cc memory search` | Find past decisions | When context needed |
| `cc memory list` | List recent entries | Review prior sessions |
| `cc memory check` | Detect stale/broken memory references (0–100 score; exits 1 on fail) | After restructures, renames, or framework updates |
| `cc usage` | Show current Claude quota from server-side counters | Before long `/protocol` tasks; morning check |
| `tc task create` | Create a task | New work item |
| `tc wp store` | Store a work product | After agent completes |
| `tc progress` | View task status | Check initiative state |

### Success Criteria

- [ ] Machine setup completed
- [ ] Both CLIs respond (cc --version, tc version)
- [ ] You understand what Memory Copilot does
- [ ] You're ready to set up a project

### What's Next?

Memory alone is valuable, but the real power comes from combining it with structured workflows. That's Milestone 2.

---

## Milestone 2: Agent Workflow

**Complexity**: Beginner+
**Prerequisites**: Memory Copilot installed
**Goal**: Start using /protocol for structured, expert-guided work sessions

### What You'll Achieve

- /protocol breaks down complex requests
- Tasks automatically routed to right specialist
- Structured session with clear next steps
- Work properly saved for /continue

### The Problem This Solves

You say "add user auth" and Claude either gives generic advice or starts coding without planning. Protocol adds structure: classify → route → expert guidance → save progress.

### Hands-on Exercise

```bash
# 1. Open any project in Claude Code
cd ~/your-project && claude

# 2. Set up the project
/setup-project
```

This creates:
```
your-project/
├── .mcp.json              # MCP configuration
├── CLAUDE.md              # Project instructions
└── .claude/
    ├── commands/          # /protocol, /continue
    └── agents/            # 16 specialist agents
```

### Try Your First Protocol Session

```
/protocol
```

When prompted, say:
```
I need to add user authentication to this app
```

Watch what happens:

1. **Classification**: Task identified as "Feature Implementation"
2. **Routing**: Sent to Tech Architect (ta)
3. **Breakdown**: Architecture decisions + task list
4. **Saved**: Everything stored in memory for /continue

### Understanding Protocol Flow

```mermaid
graph TD
    A[User Request] --> B{Protocol Classifies}
    B -->|Bug Fix| C[Engineer me]
    B -->|Feature| D[Tech Architect ta]
    B -->|Security| E[security/stride-dread skill]
    B -->|Design| F[Design chain uxd/uids/uid]
    C --> G[Work + Save]
    D --> G
    E --> G
    F --> G
    G --> H[Continue Later]
```

### Protocol Request Types

| Request Type | Routes To | Example |
|--------------|-----------|---------|
| Bug Fix | Engineer (me) | "Login fails with 404" |
| Feature | Tech Architect (ta) | "Add user profiles" |
| Architecture | Tech Architect (ta) | "Design API structure" |
| Security | load `security/stride-dread` skill | "Review auth flow" |
| Documentation | Documentation (doc) | "Write API docs" |
| Testing | QA Engineer (qa) | "Test edge cases" |
| Design | Design chain (uxd/uids/uid) | "Design onboarding" |

### Verification

```bash
# 1. Start protocol session
/protocol
# Say: "Add dark mode toggle"

# 2. Let it complete

# 3. Close and reopen Claude Code

# 4. Resume work
/continue
```

You should see your previous session load with full context.

### What You Can Do Now

| Capability | How |
|------------|-----|
| **Start structured work** | `/protocol` + your request |
| **Get expert routing** | Request auto-routed to right agent |
| **Save progress** | `cc memory store --type context "<summary>"` |
| **Resume work** | `/continue` loads full context |

### Success Criteria

- [ ] /setup-project completed on a test project
- [ ] Ran /protocol with a request
- [ ] Saw task breakdown from an agent
- [ ] Used /continue to resume work
- [ ] Understand protocol → agent → memory flow

### What's Next?

You've seen one agent in action. Milestone 3 introduces all 15 framework agents + kc and shows how they work together.

---

## Milestone 3: Full Framework

**Complexity**: Intermediate
**Prerequisites**: Protocol working
**Goal**: Master all 15 framework agents + kc and understand when to use each

### What You'll Achieve

- Know all 15 framework agents + kc (setup-only)
- Understand agent routing patterns
- Use agents for complex multi-domain tasks
- See agents collaborate on solutions

### The Problem This Solves

Complex work requires multiple perspectives: architecture, security, UX, implementation, testing. Managing this yourself is overwhelming. Agents handle routing and collaboration automatically.

### Your Team

**Core agents:**

| Agent | Role | When Used |
|-------|------|-----------|
| **ta** | Tech Architect | System design, task breakdown, ADRs |
| **me** | Engineer | Implementation, bug fixes, refactoring |
| **qa** | QA Engineer | Testing strategy, edge cases, verification |
| **doc** | Documentation | READMEs, API docs, architecture docs |
| **do** | DevOps | CI/CD, containers, infrastructure |
| **sd** | Service Designer | Customer journeys, experience strategy |
| **kc** | Knowledge Copilot | Shared knowledge setup |

**Design chain (sd → uxd → uids → uid → ta → me):**

| Agent | Role | When Used |
|-------|------|-----------|
| **uxd** | UX Designer | Interaction flows, task design |
| **uids** | UI Design System | Visual tokens, color, typography |
| **uid** | UI Developer | Component specs |

**Specialist branches:**

| Agent | Role | When Used |
|-------|------|-----------|
| **sec** | Security | Threat modeling, STRIDE/DREAD |
| **ind** | Industrial Designer | Object-level essentialism review |
| **cco** | Creative Director | Brand strategy, creative direction |
| **cw** | Copywriter | Copy execution, messaging, microcopy |
| **cs** | Customer Success | Support patterns |
| **cpa** | CPA / Financial | Financial modeling, tax implications |

### Hands-on Exercises

#### Exercise 1: Multi-Agent Feature

```
/protocol
```

Request:
```
Design and implement a user profile page with avatar upload
```

Watch the routing:
1. **ta** (Tech Architect) - Breaks down architecture
2. **uxd** (UX Designer) - Designs the flow + interaction specs
3. **uids** (UI Design System) - Defines component visual tokens
4. **uid** (UI Developer) - Specs the component implementation
5. **sec** (Security) - Reviews file upload security
6. **me** (Engineer) - Implements components
7. **qa** (QA Engineer) - Tests edge cases

#### Exercise 2: Direct Agent Invocation

You can also talk directly to agents:

```
@ta What's the best way to structure a multi-tenant SaaS backend?
```

```
@uxd Design an onboarding flow for first-time users
```

(Security: use `@agent-sec` or `cc skill get stride-dread` to load the security skill for code review.)

#### Exercise 3: Agent Collaboration

Complex requests trigger multiple agents:

```
/protocol
```

Request:
```
We need to add payment processing to the checkout flow
```

Expected routing:
- **ta** - Architecture (payment providers, webhook handling)
- **sec** - Security (PCI compliance, token handling)
- **uxd** - Interaction design (payment form, error states)
- **uids** - Visual design tokens
- **uid** - Component specs
- **me** - Implementation
- **qa** - Testing (failed payments, edge cases)

### Understanding Agent Routing

Agents route to each other based on expertise:

```mermaid
graph LR
    A[Any Agent] --> B[ta: Architecture]
    D[sd: Service Design] --> E[uxd: Interaction Design]
    E --> F[uids: Visual Design System]
    F --> G[uid: Component Specs]
    G --> B
    A --> H[me: Engineering]
    A --> I[qa: Testing]
    A --> J[doc: Documentation]
    A --> K[sec: Security]
```

### Agent Decision Authority

Each agent knows when to work autonomously vs. escalate:

| Agent | Autonomous | Escalate |
|-------|------------|----------|
| **ta** | Task breakdown, tech selection | Architecture shifts → team |
| **me** | Bug fixes, features | Breaking changes → ta |
| **qa** | Test strategy, scenarios | Release decisions → team |
| **doc** | README updates, guides | Major restructuring → team |

### Verification Exercise

Create a complex request that requires multiple domains:

```
/protocol
```

Request:
```
We need to migrate our authentication from sessions to JWTs
```

Expected flow:
1. **ta** classifies as architecture change
2. **ta** breaks down migration strategy
3. [security/stride-dread skill loaded] — reviews security implications
4. **me** implements changes
5. **qa** creates test scenarios
6. **doc** updates authentication docs

### Success Criteria

- [ ] Understand all 15 framework agents + kc and their domains
- [ ] Completed multi-agent feature exercise
- [ ] Invoked agents directly with @
- [ ] Saw agents route to each other
- [ ] Understand autonomous vs. escalation decisions

### What You Can Do Now

| Capability | How |
|------------|-----|
| **Complex features** | /protocol handles multi-domain work |
| **Direct expertise** | @ agent for specific guidance |
| **Quality assurance** | qa reviews automatically |
| **Security review** | load `@include .claude/skills/security/stride-dread/SKILL.md` for STRIDE/DREAD analysis |
| **Complete documentation** | doc writes as features develop |

### What's Next?

You're now using the full framework solo. Milestone 4 adds team capabilities: shared knowledge, company standards, and custom extensions.

---

## Milestone 4: Team Setup

**Complexity**: Intermediate+
**Prerequisites**: All agents working
**Goal**: Set up shared knowledge repository and understand extensions

### What You'll Achieve

- Knowledge repository for company information
- Shared standards accessible in all projects
- Custom agent extensions for your domain
- Team can share one knowledge source

### The Problem This Solves

Every team member explains company context separately. Standards drift. Domain expertise gets lost. Knowledge repositories centralize this and make it available everywhere.

### Two-Tier Knowledge System

| Tier | Location | Purpose | Scope |
|------|----------|---------|-------|
| **Global** | `~/.claude/knowledge` | Company-wide standards | All projects |
| **Project** | `.mcp.json` override | Project-specific | One project |

**Key insight**: Set up global once, every project automatically gets it.

### Hands-on Exercise: Create Knowledge Repository

```
/knowledge-copilot
```

This guided setup:
1. Creates Git repository for your knowledge
2. Walks through documenting:
   - Company information
   - Voice and tone guidelines
   - Product domain knowledge
   - Engineering standards
3. Helps push to GitHub for team sharing
4. Links to `~/.claude/knowledge`

### What Goes In Knowledge?

```
your-company-knowledge/
├── knowledge-manifest.json       # Required metadata
├── COMPANY.md                    # About the company
├── VOICE-AND-TONE.md            # Writing guidelines
├── PRODUCTS.md                   # Product domain
├── ENGINEERING-STANDARDS.md      # Tech standards
└── .claude/
    └── extensions/
        ├── ta.extension.md       # Custom architect guidance
        ├── uid.extension.md      # Company UI component standards
        └── sd.extension.md       # Service design methodology
```

### Extension Types

| Type | File Pattern | Behavior |
|------|--------------|----------|
| **override** | `agent.override.md` | Replaces entire base agent |
| **extension** | `agent.extension.md` | Adds to base agent (merges sections) |
| **skills** | `agent.skills.json` | Injects additional skills |

### Example Extension: Custom Tech Architect Standards

Create `~/.claude/knowledge/.claude/extensions/ta.extension.md`:

```markdown
---
name: ta
type: extension
extends: ta
description: Company architecture standards
---

## Architecture Standards

### Authentication
- Use Auth0 for all applications
- JWT tokens expire in 15 minutes
- Refresh tokens valid for 7 days

### Data Privacy
- All PII must be encrypted at rest
- Use our central KMS for key management
- Log access to sensitive data

### Code Review Requirements
- Security-sensitive code needs architecture team review
- Document threat model in ADRs
- Use stride-dread skill for security analysis
```

> Security standards are best encoded as a skill extension to the `security/stride-dread` skill or as a `ta.extension.md` that includes your company's security requirements in the architecture checklist.

### Team Member Setup

Once knowledge repository is on GitHub:

```bash
# 1. Clone team knowledge
git clone git@github.com:company/knowledge.git ~/company-knowledge

# 2. Link it
ln -sf ~/company-knowledge ~/.claude/knowledge

# 3. Done - every project now has access
```

### Verification

```
/protocol
```

Request:
```
@ta Review this authentication architecture
```

The ta agent extension should now reference your company standards (Auth0, JWT expiry, etc.) instead of just generic advice. For security analysis, load the security skill: `cc skill get stride-dread`.

### Check Extension Status

Use Skills Copilot tools:

```
Ask Claude: "Show me all loaded extensions"
```

Or:
```
Ask Claude: "Check manifest status"
```

### Success Criteria

- [ ] Created knowledge repository with /knowledge-copilot
- [ ] Documented company information
- [ ] Created at least one agent extension
- [ ] Pushed to GitHub for team sharing
- [ ] Verified agents use custom knowledge
- [ ] Team member can clone and link

### What You Can Do Now

| Capability | How |
|------------|-----|
| **Company context** | Agents reference your company info |
| **Custom standards** | Extensions add domain requirements |
| **Team sharing** | One knowledge repo, all team members |
| **Consistent guidance** | Everyone gets same expert advice |

### What's Next?

Milestone 5 covers advanced customization: private skills, custom workflows, and integration patterns.

---

## Milestone 5: Power User

**Complexity**: Advanced
**Prerequisites**: Knowledge repository working
**Goal**: Master advanced customization and workflow optimization

### What You'll Achieve

- Private skills database for proprietary patterns
- Custom workflows for your domain
- Integration with external tools
- Complete framework mastery

### The Problem This Solves

Every team has proprietary patterns, internal tools, and unique workflows. Power user features let you codify and automate these.

### Advanced Capabilities

#### 1. Private Skills

Store proprietary skills as markdown files in `.claude/skills/`:

```bash
# Create a skill directory
mkdir -p .claude/skills/my-error-handling

# Author the skill (prose markdown, no Node.js required)
# .claude/skills/my-error-handling/SKILL.md
```

Skills are discovered via `cc skill search "<query>"` and loaded with `cc skill get <name>`. Local skills in `.claude/skills/` are auto-listed by `cc skill list`.

#### 2. Skills Discovery

Use the `cc` CLI to find and load skills:

```bash
# Search for a skill by keyword
cc skill search "error handling"

# Load a skill into context
cc skill get my-error-handling

# List all available skills
cc skill list
```

#### 3. Custom Workflows

Create project-specific commands in `.claude/commands/`:

Example: `.claude/commands/deploy.md`

```markdown
---
name: deploy
description: Deploy with our company process
---

# Deploy Process

1. Load deployment skill: `cc skill get company-deployment`
2. Check for security review notes in memory: `cc memory search "security review"`
3. Run pre-deployment checklist
4. Execute deployment steps
5. Store deployment info: `cc memory store --type context "Deployed vX.X.X to production"`
6. Notify team via `cc memory store --type context "<message>"`
```

#### 4. Workspace Identity

Preserve memory across renames/moves:

```bash
# Workspace identity is set via cc config or the TASK_DB_PATH env var
# The tc CLI infers workspace from the current project directory
# For portability, use explicit TASK_DB_PATH:
export TASK_DB_PATH=~/.claude/tasks/explicit-project-name
```

### Hands-on Exercises

#### Exercise 1: Create Private Skill

1. Document your company's API error handling pattern
2. Ask Claude to save it: "Save this as a private skill named 'company-error-handling'"
3. Test retrieval: "Load the company-error-handling skill"
4. Use it: "Apply our error handling to this endpoint"

#### Exercise 2: Custom Command

Create `.claude/commands/release.md`:

```markdown
---
name: release
description: Our release process
---

You are managing a release following our company process.

## Steps

1. Verify all tests pass (check with qa)
2. Review security concerns (load security/stride-dread skill)
3. Update changelog (check with doc)
4. Create release branch
5. Deploy to staging
6. Run smoke tests
7. Get approval
8. Deploy to production
9. Store release status: `cc memory store --type context "Release vX.X.X completed"`

Follow these steps and confirm each before proceeding.
```

Then use: `/release`

#### Exercise 3: Multi-Project Memory

Set up related projects to share memory by pointing both to the same memory directory. The `cc` CLI stores entries as markdown files in `.claude/memory/entries/` — committed to the repo and searchable with `cc memory search`. For cross-project memory, use a shared knowledge repository:

```bash
# Register a shared knowledge repo (machine-level config, run once)
cc config set paths.knowledge_repo ~/.claude/knowledge

# Both projects read from the same knowledge repo
# Run /knowledge-copilot once to initialize it
```

Memory entries in each project's `.claude/memory/entries/` travel with that repo. Knowledge repo entries are accessible from any project on the machine.

### Advanced Patterns

#### Pattern 1: Agent Specialization

Override agents for narrow domains:

`~/.claude/knowledge/.claude/extensions/me.override.md`:

```markdown
---
name: me
type: override
description: React Native specialist
---

## Identity

**Role:** React Native Engineer
**Mission:** Build performant cross-platform mobile apps

## React Native Expertise

- Always use TypeScript
- Follow our RN performance guidelines
- Use our component library
- Test on both iOS and Android
- [... specialized guidance ...]
```

#### Pattern 2: Workflow Automation

Chain commands together:

`.claude/commands/feature.md`:

```markdown
---
name: feature
description: Full feature workflow
---

Execute our complete feature workflow:

1. /protocol - Let ta break down architecture
2. Load security checklist - `cc skill get security-checklist`
3. Implement with me
4. Test with qa
5. Document with doc
6. Store completion: `cc memory store --type context "Feature complete"`

Confirm each step before proceeding.
```

#### Pattern 3: Knowledge Layering

Override global knowledge at project level via `cc` config:

```bash
# Point this project to a local knowledge repo (takes precedence over global)
cc config set paths.knowledge_repo ./project-knowledge
```

Resolution order:
1. Project knowledge (`KNOWLEDGE_REPO_PATH`)
2. Global knowledge (`~/.claude/knowledge`)
3. Base agents

### Success Criteria

- [ ] Set up private skills database or marketplace access
- [ ] Created custom command for your workflow
- [ ] Built at least one agent override
- [ ] Understand workspace identity
- [ ] Tested advanced integration patterns
- [ ] Can train team members on framework

### What You Can Do Now

| Capability | How |
|------------|-----|
| **Proprietary patterns** | Private skills database |
| **Custom workflows** | Project-specific commands |
| **Tool integration** | MCP server extensions |
| **Multi-project memory** | Explicit WORKSPACE_ID |
| **Domain expertise** | Agent overrides |
| **Complete automation** | Chained workflows |

### Beyond Mastery

You're now a Claude Copilot power user. Consider:

1. **Train your team** - Share knowledge and best practices
2. **Contribute** - Submit agents/skills to community
3. **Extend** - Build custom MCP servers for your tools
4. **Optimize** - Continuously improve based on usage
5. **Document** - Create guides for your specific domain

---

## Progress Tracking

Use this checklist to track your journey:

### Milestone 1: Memory
- [ ] Cloned claude-copilot to ~/.claude/copilot
- [ ] Ran machine setup (/setup)
- [ ] Verified cc/tc CLIs work
- [ ] Understand `cc memory store` and `cc memory search`
- [ ] Ran `cc memory check` and understand the score
- [ ] Ran `cc usage` and can read the quota output
- [ ] Can explain what Memory Copilot does

### Milestone 2: Protocol
- [ ] Ran /setup-project in a test project
- [ ] Started first /protocol session
- [ ] Saw task breakdown from agent
- [ ] Closed and used /continue to resume
- [ ] Understand protocol → agent → memory flow

### Milestone 3: Agents
- [ ] Know all 15 framework agents + kc and their domains
- [ ] Completed multi-agent feature
- [ ] Used @ to invoke agents directly
- [ ] Saw agents route to each other
- [ ] Understand autonomous vs. escalation

### Milestone 4: Team
- [ ] Created knowledge repository
- [ ] Documented company information
- [ ] Created agent extension
- [ ] Pushed to GitHub
- [ ] Team member cloned and linked
- [ ] Verified agents use custom knowledge

### Milestone 5: Mastery
- [ ] Set up private skills or marketplace
- [ ] Created custom command
- [ ] Built agent override
- [ ] Tested advanced patterns
- [ ] Can train others
- [ ] Framework fully integrated into workflow

---

## Learning Tips

### Do

- **Follow the milestone order** - Each builds on previous
- **Complete verification steps** - Confirm it works before moving on
- **Experiment safely** - Use test projects for learning
- **Document your patterns** - Create company-specific guides
- **Share with team** - Learn together, share discoveries

### Don't

- **Skip Memory setup** - Nothing else works without it
- **Rush to extensions** - Master base agents first
- **Copy configs blindly** - Understand what each setting does
- **Work in isolation** - Collaborate on knowledge repository
- **Forget to /continue** - Always save progress at session end

---

## Common Challenges

### Challenge 1: "cc or tc not found"

**Solution:**
1. Reinstall: `bash ~/.claude/copilot/tools/cc/install.sh` and `pip install -e ~/.claude/copilot/tools/tc`
2. Reload your shell: `source ~/.zshrc` (installer auto-appends `~/.local/bin` to your profile)
3. Verify: `cc --version` and `tc version`
4. Restart Claude Code

### Challenge 2: "/continue doesn't load context"

**Solution:**
1. Verify `cc memory list` returns recent entries
2. Check you ran /protocol (not just chatted)
3. Confirm memory entries exist in `.claude/memory/entries/`
4. Run `cc memory search "<topic>"` to find prior context manually

### Challenge 3: "Agents give generic advice"

**Solution:**
1. Create knowledge repository with company context
2. Add agent extensions with domain specifics
3. Use /protocol (not direct chat) for proper routing
4. Be specific in requests: "using our React patterns" vs "add feature"

### Challenge 4: "Which agent do I use?"

**Solution:**
- Use /protocol - routing is automatic
- For direct invocation: @ta (architecture), @me (code), @qa (test), @doc (write), @uxd (interaction design), @uids (visual design), @uid (component specs), @sec (security), @do (infra)
- Security: load `cc skill get stride-dread` for security analysis
- Check the agent routing diagram in Milestone 3

### Challenge 5: "Team members have different experiences"

**Solution:**
1. All use same knowledge repository (clone from GitHub)
2. All link: `ln -sf ~/company-knowledge ~/.claude/knowledge`
3. Document team setup in knowledge repo README
4. Version control knowledge repo for consistency

---

## What's Next After Completion?

Once you've completed all milestones:

1. **Team Enablement** - Train teammates, create onboarding docs
2. **Knowledge Curation** - Continuously improve company knowledge
3. **Workflow Optimization** - Refine agents and commands based on usage
4. **Community Contribution** - Share generic patterns back to framework
5. **Advanced Integration** - Build custom MCP servers for your tools
6. **Stay Updated** - Watch for framework updates and new capabilities

---

## Additional Resources

### Documentation

| Guide | Purpose |
|-------|---------|
| [SETUP.md](../../SETUP.md) | Detailed setup instructions |
| [01-user-journey.md](./01-user-journey.md) | Complete user journey walkthrough |
| [01-agents.md](../10-architecture/01-agents.md) | All agents in detail |
| [00-extension-spec.md](../40-extensions/00-extension-spec.md) | Creating extensions |
| [01-configuration.md](../20-configuration/01-configuration.md) | .mcp.json and environment |
| [02-customization.md](../20-configuration/02-customization.md) | Advanced customization |

### Community

- [GitHub Repository](https://github.com/Everyone-Needs-A-Copilot/claude-copilot)
- [Releases](https://github.com/Everyone-Needs-A-Copilot/claude-copilot/releases)
- [Issues](https://github.com/Everyone-Needs-A-Copilot/claude-copilot/issues)

---

## Feedback & Support

- **Found an issue?** [Create an issue](https://github.com/Everyone-Needs-A-Copilot/claude-copilot/issues)
- **Have a suggestion?** Submit a pull request
- **Need help?** Check documentation or ask in discussions

---

**Last Updated**: December 2025
**Maintained by**: Everyone Needs a Copilot
**License**: MIT

---

[← Back to README](../../README.md)
