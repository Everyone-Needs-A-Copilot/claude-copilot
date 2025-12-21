# Claude-Copilot

An AI-enabled development framework that gives every developer access to a complete team of specialized agents.

## What is Claude-Copilot?

Claude-Copilot provides **11 specialized agents** that work together to help you build better software. Whether you're a solo developer or part of a team, you get access to:

- **Technical experts** for architecture, implementation, testing, security, and DevOps
- **Human advocates** for service design, UX, UI, and content

Each agent follows industry-standard methodologies and best practices, giving you professional-grade guidance throughout your development process.

## Quick Start

```bash
# Clone the framework
git clone https://github.com/Everyone-Needs-A-Copilot/claude-copilot.git

# Copy agents to your project
cp -r claude-copilot/.claude your-project/
```

That's it. The agents are now available in your project.

## Agents

### Technical Core

| Agent | Name | Purpose |
|-------|------|---------|
| `me` | Engineer | Feature implementation, bug fixes, code writing |
| `ta` | Tech Architect | System design, architecture decisions, task breakdown |
| `qa` | QA Engineer | Test plans, automated testing, quality assurance |
| `sec` | Security | Vulnerability analysis, security review, OWASP compliance |
| `doc` | Documentation | Technical writing, API docs, knowledge curation |
| `do` | DevOps | CI/CD, deployment, infrastructure, monitoring |

### Human Advocates

| Agent | Name | Purpose |
|-------|------|---------|
| `sd` | Service Designer | Service blueprints, journey mapping, experience strategy |
| `uxd` | UX Designer | Interaction design, wireframes, usability, accessibility |
| `uids` | UI Designer | Visual design, design systems, typography, color |
| `uid` | UI Developer | Component implementation, responsive layouts, CSS |
| `cw` | Copywriter | UI copy, microcopy, error messages, content strategy |

## Using Agents

Invoke agents in Claude Code with `@agent-[name]`:

```
@agent-ta Design the architecture for a user authentication system

@agent-uxd Create a task flow for the checkout process

@agent-me Implement the login endpoint with JWT authentication
```

Agents automatically route to each other when appropriate. For example, `@agent-sd` will hand off interaction design to `@agent-uxd`.

## Extending with Knowledge Repositories

Claude-Copilot works standalone with generic, industry-standard methodologies. For teams with proprietary methods, you can extend agents with a **knowledge repository**.

### How Extensions Work

```
┌────────────────────────────────────────┐
│  Claude-Copilot (Base Framework)       │
│  Generic industry methodologies        │
│  Works for any developer               │
└────────────────────────────────────────┘
                    ↓ extends
┌────────────────────────────────────────┐
│  Your Knowledge Repo (Optional)        │
│  Company-specific methodologies        │
│  Proprietary skills & practices        │
└────────────────────────────────────────┘
```

### Extension Types

| Type | Description | Use Case |
|------|-------------|----------|
| **Override** | Replace base methodology | Fundamentally different approach |
| **Extension** | Add to base methodology | Company-specific additions |
| **Skills** | Inject additional skills | Extra capabilities |

### Creating a Knowledge Repository

1. Create a `knowledge-manifest.json`:

```json
{
  "version": "1.0",
  "name": "your-company",
  "extensions": [
    {
      "agent": "sd",
      "type": "override",
      "file": ".claude/extensions/sd.override.md",
      "description": "Your proprietary service design methodology"
    }
  ],
  "glossary": "docs/glossary.md"
}
```

2. Create extension files that modify agent behavior.

See [docs/EXTENSION-SPEC.md](docs/EXTENSION-SPEC.md) for the complete specification.

## Project Structure

```
claude-copilot/
├── .claude/
│   ├── agents/          # 11 base agents
│   ├── skills/          # Generic skills (optional)
│   └── hooks/           # Automation hooks (optional)
├── docs/
│   ├── EXTENSION-SPEC.md              # How to extend agents
│   ├── knowledge-manifest-schema.json # Schema for extensions
│   └── knowledge-manifest.example.json
├── scripts/             # Setup and utility scripts
├── CLAUDE.md           # Framework configuration for Claude Code
└── README.md           # This file
```

## Integrating into Your Project

### Option 1: Copy Agents

```bash
cp -r claude-copilot/.claude your-project/
cp claude-copilot/CLAUDE.md your-project/
```

### Option 2: Git Subtree

```bash
git subtree add --prefix .claude https://github.com/Everyone-Needs-A-Copilot/claude-copilot.git main --squash
```

### Option 3: With Knowledge Repository

```bash
# Add framework
cp -r claude-copilot/.claude your-project/

# Add your knowledge repo
git subtree add --prefix docs/shared https://github.com/your-org/your-knowledge.git main --squash
```

## Philosophy

### Every Developer Deserves a Team

Solo developers shouldn't have to be experts in everything. Claude-Copilot gives you access to specialized expertise when you need it.

### Human Advocates

The "Human Advocate" agents (SD, UXD, UIDS, UID, CW) represent disciplines that ensure your software serves real human needs. They have equal standing with technical agents.

### Extensible, Not Prescriptive

The base framework uses generic methodologies that work for everyone. Your organization's specific approaches layer on top without modifying the core.

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

MIT License - see [LICENSE](LICENSE)

---

Built by [Everyone Needs a Copilot](https://github.com/Everyone-Needs-A-Copilot)
