# Knowledge Repository Structure Guide

> This document defines the recommended structure for your knowledge repository. Use it as a reference when building out documentation.

---

## Repository Structure

```
[company]-knowledge/
├── knowledge-manifest.json    # Required - declares the repository
├── README.md                  # Overview for humans
├── 01-company/                # Company identity
│   ├── 00-overview.md         # Company overview
│   ├── 01-values.md           # Core values
│   ├── 02-origin.md           # Origin story
│   └── 03-mission.md          # Mission and vision
├── 02-voice/                  # Communication identity
│   ├── 00-overview.md         # Voice overview
│   ├── 01-style.md            # Communication style
│   ├── 02-terminology.md      # Words to use
│   └── 03-anti-patterns.md    # Words to avoid
├── 03-products/               # Product documentation
│   ├── 00-overview.md         # Products overview
│   └── [product-name]/        # Per-product directories
│       ├── overview.md
│       └── ...
├── 04-standards/              # Team standards
│   ├── 00-overview.md         # Standards overview
│   ├── 01-development.md      # Coding standards
│   ├── 02-design.md           # Design standards
│   └── 03-operations.md       # Operations standards
├── .claude/
│   └── extensions/            # Agent customizations
│       ├── ta.extension.md    # Tech Architect extension
│       └── ...
└── .gitignore
```

---

## Directory Purposes

### 01-company/ - Identity

Everything that defines WHO you are.

| File | Purpose | Key Content |
|------|---------|-------------|
| `00-overview.md` | Company at a glance | Elevator pitch, key facts |
| `01-values.md` | Core values | What you stand for, non-negotiables |
| `02-origin.md` | Origin story | Why the company exists |
| `03-mission.md` | Mission & vision | What change you create |

### 02-voice/ - Communication

HOW you communicate - your distinctive style.

| File | Purpose | Key Content |
|------|---------|-------------|
| `00-overview.md` | Voice summary | Quick reference for tone |
| `01-style.md` | Communication style | Formal/casual, direct/gentle |
| `02-terminology.md` | Words to use | Key terms, definitions |
| `03-anti-patterns.md` | Words to avoid | Terms that don't fit |

### 03-products/ (or 03-services/)

WHAT you offer - products, services, or both.

| Structure | Purpose |
|-----------|---------|
| `00-overview.md` | All offerings at a glance |
| `[product]/overview.md` | Individual product/service details |
| `[product]/features.md` | Features and capabilities |
| `[product]/use-cases.md` | How it's used |

### 04-standards/

HOW your team works - processes and standards.

| File | Purpose | Key Content |
|------|---------|-------------|
| `00-overview.md` | Standards summary | Quick reference |
| `01-development.md` | Code standards | Style, testing, review |
| `02-design.md` | Design standards | Components, accessibility |
| `03-operations.md` | Ops standards | Deploy, security, monitoring |

### .claude/extensions/

Customizations that make AI work like your team.

| File | Type | Purpose |
|------|------|---------|
| `ta.extension.md` | Extension | Adds to Tech Architect |
| `sd.override.md` | Override | Replaces Service Designer |
| `custom.md` | New agent | Adds new specialist |

---

## Discovery Phases

Knowledge Copilot builds this structure through guided discovery:

### Phase 1: Foundation (Identity)

**Creates:** `01-company/`

| Topic | Questions Asked |
|-------|-----------------|
| Origin | Why does your company exist? What moment led to starting? |
| Name | Why this name? What does it signal? |
| Values | What do you never compromise on? |
| Mission | What change do you create? |

### Phase 2: Voice (Communication)

**Creates:** `02-voice/`

| Topic | Questions Asked |
|-------|-----------------|
| Style | How do you naturally speak? |
| Terminology | What words do you use? |
| Anti-patterns | What words feel wrong? |
| Tone | How should people feel reading your content? |

### Phase 3: Offerings (Products/Services)

**Creates:** `03-products/` or `03-services/`

| Topic | Questions Asked |
|-------|-----------------|
| Offerings | What do you provide? |
| Audience | Who is this for? Who isn't it for? |
| Problems | What struggles bring people to you? |
| Outcomes | What do clients/users get? |

### Phase 4: Standards (How You Work)

**Creates:** `04-standards/`

| Topic | Questions Asked |
|-------|-----------------|
| Development | Coding standards? Review process? |
| Design | Design system? Accessibility? |
| Operations | Deployment? Security? Compliance? |

### Phase 5: Agent Extensions (Optional)

**Creates:** `.claude/extensions/`

| Topic | Questions Asked |
|-------|-----------------|
| Roles | Which agents do you use most? |
| Customization | How should they behave for your context? |

---

## File Naming Conventions

| Context | Convention | Example |
|---------|------------|---------|
| Overview files | `00-overview.md` | Every directory |
| Numbered content | `NN-kebab-case.md` | `01-values.md` |
| Directories | `NN-kebab-case/` | `01-company/` |

### Numbering

| Range | Purpose |
|-------|---------|
| `00-` | Overview/index only |
| `01-09` | Primary content |
| `10-99` | Extended content (sparse for insertions) |

---

## Document Templates

### Company Overview Template

```markdown
# [Company Name]

## What We Do

[One paragraph: What you do and for whom]

## Quick Facts

| Fact | Value |
|------|-------|
| Founded | [Year] |
| Team Size | [Number] |
| Focus | [Primary focus area] |

## What Makes Us Different

[2-3 bullet points on differentiation]
```

### Voice Guide Template

```markdown
# Voice Guide

## Our Style

| Characteristic | Description | Example |
|----------------|-------------|---------|
| [Trait] | [What it means] | [How it sounds] |

## Words We Use

| Term | Meaning | Why |
|------|---------|-----|
| [Word] | [Definition] | [Reasoning] |

## Words We Avoid

| Avoid | Use Instead | Why |
|-------|-------------|-----|
| [Word] | [Alternative] | [Reasoning] |
```

### Standards Template

```markdown
# [Area] Standards

## Overview

[What this document covers]

## Standards

| Area | Standard | Rationale |
|------|----------|-----------|
| [Area] | [Rule] | [Why] |

## Process

1. [Step 1]
2. [Step 2]
...

## Exceptions

[When standards don't apply]
```

---

## Progress Tracking

Check off as discovery proceeds:

### Foundation
- [ ] Company overview
- [ ] Core values (specific, not generic)
- [ ] Origin story
- [ ] Mission statement

### Voice
- [ ] Communication style defined
- [ ] Key terminology documented
- [ ] Anti-patterns identified
- [ ] Examples provided

### Products/Services
- [ ] Offerings documented
- [ ] Target audience defined
- [ ] Problems addressed
- [ ] Outcomes articulated

### Standards
- [ ] Development standards
- [ ] Design standards
- [ ] Operations standards
- [ ] All validated

### Repository
- [ ] Git initialized
- [ ] Pushed to GitHub
- [ ] Symlinked to ~/.claude/knowledge
- [ ] Tested with knowledge_search

---

## Usage

Once your knowledge repository is linked to `~/.claude/knowledge`:

```
# Search across all knowledge
knowledge_search("company values")
knowledge_search("coding standards")
knowledge_search("brand voice")

# Get specific file
knowledge_get("01-company/01-values.md")
knowledge_get("04-standards/01-development.md")
```

---

## Team Workflow

### Adding Knowledge

1. Edit files in the repository
2. Commit changes:
   ```bash
   git add .
   git commit -m "Add [description]"
   git push
   ```
3. Team members: `git pull`

### Reviewing Changes

Use GitHub PRs for:
- New standards
- Voice changes
- Major updates

### Keeping Current

- Review quarterly
- Update after major decisions
- Add lessons learned

---

_This guide is a living document. Update as your knowledge grows._
