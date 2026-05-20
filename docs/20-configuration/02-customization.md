# Customization Guide

Claude Copilot ships with industry-standard methodologies—but your team isn't generic. This guide shows how to make it yours.

---

## Three Ways to Customize

| Method | Effort | Best For |
|--------|--------|----------|
| **Private Skills** | Low | Encoding patterns, standards, checklists |
| **Agent Extensions** | Medium | Adding to existing agent capabilities |
| **Agent Overrides** | High | Replacing methodologies entirely |

---

## Quick Start: Private Skills

The fastest way to customize. No code changes required.

### Save a Skill

```javascript
skill_save({
  name: "our-api-standards",
  description: "REST API design standards for our team",
  content: `
# Our API Standards

## Endpoints
- Use plural nouns: /users, /products
- Use HTTP verbs correctly
- Version in URL: /v1/users

## Response Format
\`\`\`json
{
  "data": {},
  "meta": {},
  "errors": []
}
\`\`\`

## Authentication
- All endpoints require Bearer token
- Use short-lived JWTs
  `,
  keywords: ["api", "rest", "standards"],
  isProprietary: true
})
```

### Use a Skill

Any agent can now load your skill:

```
skill_get("our-api-standards")
```

Or search for it:

```
skill_search("api standards")
```

### Requirements

- PostgreSQL database configured (`POSTGRES_URL` in `.mcp.json`)
- See [Configuration](CONFIGURATION.md) for setup

---

## Knowledge Repositories

For deeper customization, create a knowledge repository. This gives you:

- Company/product documentation
- Voice and style guidelines
- Custom agent extensions
- Git-managed, shareable via GitHub

### Create with Knowledge Copilot

```
/knowledge-copilot
```

Guides you through:
1. Company identity (origin, values, mission)
2. Voice (communication style, terminology)
3. Products/Services (offerings, audience)
4. Standards (development, design, operations)
5. Agent extensions (optional customizations)

### Manual Setup

```bash
# Create directory
mkdir -p ~/my-company-knowledge

# Create manifest (required)
cat > ~/my-company-knowledge/knowledge-manifest.json << 'EOF'
{
  "version": "1.0",
  "name": "my-company",
  "description": "Company knowledge repository"
}
EOF

# Create structure
mkdir -p ~/my-company-knowledge/01-company
mkdir -p ~/my-company-knowledge/02-voice
mkdir -p ~/my-company-knowledge/03-products
mkdir -p ~/my-company-knowledge/04-standards
mkdir -p ~/my-company-knowledge/.claude/extensions

# Link to Claude Copilot
ln -sf ~/my-company-knowledge ~/.claude/knowledge
```

### Directory Structure

```
my-company-knowledge/
├── knowledge-manifest.json    # Required
├── 01-company/
│   ├── 00-overview.md         # Company overview
│   ├── 01-values.md           # Core values
│   └── 02-origin.md           # Origin story
├── 02-voice/
│   ├── 00-overview.md         # Voice overview
│   ├── 01-style.md            # Communication style
│   └── 02-terminology.md      # Words to use/avoid
├── 03-products/
│   ├── 00-overview.md         # Products overview
│   └── product-name/          # Per-product docs
├── 04-standards/
│   ├── 00-overview.md         # Standards overview
│   ├── 01-development.md      # Code standards
│   ├── 02-design.md           # Design standards
│   └── 03-operations.md       # Ops standards
└── .claude/
    └── extensions/            # Agent customizations
        ├── ta.extension.md
        └── sd.override.md
```

---

## Agent Extensions

Modify how agents behave for your context.

### Extension Types

| Type | File Pattern | Behavior |
|------|--------------|----------|
| **Override** | `agent.override.md` | Replaces base agent entirely |
| **Extension** | `agent.extension.md` | Adds to base agent |

### Create an Extension

Add to `.claude/extensions/` in your knowledge repo:

**Example: Extend Tech Architect**

`ta.extension.md`:
```markdown
# Tech Architect Extension

## Additional Standards

When designing systems for this company:

### Required Patterns
- All services must be containerized
- Use event sourcing for audit-critical data
- Implement circuit breakers for external calls

### Technology Preferences
| Need | Preferred | Avoid |
|------|-----------|-------|
| Database | PostgreSQL | MongoDB |
| Queue | RabbitMQ | Redis pub/sub |
| Cache | Redis | Memcached |

### Review Checklist
Before approving any architecture:
- [ ] Scalability plan documented
- [ ] Failure modes identified
- [ ] Cost estimate provided
- [ ] Security review scheduled
```

**Example: Override Service Designer**

`sd.override.md`:
```markdown
# Service Designer Override

## Our Methodology

This company uses the Moments Framework for service design.

## Process

### Phase 1: Discovery
[Your specific discovery process]

### Phase 2: Definition
[Your specific definition process]

### Phase 3: Development
[Your specific development process]

## Templates

### Journey Map Template
[Your specific format]

### Blueprint Template
[Your specific format]
```

### Extension Resolution

Extensions are resolved in order:

1. Project-level (`$KNOWLEDGE_REPO_PATH/.claude/extensions/`)
2. Global-level (`~/.claude/knowledge/.claude/extensions/`)
3. Base agent (framework default)

---

## Custom Agents

Create entirely new specialist agents.

### Agent Structure

```markdown
# Agent Name — Agent Profile

## Identity

**Role:** Agent Name
**Code:** `code`

**Mission:** What this agent does.

**You succeed when:**
- Success criteria 1
- Success criteria 2

---

## Core Behaviors

### Always Do
- Behavior 1
- Behavior 2

### Never Do
- Anti-pattern 1
- Anti-pattern 2

---

## Process

[How this agent approaches tasks]

---

## Output Formats

[Templates for deliverables]

---

## Quality Gates

[Checklists before completion]

---

## Route To Other Agents

| Route To | When |
|----------|------|
| `agent-code` | Condition |

---

## Decision Authority

### Autonomous
- Decisions this agent makes alone

### Escalate to User
- Decisions requiring approval
```

### Add Custom Agent

1. Create agent file in `.claude/agents/`:
   ```
   .claude/agents/cpa.md    # Your custom CPA agent
   ```

2. Add to routing (other agents can reference it)

3. Invoke directly:
   ```
   @agent-cpa review the tax implications
   ```

---

## Sharing with Teams

### Push to GitHub

```bash
cd ~/my-company-knowledge
git init
git add .
git commit -m "Initial knowledge repository"

# Create private repo on GitHub, then:
git remote add origin git@github.com:your-org/company-knowledge.git
git push -u origin main
```

### Team Member Setup

```bash
# Clone
git clone git@github.com:your-org/company-knowledge.git ~/company-knowledge

# Link
ln -sf ~/company-knowledge ~/.claude/knowledge

# Or use Knowledge Copilot
/knowledge-copilot
# Choose "Link existing repository"
```

### Updating Knowledge

```bash
# Make changes
cd ~/my-company-knowledge
# Edit files...

# Commit and push
git add .
git commit -m "Update API standards"
git push

# Team members
git pull
```

---

## Examples

### Example: React Team

**Knowledge structure:**
```
react-team-knowledge/
├── 04-standards/
│   ├── 01-development.md     # React patterns, hooks, testing
│   └── 02-design.md          # Component library, design tokens
└── .claude/extensions/
    └── design.extension.md   # Design agent extensions
```

**design.extension.md:**
```markdown
# UI Developer Extension

## Component Standards

- Use functional components with hooks
- Implement with TypeScript
- Follow atomic design principles

## Testing Requirements

- Unit tests for all components
- Storybook stories for visual testing
- Accessibility tests with jest-axe

## Performance

- Lazy load routes
- Memoize expensive calculations
- Use virtual lists for long lists
```

### Example: Compliance Team

**Custom agent: `compliance.md`**
```markdown
# Compliance Officer — Agent Profile

## Identity

**Role:** Compliance Officer
**Code:** `compliance`

**Mission:** Ensure all work meets regulatory requirements.

## Core Behaviors

### Always Do
- Check against SOC 2 requirements
- Verify data handling meets GDPR
- Document compliance decisions

### Never Do
- Approve without documentation
- Skip security review for PII
- Assume compliance without verification

## Checklist

Before approving any feature:
- [ ] Data classification documented
- [ ] Retention policy defined
- [ ] Access controls specified
- [ ] Audit logging implemented
```

---

## Best Practices

### Keep Extensions Focused

- One concern per extension
- Clear, specific guidance
- Actionable, not theoretical

### Version Control Everything

- Use Git for all knowledge
- Review changes via PRs
- Tag releases for rollback

### Document Decisions

- Why, not just what
- Include context and trade-offs
- Update when things change

### Test with Team

- Have team members use extensions
- Gather feedback
- Iterate on what works

---

## Next Steps

- [Extension Specification](EXTENSION-SPEC.md) - Technical details
- [Agents](AGENTS.md) - All 12 specialist agents
- [Configuration](CONFIGURATION.md) - Setup options
