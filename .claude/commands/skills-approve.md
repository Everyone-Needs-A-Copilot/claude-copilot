# Skills Approve Command

Review and manage skill extraction suggestions detected during work sessions.

## Overview

The `/skills-approve` command is part of the inline skill extraction system:
1. **Pattern Detection** (Auto): Patterns are detected from work products and memory
2. **Template Generation** (Auto): Patterns are converted to skill templates
3. **User Review** (Manual): User approves, rejects, or modifies skill suggestions

## Usage

```
/skills-approve [suggestion-id]
/skills-reject <reason> [suggestion-id]
/skills-modify [suggestion-id]
/skills-preview [suggestion-id]
/skills-metrics
```

If no `suggestion-id` is provided, commands operate on the most recent pending suggestion.

## Step 1: Check for Pending Suggestions

Call the notification handler to get pending suggestions:

```typescript
import { getPendingSuggestions } from 'copilot-memory/tools/notification-handler';

const suggestions = await getPendingSuggestions(db, projectId);
```

If no suggestions exist:
```
No pending skill suggestions found.

Run your work session and the system will detect patterns automatically.
```

## Step 2: Display Pending Suggestions

Format the suggestions dashboard:

```
## Skill Suggestions Review

You have 3 pending skill suggestions:

---
**Suggestion #1** | ID: `skill-suggestion-abc123`
**Skill:** testing-patterns
**Confidence:** 87%
**Category:** best_practice
**Triggers:** `**/*.test.ts`, testing, jest
**Detected:** 5 times in recent work

[Preview] [Approve] [Reject] [Modify]

---
**Suggestion #2** | ID: `skill-suggestion-def456`
**Skill:** async-await-pattern
**Confidence:** 78%
**Category:** pattern
**Triggers:** async, await, promise
**Detected:** 7 times in recent work

[Preview] [Approve] [Reject] [Modify]

---
**Suggestion #3** | ID: `skill-suggestion-ghi789`
**Skill:** error-handling-pattern
**Confidence:** 82%
**Category:** pattern
**Triggers:** `try`, `catch`, error handling
**Detected:** 4 times in recent work

[Preview] [Approve] [Reject] [Modify]

---

**Commands:**
- `/skills-preview` - View full skill content
- `/skills-approve` - Accept and save skill
- `/skills-reject <reason>` - Decline suggestion
- `/skills-modify` - Customize before saving
- `/skills-metrics` - View approval statistics
```

## Step 3: Handle Commands

### Preview Command

Show full skill template content:

```typescript
import { handlePreview } from 'copilot-memory/tools/notification-handler';

const preview = await handlePreview(db, projectId, suggestionId);
```

Output includes:
- Complete skill content (markdown format)
- Triggers (file patterns and keywords)
- Examples and best practices
- Metadata (confidence, category, complexity)
- Action commands

### Approve Command

Accept skill suggestion and save to local skills:

```typescript
import { handleApprove } from 'copilot-memory/tools/notification-handler';

const result = await handleApprove(db, projectId, suggestionId);
```

Then save skill to file system:

```typescript
import { formatSkillMarkdown, generateSkillFilename } from 'skills-copilot/extraction/template-generator';

const suggestion = suggestions.find(s => s.id === suggestionId);
const filename = generateSkillFilename(suggestion.template);
const content = formatSkillMarkdown(suggestion.template);

// Save to .claude/skills/extracted/
const filepath = `.claude/skills/extracted/${filename}`;
await writeFile(filepath, content);
```

Output:
```
✅ Skill suggestion approved!

**Skill saved:** .claude/skills/extracted/testing-patterns.md

You can now reference this skill with:
@include .claude/skills/extracted/testing-patterns.md

Or move it to a category directory:
mv .claude/skills/extracted/testing-patterns.md .claude/skills/testing/
```

### Reject Command

Decline skill suggestion with reason:

```typescript
import { handleReject } from 'copilot-memory/tools/notification-handler';

const result = await handleReject(db, projectId, reason, suggestionId);
```

Output:
```
❌ Skill suggestion rejected.

**Reason:** Too specific to this project
**Feedback recorded:** This will help improve future suggestions.

Common rejection reasons:
- Too specific to current project
- Already covered by existing skill
- Pattern not repeatable
- Low confidence/quality
```

### Modify Command

Customize skill before approval:

```typescript
import { handleModify } from 'copilot-memory/tools/notification-handler';

// Prompt user for modifications
const modifications = {
  name: 'custom-testing-patterns',
  description: 'Updated description...',
  triggers: {
    filePatterns: ['**/*.spec.ts'],
    keywords: ['testing', 'jest', 'vitest']
  }
};

const result = await handleModify(db, projectId, modifications, suggestionId);
```

Then save modified skill using approve flow.

Output:
```
✏️ Skill suggestion modified and approved!

**Changes applied:**
- Name: testing-patterns → custom-testing-patterns
- Triggers: Added vitest keyword
- Description: Updated

**Skill saved:** .claude/skills/extracted/custom-testing-patterns.md
```

### Metrics Command

Show approval statistics for pattern refinement:

```typescript
import { getApprovalMetrics, formatApprovalMetrics } from 'copilot-memory/tools/notification-handler';

const metrics = await getApprovalMetrics(db, projectId, 30);
const output = formatApprovalMetrics(metrics);
```

Output:
```
╭─────────────────────────────────────────────╮
│  📊 Skill Suggestion Metrics                │
╰─────────────────────────────────────────────╯

**Total Suggestions:** 15
**Approved:** 8 (53%)
**Modified & Approved:** 4 (27%)
**Rejected:** 3 (20%)
**Approval Rate:** 80%

**Top Rejection Reasons:**
- Too specific to this project: 2 times
- Already covered by existing skill: 1 times

**Pattern Quality Trends:**
- High confidence (>80%) suggestions: 90% approval rate
- Medium confidence (60-80%): 65% approval rate
- Low confidence (<60%): 40% approval rate
```

## Step 4: Auto-Suggestions During Work

The system can suggest skills inline during work sessions:

```typescript
import { displayInlineSuggestion, storeSuggestion } from 'copilot-memory/tools/notification-handler';
import { detectPatterns } from 'copilot-memory/tools/pattern-detection';
import { generateTemplate } from 'skills-copilot/extraction/template-generator';

// Detect patterns from recent work
const patterns = await detectPatterns(db, projectId);

// Generate templates for high-confidence patterns
for (const pattern of patterns) {
  const template = generateTemplate(pattern);
  if (template && template.confidence >= 0.75) {
    // Store suggestion
    const suggestionId = await storeSuggestion(db, projectId, template);

    // Display inline notification
    const notification = displayInlineSuggestion(template);
    console.log(notification);
  }
}
```

Inline notification format:
```
╭─────────────────────────────────────────────╮
│  💡 Skill Pattern Detected                 │
╰─────────────────────────────────────────────╯

**Skill:** testing-patterns
**Confidence:** 87%
**Category:** best_practice

**Description:** Guidance for working with files matching: **/*.test.ts...

**Triggers:** **/*.test.ts, testing

**Options:**
- Type `/skills-approve` to accept and save this skill
- Type `/skills-reject <reason>` to decline
- Type `/skills-modify` to customize before saving
- Type `/skills-preview` to view full content
```

## Integration with Pattern Detection

Skills are extracted from:

1. **Work Products** (Task Copilot)
   - Implementation notes
   - Test plans
   - Architecture decisions

2. **Memory** (Memory Copilot)
   - Decisions
   - Lessons learned
   - Context notes

3. **Recent Activity**
   - Files modified
   - Keywords used
   - Workflows followed

## Configuration

Skill extraction is configured in Task Copilot:

```typescript
interface SkillExtractionConfig {
  enabled: boolean;              // Auto-extraction on/off
  minConfidence: number;         // Min confidence (0.0-1.0)
  minFrequency: number;          // Min pattern frequency
  maxSkillsPerSession: number;   // Suggestion limit
  autoSave: boolean;             // Auto-save approved skills
  outputDir: string;             // Where to save skills
}
```

Default settings:
```json
{
  "enabled": true,
  "minConfidence": 0.65,
  "minFrequency": 3,
  "maxSkillsPerSession": 5,
  "autoSave": false,
  "outputDir": ".claude/skills/extracted"
}
```

## File Organization

Approved skills are saved to:
```
.claude/skills/extracted/
├── testing-patterns.md
├── async-await-pattern.md
├── error-handling-pattern.md
└── ...
```

You can organize them by moving to category directories:
```
.claude/skills/
├── testing/
│   └── testing-patterns.md
├── patterns/
│   ├── async-await-pattern.md
│   └── error-handling-pattern.md
└── extracted/
    └── (pending review)
```

## Best Practices

### Review Regularly

Check for suggestions at natural breakpoints:
- End of feature implementation
- After bug fixes
- During code review
- End of work session

### Quality Over Quantity

- Reject low-quality or too-specific suggestions
- Modify generic suggestions to add team context
- Merge similar skills to reduce duplication

### Maintain Skills

- Update skills as patterns evolve
- Remove outdated skills
- Add examples and edge cases
- Document team-specific variations

### Feedback Loop

- Rejection reasons improve detection
- Approval rates guide confidence thresholds
- Metrics show pattern quality trends

## Edge Cases

### No Suggestions

```
No pending skill suggestions found.

**Why?**
- Not enough pattern repetition detected
- Confidence thresholds not met
- Patterns already covered by existing skills

**To increase suggestions:**
- Work on similar tasks repeatedly
- Lower minConfidence threshold
- Lower minFrequency threshold
```

### Too Many Suggestions

```
You have 15 pending skill suggestions.

**Tip:** This might indicate:
- Threshold too low (many low-quality patterns)
- Diverse work (many different patterns)
- Need to review more frequently

Consider:
- Raising minConfidence threshold
- Using bulk reject for low-quality patterns
- Reviewing skills more regularly
```

### Duplicate Detection

System automatically merges similar patterns:
- Same category
- Overlapping keywords
- Similar file patterns

## Workflow Example

```
# During work session
[Auto-detect pattern after 3rd similar operation]

╭─────────────────────────────────────────────╮
│  💡 Skill Pattern Detected                 │
╰─────────────────────────────────────────────╯
[Inline notification shown]

# Review at end of session
> /skills-approve

✅ Skill saved: .claude/skills/extracted/testing-patterns.md

# Check metrics periodically
> /skills-metrics

📊 Approval Rate: 85% (good pattern quality)

# Organize approved skills
> mv .claude/skills/extracted/testing-patterns.md .claude/skills/testing/
```

## End

Present pending suggestions and begin interactive review process.
