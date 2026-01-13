---
# Reference Module Template
# Use this template to create expert knowledge modules that skills can load on-demand.
# Copy to appropriate directory: docs/60-references/{languages,frameworks,domains,quality}/
---
module_name: module-name                     # required, kebab-case
module_type: language                        # required: language, framework, domain, quality
description: Brief description of the module # required, max 100 chars
version: 1.0                                 # required, semver
last_updated: 2026-01-13                     # required, ISO date
token_estimate: 2000                         # required, keep under 3000 for efficiency
status: active                               # required: active, deprecated, draft

# Quality detection metadata
quality_keywords: [pattern, anti-pattern, idiom, best-practice, validation]
tags: [category-tag, domain-tag]

# Related modules for cross-referencing
related_modules: []
---

# Module Name

Brief introduction to what this module covers and when to use it.

## Overview

### Purpose
What problems does this module address? Who benefits from it?

### Scope
- What's included
- What's NOT included (and where to find it)

### Prerequisites
Knowledge or tools required to use this module effectively.

---

## Core Concepts

### Concept 1: [Name]

**Definition:** Brief explanation.

**Key points:**
- Point 1
- Point 2

### Concept 2: [Name]

**Definition:** Brief explanation.

---

## Patterns

### Pattern 1: [Name]

**Purpose:** Why use this pattern.

**When to use:**
- Scenario 1
- Scenario 2

**Implementation:**
```
// Code example showing correct implementation
```

**Variations:**
- Variation for scenario A
- Variation for scenario B

### Pattern 2: [Name]

**Purpose:** Why use this pattern.

**Implementation:**
```
// Code example
```

---

## Anti-Patterns

### Anti-Pattern 1: [Name]

| Aspect | Description |
|--------|-------------|
| **WHY** | Why this is problematic |
| **DETECTION** | How to identify this issue |
| **FIX** | How to correct it |

**Bad:**
```
// What NOT to do
```

**Good:**
```
// Correct approach
```

### Anti-Pattern 2: [Name]

| Aspect | Description |
|--------|-------------|
| **WHY** | Explanation |
| **DETECTION** | Symptoms |
| **FIX** | Solution |

---

## Quick Reference

> Condensed cheat-sheet for common operations.

### Common Operations

| Operation | Syntax/Approach |
|-----------|-----------------|
| Operation 1 | How to do it |
| Operation 2 | How to do it |

### Do's and Don'ts

| Do | Don't |
|----|-------|
| Recommended approach | Avoid this |
| Best practice | Anti-pattern |

### Decision Guide

| Situation | Recommendation |
|-----------|----------------|
| When X | Use pattern Y |
| When A | Use pattern B |

---

## Related Resources

- Related module: `@include docs/60-references/related/module.md`
- External resource: [Link]
- Related skill: `skill_get("skill-name")`

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-13 | Initial version |
