# Agent Extension Specification

This document defines how knowledge repositories extend Claude-Copilot framework agents.

> **Implementation status (read this first):** `cc` deterministically resolves
> `paths.knowledge_repo` / `paths.shared_docs` as **config values** — including,
> since the layered-knowledge-repos feature, an **ordered list** of repo paths
> (see [Layered Knowledge Repos](#layered-knowledge-repos-ordered-list) below)
> — and exports them as `CC_*` environment variables via `cc env`. That is the
> full extent of what `cc` parses and merges automatically today.
>
> The richer per-agent model described later in this document — `.override.md` /
> `.extension.md` / `.skills.json` files, `knowledge-manifest.json` parsing,
> section-level merging, and `requiredSkills` validation — is **not**
> implemented by `cc`. It is documented here as an **agent-read convention**:
> an agent invocation may choose to look inside the resolved knowledge-repo
> path(s) for these files and interpret them itself, but no `cc` command
> parses a manifest, merges an `.extension.md` into a base agent, or validates
> `requiredSkills`. Treat every example below that references manifests,
> overrides, or skills injection as a **convention for agents to follow**, not
> a `cc`-resolved behavior, unless explicitly marked otherwise.

## Overview

Claude-Copilot provides **base agents** with generic, industry-standard methodologies. Knowledge repositories can **extend** these agents with company-specific methodologies, skills, and practices.

The system supports **two-tier resolution**: a global knowledge repository shared across all projects, and optional project-specific overrides. Since the layered-knowledge-repos feature, the value that wins at each tier may itself be an **ordered list of repo paths** rather than a single path — see [Layered Knowledge Repos](#layered-knowledge-repos-ordered-list).

```
┌─────────────────────────────────────┐
│  Project Knowledge Repo (optional)  │
│  Path: $KNOWLEDGE_REPO_PATH         │
│  Priority: HIGHEST                  │
└─────────────────────────────────────┘
              ↓ fallback
┌─────────────────────────────────────┐
│  Global Knowledge Repo (shared)     │
│  Path: ~/.claude/knowledge          │
│  Priority: MEDIUM (auto-detected)   │
└─────────────────────────────────────┘
              ↓ fallback
┌─────────────────────────────────────┐
│  Framework: Base Agents (Generic)   │
│  - Industry-standard methodologies  │
│  - Universal best practices         │
│  - Works standalone                 │
└─────────────────────────────────────┘
```

**Key benefit:** Set up your company knowledge once in `~/.claude/knowledge` and it's automatically available in every project. No per-project configuration needed.

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
extends: uid
type: extension
description: Company UI component standards integration
overrideSections:
  - Component Standards
  - Output Formats
preserveSections:
  - Core Methodologies
  - Quality Gates
---

# UI Developer Extensions

## Component Standards
[OVERRIDES base Component Standards section]

Check Figma design system before creating new components...

## Output Formats
[OVERRIDES base Output Formats section]

All components must include Figma component references...
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

When an agent is invoked, the system uses **two-tier resolution**:

```
1. Check PROJECT knowledge repo ($KNOWLEDGE_REPO_PATH)
   ├─ Has extension for this agent? → Use it (highest priority)
   └─ No extension → Continue to step 2

2. Check GLOBAL knowledge repo (~/.claude/knowledge)
   ├─ Has extension for this agent? → Use it
   └─ No extension → Continue to step 3

3. Use base agent (framework only)

4. For resolved extension, check required skills:
   ├─ All available → Apply extension
   └─ Missing skills → Apply fallbackBehavior
        ├─ "use_base" → Use base agent silently
        ├─ "use_base_with_warning" → Use base + warn user
        └─ "fail" → Error, don't proceed

5. Apply extension based on type:
   ├─ "override" → Replace base entirely
   ├─ "extension" → Merge specified sections
   └─ "skills" → Inject skills into base
```

### Precedence Examples

| Project Repo | Global Repo | Result |
|--------------|-------------|--------|
| SD override | SD override | Uses **project** SD override |
| (none) | SD override | Uses **global** SD override |
| uid extension | SD override | uid from project, SD from global |
| (none) | (none) | Base agents only |

## Layered Knowledge Repos (ordered list)

`paths.knowledge_repo` accepts an **ordered list** of repo paths, not just a
single path. This lets a project combine a shared team repo with a personal
one — both are active simultaneously, rather than one replacing the other.

**Value shapes `cc` resolves (implemented, deterministic):**

| Shape | Example | Resolves to |
|-------|---------|-------------|
| Legacy string | `"/vol/shared-kc"` | `["/vol/shared-kc"]` |
| JSON list | `["/vol/shared-kc", "/vol/personal-kc"]` | Same list, in order |
| Absent / `null` | — | `[]` |

**What does NOT change:** layer precedence for *which source* wins is
unchanged — `CC_PATHS_KNOWLEDGE_REPO` env var > project config > machine
config > default. The highest-precedence source that **sets** the key
supplies the **whole** ordered list; `cc` does not concatenate lists across
config layers (e.g. it will not merge a machine-layer list with a
project-layer list). To combine a shared and a personal repo, put both paths
in one list at whichever layer you control:

```bash
# Ordered append, idempotent (no duplicate on repeat)
cc config add paths.knowledge_repo /vol/shared-kc
cc config add paths.knowledge_repo /vol/personal-kc
cc config remove paths.knowledge_repo /vol/personal-kc   # symmetric removal

# Or set the whole list at once — comma-separated values parse into a list
# for this key only (other config keys keep literal commas)
cc config set paths.knowledge_repo /vol/shared-kc,/vol/personal-kc

# Env override also accepts a comma-separated list
export CC_PATHS_KNOWLEDGE_REPO="/vol/shared-kc,/vol/personal-kc"
```

**`cc env` output:** `CC_PATHS_KNOWLEDGE_REPO` is emitted as a comma-joined
string in resolution order. The back-compat alias `CC_KNOWLEDGE_REPO` carries
only the **first** element, so agents/hooks reading a single value keep
working unchanged.

Order in the list is resolution order — index 0 is consulted first if an
agent (per the agent-read convention above) walks the list looking for
extension files.



## File Structure

### Framework (claude-copilot repo)

```
claude-copilot/
├── .claude/
│   └── agents/
│       ├── me.md      # Engineer (base)
│       ├── ta.md      # Tech Architect (base)
│       ├── qa.md      # QA Engineer (base)
│       ├── doc.md     # Documentation (base)
│       ├── do.md      # DevOps (base)
│       ├── sd.md      # Service Designer (base)
│       ├── uxd.md     # UX Designer (base)
│       ├── uids.md    # UI Design System (base)
│       ├── uid.md     # UI Developer (base)
│       └── kc.md      # Knowledge Copilot setup (base)
└── docs/
    └── EXTENSION-SPEC.md  # This file
```

### Global Knowledge Repository (shared across projects)

Located at `~/.claude/knowledge` - automatically detected, no configuration needed.

```
~/.claude/knowledge/
├── knowledge-manifest.json    # REQUIRED: Declares extensions
├── .claude/
│   └── extensions/
│       ├── sd.override.md       # Override example
│       ├── uid.extension.md     # Extension example
│       └── ta.skills.json       # Skills injection example
├── skills/
│   ├── company-skill-1.md
│   └── company-skill-2.md
└── docs/
    └── glossary.md            # Company terminology
```

### Project-Specific Knowledge Repository (optional override)

Only needed when a project requires different extensions than global.

```
your-project/
├── .mcp.json                  # Set KNOWLEDGE_REPO_PATH here
└── project-knowledge/
    ├── knowledge-manifest.json
    └── .claude/
        └── extensions/
            └── sd.override.md  # Project-specific override
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

1. **Setup:** Configure `KNOWLEDGE_REPO_PATH` via `cc config set paths.knowledge_repo <path>` or the env variable
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

### Knowledge Repository Configuration

The framework automatically checks for a global knowledge repository at `~/.claude/knowledge`. No configuration is required for global extensions.

**Register the global knowledge repo path (recommended):**

```bash
cc config set paths.knowledge_repo ~/.claude/knowledge
```

**Register multiple repos (shared + personal, both active):**

```bash
cc config add paths.knowledge_repo ~/.claude/knowledge
cc config add paths.knowledge_repo ~/.claude/knowledge-personal
```

**With project-specific override:**

Set `KNOWLEDGE_REPO_PATH` only when you need project-specific extensions that differ from global:

```bash
# In your project shell or .env
export KNOWLEDGE_REPO_PATH=/path/to/project-specific/knowledge

# Or register with cc config
cc config set paths.knowledge_repo /path/to/project-specific/knowledge
```

See [Layered Knowledge Repos](#layered-knowledge-repos-ordered-list) for the full value-shape and precedence contract.

> **Note:** The `cc env` command exports these as environment variables. Use `eval "$(cc env)"` in agent preambles.

### Available Extension Tools

Extension resolution is performed by the `cc` CLI at agent-invocation time. Use `eval "$(cc env)"` in agent preambles to hydrate `CC_SHARED_DOCS`, `CC_KNOWLEDGE_REPO`, and related variables. The runtime assembles base agent + project override + global override before the agent runs.

#### `cc env` — Runtime assembly

Run `eval "$(cc env)"` to export all configured paths and knowledge-repo variables into the shell environment. The `cc` runtime then uses these to resolve which extension files apply to the invoked agent.

**Example:**
```bash
eval "$(cc env)"
# Sets CC_KNOWLEDGE_REPO, CC_SHARED_DOCS, KNOWLEDGE_REPO_PATH, etc.
```

**Output:** Returns extension content with metadata (type, required skills, fallback behavior).

#### Extension list (via `cc config`)

Lists all available extensions from both global and project repositories.

**Output:** Table showing agent, type, source, description, and required skills for each extension.

```
| Agent | Type | Source | Description | Required Skills |
|-------|------|--------|-------------|-----------------|
| @agent-sd | override | global | Moments Framework | moments-mapping |
| @agent-uid | extension | project (overrides global) | Project UI component standards | - |
```

The `source` column indicates where each extension comes from:
- `global` - From `~/.claude/knowledge`
- `project` - From `$KNOWLEDGE_REPO_PATH`
- `project (overrides global)` - Project extension that takes precedence over a global one

#### Knowledge repo status (via `cc env` / `cc config`)

Returns the status of both global and project knowledge repositories.

**Output:**
```json
{
  "configured": true,
  "global": {
    "path": "/Users/yourname/.claude/knowledge",
    "loaded": true,
    "manifest": {
      "name": "company-knowledge",
      "description": "Company-specific methodologies",
      "extensions": 4,
      "skills": 5
    }
  },
  "project": {
    "path": "/path/to/project/knowledge",
    "loaded": true,
    "manifest": {
      "name": "project-overrides",
      "extensions": 1,
      "skills": 0
    }
  },
  "resolution": "project → global → base agents",
  "howToEnable": {
    "global": "Create ~/.claude/knowledge/knowledge-manifest.json (auto-detected)",
    "project": "Set KNOWLEDGE_REPO_PATH in .mcp.json for project-specific overrides"
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

When invoking an agent with extensions enabled, the `cc` runtime (via `cc env`) resolves extensions automatically:

1. **`cc` CLI resolves extensions** by checking project then global knowledge repo for the agent
2. **Apply extension based on type:**
   - `override`: Use extension content AS the agent instructions (ignore base agent)
   - `extension`: Merge extension with base agent (extension sections override base)
   - `skills`: Inject skills into base agent
3. **If no extension exists:** Use base agent unchanged

### Required Skills Validation

If the extension has `requiredSkills`:

1. Verify each skill is available via `cc skill get <name>`
2. If skills unavailable, apply `fallbackBehavior`:
   - `use_base`: Use base agent silently
   - `use_base_with_warning`: Use base agent, warn user that proprietary features unavailable
   - `fail`: Don't proceed, explain missing skills

### Provider Architecture

Extension resolution is handled by the `cc` CLI (`tools/cc/`). Resolution order: project knowledge repo → global knowledge (`~/.claude/knowledge`) → base framework agents.

```
tools/cc/
├── cc/
│   ├── api.py                      # Public API (memory_store, memory_search, etc.)
│   ├── skills.py                   # Skill discovery and loading
│   ├── knowledge.py                # Extension/knowledge repo resolution
│   └── config.py                  # cc config management
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

The system degrades gracefully at each tier:

**No knowledge repositories found:**
- Global path (`~/.claude/knowledge`) checked but not found
- No project path configured
- All extension tools return informational messages with setup instructions
- Base agents work unchanged
- No errors or failures

**Global repo exists, project repo missing:**
- Global extensions used for all agents
- Project-specific features unavailable (expected behavior)

**Global repo fails to load:**
- Error logged for global repo
- System continues with base agents
- `cc env` output / cc config reports the specific error

**Project repo fails to load:**
- Error logged for project repo
- Falls back to global repo (if available)
- Falls back to base agents (if global also unavailable)

**Both repos exist, extension in project only:**
- Project extension used (highest priority)
- Other agents fall back to global extensions
