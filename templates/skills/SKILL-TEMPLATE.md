---
# SKILL.md Template
# Canonical frontmatter shape: name + trigger-rich description.
# Native Claude Code surfaces name + description to the model; the model
# fires the skill automatically when a prompt matches. cc skill search is a
# fallback (case-insensitive substring match over name + description + tags).
#
# To use: Copy this file to your skill directory as SKILL.md and fill in the sections.
---
name: your-skill-name          # required, kebab-case; used by cc skill get / cc skill search
description: >-
  One paragraph describing what this skill covers. End with "Use proactively
  when <trigger conditions>." This text drives both native auto-firing and
  cc skill search substring matching — make it trigger-rich.
version: 1.0.0                 # semver; use 2.0.0 for code-bearing (L3 script) skills
allowed-tools: [Read, Glob, Grep]  # add Bash if the skill has an executable script
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
