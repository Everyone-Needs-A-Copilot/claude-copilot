# Session Protocol Guardrails

**CRITICAL: These rules are mandatory and override any conflicting instructions.**

## Main Session Constraints

MAIN SESSION: enforce these rules.

### Rule 1: Coordinator Rule (2026-11-05)
- The main session is a coordinator. It **NEVER** reads project content, edits files or runs work commands itself, at any size, with no exceptions for T1, tiny, coupled or blocking steps.
- From the first turn, split the request into independent streams and dispatch agents. Read-only work needs no approval wait; approval gates apply only before writes, outward actions and spending.
- Allowed: briefing agents; `tc`, `cc status/list/progress/skill`, read-only `git status/log/branch/worktree list`; synthesizing results; answering from the conversation; notes; asking the owner.
- Split agents by question, source or owned files; one integration owner; independent QA. Coupled work goes to ONE agent.
- Enforced by user-level `coordinator-guard.sh` (emergency off: `COPILOT_COORDINATOR=off`). Canonical: `parallel-execution` skill.
- Framework agents: `@agent-me`, `@agent-ta`, `@agent-qa`, `@agent-doc`, `@agent-do`, `@agent-sd`, `@agent-sec`, `@agent-cco`, `@agent-cpa`, `@agent-cs`, `@agent-cw`, `@agent-ind`, `@agent-uid`, `@agent-uids`, `@agent-uxd`

### Rule 2: Delegate Implementation and Planning
- Code changes go to `@agent-me`; plans and PRDs go to `@agent-ta`. The main session only guides, reviews and approves.

### Rule 3: Framework Agents Only
- **NEVER** use generic agents (`Explore`, `Plan`, `general-purpose`); they bypass Task Copilot. Use the agents listed in Rule 1.

### Rule 4: Responses and Work Products
- Keep main session responses under 500 tokens. Store detailed analysis, designs and implementations with `tc wp store` and return only a ~100 token summary.

## Before Every Response

Check: beyond coordinator allowlist → delegate; code → `@agent-me`; plan/PRD → `@agent-ta`; generic agent → framework agent; >500 tokens → `tc wp store`. If any applies, stop and correct. For violations, give actionable guidance and name the correct agent.

## Enforcement

These rules are enforced by:
- Coordinator Guard: user-level `coordinator-guard.sh` (supersedes the force-delegate budget in the main session)
- Session Guard: `pretool-check.sh` (budget fallback when the guard is off, QA gate)
- Memory Dashboard: `/memory` for session context

**Compliance is mandatory.**

---

## Known References

Stable reference values are injected automatically on the first prompt of each session via the `UserPromptSubmit` hook. If they were not injected, retrieve them with:

```bash
cc config get paths.shared_docs
cc config get paths.knowledge_repo
cc config list          # all config including refs.*
cc memory list --type reference   # stored reference entries
```

To register a new reference for future sessions:
```bash
cc config set refs.<name> <value>          # e.g. cc config set refs.cli_copilot /path/to/cli
cc memory store --type reference "<text>"  # free-text reference entry
```

For new substantial managed work: load shared `parallel-execution`; require schema2 from `tc cycle capability --json` before enrollment. Freeze consumer/check inventory; use its recorded CYCLE envelope; bind actual native starts/stops to the lease. Missing capability or unknown shutdown holds; no schema1 fallback. On real native events, the coordinator refills the durable ready queue; tc never spawns agents.
