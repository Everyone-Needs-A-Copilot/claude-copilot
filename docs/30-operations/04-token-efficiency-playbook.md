# Token Efficiency Playbook

Practical rules to keep token usage low without losing rigor.

---

## Principles

- Prefer low-effort models for routine work.
- Keep the main session concise; store details in work products.
- Budget tokens per stream to avoid runaway context.
- Summarize before pausing or escalating.

---

## Fast Wins

- Use `eco:` or `fast:` on `/protocol` for routine changes.
- Keep responses under ~500 tokens in the main session.
- Store large outputs in work products instead of chat.

---

## Stream Budgets

Set a stream-level budget in task metadata:

```json
{
  "streamId": "Stream-A",
  "streamTokenBudget": 2500
}
```

Behavior:
- Work product storage is blocked if the stream exceeds its budget.
- `stream_list()` and `stream_get()` show `tokenUsage` and `tokenBudget`.
- Progress HUD can show `~usage/budget tokens` when provided.

---

## Ecomode Controls

Global routing thresholds can be tuned per repo:

```
ECOMODE_THRESHOLD_LOW=0.25
ECOMODE_THRESHOLD_MEDIUM=0.65
```

Guidance:
- Lower thresholds push more tasks to Haiku/Sonnet.
- Keep `low < medium`.

---

## Compaction Discipline

When a stream stalls or blocks:
- Provide a short summary and next action.
- Avoid repeating full context; link to work products.
- Use checkpoints for continuity and compaction.

---

## Recommended Defaults

- Stream token budgets: 2k to 4k tokens per stream
- `progress_summary()` for ~200 token status updates
- Work product summaries for long outputs

---

## References

- Ecomode: `docs/50-features/ecomode.md`
- Orchestration workflow: `docs/50-features/02-orchestration-workflow.md`
- Progress HUD: `docs/50-features/progress-hud.md`
- Working protocol: `docs/30-operations/01-working-protocol.md`
