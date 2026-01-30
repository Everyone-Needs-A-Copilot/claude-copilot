# Stream-D: Skill Extraction Implementation

**Initiative:** OMC Learnings Integration
**Stream:** Stream-D
**Status:** Complete
**Date:** 2026-01-26

## Overview

Implemented automatic skill extraction from work patterns across three components:
1. Pattern detection in Memory Copilot
2. Skill template generation in Skills Copilot
3. Inline notification and approval UI in Memory Copilot

## Components Implemented

### 1. Pattern Detection (Task TASK-0039642c-5c67-462b-ab59-7aca2234e505)

**File:** `mcp-servers/copilot-memory/src/tools/pattern-detection.ts`

**Features:**
- Detects repeated code patterns from memories (decisions, lessons, context)
- Identifies pattern candidates across 4 types:
  - `file_pattern`: File path patterns (e.g., `src/**/*.test.ts`)
  - `keyword`: Technical terms and concepts (e.g., `authentication`, `async`)
  - `workflow`: Multi-step processes (e.g., sequential operations)
  - `code_snippet`: Code pattern types (e.g., `async-await-pattern`, `error-handling-pattern`)
- Scores pattern quality based on frequency and confidence (0.0 to 1.0)
- Stores candidates in memory for review
- Configurable thresholds (min frequency, min confidence, lookback days)

**Key Functions:**
```typescript
detectPatterns(db, projectId, config): Promise<PatternCandidate[]>
storePatternCandidate(db, projectId, pattern): Promise<string>
getPatternCandidates(db, projectId, minConfidence): Promise<PatternCandidate[]>
```

**Detection Methods:**
- File pattern matching via regex on file paths
- Keyword detection using TF-IDF-like approach
- Workflow detection from numbered lists and sequential markers
- Code snippet classification from markdown code blocks

**Confidence Calculation:**
- Frequency score (normalized, max 0.5)
- Context quality score (0-1 based on context diversity)
- Pattern type weight (workflow: 0.9, code_snippet: 0.85, file_pattern: 0.8, keyword: 0.7)
- Formula: `((frequencyScore + contextQuality * 0.5) * typeWeight)`

### 2. Skill Template Generation (Task TASK-723e0bb2-3fd1-4f25-ab77-a050eae87d54)

**File:** `mcp-servers/skills-copilot/src/extraction/template-generator.ts`

**Features:**
- Converts pattern candidates to SKILL.md format
- Generates trigger keywords from pattern context
- Creates example usage sections with placeholders
- Adds metadata (category, complexity, confidence)
- Merges similar templates to reduce duplication

**Key Functions:**
```typescript
generateTemplate(pattern, config): SkillTemplate | null
generateTemplates(patterns, config): SkillTemplate[]
formatSkillMarkdown(template): string
generateSkillFilename(template): string
mergeSimilarTemplates(templates): SkillTemplate[]
```

**Template Structure:**
```markdown
# skill-name

Description from pattern context

## Triggers
**File Patterns:**
- `pattern1`

**Keywords:**
- keyword1
- keyword2

## Context
Pattern detected N times in your work.

## Example Usage
[Auto-generated examples based on pattern type]

## Best Practices
[Placeholder for customization]

## Metadata
- Category: pattern/framework/workflow/best_practice
- Complexity: low/medium/high
- Confidence: XX%
- Frequency: N occurrences
```

**Category Determination:**
- Testing-related → `best_practice`
- Workflow patterns → `workflow`
- Code snippets → `pattern`
- File patterns → `framework`

**Complexity Calculation:**
- Score = (frequency * 0.4) + (confidence * 0.6)
- High score (>0.8) = low complexity (well-established)
- Medium score (0.6-0.8) = medium complexity
- Low score (<0.6) = high complexity (emerging pattern)

### 3. Inline Notification and Approval UI (Task TASK-90709db1-90cc-44ad-a657-53dfcfcfe7fa)

**File:** `mcp-servers/copilot-memory/src/tools/notification-handler.ts`

**Features:**
- Display inline skill suggestions during work
- Provide approve/reject/modify options
- Track approval rates for pattern refinement
- Format metrics dashboard
- Command handlers for user actions

**Key Functions:**
```typescript
displayInlineSuggestion(template): string
storeSuggestion(db, projectId, template): Promise<string>
getPendingSuggestions(db, projectId): Promise<SkillSuggestion[]>
updateSuggestionStatus(db, projectId, suggestionId, status, feedback?, modifications?): Promise<void>
getApprovalMetrics(db, projectId, lookbackDays): Promise<ApprovalMetrics>
handleApprove(db, projectId, suggestionId?): Promise<string>
handleReject(db, projectId, reason, suggestionId?): Promise<string>
handleModify(db, projectId, modifications, suggestionId?): Promise<string>
handlePreview(db, projectId, suggestionId?): Promise<string>
checkForAutoSuggestions(db, projectId, recentFiles, recentKeywords): Promise<SkillSuggestion[]>
```

**Notification Format:**
```
╭─────────────────────────────────────────────╮
│  💡 Skill Pattern Detected                 │
╰─────────────────────────────────────────────╯

**Skill:** skill-name
**Confidence:** XX%
**Category:** category
**Description:** Short description...
**Triggers:** pattern1, pattern2

**Options:**
- Type `/skills-approve` to accept and save
- Type `/skills-reject <reason>` to decline
- Type `/skills-modify` to customize
- Type `/skills-preview` to view full content
```

**Approval Metrics:**
- Total suggestions
- Approved count and percentage
- Modified & approved count
- Rejected count
- Overall approval rate
- Top rejection reasons (frequency tracked)
- Quality trends by confidence level

**Auto-suggestion Logic:**
- Checks approval rate (skip if <30% after 5 suggestions)
- Limits pending suggestions (max 3 at a time)
- Integrates with pattern detection
- Learns from user feedback

### 4. Command Reference

**File:** `.claude/commands/skills-approve.md`

**Commands:**
- `/skills-approve [id]` - Accept skill suggestion
- `/skills-reject <reason> [id]` - Decline suggestion
- `/skills-modify [id]` - Customize before approval
- `/skills-preview [id]` - View full skill content
- `/skills-metrics` - View approval statistics

**Workflow:**
1. Pattern detection runs automatically during work
2. High-confidence patterns (≥0.75) trigger inline notification
3. User reviews via commands
4. Approved skills saved to `.claude/skills/extracted/`
5. User organizes skills into category directories
6. Metrics inform pattern detection refinement

## Integration Points

### Memory Copilot Integration
- Patterns detected from `memories` table (type: decision, lesson, context)
- Suggestions stored in `memories` table (type: context, tags: skill-suggestion)
- Uses existing database schema (no migrations needed)

### Skills Copilot Integration
- Template generator in `src/extraction/` directory
- Uses OMC types from `task-copilot/src/types/omc-features.ts`
- Outputs standard SKILL.md format compatible with existing system

### Task Copilot Integration
- Shares types via `omc-features.ts`
- Pattern detection can integrate with work product analysis
- Future: Auto-extract from work products in addition to memories

## Configuration

Default configuration values:

**Pattern Detection:**
```typescript
{
  minFrequency: 3,        // Min occurrences to consider
  minConfidence: 0.6,     // Min confidence threshold
  maxPatterns: 10,        // Max patterns to return
  lookbackDays: 30        // Analysis window
}
```

**Template Generation:**
```typescript
{
  includeExamples: true,     // Add example sections
  includeMetadata: true,     // Add metadata section
  minConfidence: 0.65        // Min confidence to generate
}
```

**Skill Extraction (OMC Config):**
```typescript
{
  enabled: true,                    // Auto-extraction on/off
  minConfidence: 0.65,              // Min pattern confidence
  minFrequency: 3,                  // Min pattern frequency
  maxSkillsPerSession: 5,           // Suggestion limit
  autoSave: false,                  // Auto-save without approval
  outputDir: ".claude/skills/extracted"  // Save location
}
```

## Testing

**Test File:** `mcp-servers/copilot-memory/src/tools/__tests__/skill-extraction.test.ts`

**Test Coverage:**
- Pattern detection from memories
- Template generation from patterns
- Skill suggestion storage and retrieval
- Approval status updates
- Metrics calculation
- Template merging

## Files Created

```
mcp-servers/copilot-memory/src/tools/
├── pattern-detection.ts            # Pattern detection engine
├── notification-handler.ts         # Notification and approval UI
└── __tests__/
    └── skill-extraction.test.ts    # Integration tests

mcp-servers/skills-copilot/src/extraction/
├── template-generator.ts           # Template generation
└── index.ts                        # Module exports

.claude/commands/
└── skills-approve.md              # Command reference documentation

docs/
└── stream-d-implementation.md      # This file
```

## Export Updates

**Memory Copilot:** `mcp-servers/copilot-memory/src/tools/index.ts`
- Exported pattern detection functions
- Exported notification handler functions
- Exported related types

**Skills Copilot:** `mcp-servers/skills-copilot/src/extraction/index.ts`
- Exported template generation functions
- Exported configuration types

## Usage Example

```typescript
// 1. Detect patterns from recent work
import { detectPatterns } from 'copilot-memory/tools/pattern-detection';
const patterns = await detectPatterns(db, projectId, {
  minFrequency: 3,
  minConfidence: 0.65
});

// 2. Generate skill templates
import { generateTemplates } from 'skills-copilot/extraction';
const templates = generateTemplates(patterns);

// 3. Store suggestions for user review
import { storeSuggestion, displayInlineSuggestion } from 'copilot-memory/tools/notification-handler';
for (const template of templates) {
  if (template.confidence >= 0.75) {
    const id = await storeSuggestion(db, projectId, template);
    console.log(displayInlineSuggestion(template));
  }
}

// 4. User approves via command
import { handleApprove } from 'copilot-memory/tools/notification-handler';
await handleApprove(db, projectId); // Approves most recent pending

// 5. Save approved skill to file
import { formatSkillMarkdown, generateSkillFilename } from 'skills-copilot/extraction';
const filename = generateSkillFilename(template);
const content = formatSkillMarkdown(template);
await writeFile(`.claude/skills/extracted/${filename}`, content);
```

## Future Enhancements

1. **Work Product Integration:** Extract patterns directly from Task Copilot work products
2. **Semantic Similarity:** Use embeddings to detect similar patterns across sessions
3. **Skill Versioning:** Track skill evolution and updates over time
4. **Team Sharing:** Share approved skills across team members
5. **Quality Scoring:** ML-based quality prediction for patterns
6. **Auto-categorization:** Automatically organize skills into directories
7. **Skill Composition:** Combine related skills into larger frameworks

## Performance Considerations

- Pattern detection limited to 30-day lookback by default
- Max 10 patterns returned per detection run
- Max 3 pending suggestions at once to avoid overwhelming user
- Approval rate tracking prevents spam if <30% acceptance
- Database indexes on memories table optimize pattern queries

## Security & Privacy

- No external API calls (all processing local)
- Patterns extracted only from user's own work
- No telemetry or data sharing
- Skills stored locally in project
- User explicit approval required before skill creation

## Success Metrics

- Approval rate target: >70% (indicates quality patterns)
- Pattern detection accuracy: Confidence correlates with user approval
- Time savings: Reduce skill creation time from manual to automatic
- Coverage: Capture 80%+ of repetitive patterns

## Conclusion

Stream-D successfully implements automatic skill extraction with:
- 3 new modules (pattern detection, template generation, notifications)
- 15+ exported functions
- 1 command reference document
- Integration test suite
- Full type safety via OMC types

The system provides intelligent pattern detection, professional skill templates, and user-friendly approval workflow - reducing manual skill creation effort while maintaining quality control.
