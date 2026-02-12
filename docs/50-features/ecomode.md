# Ecomode - Smart Model Routing

Ecomode automatically routes tasks to the appropriate Claude model (haiku/sonnet/opus) based on task complexity analysis.

## Overview

Instead of always using the most expensive model, Ecomode analyzes task characteristics and selects the optimal model for cost/performance balance.

**Location:** `mcp-servers/task-copilot/src/ecomode/`

| File | Purpose |
|------|---------|
| `complexity-scorer.ts` | Analyzes task complexity (0.0-1.0 score) |
| `model-router.ts` | Routes to model based on score + modifiers |

---

## Complexity Scoring

The complexity scorer analyzes multiple factors to produce a normalized score.

### Scoring Factors

| Factor | Weight | Analysis |
|--------|--------|----------|
| Keywords | 50% | Task title/description keywords |
| File Count | 30% | Number of files to modify |
| Agent Type | 20% | Assigned agent complexity |

### Keyword Patterns

| Level | Score Range | Example Keywords |
|-------|-------------|------------------|
| Trivial | 0.1-0.2 | typo, spelling, comment, whitespace, formatting |
| Low | 0.2-0.4 | bug fix, small change, minor update, hotfix, patch |
| Medium | 0.4-0.6 | feature, enhancement, refactor, component, API endpoint |
| High | 0.6-0.8 | architecture, migration, integration, security review |
| Very High | 0.8-1.0 | full rewrite, major refactor, platform migration |

### File Count Scoring

| Files | Score | Reasoning |
|-------|-------|-----------|
| 0 | 0.3 | No files specified (medium-low default) |
| 1 | 0.2 | Single file = low complexity |
| 2-3 | 0.35 | Few files = medium-low |
| 4-5 | 0.5 | Several files = medium |
| 6-10 | 0.65 | Many files = medium-high |
| 10+ | 0.8 | Large scope = high |

### Agent Type Scoring

| Agent | Score | Reasoning |
|-------|-------|-----------|
| qa, doc, cw | 0.2 | Typically lower complexity work |
| me, uid | 0.4 | Implementation work |
| uids, uxd | 0.5 | Design work |
| sd, cco | 0.6 | Strategic/creative work |
| ta, sec, do | 0.7 | Architecture/security/infrastructure |

---

## Model Routing

### Default Thresholds

| Score Range | Model | Cost Tier |
|-------------|-------|-----------|
| < 0.3 | Haiku | Low |
| 0.3 - 0.7 | Sonnet | Medium |
| > 0.7 | Opus | High |

### Modifier Keywords

**BREAKING CHANGE (v2.8.0):** Keywords now separate model selection from effort level.

**Effort-level keywords** (auto-select model):
| Keyword | Effort Level | Confidence | Description |
|---------|--------------|------------|-------------|
| `eco:` | low | 0.85 | Minimal reasoning, fast response |
| `fast:` | medium | 0.85 | ⚠️ BREAKING: Was haiku model, now medium effort |
| `max:` | max | 0.85 | ✨ NEW: Maximum reasoning depth |
| `auto:` | (complexity-based) | 0.85 | Auto-select everything |
| `ralph:` | (complexity-based) | 0.85 | Auto-select everything |

**Model-selection keywords** (force model, effort from complexity):
| Keyword | Target Model | Confidence | Description |
|---------|--------------|------------|-------------|
| `opus:` | Opus | 1.0 | Force Opus, effort from task complexity |
| `sonnet:` | Sonnet | 1.0 | Force Sonnet, effort from task complexity |
| `haiku:` | Haiku | 1.0 | Force Haiku, effort from task complexity |

---

## API Reference

### calculateComplexityScore

Analyzes task complexity and returns a normalized score.

```typescript
import { calculateComplexityScore } from 'task-copilot/ecomode/complexity-scorer';

const score = calculateComplexityScore({
  title: 'Fix login authentication bug',
  description: 'Users cannot log in with valid credentials',
  fileCount: 2,
  agentId: 'qa'
});

// Result:
// {
//   score: 0.28,
//   level: 'low',
//   factors: { keywords: 0.25, fileCount: 0.35, agentType: 0.2 },
//   reasoning: 'Low complexity keywords detected (bug fix/small change/typo)'
// }
```

**Input:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | string | Yes | Task title |
| `description` | string | No | Task description |
| `context` | string | No | Additional context |
| `fileCount` | number | No | Number of files (default: 0) |
| `agentId` | string | No | Agent ID (e.g., 'me', 'ta', 'qa') |

**Output:**

| Field | Type | Description |
|-------|------|-------------|
| `score` | number | Normalized score (0.0-1.0) |
| `level` | string | 'trivial', 'low', 'medium', 'high', 'very_high' |
| `factors` | object | Individual factor scores |
| `reasoning` | string | Human-readable explanation |

### routeToModel

Routes a task to the appropriate model based on complexity and modifiers.

```typescript
import { routeToModel } from 'task-copilot/ecomode/model-router';

const result = routeToModel({
  title: 'opus: Design authentication architecture',
  fileCount: 10,
  agentId: 'ta'
});

// Result:
// {
//   route: {
//     model: 'opus',
//     confidence: 1.0,
//     reason: 'User override: opus: → opus',
//     isOverride: true,
//     costTier: 'high'
//   },
//   complexityScore: { score: 0.73, level: 'high', ... },
//   modifier: { keyword: 'opus', targetModel: 'opus', ... }
// }
```

**Input:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | string | Yes | Task title (may include modifier keywords) |
| `description` | string | No | Task description |
| `fileCount` | number | No | Number of files |
| `agentId` | string | No | Agent ID |
| `thresholds` | object | No | Custom routing thresholds |

**Output:**

| Field | Type | Description |
|-------|------|-------------|
| `route` | ModelRoute | Routing decision |
| `complexityScore` | ComplexityScore | Complexity analysis |
| `modifier` | ModifierKeyword | Detected modifier (if any) |

### getRecommendedModel

Simple API to get just the recommended model name.

```typescript
import { getRecommendedModel } from 'task-copilot/ecomode/model-router';

const model = getRecommendedModel('Fix typo in README', {
  fileCount: 1,
  agentId: 'doc'
});

// Result: 'haiku'
```

---

## Examples

### Low Complexity → Haiku

```typescript
routeToModel({ title: 'Fix typo in README', fileCount: 1, agentId: 'doc' });
// → model: 'haiku', score: 0.18, level: 'trivial'
```

### Medium Complexity → Sonnet

```typescript
routeToModel({ title: 'Add user profile feature', fileCount: 5, agentId: 'me' });
// → model: 'sonnet', score: 0.52, level: 'medium'
```

### High Complexity → Opus

```typescript
routeToModel({ title: 'Architecture migration for microservices', fileCount: 15, agentId: 'ta' });
// → model: 'opus', score: 0.73, level: 'high'
```

### Explicit Override

```typescript
routeToModel({ title: 'opus: Simple bug fix' });
// → model: 'opus', isOverride: true (ignores low complexity)
```

### Auto-Routing with eco: (Low Effort)

```typescript
routeToModel({ title: 'eco: Implement new feature', fileCount: 3 });
// → model: 'sonnet' (from complexity)
// → effortLevel: 'low' (from eco: keyword)
// → reason: 'Auto-routing (eco:): Medium complexity... [effort: low]'
```

### Auto-Routing with fast: (Medium Effort)

```typescript
routeToModel({ title: 'fast: Refactor auth module', fileCount: 5 });
// → model: 'sonnet' (from complexity)
// → effortLevel: 'medium' (from fast: keyword)
// ⚠️ BREAKING: Previously forced haiku model
```

### Auto-Routing with max: (Maximum Effort)

```typescript
routeToModel({ title: 'max: Design microservices architecture', fileCount: 12 });
// → model: 'opus' (from complexity)
// → effortLevel: 'max' (from max: keyword)
// ✨ NEW in v2.8.0
```

---

## Performance

The complexity scorer is optimized for speed:

- Target: < 50ms per scoring operation
- Warning logged if scoring exceeds 50ms
- Batch scoring available via `calculateComplexityScores()`

---

## Configuration

### Custom Thresholds

Override default routing thresholds:

```typescript
routeToModel({
  title: 'My task',
  thresholds: {
    low: 0.25,   // Below this → haiku (default: 0.3)
    medium: 0.65 // Below this → sonnet, above → opus (default: 0.7)
  }
});
```

---

## Related Documentation

- [Magic Keywords](./magic-keywords.md) - Modifier and action keywords
- [Progress HUD](./progress-hud.md) - Real-time status display
