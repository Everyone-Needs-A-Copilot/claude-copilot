# Codex Hook Enforcement Gap

**Diátaxis mode:** Explanation (findings and remediation options)

**Status:** Open — needs review and a decision
**Date:** 2026-09-07
**Component:** Codex integration — `.codex/hooks.json`, `plugins/codex-copilot/hooks/`

---

## Summary

Framework hook enforcement stopped running under Codex on 2026-07-13 and has not run since. The `plugins/codex-copilot/` hooks that were built afterwards are a different, smaller feature set and do not replace it. The practical consequence is that Codex sessions in this repo currently have no destructive-command guard, no QA gate, and no force-delegate rule, while Claude Code sessions in the same repo have all three.

This document records how that was established, why it broke, and the options for closing it. Nothing has been changed. The remediation decision is open.

## Do not do these things

Two safe-looking actions would cause damage, and both were considered and rejected during the investigation.

**Do not delete `.codex/` in any repo.** Nine repos on this machine carry a `.codex/` directory and in seven of them it holds only `agents/`, which is live, in-daily-use Codex configuration. The directories are excluded from git through `.git/info/exclude`, so deletion is unrecoverable. Convoco additionally has a working `hooks.json` driving Discord notifications that is unrelated to framework enforcement.

**Do not simply repoint the dead absolute paths.** That revives a stale fork rather than fixing the cause. See Option A below.

## Evidence

The registration in `claude-copilot/.codex/hooks.json` names four framework hooks: `PreToolUse` matching `Bash|Read|Edit|Agent`, `SessionStart`, `UserPromptSubmit`, and `SubagentStop` matching `me|qa`. Every one of its command paths is absolute and rooted at `/Users/pabs/Sites/COPILOT/claude-copilot/`, which ceased to exist when the framework repos moved to `/Users/pabs/Sites/CSE/` in August 2026.

The hooks stopped earlier than that move. The suite's own state file is the record:

```
.codex/hooks/state/session-turns.json    last written 2026-07-13
```

Nothing under that state directory has been written since. The August root move made a already-inert registration additionally unresolvable.

Convoco is the control case. Its `.codex/hooks.json` uses paths relative to the project root, so the root move never affected it, and it still works. The claude-copilot file is the only one on the machine that hardcoded an absolute root.

To reproduce:

```bash
cd /Users/pabs/Sites/CSE/claude-copilot
grep -o '/[^"]*/\.codex/hooks/[a-z-]*\.sh' .codex/hooks.json | while read -r p; do [ -e "$p" ] || echo "DEAD: $p"; done
ls -lt .codex/hooks/state
```

## What the plugin does and does not cover

`plugins/codex-copilot/hooks/` was added after the July suite went inert. It resolves its paths through `PLUGIN_ROOT` / `CLAUDE_PLUGIN_ROOT` rather than hardcoding them, which is the correct pattern. But it implements different behavior, not the same behavior by another route.

| Capability | July `.codex/` suite | `plugins/codex-copilot/` |
|---|---|---|
| `rule_destructive_command` (`/careful`) | Present, backed by 6 rules in its own `security-rules.json` | **Absent — no `security-rules.json` at all** |
| `rule_qa_gate` | Present | Absent |
| `rule_force_delegate` | Present | Absent |
| `rule_path_scope` (`/freeze`) | Present | Absent |
| SessionStart injection | Present | Absent |
| Protocol injection on prompt | Via `user-prompt-submit.sh` | `user-prompt-protocol.sh` |
| Debug circuit breaker | Absent | Present, on Bash pre and post |
| Subagent return contract | Via `subagent-stop.sh` | `subagent-return-contract.sh` |

The destructive-command row is the one that matters most. Codex has run without a shell-command safety guard in this repo since July.

Note also that the July suite is itself behind. It carries four rule sets where the current `.claude/hooks/pretool-check.sh` carries six, having since gained `rule_journey_dispatch` and `rule_extension_resolution`.

| File | Lines |
|---|---|
| `.codex/hooks/pretool-check.sh` (July fork) | 648 |
| `.claude/hooks/pretool-check.sh` (current) | 950 |

## Options

**Option A — Repoint the absolute paths.** Change the four commands in `.codex/hooks.json` to relative paths, matching the convoco pattern. Restores enforcement immediately and is a small change. The cost is that it revives a fork roughly three hundred lines behind current, with a second `security-rules.json` that must be maintained separately and will silently drift again. This is the change that looks obvious and is the reason this document exists.

**Option B — Retire the registration, rely on the plugin.** Neutralize the dead file and accept `plugins/codex-copilot/` as the Codex story. Nothing regresses relative to today, since the hooks already do not run. But the coverage table above shows this permanently accepts the loss of the destructive-command guard and the other three rule sets, which is a real safety position and should be taken deliberately if taken at all.

**Option C — Point Codex at the same global rules Claude Code uses.** Replace the vendored `.codex/hooks/` invocation with a shim that resolves the global framework install and delegates to it, exactly as `.claude/hooks/copilot-hook.sh` already does. One rule set, one `security-rules.json`, one place to fix a guardrail. This is the architecture the shim was designed for, stated in its own header: vendor a shim, keep rules global, so that fixing a guardrail fixes it in every project that carries the shim.

## Recommendation

**Option C, with Option A as a stopgap only if the safety gap must close before C is ready.**

Option A recreates the divergence that caused this failure. Option B leaves Codex permanently less guarded than Claude Code in the same repo, on the same machine, for the same user. Option C is the only one that ends the class of problem rather than the instance, and the machinery for it already exists and is proven in the Claude Code path.

## What needs verifying before Option C can be built

These are the open unknowns. They are the reason this is a proposal rather than a change.

1. **Payload compatibility.** `pretool-check.sh` reads `session_id`, `tool_name`, `agent_type`, and `tool_input.command` from a JSON object on stdin, and the shim's fail-closed branch keys on `tool_name == "Bash"`. Whether Codex supplies the same field names and shape is unknown and decides whether the shim can be reused as-is or needs a translation layer.
2. **Exit-code contract.** The rules signal deny with exit 2 plus a `permissionDecision` JSON on stdout. Whether Codex honors that same contract, or expects a different signal, needs confirming.
3. **Event-name mapping.** The shim dispatches `session-start`, `pretool-check`, `subagent-stop`, and `user-prompt-submit`. Codex's event names may not map one-to-one, and `SubagentStart` in the plugin config suggests at least one that Claude Code does not have.
4. **Whether the plugin and a shim can coexist.** If both register a `PreToolUse` hook on Bash, the interaction between the debug circuit breaker and the destructive-command guard needs to be defined rather than discovered.
5. **Scope beyond this repo.** Only claude-copilot registers framework hooks under Codex today. Whether the other repos should also get enforcement is a separate product decision, not a bug fix.
