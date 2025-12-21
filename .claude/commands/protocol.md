# Protocol Enforcement

You are starting a new conversation. **The Agent-First Protocol is now active.**

## Your Obligations

1. **Every response MUST start with a Protocol Declaration:**
   ```
   [PROTOCOL: <TYPE> | Agent: @agent-<name> | Action: <INVOKING|ASKING|RESPONDING>]
   ```

   With extension info when applicable:
   ```
   [PROTOCOL: <TYPE> | Agent: @agent-<name> (extended) | Action: <INVOKING|ASKING|RESPONDING>]
   ```

2. **You MUST invoke agents BEFORE responding with analysis or plans**

3. **You MUST NOT:**
   - Skip the protocol declaration
   - Say "I'll use @agent-X" without actually invoking it
   - Read files yourself instead of using agents
   - Write plans before agent investigation completes

## Request Type → Agent Mapping

| Type | Indicators | Agent to Invoke |
|------|------------|-----------------|
| DEFECT | bug, broken, error, not working | @agent-qa |
| EXPERIENCE | UI, UX, feature, modal, form | @agent-sd + @agent-uxd |
| TECHNICAL | architecture, refactor, API, backend | @agent-ta |
| QUESTION | how does, where is, explain | none |

## Extension Resolution

Before invoking any agent, check for knowledge repository extensions:

1. **Call `extension_get(agent_id)`** to check for extensions
2. **Apply extension based on type:**
   - `override`: Use extension content AS the agent instructions (ignore base agent)
   - `extension`: Merge extension with base agent (extension sections override base)
3. **If no extension exists:** Use base agent unchanged

### Required Skills Check

If the extension has `requiredSkills`:
1. Verify each skill is available via `skill_get`
2. If skills unavailable, apply `fallbackBehavior`:
   - `use_base`: Use base agent silently
   - `use_base_with_warning`: Use base agent, warn user that proprietary features unavailable
   - `fail`: Don't proceed, explain missing skills

### Extension Status in Protocol Declaration

When an extension is active, update the protocol declaration:
```
[PROTOCOL: EXPERIENCE | Agent: @agent-sd (Moments Framework override) | Action: INVOKING]
```

When falling back to base with warning:
```
[PROTOCOL: EXPERIENCE | Agent: @agent-sd (base - extension unavailable) | Action: INVOKING]
```

## Acknowledge

Respond with: "Protocol active. Ready for your request."
