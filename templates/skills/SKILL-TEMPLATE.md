---
# SKILL.md Template - Quality-Focused Structure
# This template provides the standard structure for creating skills
# with embedded quality rules, anti-patterns, and validation checklists.
#
# To use: Copy this file to your skill directory as SKILL.md
# and fill in the sections below.
---
skill_name: your-skill-name                    # required, kebab-case
skill_category: engineering                    # required: analysis, engineering, testing, security, documentation, devops, design
description: One-line description of the skill # required, max 100 chars
allowed_tools: [Read, Edit, Glob, Grep]        # required, array of allowed tools
token_estimate: 500                            # required, estimated token count (actual should be within 10%)
version: 1.0                                   # required, semver
last_updated: 2026-01-13                       # required, ISO date
owner: Your Team                               # required
status: active                                 # required: active, deprecated, draft

# Quality-focused metadata (enables quality skill detection)
tags: [pattern, anti-pattern, best-practice, validation]  # Include quality tags for detection
related_skills: []                             # optional, array of related skill names

# Trigger configuration for auto-detection
trigger_files: ["**/*.ts", "**/*.js"]          # File patterns that activate this skill
trigger_keywords: [keyword1, keyword2]          # Keywords in prompts that activate this skill

# Quality keywords (optional, helps with quality detection boosting)
# Include terms like: anti-pattern, best-practice, validation, pattern, idiom, etc.
quality_keywords: [anti-pattern, pattern, validation, best-practice]
---

# Skill Name

Brief description of what this skill provides and when to use it.

## Purpose

Explain the purpose of this skill in 2-3 sentences:
- What problem does it solve?
- Who benefits from it?
- When should it be applied?

---

## Core Patterns

> Best practices and recommended approaches for this domain.

### Pattern 1: [Name]

**When to use:** Describe the context where this pattern applies.

**Implementation:**
```typescript
// Example code showing the correct pattern
function examplePattern() {
  // Correct implementation
}
```

**Benefits:**
- Benefit 1
- Benefit 2

### Pattern 2: [Name]

**When to use:** Context description.

**Implementation:**
```typescript
// Code example
```

---

## Anti-Patterns

> Common mistakes to avoid. Each anti-pattern follows the WHY/DETECTION/FIX structure.

### Anti-Pattern 1: [Name]

| Aspect | Description |
|--------|-------------|
| **WHY** | Explain why this is problematic (performance, maintainability, security, etc.) |
| **DETECTION** | How to identify this issue in code (patterns, symptoms, smells) |
| **FIX** | How to correct the issue with specific guidance |

**Bad Example:**
```typescript
// What NOT to do
function badExample() {
  // Problematic code
}
```

**Good Example:**
```typescript
// Corrected implementation
function goodExample() {
  // Proper code
}
```

### Anti-Pattern 2: [Name]

| Aspect | Description |
|--------|-------------|
| **WHY** | Why this is problematic |
| **DETECTION** | How to detect it |
| **FIX** | How to fix it |

---

## Code Examples

> Complete, runnable examples demonstrating key concepts.

### Example 1: [Basic Usage]

```typescript
// Complete example with context
import { something } from 'somewhere';

function basicUsage() {
  // Implementation
}

// Usage
basicUsage();
```

### Example 2: [Advanced Usage]

```typescript
// More complex example
```

---

## Validation Checklist

> Use this checklist to verify implementations follow best practices.

### Pre-Implementation
- [ ] Understand the requirements fully
- [ ] Review existing patterns in codebase
- [ ] Check for related functionality

### Implementation
- [ ] Follow core patterns from this skill
- [ ] Avoid documented anti-patterns
- [ ] Include appropriate error handling
- [ ] Add necessary tests

### Post-Implementation
- [ ] Run tests and verify all pass
- [ ] Review code for anti-patterns
- [ ] Update documentation if needed
- [ ] Consider edge cases

---

## Related Resources

- [Link to related documentation]
- [Link to external resources]
- Related skills: `skill_get("related-skill-name")`

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-13 | Initial version |
