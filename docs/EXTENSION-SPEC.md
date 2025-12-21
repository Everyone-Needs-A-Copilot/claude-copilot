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

1. **Setup:** Configure `KNOWLEDGE_REPO_PATH` in your MCP server configuration
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

---

## Implementation Details

### MCP Server Configuration

Add `KNOWLEDGE_REPO_PATH` to your skills-copilot MCP server configuration:

```json
{
  "mcpServers": {
    "skills-copilot": {
      "command": "node",
      "args": ["~/.claude/copilot/mcp-servers/skills-copilot/dist/index.js"],
      "env": {
        "LOG_LEVEL": "info",
        "LOCAL_SKILLS_PATH": "~/.claude/copilot/templates/skills",
        "KNOWLEDGE_REPO_PATH": "/path/to/your/knowledge-repo"
      }
    }
  }
}
```

### Available MCP Tools

Three tools are available for extension resolution:

#### `extension_get`

Retrieves the extension for a specific agent.

**Input:**
```json
{
  "agent": "sd"  // Agent ID: me, ta, qa, sec, doc, do, sd, uxd, uids, uid, cw
}
```

**Output:** Returns extension content with metadata (type, required skills, fallback behavior).

#### `extension_list`

Lists all available extensions from the knowledge repository.

**Output:** Table showing agent, type, description, and required skills for each extension.

#### `manifest_status`

Returns the status of the knowledge repository configuration.

**Output:**
```json
{
  "configured": true,
  "path": "/path/to/knowledge-repo",
  "manifest": {
    "name": "company-knowledge",
    "description": "Company-specific methodologies",
    "extensions": 4,
    "skills": 5
  }
}
```

### Protocol Declaration with Extensions

When using the Agent-First Protocol, the declaration should indicate extension status:

**Standard (with extension):**
```
[PROTOCOL: EXPERIENCE | Agent: @agent-sd (Moments Framework override) | Action: INVOKING]
```

**Fallback (extension unavailable):**
```
[PROTOCOL: EXPERIENCE | Agent: @agent-sd (base - extension unavailable) | Action: INVOKING]
```

### Extension Resolution Process

When invoking an agent with extensions enabled:

1. **Call `extension_get(agent_id)`** to check for extensions
2. **Apply extension based on type:**
   - `override`: Use extension content AS the agent instructions (ignore base agent)
   - `extension`: Merge extension with base agent (extension sections override base)
   - `skills`: Inject skills into base agent
3. **If no extension exists:** Use base agent unchanged

### Required Skills Validation

If the extension has `requiredSkills`:

1. Verify each skill is available via `skill_get`
2. If skills unavailable, apply `fallbackBehavior`:
   - `use_base`: Use base agent silently
   - `use_base_with_warning`: Use base agent, warn user that proprietary features unavailable
   - `fail`: Don't proceed, explain missing skills

### Provider Architecture

The extension resolution is handled by `KnowledgeRepoProvider` in the skills-copilot MCP server:

```
mcp-servers/skills-copilot/
├── src/
│   ├── index.ts                    # MCP server with extension tools
│   ├── types.ts                    # Extension type definitions
│   └── providers/
│       ├── index.ts                # Provider exports
│       ├── knowledge-repo.ts       # Extension resolution provider
│       ├── local.ts                # Local skills provider
│       ├── cache.ts                # Skill caching
│       └── ...
```

### Type Definitions

Key types for extension resolution:

```typescript
// Extension types
type ExtensionType = 'override' | 'extension' | 'skills';
type FallbackBehavior = 'use_base' | 'use_base_with_warning' | 'fail';

// Manifest structure
interface KnowledgeManifest {
  version: string;
  name: string;
  description?: string;
  extensions?: ExtensionDeclaration[];
  skills?: { local?: ManifestSkillDeclaration[] };
  glossary?: string;
}

// Extension declaration
interface ExtensionDeclaration {
  agent: string;
  type: ExtensionType;
  file: string;
  description?: string;
  requiredSkills?: string[];
  fallbackBehavior?: FallbackBehavior;
}

// Resolved extension
interface ResolvedExtension {
  agent: string;
  type: ExtensionType;
  content: string;
  requiredSkills: string[];
  fallbackBehavior: FallbackBehavior;
}
```

### Graceful Degradation

When no knowledge repository is configured:

- All extension tools return informational messages
- Base agents work unchanged
- No errors or failures

When knowledge repository is configured but manifest fails to load:

- `manifest_status` reports the error
- `extension_get` returns error with details
- System continues to function with base agents
