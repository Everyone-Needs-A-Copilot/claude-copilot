---
title: Reference Modules Overview
doc_type: guide
category: references
last_updated: 2026-01-13
status: active
token_estimate: 800
---

# Reference Modules

Reference modules provide deep expert knowledge that skills can load on-demand. Unlike skills (which focus on workflows), reference modules contain comprehensive technical knowledge, idioms, and best practices for specific domains.

## Purpose

Reference modules solve the "fat agent" problem by:
1. **Externalizing expertise** - Domain knowledge lives in dedicated modules, not agent prompts
2. **Loading on-demand** - Only loaded when needed, reducing token usage
3. **Easy maintenance** - Updates to references don't require agent changes
4. **Cross-skill sharing** - Multiple skills can reference the same knowledge

## Module Types

| Type | Purpose | Example |
|------|---------|---------|
| **Language** | Language-specific idioms, patterns | `python-idioms.md`, `typescript-patterns.md` |
| **Framework** | Framework best practices | `react-patterns.md`, `express-patterns.md` |
| **Domain** | Domain expertise | `api-design.md`, `distributed-systems.md` |
| **Quality** | Quality-focused patterns | `testing-patterns.md`, `security-patterns.md` |

## Directory Structure

```
docs/60-references/
├── 00-overview.md           # This file
├── languages/               # Language-specific modules
│   ├── python-idioms.md
│   ├── typescript-patterns.md
│   └── javascript-patterns.md
├── frameworks/              # Framework-specific modules
│   ├── react-patterns.md
│   ├── express-patterns.md
│   └── nextjs-patterns.md
├── domains/                 # Domain expertise modules
│   ├── api-design.md
│   ├── distributed-systems.md
│   └── database-patterns.md
└── quality/                 # Quality-focused modules
    ├── testing-patterns.md
    ├── security-patterns.md
    └── performance-patterns.md
```

## Module Structure

Each reference module follows a standard structure:

```markdown
---
module_name: module-name
module_type: language | framework | domain | quality
description: Brief description
version: 1.0
last_updated: 2026-01-13
token_estimate: 2000
quality_keywords: [pattern, anti-pattern, idiom, best-practice]
---

# Module Name

## Overview
Brief introduction to the module's purpose.

## Core Concepts
Key concepts and terminology.

## Patterns
Recommended patterns with examples.

## Anti-Patterns
Common mistakes to avoid (WHY/DETECTION/FIX).

## Quick Reference
Condensed cheat-sheet for common operations.
```

## Loading Reference Modules

Skills can load reference modules using:

1. **Direct @include** (in skill definition):
   ```markdown
   @include docs/60-references/languages/python-idioms.md
   ```

2. **Skill metadata** (triggers auto-loading):
   ```yaml
   references: [python-idioms, testing-patterns]
   ```

3. **Runtime loading** (via skill_get):
   ```
   skill_get("python-idioms")
   ```

## Creating a Reference Module

1. Choose the appropriate category (language/framework/domain/quality)
2. Use the template from `templates/references/REFERENCE-TEMPLATE.md`
3. Follow the standard structure
4. Include quality keywords for detection boosting
5. Keep token estimate under 3000 for efficiency

## Quality Integration

Reference modules integrate with the quality skill detection system:
- Modules with quality keywords (`anti-pattern`, `pattern`, `best-practice`, etc.) are boosted in quality contexts
- The `skill_evaluate` tool can recommend relevant reference modules based on context
- Quality-focused modules appear in the "Quality-Focused Skills" section of evaluation results
