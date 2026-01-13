# Lean Agent Model Migration Guide

This guide explains the lean agent model introduced in v1.8.0 and how to migrate custom agents.

## Overview

The lean agent model reduces agent file size from ~200-400 lines to ~60-100 lines by:

1. **Moving domain knowledge to skills** - Detailed patterns, anti-patterns, and examples live in skill files
2. **Adding skill_evaluate integration** - Agents auto-detect and load relevant skills based on context
3. **Standardizing structure** - All agents follow the same sections and format
4. **Reducing token usage** - Smaller agents load faster and use fewer tokens

### Benefits

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Agent file size | 200-400 lines | 60-100 lines | ~75% smaller |
| Token usage per agent | ~3,000 tokens | ~1,000 tokens | ~67% savings |
| Domain expertise | In agent | Loaded on-demand | Flexible, extensible |
| Skill loading | Manual @include | Auto-detected | Context-aware |

## Lean Agent Structure

Every lean agent has these sections:

```markdown
---
name: agent-name
description: Brief description for routing
tools: [...tools..., preflight_check, skill_evaluate]
model: sonnet
---

# Agent Title

Brief description of role (1-2 sentences).

## Workflow

1. Run `preflight_check({ taskId })`
2. Use `skill_evaluate({ files, text })`
3. [Domain-specific steps]
4. Store work product, return summary only

## Skill Loading Protocol

**Auto-load skills based on context:**
```typescript
const skills = await skill_evaluate({...});
```

**Available skills table**

## Core Behaviors

**Always:**
- [Required behaviors]
- Emit `<promise>COMPLETE</promise>` when done

**Never:**
- [Prohibited behaviors]
- Emit completion promise prematurely

## Output Format

Return ONLY (~100 tokens):
```
Task: TASK-xxx | WP: WP-xxx
[Minimal summary]
```

## Route To Other Agent

| Route To | When |
|----------|------|
| @agent-x | [Condition] |
```

## Required Tools

All lean agents MUST include these tools:

| Tool | Purpose | Required |
|------|---------|----------|
| `preflight_check` | Verify environment before work | ✅ Yes |
| `skill_evaluate` | Auto-detect and load skills | ✅ Yes |
| `task_get` | Retrieve task details | ✅ Yes |
| `task_update` | Update task status | ✅ Yes |
| `work_product_store` | Store output | ✅ Yes |

## Skill Loading Protocol

The skill loading protocol is the key innovation of lean agents:

```typescript
// In agent workflow
const skills = await skill_evaluate({
  files: ['src/auth/*.ts'],         // Files being worked on
  text: task.description,            // Task context
  threshold: 0.5                     // Minimum confidence
});

// Load top matching skills
// @include skills[0].path
```

### How It Works

1. **File Pattern Matching** - `trigger_files` in skill metadata match against provided file paths
2. **Keyword Detection** - `trigger_keywords` in skill metadata match against text content
3. **Confidence Scoring** - Combined score determines relevance (0-1 scale)
4. **Skill Loading** - Agent loads skills above threshold using `@include`

### Skill Metadata

Skills must have trigger metadata for auto-detection:

```yaml
---
skill_name: python-idioms
trigger_files: ["*.py", "**/*.py", "requirements.txt"]
trigger_keywords: [python, django, flask, pytest, pythonic]
---
```

## Migration Steps

### Step 1: Identify Domain Knowledge

Extract domain-specific patterns, anti-patterns, and examples from your agent:

| Keep in Agent | Move to Skill |
|---------------|---------------|
| Workflow steps | Code patterns |
| Core behaviors (brief) | Detailed patterns |
| Routing rules | Anti-patterns |
| Output format | Code examples |
| Tool requirements | Quality checklists |

### Step 2: Create Skill Files

Create skill files in `.claude/skills/[category]/`:

```markdown
---
skill_name: my-domain-patterns
skill_category: engineering
description: Domain-specific patterns and quality rules
trigger_files: ["*.ext", "**/*.ext"]
trigger_keywords: [keyword1, keyword2]
token_estimate: 1500
---

# Domain Patterns

## Core Patterns

### Pattern: [Name]
[Pattern content]

## Anti-Patterns

### Anti-Pattern: [Name]
| WHY | Description |
| DETECTION | How to detect |
| FIX | How to fix |

## Quality Checklist

| Check | Rule |
|-------|------|
| Check 1 | Rule 1 |
```

### Step 3: Simplify Agent

Reduce agent to lean structure (~60-100 lines):

1. Keep frontmatter with required tools
2. Add Skill Loading Protocol section
3. Simplify Core Behaviors to brief lists
4. Add standard Output Format
5. Keep Route To Other Agent table
6. Remove all detailed patterns (now in skills)

### Step 4: Update Tools

Add required tools to frontmatter:

```yaml
tools: [...existing..., preflight_check, skill_evaluate]
```

### Step 5: Test Integration

Run the integration tests to verify:

```bash
npx tsx tests/integration/lean-agents-skills.test.ts
```

## Example Migration

### Before (200 lines)

```markdown
---
name: my-agent
tools: Read, Grep, Edit
model: sonnet
---

# My Agent

... [200 lines of patterns, examples, etc.] ...
```

### After (80 lines)

```markdown
---
name: my-agent
tools: Read, Grep, Edit, task_get, task_update, work_product_store, preflight_check, skill_evaluate
model: sonnet
---

# My Agent

Brief description.

## Workflow
1. preflight_check
2. skill_evaluate
3. Domain work
4. Store work product

## Skill Loading Protocol
[Standard skill loading]

## Core Behaviors
**Always:** [3-5 items]
**Never:** [3-5 items]

## Output Format
[~100 token response template]

## Route To Other Agent
[Routing table]
```

### Skill (150 lines)

```markdown
---
skill_name: my-domain-patterns
trigger_files: [patterns...]
trigger_keywords: [keywords...]
---

# Domain Patterns

[All the detailed patterns, anti-patterns, examples]
```

## Compatibility

### With Extensions

Extensions continue to work with lean agents:

- `override` extensions replace the lean agent entirely
- `extension` extensions add sections to the lean agent
- `skills` extensions inject additional skills

### With Existing Workflows

Existing workflows remain compatible:

- `/protocol` routing works with lean agents
- Task Copilot integration unchanged
- Work product storage unchanged
- Agent handoffs unchanged

## Troubleshooting

### Agent Not Loading Skills

1. Verify `skill_evaluate` is in tools list
2. Check skill has `trigger_files` and `trigger_keywords`
3. Verify skill metadata format (YAML frontmatter)

### Skill Not Detected

1. Check `trigger_files` patterns match your file paths
2. Check `trigger_keywords` match task description
3. Lower `threshold` parameter (try 0.3)
4. Use `skill_list` to verify skill is discovered

### Tests Failing

1. Run `npx tsx tests/integration/lean-agents-skills.test.ts`
2. Check agent has all required sections
3. Verify tools list includes required tools
4. Ensure model is set to `sonnet`

## Related Documentation

- [Skill Evaluation](skill-evaluation.md) - How skill_evaluate works
- [Skill Template](../../templates/skills/SKILL-TEMPLATE.md) - Creating quality skills
- [Agent Structure](../10-architecture/agents.md) - Agent architecture
