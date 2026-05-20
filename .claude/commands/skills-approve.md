# Skills Manager

Browse, search, and manage reusable skills via the `cc` CLI.

## Overview

Skills are `SKILL.md` files discovered from configured directories:
- **Project skills:** `.claude/skills/` (project-local, highest priority)
- **Global skills:** `~/.claude/skills/` (machine-level)
- **Knowledge repo:** configured via `cc config set paths.knowledge_repo`

## Step 1: List Available Skills

```bash
cc skill list
```

This shows all discovered skills with name, description, tags, and source (project/global).

---

## Step 2: Search Skills

```bash
cc skill search "<keywords>"
```

Example:
```bash
cc skill search "testing patterns"
cc skill search "auth security"
```

---

## Step 3: Inspect a Skill

```bash
cc skill get <name>
```

Example:
```bash
cc skill get testing-patterns
```

---

## Step 4: Create a New Skill

To add a skill, create a `SKILL.md` file in the appropriate directory:

```bash
# Project skill (committed to git)
mkdir -p .claude/skills/<category>
# Then write .claude/skills/<category>/SKILL.md

# Global skill (machine-level, all projects)
mkdir -p ~/.claude/skills/<category>
# Then write ~/.claude/skills/<category>/SKILL.md
```

**SKILL.md format:**
```markdown
---
name: skill-name
description: One-line description used for search and discovery
tags: [tag1, tag2]
triggers:
  filePatterns: ["**/*.test.ts"]
  keywords: ["testing", "jest"]
---

# Skill Name

[Skill content here — guidelines, patterns, examples]
```

---

## Step 5: Find Relevant Skills by Keyword

Search for skills relevant to the current task:

```bash
cc skill search "auth security"
cc skill search "testing"
```

---

## Step 6: Load a Skill in Claude

Use `@include` to inject a skill into the current session:

```
@include .claude/skills/<category>/SKILL.md
```

Skills are plain prose files — the model reads them directly via `@include` or by running `cc skill get <name>` and reading the output.

---

## File Organization

```
.claude/skills/
├── testing/
│   └── SKILL.md
├── patterns/
│   └── SKILL.md
└── security/
    └── SKILL.md
```

---

## Best Practices

- One skill per `SKILL.md` file in its own directory
- Keep names kebab-case and descriptive
- Add tags for better search results
- Commit project skills to git so they travel with the repo
- Use global skills for machine-wide patterns not tied to one project
