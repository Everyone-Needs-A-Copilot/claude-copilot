# Correction Detection System

The correction detection system automatically captures user corrections and feedback, enabling continuous improvement of agents and skills through a two-stage workflow.

## Overview

Correction detection implements a two-stage learning workflow:

| Stage | Trigger | Action |
|-------|---------|--------|
| **Auto-Capture** | User message matches correction patterns | Store with confidence score |
| **Manual Review** | `/reflect` command | User confirms, rejects, or modifies |

## Architecture

```
User Message
      │
      ▼
┌─────────────────────┐
│ Pattern Detection   │ → Regex matching against known patterns
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│ Confidence Scoring  │ → Combine pattern weights + context
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│ Value Extraction    │ → Extract old/new values from captures
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│ Target Inference    │ → Determine where correction applies
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│ Storage (pending)   │ → Store for /reflect review
└─────────────────────┘
```

## Correction Patterns

The system recognizes various correction pattern types:

| Type | Pattern Examples | Weight |
|------|------------------|--------|
| `explicit_correction` | "Correction: X should be Y" | 0.95 |
| `negation` | "No, that's wrong" | 0.90 |
| `replacement` | "Not X, but Y", "Use X instead of Y" | 0.90 |
| `factual_error` | "That's incorrect, the actual..." | 0.90 |
| `clarification` | "What I meant was...", "I said X, not Y" | 0.80-0.90 |
| `preference` | "I prefer X over Y" | 0.75 |
| `style_preference` | "Don't use X, use Y", "Never/Always use X" | 0.80-0.85 |

### Pattern Detection

```typescript
import { matchCorrectionPatterns } from 'copilot-memory/tools/correction-tools';

const message = 'Actually, use TypeScript instead of JavaScript';
const matches = matchCorrectionPatterns(message);

// Returns:
// [{
//   patternId: 'actually-instead',
//   type: 'replacement',
//   matchedText: 'Actually, use TypeScript instead of JavaScript',
//   position: { start: 0, end: 46 },
//   captures: { group1: 'TypeScript', group2: 'JavaScript' }
// }]
```

## Confidence Scoring

Confidence is calculated from multiple factors:

| Factor | Effect |
|--------|--------|
| Pattern weight | Base score from matched pattern |
| Multiple patterns | Boost for cross-validation |
| Message length | Short = boost (focused), Long = penalty (embedded) |
| Previous context | Boost when agent output available |

### Score Interpretation

| Confidence | Suggested Action |
|------------|------------------|
| >= 0.85 | `auto_capture` - High confidence, store automatically |
| 0.50 - 0.84 | `prompt_user` - Ask user to confirm |
| < 0.50 | `ignore` - Below threshold, likely not a correction |

### API

```typescript
import { calculateConfidence } from 'copilot-memory/tools/correction-tools';

const matches = matchCorrectionPatterns(message);
const confidence = calculateConfidence(
  matches,
  message,
  previousAgentOutput  // Optional context
);
// Returns: 0.0 - 1.0
```

## Value Extraction

The system extracts old and new values from matched patterns:

```typescript
import { extractValues } from 'copilot-memory/tools/correction-tools';

const message = 'Not src/index.ts, but src/main.ts';
const matches = matchCorrectionPatterns(message);
const { oldValue, newValue } = extractValues(matches);

// oldValue: 'src/index.ts'
// newValue: 'src/main.ts'
```

### Extraction Priority

1. Explicit correction patterns (highest priority)
2. Replacement patterns
3. Negation patterns
4. Factual error patterns
5. Clarification patterns
6. Preference patterns

## Target Inference

Corrections are routed to appropriate targets based on context:

| Target | When Routed | Storage Location |
|--------|-------------|------------------|
| `skill` | Code/design agent corrections | `.claude/skills/` or agent file |
| `agent` | Architecture/QA agent corrections | `.claude/agents/` |
| `memory` | General knowledge corrections | Memory Copilot (lesson) |
| `preference` | Style/preference corrections | Memory Copilot (context) |

### Agent-Based Routing

| Agent ID | Default Target |
|----------|----------------|
| `me`, `uid` | `skill` (agent-specific) |
| `doc`, `cw` | `skill` (agent-specific) |
| `sd`, `uxd`, `uids` | `skill` (agent-specific) |
| `ta`, `qa`, `sec`, `do` | `agent` |

### Keyword-Based Routing

| Keywords | Target |
|----------|--------|
| "skill", "pattern", "template" | `skill` |
| "prefer", "style", "always", "never" | `preference` |
| "remember", "note", "important" | `memory` |

## Full Detection Flow

```typescript
import { detectCorrections } from 'copilot-memory/tools/correction-tools';

const result = detectCorrections({
  userMessage: 'Correction: use async/await instead of callbacks',
  previousAgentOutput: 'Using callbacks for async...',
  agentId: 'me',
  threshold: 0.5
}, 'project-id');

// Returns:
// {
//   detected: true,
//   corrections: [{
//     id: 'uuid',
//     originalContent: 'Using callbacks for async...',
//     correctedContent: 'async/await',
//     rawUserMessage: 'Correction: use async/await...',
//     matchedPatterns: [...],
//     target: 'skill',
//     targetId: 'agent-me',
//     confidence: 0.95,
//     status: 'pending',
//     expiresAt: '...'  // 7 days
//   }],
//   patternMatchCount: 1,
//   maxConfidence: 0.95,
//   suggestedAction: 'auto_capture'
// }
```

## /reflect Command

The `/reflect` command provides a review interface for pending corrections.

### Usage

```bash
# Review all pending corrections
/reflect

# Filter by status
/reflect --status pending
/reflect --status approved

# Filter by agent
/reflect --agent me

# Include applied corrections
/reflect --include-applied
```

### Review Actions

| Action | Effect |
|--------|--------|
| Approve | Mark as approved, queue for application |
| Reject | Mark as rejected (false positive) |
| Modify | Edit correction before approval |
| Skip | Leave pending for later review |

### Deduplication

Use `--dedupe` to consolidate similar corrections:

```bash
/reflect --dedupe
```

This groups corrections with similar content and allows bulk approval/rejection.

## Correction Routing

After approval, corrections are routed to their target:

### To Skill/Agent Files

```typescript
import { routeCorrection } from 'copilot-memory/tools/correction-tools';

const route = routeCorrection(db, correctionId);
// Returns:
// {
//   correctionId: '...',
//   target: 'skill',
//   targetPath: '.claude/agents/me.md',
//   responsibleAgent: 'me',
//   confidence: 0.95,
//   applyInstructions: 'Update .claude/agents/me.md:\n- Find section...'
// }
```

### To Memory

For `memory` and `preference` targets, corrections are stored via Memory Copilot:

```typescript
// memory_store is called with:
{
  type: 'lesson',  // or 'context' for preferences
  content: 'User prefers: async/await over callbacks',
  tags: ['correction', 'user-feedback']
}
```

## MCP Tools

| Tool | Purpose |
|------|---------|
| `correction_detect` | Detect corrections in user message |
| `correction_list` | List corrections with filters |
| `correction_update` | Update correction status |
| `correction_route` | Get routing info for correction |
| `correction_apply` | Apply approved correction |
| `correction_stats` | Get correction statistics |

### correction_detect

```typescript
const result = await correction_detect({
  userMessage: 'Actually, use the other approach',
  previousAgentOutput: '...',
  agentId: 'me',
  threshold: 0.5,
  autoStore: false  // If true, stores automatically above threshold
});
```

### correction_list

```typescript
const corrections = await correction_list({
  status: 'pending',
  agentId: 'me',
  target: 'skill',
  limit: 20,
  includeExpired: false
});
```

### correction_update

```typescript
await correction_update({
  correctionId: '...',
  status: 'approved',  // or 'rejected'
  rejectionReason: 'False positive'  // If rejecting
});
```

## Database Schema

Corrections are stored in the Memory Copilot database:

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT | Unique identifier |
| `project_id` | TEXT | Project context |
| `session_id` | TEXT | Session where detected |
| `task_id` | TEXT | Task context (if any) |
| `agent_id` | TEXT | Agent that received correction |
| `original_content` | TEXT | What was corrected |
| `corrected_content` | TEXT | The correction |
| `raw_user_message` | TEXT | Full user message |
| `matched_patterns` | JSON | Pattern matches |
| `target` | TEXT | skill/agent/memory/preference |
| `target_id` | TEXT | Specific target identifier |
| `confidence` | REAL | 0-1 confidence score |
| `status` | TEXT | pending/approved/rejected/applied |
| `expires_at` | TEXT | Expiration timestamp (7 days) |

## Best Practices

1. **Threshold Tuning**: Start with 0.5 threshold, adjust based on false positive rate
2. **Review Regularly**: Use `/reflect` periodically to prevent expiration
3. **Agent Context**: Provide `agentId` for better target inference
4. **Previous Output**: Include `previousAgentOutput` for context-aware detection

## Troubleshooting

### Missing Detections

1. Check if message matches any pattern: `matchCorrectionPatterns(message)`
2. Verify threshold isn't too high
3. Try lowering `threshold` parameter

### False Positives

1. Increase threshold (0.6-0.7)
2. Review and reject via `/reflect`
3. Check if patterns are too broad

### Routing Issues

1. Provide `agentId` for agent-based routing
2. Check keyword detection for target inference
3. Use `forceTarget` parameter if needed

## Related Documentation

- [Lifecycle Hooks](./lifecycle-hooks.md)
- [Skill Evaluation](./skill-evaluation.md)
- [Memory Copilot](../../CLAUDE.md#1-memory-copilot)
