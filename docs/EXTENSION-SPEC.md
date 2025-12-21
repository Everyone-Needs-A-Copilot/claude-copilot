# Agent Extension Specification

This document defines how knowledge repositories extend Claude-Copilot framework agents.

## Overview

Claude-Copilot provides **base agents** with generic, industry-standard methodologies. Knowledge repositories can **extend** these agents with company-specific methodologies, skills, and practices.

```
┌─────────────────────────────────────┐
│  Framework: Base Agents (Generic)   │
│  - Industry-standard methodologies  │
│  - Universal best practices         │
│  - Works standalone                 │
└─────────────────────────────────────┘
              ↓ extends
┌─────────────────────────────────────┐
│  Knowledge Repo: Extensions         │
│  - Company-specific methodologies   │
│  - Proprietary skills               │
│  - Custom deliverable templates     │
└─────────────────────────────────────┘
```

## Extension Types

### 1. Override (`type: "override"`)

**Completely replaces** the base agent's methodology.

**Use when:** Your methodology is fundamentally different from the generic approach.

**File naming:** `[agent].override.md`

**Example:** Service Designer using Moments Framework instead of generic Service Blueprinting

```markdown
---
extends: sd
type: override
description: Moments Framework methodology
requiredSkills:
  - moments-mapping
  - forces-analysis
fallback: use_base_with_warning
---

# Service Designer — System Instructions

[Complete replacement of agent instructions]
```

### 2. Extension (`type: "extension"`)

**Layers company-specific content** on top of the base agent.

**Use when:** You want to keep generic practices but add company-specific enhancements.

**File naming:** `[agent].extension.md`

**Behavior:** Specified sections override base; unspecified sections inherit from base.

```markdown
---
extends: uxd
type: extension
description: Company design system integration
overrideSections:
  - Design System
  - Output Formats
preserveSections:
  - Core Methodologies
  - Quality Gates
---

# UX Designer Extensions

## Design System
[OVERRIDES base Design System section]

Check Figma design system before creating new components...

## Output Formats
[OVERRIDES base Output Formats section]

All wireframes must include Figma component references...
```

### 3. Skills Injection (`type: "skills"`)

**Adds skills** to an agent without changing core behavior.

**Use when:** You want to give agents access to company-specific skills.

**File naming:** `[agent].skills.json`

```json
{
  "extends": "ta",
  "type": "skills",
  "skills": [
    {
      "name": "architecture-patterns",
      "source": "local",
      "path": "skills/architecture-patterns.md",
      "whenToUse": "When designing new features or services",
      "priority": "required"
    },
    {
      "name": "api-standards",
      "source": "mcp://skills-hub",
      "whenToUse": "When creating API endpoints",
      "priority": "recommended"
    }
  ]
}
```

## Resolution Algorithm

When an agent is invoked:

```
1. Check: Does knowledge repo exist?
   ├─ No  → Use base agent (framework only)
   └─ Yes → Continue

2. Load knowledge-manifest.json

3. Check: Is there an extension for this agent?
   ├─ No  → Use base agent
   └─ Yes → Continue

4. Check: Are required skills available?
   ├─ No  → Apply fallbackBehavior
   │        ├─ "use_base" → Use base agent silently
   │        ├─ "use_base_with_warning" → Use base + warn user
   │        └─ "fail" → Error, don't proceed
   └─ Yes → Continue

5. Apply extension based on type:
   ├─ "override" → Replace base entirely
   ├─ "extension" → Merge specified sections
   └─ "skills" → Inject skills into base
```

## File Structure

### Framework (claude-copilot repo)

```
claude-copilot/
├── .claude/
│   └── agents/
│       ├── me.md      # Engineer (base)
│       ├── ta.md      # Tech Architect (base)
│       ├── qa.md      # QA Engineer (base)
│       ├── sec.md     # Security Engineer (base)
│       ├── doc.md     # Documentation (base)
│       ├── do.md      # DevOps (base)
│       ├── sd.md      # Service Designer (base)
│       ├── uxd.md     # UX Designer (base)
│       ├── uids.md    # UI Designer (base)
│       ├── uid.md     # UI Developer (base)
│       └── cw.md      # Copywriter (base)
└── docs/
    └── EXTENSION-SPEC.md  # This file
```

### Knowledge Repository (company-specific)

```
your-knowledge-repo/
├── knowledge-manifest.json    # REQUIRED: Declares extensions
├── .claude/
│   └── extensions/
│       ├── sd.override.md     # Override example
│       ├── uxd.extension.md   # Extension example
│       └── ta.skills.json     # Skills injection example
├── skills/
│   ├── your-skill-1.md
│   └── your-skill-2.md
└── docs/
    └── glossary.md            # Company terminology
```

## Minimum Viable Knowledge Repository

The simplest knowledge repo requires only 2 files:

```
my-knowledge/
├── knowledge-manifest.json
└── docs/
    └── glossary.md
```

**Minimal knowledge-manifest.json:**

```json
{
  "version": "1.0",
  "name": "my-company",
  "glossary": "docs/glossary.md"
}
```

This adds company terminology without modifying any agents.

## Extension File Format

### Override File (.override.md)

```markdown
---
extends: [agent-id]
type: override
description: [What this override provides]
requiredSkills:
  - skill-1
  - skill-2
fallback: use_base_with_warning
---

# [Agent Name] — System Instructions

## Identity
[Complete agent definition]

## Core Behaviors
[All behaviors]

## Methodologies
[Your proprietary methodologies]

## Available Skills
[Skills this agent can use]

## Output Formats
[Deliverable templates]

## Quality Gates
[Checklists]
```

### Extension File (.extension.md)

```markdown
---
extends: [agent-id]
type: extension
description: [What this extension adds]
overrideSections:
  - Section Name 1
  - Section Name 2
preserveSections:
  - Section Name 3
requiredSkills:
  - skill-1
fallback: use_base
---

# [Agent Name] Extensions

## Section Name 1
[OVERRIDES base section]

## Section Name 2
[OVERRIDES base section]

## Additional Section
[ADDS to base agent]
```

### Skills Injection File (.skills.json)

```json
{
  "extends": "[agent-id]",
  "type": "skills",
  "description": "Additional skills for [agent name]",
  "skills": [
    {
      "name": "skill-name",
      "source": "local | mcp://server-name",
      "path": "path/to/skill.md",
      "whenToUse": "Description of when to use this skill",
      "priority": "required | recommended | optional"
    }
  ]
}
```

## Fallback Behavior

| Behavior | When Skills Unavailable |
|----------|------------------------|
| `use_base` | Silently use base agent, no warning |
| `use_base_with_warning` | Use base agent, warn user that proprietary features unavailable |
| `fail` | Error out, don't proceed without required skills |

**Recommended:** Use `use_base_with_warning` for graceful degradation.

## Best Practices

### DO

- Keep base agent functional standalone
- Use `override` only when methodology is fundamentally different
- Prefer `extension` for additive changes
- Use `skills` for capability injection without behavior change
- Provide fallbacks for all required skills
- Document what each extension changes

### DON'T

- Override agents unnecessarily (extension is usually sufficient)
- Require skills without fallbacks (breaks portability)
- Create circular dependencies between extensions
- Modify base agent files (extend instead)

## Integration with Claude Code

When a project uses both claude-copilot framework and a knowledge repository:

1. **Setup:** Run `npx claude-copilot init --knowledge path/to/knowledge-repo`
2. **Resolution:** Framework automatically detects and applies extensions
3. **Runtime:** Agents use extended behavior when invoking `@agent-[name]`

## Version Compatibility

The `framework.minVersion` field in knowledge-manifest.json ensures compatibility:

```json
{
  "framework": {
    "name": "claude-copilot",
    "minVersion": "1.0.0"
  }
}
```

Extensions are validated against framework version at setup time.
