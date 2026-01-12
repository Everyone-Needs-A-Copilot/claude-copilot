# Skill Evaluation System

The skill evaluation system automatically detects relevant skills based on file patterns and text analysis, providing confidence-scored recommendations.

## Overview

Skill evaluation combines two detection mechanisms:

| Mechanism | Analyzes | Best For |
|-----------|----------|----------|
| **Pattern Matching** | File paths and extensions | Context with file references |
| **Keyword Detection** | Prompt text and conversation | Natural language requests |

The confidence scorer combines both signals for unified skill recommendations.

## Architecture

```
Context (files + text)
        │
        ├────────────────────┐
        ▼                    ▼
┌──────────────────┐  ┌──────────────────┐
│ Pattern Matcher  │  │ Keyword Detector │
│  (file triggers) │  │   (text/tags)    │
└──────────────────┘  └──────────────────┘
        │                    │
        └────────┬───────────┘
                 ▼
        ┌──────────────────┐
        │ Confidence Scorer │
        │ (0-1 combined)    │
        └──────────────────┘
                 │
                 ▼
        Ranked Skill Recommendations
```

## Pattern Matcher

Matches file paths against glob-like patterns defined in skill metadata.

### Supported Patterns

| Pattern | Example | Matches |
|---------|---------|---------|
| `*.ts` | `*.ts` | `app.ts`, `utils.ts` |
| `*.test.ts` | `*.test.ts` | `app.test.ts`, `utils.test.ts` |
| `src/**` | `src/**` | `src/app.ts`, `src/lib/utils.ts` |
| `package.json` | `package.json` | Exact filename match |
| `**/*.tsx` | `**/*.tsx` | Any .tsx file in any directory |

### Pattern Weights

Different pattern types contribute differently to confidence:

| Pattern Type | Weight | Example |
|--------------|--------|---------|
| Exact filename | 0.35 | `package.json` |
| Simple extension | 0.30 | `*.ts` |
| Directory pattern | 0.25 | `src/**` |
| Compound extension | 0.20 | `*.test.ts` |
| Generic wildcard | 0.15 | `test-*` |

### API

```typescript
import { PatternMatcher } from 'skills-copilot/evaluation';

const matcher = new PatternMatcher();

// Match single file against pattern
const matches = matcher.matchFilePattern('src/app.test.ts', '*.test.ts');
// true

// Match files against skills
const skills = new Map();
skills.set('testing', {
  name: 'testing',
  triggers: { files: ['*.test.ts', '*.spec.ts'] }
});

const results = matcher.match(['src/app.test.ts', 'src/app.ts'], skills);
// [{ skillName: 'testing', confidence: 0.X, matchedPatterns: [...] }]
```

## Keyword Detector

Extracts keywords from text and matches against skill metadata (name, keywords, tags, description).

### TF-IDF Scoring

Keywords are scored using TF-IDF inspired weighting:
- **Term Frequency (TF)**: How often the keyword appears in input
- **Inverse Document Frequency (IDF)**: Rare terms across skills get higher weight

### Match Source Weights

| Source | Weight | Description |
|--------|--------|-------------|
| Skill name | 0.40 | Keywords matching skill name |
| Keywords | 0.35 | Explicit keywords in skill metadata |
| Tags | 0.25 | Tag matches |
| Description | 0.15 | Matches in skill description |

### Text Preprocessing

The detector normalizes input text:
1. Lowercases all text
2. Removes punctuation (except hyphens)
3. Splits on whitespace, underscores, camelCase, kebab-case
4. Filters stop words and short tokens (<3 chars)
5. Applies simple stemming (removes common suffixes)

### API

```typescript
import { KeywordDetector } from 'skills-copilot/evaluation';

const detector = new KeywordDetector();

// Build index from skills
const skills = new Map();
skills.set('react-skill', {
  name: 'react-skill',
  description: 'React component patterns',
  keywords: ['react', 'component', 'hooks'],
  tags: ['frontend', 'ui']
});

detector.buildIndex(skills);

// Match text against skills
const results = detector.match(
  'Help me create a React component with hooks',
  skills
);
// [{ skillName: 'react-skill', confidence: 0.X, matchedKeywords: [...] }]
```

## Confidence Scorer

Combines pattern matching and keyword detection into unified confidence scores.

### Scoring Algorithm

1. **Pattern Score**: Weighted average of matched pattern weights
2. **Keyword Score**: TF-IDF based score from keyword matches
3. **Combined Score**: Weighted combination with multi-signal bonus

```
combined = (patternScore * patternWeight) + (keywordScore * keywordWeight) + agreementBonus
```

Where:
- `patternWeight` = 0.5 (configurable)
- `keywordWeight` = 0.5 (configurable)
- `agreementBonus` = min(patternScore, keywordScore) * 0.1

### Single-Signal Adjustment

When only one signal is present:
- Pattern only: `score * 0.9`
- Keyword only: `score * 0.9`

This slightly penalizes single-signal matches to favor multi-signal confirmation.

### Confidence Levels

| Level | Threshold | Meaning |
|-------|-----------|---------|
| High | >= 0.7 | Strong match, likely relevant |
| Medium | >= 0.4 | Moderate match, possibly relevant |
| Low | < 0.4 | Weak match, may not be relevant |

### Activity Boost

Skills matching recent activity keywords receive a 1.2x confidence boost:

```typescript
const results = scorer.evaluate({
  files: ['src/Button.tsx'],
  text: 'Add accessibility',
  recentActivity: ['accessibility', 'a11y']  // Boosts matching skills
});
```

### API

```typescript
import { ConfidenceScorer } from 'skills-copilot/evaluation';

const scorer = new ConfidenceScorer();

// Set skills to evaluate against
const skills = new Map();
skills.set('react-testing', {
  name: 'react-testing',
  description: 'React component testing',
  keywords: ['test', 'react', 'jest'],
  tags: ['testing'],
  triggers: { files: ['*.test.tsx'] }
});
scorer.setSkills(skills);

// Full evaluation with options
const results = scorer.evaluate(
  {
    files: ['src/Button.test.tsx'],
    text: 'Help me test this React component',
    recentActivity: ['testing']
  },
  {
    threshold: 0.3,      // Minimum confidence
    patternWeight: 0.5,  // Weight for patterns
    keywordWeight: 0.5,  // Weight for keywords
    limit: 10,           // Max results
    activityBoost: 1.2   // Boost for activity matches
  }
);

// Quick checks
const hasMatch = scorer.hasMatch(context, 0.5);
const bestMatch = scorer.getBestMatch(context);
```

## skill_evaluate MCP Tool

The `skill_evaluate` tool provides access to the evaluation system via MCP.

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `files` | string[] | File paths to analyze |
| `text` | string | Text content to analyze |
| `recentActivity` | string[] | Recent activity keywords |
| `threshold` | number | Minimum confidence (default: 0.3) |
| `limit` | number | Max results (default: 10) |
| `showDetails` | boolean | Include match details |

### Example

```typescript
const result = await skill_evaluate({
  files: ['src/auth/login.test.ts', 'src/auth/login.ts'],
  text: 'Help me fix the authentication test',
  threshold: 0.3,
  limit: 5,
  showDetails: true
});
```

### Response

```json
{
  "results": [
    {
      "skillName": "testing-patterns",
      "confidence": 0.78,
      "level": "high",
      "reason": "File patterns: *.test.ts | Keywords: test, authentication"
    },
    {
      "skillName": "auth-patterns",
      "confidence": 0.65,
      "level": "medium",
      "reason": "Keywords: authentication, login"
    }
  ],
  "message": "## Skill Evaluation Results (2 matched)\n..."
}
```

## Skill Metadata for Evaluation

Skills should include evaluation metadata in their frontmatter:

```yaml
---
name: my-skill
description: Brief description for keyword matching
keywords:
  - keyword1
  - keyword2
tags:
  - category1
  - category2
triggers:
  files:
    - "*.test.ts"
    - "src/components/**"
  keywords:
    - specific-keyword
---
```

## Best Practices

1. **Specific Patterns**: Use specific file patterns rather than generic wildcards
2. **Meaningful Keywords**: Include domain-specific keywords, not common words
3. **Unique Tags**: Use tags that differentiate skills from each other
4. **Test Triggers**: Verify skill triggers with `skill_evaluate` before deploying

## Troubleshooting

### Skill Not Matching

1. Check file patterns with `PatternMatcher.matchFilePattern()`
2. Verify keywords aren't being filtered as stop words
3. Ensure threshold isn't too high
4. Check if skill has triggers defined

### Wrong Skill Matching

1. Make patterns more specific
2. Remove generic keywords
3. Increase threshold to filter weak matches
4. Check for keyword overlap with other skills

### Low Confidence Scores

1. Add more relevant keywords
2. Include file trigger patterns
3. Use activity boost for active contexts
4. Combine file and text context

## Related Documentation

- [Skills Copilot Overview](../../CLAUDE.md#3-skills-native--mcp)
- [Extension System](../40-extensions/00-extension-spec.md)
- [Lifecycle Hooks](./lifecycle-hooks.md)
