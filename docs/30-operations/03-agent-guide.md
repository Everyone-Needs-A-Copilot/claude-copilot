# Agent Guide

This guide covers agent configuration, model routing, and best practices for working with Claude Copilot agents.

---

## Agent Frontmatter

Every agent file (`.claude/agents/*.md`) includes YAML frontmatter with configuration:

```yaml
---
name: agent-id
description: Brief description of agent's role
tools: tool1, tool2, tool3
model: opus | sonnet | haiku
iteration:
  enabled: true
  maxIterations: 15
  completionPromises:
    - "<promise>COMPLETE</promise>"
    - "<promise>BLOCKED</promise>"
---
```

### Model Field

The `model` field specifies the default Claude model for the agent:

| Model | Use Case | Default Agents |
|-------|----------|----------------|
| `opus` | Complex architectural decisions, system design | ta (Tech Architect) |
| `sonnet` | Standard implementation, testing, documentation | me (Engineer), qa (QA), doc, sec, do, sd, uxd, uids, uid, cw |
| `haiku` | Simple tasks, quick operations | (None by default, can be set per-task) |

### Model Override Priority

When executing a task, the effective model is resolved in this order:

1. **Task metadata override** - `task.metadata.modelOverride` (highest priority)
2. **Agent default** - `agent.model` field from frontmatter
3. **System default** - `sonnet` (fallback if not specified)

**Example:**
```typescript
// Task with model override (uses haiku regardless of agent default)
task_create({
  title: "Quick bug fix",
  assignedAgent: "me",
  metadata: {
    modelOverride: "haiku"
  }
})

// Task without override (uses agent's default model)
task_create({
  title: "Implement feature",
  assignedAgent: "me"
  // Uses 'sonnet' from me.md frontmatter
})
```

### Iteration Configuration

Agents can opt into the iteration loop for test-driven development:

```yaml
iteration:
  enabled: true              # Enable iteration support
  maxIterations: 15          # Maximum iterations before circuit breaker
  completionPromises:        # Signals that trigger loop exit
    - "<promise>COMPLETE</promise>"
    - "<promise>BLOCKED</promise>"
  validationRules:           # Optional validation checks
    - tests_pass
    - compiles
    - lint_clean
```

---

## Model Routing Heuristics

The Task Copilot includes an automatic model router (`ecomode/model-router.ts`) that recommends models based on task complexity.

### Complexity Scoring

Tasks are scored 0.0-1.0 based on:

- **Title keywords** - "architecture", "refactor", "design" → higher score
- **File count** - More files → higher score
- **Agent type** - `ta` → higher base score
- **Magic keywords** - `opus:`, `sonnet:`, `haiku:` force models; `eco:`, `fast:`, `max:` set effort

### Routing Thresholds

| Score | Model | Effort | Rationale |
|-------|-------|--------|-----------|
| < 0.3 | haiku | low | Low complexity (quick fixes, simple tasks) |
| 0.3 - 0.7 | sonnet | high | Medium complexity (standard implementation) |
| > 0.7 | opus | max | High complexity (architecture, system design) |

### Magic Keywords (BREAKING CHANGE v2.8.0)

**Effort-level keywords** (auto-select model):

| Keyword | Effort | Effect |
|---------|--------|--------|
| `eco:` | low | Auto-select model, minimal reasoning |
| `fast:` | medium | Auto-select model, balanced reasoning ⚠️ BREAKING |
| `max:` | max | Auto-select model, maximum reasoning ✨ NEW |
| `auto:` | (auto) | Auto-select model and effort |
| `ralph:` | (auto) | Auto-select model and effort |

**Model-selection keywords** (force model):

| Keyword | Effect |
|---------|--------|
| `opus:` | Force Opus model (effort from complexity) |
| `sonnet:` | Force Sonnet model (effort from complexity) |
| `haiku:` | Force Haiku model (effort from complexity) |

**Example:**
```bash
/protocol eco: fix typo in login page
# → Auto-selects model (likely haiku), low effort

/protocol max: design multi-tenant architecture
# → Auto-selects model (likely opus), max effort

/protocol haiku: implement user profile
# → Forces haiku model, effort from complexity

# BREAKING: Old fast: keyword behavior changed
# OLD: /protocol fast: fix bug → forced haiku model
# NEW: /protocol fast: fix bug → auto-selects model, medium effort
# MIGRATION: Use haiku: to force haiku model
```

---

## Agent Selection Matrix

Choose the right agent for each task type:

| Task Type | Agent | Model | Why |
|-----------|-------|-------|-----|
| System architecture | `ta` | opus | Complex design decisions |
| Feature implementation | `me` | sonnet | Standard coding work |
| Bug fixes | `me` | sonnet | Code changes with context |
| Test coverage | `qa` | sonnet | Test design and execution |
| Security review | `sec` | sonnet | Security analysis |
| Documentation | `doc` | sonnet | Technical writing |
| Infrastructure | `do` | sonnet | DevOps configuration |
| Service design | `sd` | sonnet | User journey mapping |
| UX design | `uxd` | sonnet | Interaction design |
| UI design | `uids` | sonnet | Visual design |
| UI implementation | `uid` | sonnet | Frontend code |
| Content writing | `cw` | sonnet | Copy and messaging |

---

## Best Practices

### When to Use Model Overrides

**Use task-level overrides when:**
- Quick fix needed (use `eco:` for low effort or `haiku:` to force haiku)
- Complex reasoning needed (use `max:` for maximum effort or `opus:` to force opus)
- Orchestration workflows (use `max:` or force opus for coordination)

**Don't override when:**
- Agent's default model is already appropriate
- Task complexity matches agent's normal workload
- No specific performance or cost constraint

### Cost Optimization

| Strategy | Savings | When to Use |
|----------|---------|-------------|
| Use `eco:` keyword | ~95% vs opus | Simple fixes, typos, small changes (low effort) |
| Use `haiku:` keyword | ~95% vs opus | Force haiku model for simple tasks |
| Use automatic routing | ~30-50% | Let complexity scoring choose model |
| Set haiku as agent default | ~95% vs opus | Agents doing repetitive simple tasks |
| Use `max:` selectively | Higher cost | Only for complex architecture/design (max effort) |

### Model Performance Characteristics

| Model | Speed | Context | Cost | Best For |
|-------|-------|---------|------|----------|
| Opus | Slowest | Largest | Highest | Architecture, complex problems |
| Sonnet | Medium | Large | Medium | Standard implementation work |
| Haiku | Fastest | Medium | Lowest | Quick fixes, simple tasks |

---

## Model Usage Tracking

Work products automatically track which model was used via `metadata.modelUsed`.

**Query model usage:**
```typescript
// Get progress summary with model breakdown
progress_summary({ initiativeId: "INIT-xxx" })

// Returns:
{
  workProducts: {
    total: 45,
    byType: { implementation: 20, architecture: 10, ... },
    modelUsage: {
      opus: 12,
      sonnet: 30,
      haiku: 3
    }
  }
}
```

**Use this data to:**
- Identify cost optimization opportunities
- Validate model routing decisions
- Tune complexity thresholds
- Analyze agent performance by model

---

## Adding New Agents

When creating a new agent:

1. **Choose default model** based on agent's typical work complexity
2. **Document model choice** in agent's README or comments
3. **Set iteration config** if agent needs TDD loop
4. **Add to agent matrix** in this guide

**Example agent frontmatter:**
```yaml
---
name: my-agent
description: Custom agent for specific domain
tools: Read, Write, Grep, task_get, work_product_store
model: sonnet  # Standard complexity work
iteration:
  enabled: false  # No iteration loop needed
---
```

---

## Troubleshooting

### Model Override Not Working

**Symptom:** Task uses wrong model despite override

**Causes:**
1. Override in wrong field - use `metadata.modelOverride`, not `metadata.model`
2. Magic keyword typo - must be exact (case-insensitive)
3. Caching issue - restart MCP server

**Solution:**
```typescript
// Correct override
task_update({
  id: "TASK-xxx",
  metadata: { modelOverride: "haiku" }
})

// Incorrect (won't work)
task_update({
  id: "TASK-xxx",
  metadata: { model: "haiku" }  // Wrong field name
})
```

### High Costs with Auto-Routing

**Symptom:** More opus usage than expected

**Causes:**
1. Thresholds too low - increase `medium` threshold
2. Keywords triggering opus - review task titles
3. Agent defaults set to opus unnecessarily

**Solution:**
```typescript
// Lower thresholds for more haiku/sonnet usage
const result = routeToModel({
  title: task.title,
  thresholds: {
    low: 0.4,    // Was 0.3 - more haiku
    medium: 0.8  // Was 0.7 - less opus
  }
});
```

---

## Reference

- **Model Router Implementation:** `mcp-servers/task-copilot/src/ecomode/model-router.ts`
- **Complexity Scorer:** `mcp-servers/task-copilot/src/ecomode/complexity-scorer.ts`
- **Agent Definitions:** `.claude/agents/*.md`
- **Task Metadata Types:** `mcp-servers/task-copilot/src/types.ts`
