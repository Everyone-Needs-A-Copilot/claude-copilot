# Claude Copilot

**A complete AI development framework that gives every developer access to a full team of specialists.**

---

## The Problem

Building software alone is hard. You're expected to be an expert in architecture, security, testing, UX, accessibility, DevOps, and more—all at once. AI assistants help, but they:

- **Forget everything** between sessions (wasted tokens rebuilding context)
- **Give generic advice** (no specialized expertise for complex decisions)
- **Lack process** (ad-hoc responses instead of proven workflows)
- **Can't grow** (no way to add your team's knowledge and standards)

## The Solution

Claude Copilot transforms Claude Code into a **complete development environment** with:

| Challenge | Solution | Result |
|-----------|----------|--------|
| Lost context | **Memory Copilot** persists decisions, lessons, and progress | Pick up exactly where you left off |
| Generic advice | **11 Specialized Agents** with deep domain expertise | Expert guidance for every task type |
| No process | **Protocol Commands** enforce proven workflows | Consistent quality, nothing missed |
| Can't customize | **Skills + Extensions** add your team's knowledge | Your standards, your way |

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
│   ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐              │
│   │   sd    │ │   uxd   │ │  uids   │ │   uid   │ │   cw    │              │
│   │ Service │ │   UX    │ │   UI    │ │   UI    │ │  Copy   │              │
│   │Designer │ │Designer │ │Designer │ │Developer│ │ Writer  │              │
│   └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘              │
└───────────────────────────────┼─────────────────────────────────────────────┘
                                │
              ┌─────────────────┴─────────────────┐
              │                                   │
              ▼                                   ▼
┌──────────────────────────────┐   ┌──────────────────────────────────────────┐
│      MEMORY COPILOT          │   │           SKILLS COPILOT                  │
│                              │   │                                          │
│  • Stores decisions made     │   │  • 25,000+ public skills (SkillsMP)     │
│  • Remembers lessons learned │   │  • Your private/proprietary skills      │
│  • Tracks progress           │   │  • Local project skills                 │
│  • Enables /continue         │   │  • Intelligent caching                  │
└──────────────────────────────┘   └──────────────────────────────────────────┘
```

---

## Meet Your Team

Claude Copilot gives you access to **11 specialized agents**—each an expert in their domain, knowing when to collaborate and when to hand off to others.

### Development Team

#### `@agent-ta` — Tech Architect
**Your systems thinker who designs before building.**

- Converts requirements into actionable task breakdowns
- Designs scalable, maintainable architectures
- Evaluates technology choices with documented trade-offs
- Creates Architecture Decision Records (ADRs)

**Value:** Clear plans that developers can execute. Decisions documented so you remember *why* six months later.

**When to use:** "Design the auth system", "Break down this PRD into tasks", "Should we use GraphQL or REST?"

---

#### `@agent-me` — Engineer
**Your implementer who writes clean, working code.**

- Implements features across any tech stack
- Fixes bugs with proper error handling
- Writes tests alongside implementation
- Refactors while maintaining functionality

**Value:** Code that works, handles edge cases, and other developers can maintain.

**When to use:** "Implement the login endpoint", "Fix this null pointer bug", "Add validation to this form"

---

#### `@agent-qa` — QA Engineer
**Your quality guardian who catches bugs before users do.**

- Designs test strategies (unit, integration, E2E)
- Identifies edge cases you didn't think of
- Creates meaningful test coverage (not just high numbers)
- Verifies bug fixes actually work

**Value:** Confidence that your code works. Regression prevention. Clear bug reports with reproduction steps.

**When to use:** "Write tests for this feature", "Is this bug actually fixed?", "What edge cases am I missing?"

---

#### `@agent-sec` — Security Engineer
**Your security expert who protects users and data.**

- Reviews code for vulnerabilities (OWASP Top 10)
- Performs threat modeling (STRIDE methodology)
- Ensures authentication/authorization is solid
- Balances security with usability

**Value:** Vulnerabilities caught before exploitation. Security built in, not bolted on. Compliance requirements met.

**When to use:** "Review this auth code", "Is this API secure?", "What are the security risks here?"

---

#### `@agent-doc` — Documentation
**Your technical writer who makes complex things clear.**

- Creates accurate, useful documentation
- Structures information for findability
- Maintains API documentation
- Keeps READMEs current

**Value:** Users find what they need. New team members onboard faster. Less "how does this work?" questions.

**When to use:** "Document this API", "Update the README", "Create a getting started guide"

---

#### `@agent-do` — DevOps Engineer
**Your infrastructure expert who makes deployment reliable.**

- Configures CI/CD pipelines
- Sets up monitoring and alerting
- Manages containers and orchestration
- Automates infrastructure with IaC

**Value:** Reliable deployments. Reproducible environments. Fast recovery from failures. Ship with confidence.

**When to use:** "Set up the CI pipeline", "Why is production slow?", "Configure the Docker setup"

---

### Human Advocates

These agents ensure your software serves real human needs—not just technical requirements.

#### `@agent-sd` — Service Designer
**Your experience strategist who sees the whole journey.**

- Maps complete customer journeys across touchpoints
- Creates service blueprints (frontstage + backstage)
- Identifies pain points and opportunities
- Orchestrates coherent experiences

**Value:** Designs grounded in user evidence. All touchpoints working together. Clear implementation priorities.

**When to use:** "Map the onboarding journey", "Where are users dropping off?", "How do all these features connect?"

---

#### `@agent-uxd` — UX Designer
**Your interaction designer who makes things intuitive.**

- Designs task flows that users can follow
- Creates wireframes and interaction specifications
- Ensures accessibility (WCAG 2.1 AA)
- Validates usability before development

**Value:** Users complete tasks without confusion. Interfaces accessible to everyone. Designs validated before code.

**When to use:** "Design the checkout flow", "Is this form usable?", "How should error states work?"

---

#### `@agent-uids` — UI Designer
**Your visual designer who makes interfaces beautiful and functional.**

- Creates design systems and tokens
- Designs color palettes (WCAG compliant)
- Establishes typography hierarchies
- Ensures brand consistency

**Value:** Visual design that reinforces usability. Scalable design systems. WCAG compliance. Documented design decisions.

**When to use:** "Create a color palette", "Design the component library", "Is this visually consistent?"

---

#### `@agent-uid` — UI Developer
**Your frontend specialist who brings designs to life.**

- Implements accessible, responsive components
- Translates designs to pixel-perfect code
- Optimizes frontend performance
- Builds reusable component libraries

**Value:** UI matches design specs. Components work on all devices. Accessible to screen readers. Maintainable code.

**When to use:** "Build this component", "Make this responsive", "Implement the design system"

---

#### `@agent-cw` — Copywriter
**Your content designer who writes words that work.**

- Crafts clear microcopy and button labels
- Writes helpful error messages
- Creates onboarding flows that guide users
- Establishes voice and tone guidelines

**Value:** Users understand without thinking. Error messages help recovery. Consistent voice throughout.

**When to use:** "Write the error messages", "What should this button say?", "Create onboarding copy"

---

## Agent Collaboration

Agents don't work in isolation—they route to each other based on expertise:

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

---

## Quick Start

### Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Node.js | 18+ | Required for MCP servers |
| Claude Code | Latest | The runtime environment |
| Build tools | Platform-specific | For native SQLite compilation |

**Build tools by platform:**
- **macOS:** `xcode-select --install`
- **Linux:** `sudo apt-get install build-essential python3`
- **Windows:** `npm install --global windows-build-tools`

### Installation

```bash
# 1. Clone to global location
mkdir -p ~/.claude
cd ~/.claude
git clone https://github.com/Everyone-Needs-A-Copilot/claude-copilot.git copilot

# 2. Build Memory Copilot
cd copilot/mcp-servers/copilot-memory
npm install
npm run build

# 3. Build Skills Copilot
cd ../skills-copilot
npm install
npm run build

# 4. Copy templates to your project
cd /your/project
cp ~/.claude/copilot/templates/mcp.json ./.mcp.json
cp ~/.claude/copilot/templates/CLAUDE.template.md ./CLAUDE.md

# 5. Restart Claude Code
```

### Start Working

```bash
/protocol    # Start fresh work with Agent-First Protocol
/continue    # Resume where you left off
```

---

## Configuration

### Basic Setup (Works Offline)

The default `.mcp.json` works with no external services:

```json
{
  "mcpServers": {
    "copilot-memory": {
      "command": "node",
      "args": ["~/.claude/copilot/mcp-servers/copilot-memory/dist/index.js"]
    },
    "skills-copilot": {
      "command": "node",
      "args": ["~/.claude/copilot/mcp-servers/skills-copilot/dist/index.js"]
    }
  }
}
```

**What works offline:**
- All 11 agents
- Memory persistence (local SQLite)
- Local project skills
- `/protocol` and `/continue` commands

### Full Setup (With External Services)

For access to 25,000+ public skills and team-shared private skills:

```json
{
  "mcpServers": {
    "copilot-memory": {
      "command": "node",
      "args": ["~/.claude/copilot/mcp-servers/copilot-memory/dist/index.js"]
    },
    "skills-copilot": {
      "command": "node",
      "args": ["~/.claude/copilot/mcp-servers/skills-copilot/dist/index.js"],
      "env": {
        "SKILLSMP_API_KEY": "sk_live_skillsmp_your_key_here",
        "POSTGRES_URL": "postgresql://user:pass@host:5432/database"
      }
    }
  }
}
```

---

## External Services Setup

### SkillsMP (Public Skills)

SkillsMP provides access to **25,000+ curated public skills** for frameworks, languages, and best practices.

**To get your API key:**

1. Visit [skillsmp.com](https://skillsmp.com) (or your organization's SkillsMP instance)
2. Create an account or sign in
3. Navigate to Settings → API Keys
4. Generate a new API key
5. Add to your `.mcp.json` as `SKILLSMP_API_KEY`

**What you get:**
- Skills for popular frameworks (React, Next.js, Laravel, Rails, etc.)
- Language-specific patterns and best practices
- Community-curated and maintained content
- Regular updates as frameworks evolve

### PostgreSQL (Private/Team Skills)

For teams that want to share proprietary skills, methodologies, or company standards.

**Option 1: Managed PostgreSQL (Recommended)**

| Provider | Free Tier | Setup Time |
|----------|-----------|------------|
| [Supabase](https://supabase.com) | 500MB | 5 minutes |
| [Neon](https://neon.tech) | 512MB | 5 minutes |
| [Railway](https://railway.app) | $5 credit | 5 minutes |

**Setup steps:**

1. Create account at your chosen provider
2. Create a new PostgreSQL database
3. Get your connection string (format: `postgresql://user:pass@host:port/db`)
4. Run the schema migration:
   ```bash
   psql "your_connection_string" -f ~/.claude/copilot/mcp-servers/skills-copilot/schema.sql
   ```
5. Add `POSTGRES_URL` to your `.mcp.json`

**Option 2: Self-Hosted PostgreSQL**

```bash
# Using Docker
docker run -d \
  --name skills-db \
  -e POSTGRES_PASSWORD=yourpassword \
  -p 5432:5432 \
  postgres:15

# Run migrations
psql -h localhost -U postgres -f ~/.claude/copilot/mcp-servers/skills-copilot/schema.sql
```

**Saving private skills:**

```
skill_save({
  name: "company-api-standards",
  description: "Our REST API design standards",
  content: "Your skill content here...",
  category: "architecture",
  keywords: ["api", "rest", "standards"],
  isProprietary: true
})
```

---

## Extending Claude Copilot

### Knowledge Repositories

Claude Copilot works standalone with industry-standard methodologies. Teams can extend it with **knowledge repositories** containing proprietary methods.

```
┌────────────────────────────────────────┐
│  Claude Copilot (Base Framework)       │
│  Generic, industry-standard methods    │
│  Works for any developer               │
└────────────────────────────────────────┘
                    │
                    ▼ extends
┌────────────────────────────────────────┐
│  Your Knowledge Repo (Optional)        │
│  Company-specific methodologies        │
│  Proprietary skills & standards        │
└────────────────────────────────────────┘
```

### Extension Types

| Type | Purpose | Example |
|------|---------|---------|
| **Override** | Replace base methodology | Your company's architecture standards instead of generic ones |
| **Extension** | Add to base methodology | Additional security checks for your industry |
| **Skills** | Add capabilities | Your proprietary analysis frameworks |

See [docs/EXTENSION-SPEC.md](docs/EXTENSION-SPEC.md) for the complete specification.

---

## Project Structure

```
claude-copilot/
├── .claude/
│   ├── agents/              # 11 specialized agents
│   │   ├── ta.md            # Tech Architect
│   │   ├── me.md            # Engineer
│   │   ├── qa.md            # QA Engineer
│   │   ├── sec.md           # Security Engineer
│   │   ├── doc.md           # Documentation
│   │   ├── do.md            # DevOps
│   │   ├── sd.md            # Service Designer
│   │   ├── uxd.md           # UX Designer
│   │   ├── uids.md          # UI Designer
│   │   ├── uid.md           # UI Developer
│   │   └── cw.md            # Copywriter
│   └── commands/
│       ├── protocol.md      # /protocol command
│       └── continue.md      # /continue command
├── mcp-servers/
│   ├── copilot-memory/      # Persistence layer
│   └── skills-copilot/      # Knowledge layer
├── docs/
│   ├── ARCHITECTURE.md      # System architecture
│   ├── EXTENSION-SPEC.md    # How to extend
│   └── operations/          # Development standards
├── templates/
│   ├── mcp.json             # MCP config template
│   └── CLAUDE.template.md   # Project CLAUDE.md template
└── README.md
```

---

## Session Management

### Starting Fresh

```bash
/protocol
```

Activates the **Agent-First Protocol**:
1. Every response starts with a protocol declaration
2. Requests are classified and routed to the right agent
3. Agents investigate before presenting solutions
4. You approve before execution

### Resuming Work

```bash
/continue
```

Loads from **Memory Copilot**:
- Current initiative and status
- What you've completed
- What's in progress
- Decisions made and why
- Lessons learned
- Exactly where to pick up

### End of Session

Memory Copilot automatically stores:
- Tasks completed
- Current progress
- Key files touched
- Decisions and rationale
- Lessons learned
- Resume instructions for next time

---

## Philosophy

### Every Developer Deserves a Team

Solo developers shouldn't have to be experts in architecture, security, testing, UX, accessibility, DevOps, and documentation all at once. Claude Copilot gives you access to specialized expertise when you need it.

### Human Advocates Have Equal Standing

The "Human Advocate" agents (Service Designer, UX Designer, UI Designer, UI Developer, Copywriter) aren't secondary to technical agents. Software exists to serve humans—these agents ensure that happens.

### Memory That Persists

Your context shouldn't evaporate between sessions. Decisions, lessons, and progress persist so you never waste tokens rebuilding context.

### Skills On Demand

Load specialized knowledge when you need it, not as bloated context at the start of every session. 25,000+ skills available, each loaded only when relevant.

---

## Requirements

| Component | Required | Optional |
|-----------|----------|----------|
| Node.js 18+ | Yes | - |
| Claude Code CLI | Yes | - |
| Build tools | Yes | - |
| ~300MB disk space | Yes | - |
| SkillsMP API key | No | Enables 25K+ public skills |
| PostgreSQL | No | Enables team-shared private skills |
| Internet connection | No | Only for external skills |

---

## Troubleshooting

### Build fails with native module errors

```bash
# macOS
xcode-select --install

# Linux
sudo apt-get install build-essential python3

# Then rebuild
cd ~/.claude/copilot/mcp-servers/copilot-memory
npm rebuild better-sqlite3
```

### MCP servers not connecting

1. Ensure servers are built: check for `dist/` folders
2. Restart Claude Code after config changes
3. Check paths in `.mcp.json` are absolute or use `~`

### Memory not persisting

- Memory is project-scoped (per directory)
- Check `~/.claude/memory/` for database files
- Ensure write permissions on the directory

---

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

When modifying agents:
- Keep base agents generic (no company-specific content)
- Use industry-standard methodologies
- Include routing to other agents
- Document decision authority

---

## License

MIT License - see [LICENSE](LICENSE)

---

## Links

- [Architecture Documentation](docs/ARCHITECTURE.md)
- [Extension Specification](docs/EXTENSION-SPEC.md)
- [Development Standards](docs/operations/development-standards.md)
- [Security Guidelines](docs/operations/security-guidelines.md)

---

Built by [Everyone Needs a Copilot](https://github.com/Everyone-Needs-A-Copilot)
