# Opus 4.6 Capabilities

Claude Opus 4.6 brings transformative capabilities to the Claude Copilot framework with a 1M token context window and adaptive thinking.

## Overview

Claude Opus 4.6 represents a significant leap in model capabilities:

| Capability | Opus 4.6 | Previous (Opus 4) | Impact on Framework |
|------------|----------|------------------|---------------------|
| Context Window | 1M tokens | 200K tokens | 5x larger context, less compaction needed |
| Output Tokens | 128K | 16K | 8x larger responses, enables comprehensive work products |
| Adaptive Thinking | Effort parameter (low/medium/high/max) | None | Controlled reasoning depth per task |
| Context Compaction | Native API | Manual | Automatic context management |
| Agent Teams | Multi-agent orchestration | None | Experimental parallel execution |
| Agentic Coding | Enhanced | Standard | Improved code understanding and generation |

---

## What Changed in Claude Copilot

The framework has been modernized to leverage Opus 4.6 capabilities while maintaining backward compatibility.

### 1. Effort Parameter Replaces Model Selection

**Previous approach (legacy):** Tasks routed to different models (haiku/sonnet/opus) based on complexity.

**New approach (Opus 4.6):** All tasks use Opus 4.6 with varying effort levels.

| Effort Level | Use When | Reasoning Depth | Cost Impact |
|--------------|----------|----------------|-------------|
| `low` | Trivial tasks, quick fixes, typos | Minimal thinking | Lowest |
| `medium` | Standard implementation, simple features | Moderate reasoning | Medium |
| `high` | Default for most tasks | Full reasoning | Standard |
| `max` | Complex architecture, critical design | Deep extended thinking | Highest |

**Code example:**

```typescript
// Effort-based routing (Opus 4.6)
import { routeToModel } from 'ecomode/model-router';

const result = routeToModel({
  title: 'Design authentication architecture',
  fileCount: 10,
  agentId: 'ta'
});

// result.route.effortLevel = 'max' (high complexity detected)
// result.route.model = 'opus' (Opus 4.6)
```

**Complexity-to-Effort Mapping:**

| Complexity Score | Effort Level | Rationale |
|------------------|--------------|-----------|
| < 0.3 | low | Trivial tasks, fast responses |
| 0.3 - 0.7 | high | Standard tasks, default depth |
| > 0.7 | max | Architecture/design, deep reasoning |

**Note:** `medium` effort is reserved for future use or explicit overrides.

### 2. Magic Keyword Changes (Breaking)

Magic keywords now control effort levels instead of model selection.

**Breaking change:**

| Keyword | Old Behavior (Legacy) | New Behavior (Opus 4.6) |
|---------|----------------------|-------------------------|
| `eco:` | Auto-select model | effort: low |
| `fast:` | Force Haiku | effort: medium |
| `max:` | N/A | effort: max |

**Migration guide:**

```bash
# Old (legacy):
/protocol fast: fix the login bug
# → Routed to Haiku model

# New (Opus 4.6):
/protocol fast: fix the login bug
# → Opus 4.6 with effort: medium

# To get truly fast execution with low effort:
/protocol eco: fix the login bug
# → Opus 4.6 with effort: low
```

**All keywords:**

```
eco:     → effort: low (cost-optimized, minimal thinking)
fast:    → effort: medium (balanced speed and quality)
max:     → effort: max (deep reasoning, highest quality)
```

**Model-specific keywords removed:** `opus:`, `sonnet:`, `haiku:` are deprecated. All tasks use Opus 4.6 with varying effort.

### 3. Relaxed Main Session Guardrails

Context limits increased to leverage 1M token window.

**File read limits:**

| Limit | Old (Opus 4) | New (Opus 4.6) | Rationale |
|-------|-------------|----------------|-----------|
| MUST NEVER read | >3 files | None (removed) | 1M context supports larger exploration |
| SHOULD AVOID reading | None | >8 files | Soft guideline, prefer delegation for large tasks |

**Token budgets:**

| Task Type | Old (Opus 4) | New (Opus 4.6) | Increase |
|-----------|-------------|----------------|----------|
| Research + Plan | ~500 tokens | ~2,000 tokens | 4x |
| Implementation | ~500 tokens | ~2,000 tokens | 4x |
| Full initiative | ~2,000 tokens | ~8,000 tokens | 4x |

**Compaction thresholds:**

| Metric | Old (Opus 4) | New (Opus 4.6) | Increase |
|--------|-------------|----------------|----------|
| Agent response limit | 4,096 tokens | 16,384 tokens | 4x |
| Compaction threshold (85%) | 3,482 tokens | 13,927 tokens | 4x |

**Agent handoff limits:**

| Limit | Old (Opus 4) | New (Opus 4.6) | Increase |
|-------|-------------|----------------|----------|
| Handoff summary max | 50 chars | 200 chars | 4x |

**CRITICAL vs. SHOULD rules:**

Main session guardrails now split into two tiers:

**What You MUST NEVER Do:**
- Write implementation code (delegate to `@agent-me`)
- Create detailed plans (delegate to `@agent-ta`)
- Use generic agents (Explore, Plan, general-purpose)

**What You SHOULD AVOID:**
- Read more than 8 files (prefer delegation for large exploration)
- Return detailed analysis (store as work product)

### 4. Ecomode Model Router Refactor

The Ecomode model router has been refactored to separate effort selection from model routing.

**Old architecture:**

```
Task → Complexity Score → Model (haiku/sonnet/opus)
```

**New architecture (Opus 4.6):**

```
Task → Complexity Score → Effort Level (low/medium/high/max)
                        → Model (always opus for complex tasks)
```

**Type changes:**

```typescript
// New type: EffortLevel
type EffortLevel = 'low' | 'medium' | 'high' | 'max';

// ModelRoute now includes effort
interface ModelRoute {
  model: 'haiku' | 'sonnet' | 'opus';
  confidence: number;
  reason: string;
  isOverride: boolean;
  costTier: 'low' | 'medium' | 'high';
  effortLevel: EffortLevel;  // NEW
}
```

**Key files:**
- `ecomode/model-router.ts` - Routing logic with effort parameter
- `ecomode/complexity-scorer.ts` - Unchanged (complexity scoring)
- `types/omc-features.ts` - Type definitions

---

## Agent Teams Coexistence Strategy

Opus 4.6 introduces experimental Agent Teams for multi-agent orchestration. How does this relate to Claude Copilot's orchestration?

### Recommendation: COEXIST

Claude Copilot orchestration and Agent Teams serve different use cases.

| Use Case | Use | Why |
|----------|-----|-----|
| **Ad-hoc collaboration** | Agent Teams | Natural language coordination, no setup |
| **Structured initiatives** | Claude Copilot orchestration | Task tracking, work products, recovery, audit trail |
| **Quick prototypes** | Agent Teams | Fast iteration without framework overhead |
| **Production systems** | Claude Copilot orchestration | Quality gates, git integration, persistent memory |
| **Exploratory work** | Agent Teams | Flexible agent interaction without PRD structure |
| **Multi-phase projects** | Claude Copilot orchestration | Checkpoints, stream isolation, progress tracking |

### When to Use Agent Teams

**Ideal scenarios:**

```bash
# Quick exploration without formal tracking
"@agent-ta and @agent-sec, review this API endpoint for security issues"

# Rapid prototyping
"@agent-uxd and @agent-uids, sketch out a new dashboard layout"

# One-off analysis
"@agent-qa and @agent-me, debug why tests are failing"
```

**Benefits:**
- No PRD or task creation needed
- Agents coordinate naturally through conversation
- Fast setup, minimal overhead
- Good for throwaway work

**Limitations:**
- No persistent work products
- No progress tracking across sessions
- No quality gates or validation
- Hard to resume after interruptions

### When to Use Claude Copilot Orchestration

**Ideal scenarios:**

```bash
# Multi-stream initiative with deliverables
/orchestrate generate
/orchestrate start

# Work that needs recovery across sessions
/continue Stream-B

# Production code with quality requirements
# (uses quality gates, git worktrees, validation)

# Work requiring audit trail
# (all decisions, work products, and progress tracked)
```

**Benefits:**
- Persistent memory and work products
- Stream isolation with git worktrees
- Quality gates and validation
- Progress tracking and recovery
- Audit trail of all decisions

**Trade-offs:**
- More setup (PRD creation)
- Framework learning curve
- Overhead for simple tasks

### Hybrid Approach

Use both systems together:

```bash
# 1. Explore with Agent Teams (fast, informal)
"@agent-ta and @agent-sd, brainstorm authentication approaches"

# 2. Formalize with Claude Copilot (structured, tracked)
/protocol implement OAuth2 authentication
# → Creates PRD, tasks, work products, quality gates
```

**Pattern:** Agent Teams for discovery, Claude Copilot for delivery.

---

## Migration Guide

Migrating existing workflows to leverage Opus 4.6 capabilities.

### For Framework Users

**No action required.** The framework maintains backward compatibility:

- Magic keywords (`eco:`, `fast:`, `max:`) work automatically
- Existing agents route to Opus 4.6 with appropriate effort levels
- Token budgets adjusted automatically
- All tools and protocols unchanged

**Optional optimizations:**

1. **Use effort keywords explicitly:**
   ```bash
   # Old: rely on auto-detection
   /protocol fix the login bug

   # New: explicit effort control
   /protocol eco: fix the login bug  # Low effort, fast
   /protocol max: design auth system # Max effort, deep thinking
   ```

2. **Leverage larger context:**
   ```bash
   # Old: delegate to avoid reading many files
   /protocol analyze the codebase

   # New: main session can read more
   # (Still delegate for >8 files, but less strict)
   ```

3. **Create larger work products:**
   ```bash
   # Compaction threshold now 13,927 tokens (was 3,482)
   # Agents can return more detailed summaries before compacting
   ```

### For Framework Developers

**Required changes:**

1. **Update agent model references:**
   ```yaml
   # Old (.claude/agents/ta.md)
   model: opus

   # New (optional, defaults to opus)
   model: opus  # All agents use Opus 4.6
   ```

2. **Remove model-specific overrides:**
   ```bash
   # Old: Force specific model
   tc task create --title "..." --prd <id> --json
   # metadata: { modelOverride: 'haiku' }

   # New: Use effort levels
   tc task create --title "..." --prd <id> --json
   # metadata: { effortOverride: 'low' }  -- Future enhancement
   ```

3. **Update keyword documentation:**
   - Remove references to model-specific keywords (`opus:`, `sonnet:`, `haiku:`)
   - Document effort keywords (`eco:`, `fast:`, `max:`)
   - Update magic-keywords.md examples

**Optional enhancements:**

1. **Adjust compaction thresholds:**
   ```typescript
   // Old: 4,096 tokens
   const threshold = 4096;

   // New: 16,384 tokens (4x larger)
   const threshold = 16384;
   ```

2. **Increase token budgets:**
   - Agent response summaries: 100 → 400 tokens
   - Work product summaries: 500 → 2,000 tokens
   - Initiative summaries: 2,000 → 8,000 tokens

3. **Relax file read warnings:**
   ```markdown
   # Old
   **NEVER read more than 3 files**

   # New
   **SHOULD AVOID reading more than 8 files**
   ```

---

## Performance Implications

How Opus 4.6 changes framework performance and cost.

### Token Efficiency

| Scenario | Tokens Used (Opus 4) | Tokens Used (Opus 4.6) | Change |
|----------|---------------------|------------------------|--------|
| Simple bug fix (effort: low) | 2,000 (haiku) | 2,500 (opus low) | +25% |
| Standard feature (effort: high) | 8,000 (sonnet) | 8,000 (opus high) | Same |
| Architecture work (effort: max) | 15,000 (opus) | 20,000 (opus max) | +33% |

**Net impact:** Slightly higher token usage, but better quality and larger context reduces iterations.

### Cost Considerations

**Effort levels impact cost through token usage:**

| Effort Level | Relative Cost | Use When |
|--------------|--------------|----------|
| low | Lowest | Trivial tasks, cost-sensitive |
| medium | Medium | Standard work, balanced |
| high | Standard | Default, most tasks |
| max | Highest | Critical design, complex problems |

**Cost optimization strategies:**

1. **Use `eco:` keyword for simple tasks:**
   ```bash
   /protocol eco: fix typo in README
   # → effort: low (minimal tokens)
   ```

2. **Reserve `max:` for critical work:**
   ```bash
   /protocol max: design payment processing architecture
   # → effort: max (deep reasoning needed)
   ```

3. **Default to `high` for standard tasks:**
   ```bash
   /protocol implement user profile feature
   # → effort: high (auto-detected from complexity)
   ```

### Context Compaction

**Native compaction API:** Opus 4.6 includes automatic context management.

**Framework integration (future):**

```typescript
// Current: Manual compaction at 85% threshold
if (tokens > 13927) {
  compactAndStore();
}

// Future: Leverage native compaction API
const response = await claude.messages.create({
  context_compaction: {
    enabled: true,
    threshold: 0.85
  }
});
```

**Benefits:**
- Automatic context management
- No manual token counting
- Better preservation of important context

---

## Future Enhancements

Planned improvements leveraging Opus 4.6 capabilities.

### 1. Native Compaction Integration

Replace manual compaction with Opus 4.6's native API.

**Implementation:**
- Remove custom compaction logic
- Use Claude Messages API `context_compaction` parameter
- Automatic threshold management

**Timeline:** Q2 2026

### 2. Effort-Level Task Metadata

Store effort level in task metadata for better tracking.

```bash
tc task create --title "Complex refactor" --prd <id> --json
# metadata: { effortOverride: 'max', estimatedEffort: 'high' }
```

**Benefits:**
- Explicit effort control per task
- Track actual effort vs. estimated
- Better cost forecasting

**Timeline:** Q2 2026

### 3. Agent Teams Hybrid Mode

Combine Agent Teams with Claude Copilot orchestration.

**Use case:**
```bash
# Phase 1: Explore with Agent Teams
"@agent-ta and @agent-sec, design authentication approach"

# Phase 2: Formalize discoveries in PRD
/protocol implement OAuth2 authentication
# → Uses Agent Teams discoveries as context
```

**Implementation:**
- Convert Agent Teams conversations to work products
- Auto-link to PRD context
- Preserve collaborative decisions

**Timeline:** Q3 2026

### 4. Dynamic Effort Adjustment

Automatically adjust effort mid-task based on complexity signals.

**Example:**
```typescript
// Task starts with effort: high
// Agent encounters unexpected complexity
// System auto-escalates to effort: max
// Agent continues with deeper reasoning
```

**Benefits:**
- Better handling of unexpected complexity
- No manual intervention needed
- Optimal effort allocation

**Timeline:** Q4 2026

---

## FAQ

### Q: Do I need to change anything to use Opus 4.6?

**A:** No. The framework automatically uses Opus 4.6 with appropriate effort levels. Existing workflows continue unchanged.

### Q: What happened to haiku and sonnet models?

**A:** They're still supported for backward compatibility, but the framework now prefers Opus 4.6 with varying effort levels for better quality and consistency.

### Q: How do I control cost with Opus 4.6?

**A:** Use the `eco:` keyword for simple tasks (effort: low), which minimizes token usage. Reserve `max:` for complex work requiring deep reasoning.

### Q: Can I still use `fast:` keyword?

**A:** Yes, but it now maps to `effort: medium` instead of forcing Haiku model. For truly fast execution, use `eco:` (effort: low).

### Q: Should I use Agent Teams or Claude Copilot orchestration?

**A:** Use Agent Teams for quick exploration and ad-hoc collaboration. Use Claude Copilot orchestration for structured initiatives requiring tracking, quality gates, and recovery.

### Q: What's the performance impact of Opus 4.6?

**A:** Token usage may increase 25-33% compared to using haiku/sonnet for simple tasks, but better quality often reduces iterations, leading to net savings.

### Q: How do I migrate existing tasks?

**A:** No migration needed. Existing tasks continue working. Future tasks automatically use Opus 4.6 with effort levels.

### Q: Can I force a specific model instead of effort levels?

**A:** Model-specific keywords are deprecated. Use effort levels instead. If you need model control for testing, use task metadata: `{ modelOverride: 'opus' }`.

---

## Related Documentation

- [Ecomode](./ecomode.md) - Complexity scoring and model routing details
- [Magic Keywords](./magic-keywords.md) - Effort and action keyword reference
- [Main Session Guardrails](../../CLAUDE.md#critical-main-session-guardrails) - Updated token limits
- [Enhancement Features](./00-enhancement-features.md) - Auto-compaction thresholds
- [Agent Guide](../../docs/30-operations/03-agent-guide.md) - Agent-specific patterns

---

## Summary

Opus 4.6 transforms Claude Copilot with:

| Change | Impact |
|--------|--------|
| **1M token context** | 5x larger context, less compaction |
| **Effort parameter** | Controlled reasoning depth (low/medium/high/max) |
| **Relaxed limits** | 8 file reads, 16K response tokens, 4x larger budgets |
| **Breaking keyword change** | `fast:` now maps to effort: medium (not Haiku) |
| **Agent Teams coexistence** | Use Agent Teams for exploration, orchestration for delivery |

**Migration:** Zero action required. Framework automatically leverages Opus 4.6 capabilities while maintaining backward compatibility.

**Cost optimization:** Use `eco:` for simple tasks, `max:` for critical work, default `high` for everything else.
