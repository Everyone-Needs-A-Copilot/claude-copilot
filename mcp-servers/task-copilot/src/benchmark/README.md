# Token Measurement Tooling

Simple tools for measuring token usage in Claude Copilot benchmark scenarios.

## Overview

This tooling provides:

1. **Token Counting** - Simple word-based approximation (words × 1.3)
2. **Measurement Tracking** - Track token counts at different workflow points
3. **Efficiency Metrics** - Calculate context reduction, storage overhead, etc.
4. **CLI Interface** - Command-line tool for measurements
5. **Programmatic API** - Use in benchmark scripts

## Quick Start

### Programmatic Usage

```typescript
import { createMeasurementTracker } from './benchmark/index.js';

const tracker = createMeasurementTracker('BENCH-1', 'Feature Implementation');

// Measure at different points
tracker.measure('main_input', userRequest);
tracker.measure('agent_output', fullAgentResponse);
tracker.measure('main_return', summaryReturnedToMain);

// Get metrics
const metrics = tracker.calculateMetrics();
console.log(`Context Reduction: ${metrics.percentages.contextReductionPct}%`);

// Export results
const results = tracker.toJSON();
```

### CLI Usage

```bash
# Build first
npm run build

# Count tokens in a file
node dist/benchmark/cli.js count myfile.txt

# Start interactive measurement session
node dist/benchmark/cli.js measure BENCH-1 "Feature Implementation"

# Analyze saved measurements
node dist/benchmark/cli.js analyze results.json
```

## Measurement Points

Based on the technical design (WP-e06d5be3-8595-4dbd-a6bd-2c7d5d15a1b4):

| Point | Description |
|-------|-------------|
| `main_input` | User's initial request to main session |
| `main_context` | Total context loaded in main session |
| `agent_output` | Full content produced by agent |
| `main_return` | Summary returned to main session |
| `storage` | Content stored in Task Copilot |
| `retrieval` | Content retrieved from Task Copilot |

## Efficiency Metrics

The tool calculates:

1. **Context Reduction** - `(agent_output - main_return) / agent_output`
   - Measures how much agent output was compressed before returning to main session
   - Higher is better (framework goal: >95%)

2. **Storage Overhead** - `(storage - agent_output) / agent_output`
   - Additional bytes added by storage metadata/structure
   - Lower is better (acceptable: <10%)

3. **Compression Ratio** - `agent_output / storage`
   - How efficiently content is stored
   - Higher is better (>1.0 means compression)

4. **Main Session Load** - `main_context / (main_input + main_return)`
   - Context amplification in main session
   - Lower is better (framework goal: <2x)

## Examples

### Example 1: Feature Implementation Benchmark

```typescript
import { createMeasurementTracker } from './benchmark/index.js';

const tracker = createMeasurementTracker('BENCH-1', 'Feature Implementation');

// User request
tracker.measure('main_input', 'Implement user authentication');

// Main session context (input + existing context)
tracker.measure('main_context', `
  User request: Implement user authentication
  Project context: Express.js API, PostgreSQL
  Memory loaded: 5 prior decisions
`);

// Full agent output (detailed implementation)
tracker.measure('agent_output', `
  [10,000 words of detailed analysis, code, tests, docs]
`);

// Summary returned to main
tracker.measure('main_return', `
  Task complete: TASK-123
  Work Product: WP-456
  Files: auth.ts, user.model.ts
`);

// Stored in Task Copilot
tracker.measure('storage', JSON.stringify({
  id: 'WP-456',
  content: '[full agent output]',
  metadata: { ... }
}));

// Later retrieval
tracker.measure('retrieval', '[Retrieved content for review]');

// Get results
console.log(tracker.generateSummary());
```

**Expected Output:**

```
Scenario: Feature Implementation (BENCH-1)

Token Counts:
  Main Input:    8
  Main Context:  45
  Agent Output:  13,000
  Main Return:   52
  Storage:       13,500
  Retrieval:     200

Efficiency Metrics:
  Context Reduction:      99.6%
  Storage Overhead:       3.8%
  Compression Ratio:      0.96x
  Main Session Load:      0.75x
  Return vs Output:       0.4%
```

### Example 2: Simple Token Counting

```typescript
import { countTokens } from './benchmark/index.js';

const text = 'This is a sample text with multiple words.';
const tokens = countTokens(text);

console.log(`Tokens: ${tokens}`); // ~11 tokens (8 words × 1.3)
```

## Implementation Notes

### Token Approximation

Uses a simple word-based heuristic:
- Split text on whitespace
- Count words
- Multiply by 1.3

This is intentionally simple for internal testing. For production, use a proper tokenizer.

### Why 1.3x Multiplier?

Common rule of thumb:
- English: ~1.3 tokens per word on average
- Code: ~1.5-2 tokens per word
- JSON/structured: ~1.2 tokens per word

We use 1.3 as a conservative average suitable for mixed content.

### Accuracy

This approximation is within ±20% for most content. Good enough for:
- Comparing relative efficiency
- Detecting major context bloat
- Benchmarking framework improvements

Not suitable for:
- Billing calculations
- Precise token budgets
- Rate limiting

## Files

```
src/benchmark/
├── README.md                 # This file
├── index.ts                  # Public API exports
├── token-counter.ts          # Token counting functions
├── measurement-tracker.ts    # Measurement tracking class
├── cli.ts                    # Command-line interface
└── example.ts                # Usage examples
```

## Testing

Run the example:

```bash
npm run build
node dist/benchmark/example.js
```

## Future Enhancements

Potential improvements (not implemented yet):

1. **Real Tokenizer** - Use tiktoken or similar for accurate counts
2. **Batch Processing** - Measure multiple scenarios at once
3. **Visualization** - Generate charts/graphs from measurements
4. **Statistical Analysis** - Aggregate across multiple runs
5. **Regression Detection** - Alert when metrics worsen over time

## Related

- Technical Design: WP-e06d5be3-8595-4dbd-a6bd-2c7d5d15a1b4
- Task: BENCH-2 (Create token measurement tooling)
- Initiative: Context Efficiency Testing & Audit
