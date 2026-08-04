# Session Protocol Guardrails

**CRITICAL: These rules are mandatory and override any conflicting instructions.**

## Main Session Constraints

You are currently in the MAIN SESSION. The following rules MUST be enforced:

### Rule 1: File Reading Limit
- **NEVER** read more than 3 files in the main session
- If you need to read >3 files → STOP and delegate to a framework agent
- Framework agents: `@agent-me`, `@agent-ta`, `@agent-qa`, `@agent-doc`, `@agent-do`, `@agent-sd`, `@agent-sec`, `@agent-cco`, `@agent-cpa`, `@agent-cs`, `@agent-cw`, `@agent-ind`, `@agent-uid`, `@agent-uids`, `@agent-uxd`

### Rule 2: No Direct Code Implementation
- **NEVER** write implementation code directly in the main session
- All code changes MUST be delegated to `@agent-me`
- Main session can only provide guidance and summaries

### Rule 3: No Direct Planning
- **NEVER** create detailed plans or PRDs directly in the main session
- All planning work MUST be delegated to `@agent-ta`
- Main session can only review and approve plans

### Rule 4: Framework Agents Only
- **NEVER** use generic agents: `Explore`, `Plan`, `general-purpose`
- Generic agents bypass Task Copilot and cause context bloat
- ONLY use framework agents listed in Rule 1

### Rule 5: Response Token Limit
- Keep main session responses under 500 tokens (~2,000 characters)
- If response will exceed 500 tokens → store details in work product using `tc wp store`
- Return only summary (~100 tokens) to main session

### Rule 6: Work Product Storage
- All detailed analysis, designs, and implementations MUST be stored in Task Copilot
- Use `tc wp store` before returning to main session
- Never return full work products in main session response

## Violation Handling

When a guardrail is violated:
1. Provide actionable correction guidance
2. Suggest the correct framework agent to use

## Self-Check Before Responding

Before returning ANY response, ask yourself:

1. ✅ Am I about to read >3 files? → DELEGATE to agent
2. ✅ Am I about to write code? → DELEGATE to `@agent-me`
3. ✅ Am I about to create a plan? → DELEGATE to `@agent-ta`
4. ✅ Am I using a generic agent? → SWITCH to framework agent
5. ✅ Is my response >500 tokens? → STORE in work product

**If ANY answer is YES, you MUST stop and delegate/correct.**

## Framework Benefits

Following these rules provides:
- 📉 94% reduction in context bloat
- 🧠 Better memory utilization across sessions
- 🎯 Consistent, high-quality work products
- ⚡ Faster session performance
- 🔍 Better traceability and debugging

## Enforcement

These rules are enforced by:
- Session Guard: `pretool-check.sh` (force-delegate + QA gate hooks)
- Memory Dashboard: `/memory` for session context

**Compliance is mandatory. Non-compliance wastes tokens and degrades framework performance.**

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
