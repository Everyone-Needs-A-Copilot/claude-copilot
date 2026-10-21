---
name: cleanup
description: Consolidate useful project history, apply lessons and remove approved repository clutter while preserving software, fixtures, original authority and recoverability. Use for cleanup or lifecycle checkpoints.
---

# Clean up project work

Read and apply [Work lifecycle](../../agents/_shared/work-lifecycle.md), the canonical procedure and compact record template. Use its finish/cleanup sequence for accumulated clutter, or only the relevant checkpoint for ordinary work. Resolve this reference relative to this installed skill, not a machine-specific source checkout.

Work in the existing task and maintained narrative. Preserve original authority and required assets, measure actual net reduction, and obtain exact destructive approval after recovery preparation. Report retained, consolidated, actually removed and held material distinctly; no archive, summary or inventory alone completes cleanup. Route substantial implementation to the appropriate specialist and independent QA under existing task gates.

## Validation Checklist

- Resolve current task authority and source state before trusting a summary.
- Check retained assets, recovery evidence and exact approval before removal.
- Verify net reduction and report unresolved holds using the canonical template.

With the existing task ID in `TASK_ID`, inspect its live record first:

```bash
tc task get "$TASK_ID" --json
```
