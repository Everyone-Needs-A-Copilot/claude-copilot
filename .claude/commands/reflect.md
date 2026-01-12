# Reflect Command

Review and manage captured corrections from user feedback. Part of the two-stage correction workflow:
1. **Auto-capture**: Corrections detected from user messages (handled by hooks)
2. **Manual review**: User confirms via `/reflect` (this command)

## Arguments

- `--dedupe`: Consolidate similar corrections before review
- `--agent <id>`: Filter corrections for specific agent
- `--status <status>`: Filter by status (pending, approved, rejected, applied)

## Step 1: Get Correction Summary

Call the reflect_summary tool:

```
reflect_summary({ limit: 10, agentId: $ARGUMENTS.agent })
```

## Step 2: Display Summary Dashboard

Format as a clean, scannable dashboard:

```
## Corrections Dashboard

**Total Captured:** [totalCaptured]

### By Status
Pending: [count] | Approved: [count] | Rejected: [count] | Applied: [count]

### By Target
Skills: [count] | Agents: [count] | Memory: [count] | Preferences: [count]

### By Agent
[List agents with counts, or "All agents" if none filtered]
```

## Step 3: Display Pending Corrections

If there are pending corrections to review:

```
### Pending Review ([count])

---
**ID:** [shortened ID]
**Detected:** [date] | **Confidence:** [confidence]%
**Target:** [target type] → [target id or "auto-detect"]
**Agent Context:** [agentId or "none"]

**Original:** [originalContent preview, max 100 chars]
**Corrected:** [correctedContent preview, max 100 chars]

**Matched Patterns:** [list pattern types]

**Actions:**
- `/reflect approve [id]` - Accept this correction
- `/reflect reject [id] [reason]` - Reject with reason
- `/reflect modify [id]` - Edit before approving

---
[Repeat for each pending correction, max 10]
```

## Step 4: Handle Review Actions

If the command includes an action argument:

### Approve Correction

If `$ARGUMENTS` contains `approve <id>`:

```
correction_review({
  correctionId: "<id>",
  decision: "approve"
})
```

Display:
```
Approved correction [id]
Target: [target] → [targetId]
Content: [correctedContent]

This correction will be applied when you route it to the appropriate target.
Use `correction_mark_applied` after making changes.
```

### Reject Correction

If `$ARGUMENTS` contains `reject <id> [reason]`:

```
correction_review({
  correctionId: "<id>",
  decision: "reject",
  rejectionReason: "[reason or 'User rejected']"
})
```

Display:
```
Rejected correction [id]
Reason: [reason]

This correction has been marked as a false positive and won't be shown again.
```

### Modify Correction

If `$ARGUMENTS` contains `modify <id>`:

Ask the user to provide the modified content, then:

```
correction_review({
  correctionId: "<id>",
  decision: "modify",
  modifiedContent: "[user's modified content]"
})
```

## Step 5: Handle --dedupe Flag

If `$ARGUMENTS` contains `--dedupe`:

1. Get all pending corrections
2. Group by similar `correctedContent` (fuzzy match)
3. For each group with >1 item:
   - Keep the highest confidence correction
   - Auto-reject others with reason "Consolidated with [kept-id]"
4. Report consolidation results

```
### Deduplication Results

Consolidated [count] similar corrections:
- Kept [id1] (confidence: 95%), rejected 2 similar
- Kept [id2] (confidence: 87%), rejected 1 similar

Remaining pending: [new count]
```

## Step 6: Recently Applied Corrections

Show recently applied corrections for reference:

```
### Recently Applied

| Date       | Target    | Content Preview                    |
|------------|-----------|-------------------------------------|
| 2025-01-15 | agent:me  | Always use const instead of let... |
| 2025-01-14 | skill:ts  | Prefer type over interface for...  |

[If none: "No corrections applied yet"]
```

## Edge Cases

### No Corrections

If `reflect_summary` returns empty:

```
## Corrections Dashboard

No corrections captured yet.

Corrections are automatically detected when you provide feedback like:
- "Actually, use X instead of Y"
- "No, that's wrong..."
- "I prefer X over Y"
- "Correction: ..."

These corrections help Claude learn your preferences over time.
```

### Expired Corrections

If corrections have expired (> 7 days without review):

```
**Note:** [count] corrections expired without review.
Consider reviewing pending corrections more frequently.
```

### High False Positive Rate

If rejection rate > 30%:

```
**Note:** High false positive rate detected ([rate]%).
The detection patterns may need tuning for your workflow.
```

## Step 7: Explain Two-Stage Workflow

Include this explanation at the end of the first `/reflect` run:

```
---

## How Corrections Work

1. **Auto-Capture**: When you correct Claude ("Actually, use X instead"),
   the correction is detected and stored for review.

2. **Review** (this command): Review captured corrections before they're applied.
   - **Approve**: Mark as valid correction
   - **Reject**: Mark as false positive (won't be suggested again)
   - **Modify**: Edit the correction before approving

3. **Apply**: Approved corrections are routed to the appropriate target:
   - **Skill**: Updates skill file with new pattern
   - **Agent**: Stores as agent improvement suggestion
   - **Memory**: Stores as lesson or decision
   - **Preference**: Stores as user preference

Run `/reflect` regularly to review captured corrections and help Claude learn.
```

## Example Full Output

```
## Corrections Dashboard

**Total Captured:** 12

### By Status
Pending: 3 | Approved: 5 | Rejected: 2 | Applied: 2

### By Target
Skills: 4 | Agents: 3 | Memory: 3 | Preferences: 2

### By Agent
me: 5 | ta: 3 | qa: 2 | all: 2

### Pending Review (3)

---
**ID:** corr-abc123
**Detected:** 2025-01-15 | **Confidence:** 92%
**Target:** preference → auto-detect
**Agent Context:** me

**Original:** Using var for loop variables
**Corrected:** Use const with forEach or for...of instead of var

**Matched Patterns:** replacement, preference

**Actions:**
- `/reflect approve corr-abc123`
- `/reflect reject corr-abc123 [reason]`
- `/reflect modify corr-abc123`

---
**ID:** corr-def456
**Detected:** 2025-01-14 | **Confidence:** 85%
**Target:** skill → typescript
**Agent Context:** me

**Original:** interface Props { ... }
**Corrected:** type Props = { ... }

**Matched Patterns:** style_preference

**Actions:**
- `/reflect approve corr-def456`
- `/reflect reject corr-def456 [reason]`
- `/reflect modify corr-def456`

---

### Recently Applied

| Date       | Target    | Content Preview                    |
|------------|-----------|-------------------------------------|
| 2025-01-13 | agent:me  | Always use const instead of let... |
| 2025-01-12 | memory    | Prefer explicit error handling...  |

---

## How Corrections Work

[Explanation from Step 7]
```

## End

Present the dashboard and ask: "Would you like to approve, reject, or modify any of these corrections?"
