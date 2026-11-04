---
name: orchestrate
description: Deprecated compatibility redirect; parallel execution is built into protocol
alwaysAllow: true
---

# Orchestrate — deprecated

Parallel execution is part of `/protocol`; no separate orchestration workflow is required. Retain this entrypoint for old prompts and references, without creating another task board or a second approval gate.

Resolve `cc skill get parallel-execution --scope machine --json` once and apply its canonical policy. Follow `.claude/commands/protocol.md` using the existing scoped plan/cycle. If the skill is unavailable, report that fallback and follow the protocol's guarded `tc cycle` contract.

| Legacy request | Protocol action |
|---|---|
| no argument / `generate` | Frame the requested outcome and establish its scoped plan; reuse existing approval. |
| `start` | Validate the cycle, claim useful ready scopes, and actually dispatch native agents within resource/runtime limits. |
| `status` | Read `tc cycle status CYCLE --json` and summarize running, queued, blocked, integrated, accepted and held work. |
| `merge` | Route completed contributions to the single integration owner, then current independent verification and resource disposition. |

Do not print launch instructions as if work had started. Do not wait for unrelated streams to merge before dispatching a contract-ready consumer. Builders do not push. A clean merge alone never proves a worktree disposable. Prepare candidates with `tc cycle cleanup-plan CYCLE --json`, then `tc cycle cleanup CYCLE --json` automatically removes only receipt-matched fully integrated clean inactive worktrees after identity, teardown, stopped-agent, consumer and recovery checks. Preserve branches and uncertain resources; branch/other deletion retains exact approval.
