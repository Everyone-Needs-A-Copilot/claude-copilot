# Codex Hook Enforcement Gap

**Diátaxis mode:** Explanation (findings and remediation options)

**Status:** Local remediation activated and verified; broader rollout remains separate
**Date:** 2026-09-07
**Component:** Codex integration — `.codex/hooks.json`, `plugins/codex-copilot/hooks/`

## Follow-up — 2026-09-07

Revised Option C was accepted: shared policy with native Codex adapters, excluding
forced delegation and retaining task-bound QA evidence. Work is tracked in
knowledge-copilot-internal PRD-2 / TASK-2–5. The user subsequently authorized
activation in this project from hash-pinned local snapshots, without an upstream
release or changes to other projects' hook enablement.

Before activation, the Codex 0.153.4 app-server reported this project's layer as
disabled for lack of project trust, with no discovered hooks. This is an
additional observed activation gap. July state-file timestamps establish stale
state, not the exact final hook execution or the original failure cause. Codex
already has an explicit QA inspection script; the missing automatic interception
must be distinguished from absence of all QA checks.

Both a generic harmless deny hook and the new shared-policy adapter passed an
isolated CLI execution canary. The candidate shared evaluator defaults to blocking
destructive-command matches; the existing Claude rules still warn. These results
did not by themselves prove desktop or consuming-project enforcement.

After activation, saved registration and trust passed harmless allow/deny probes
with CLI 0.153.4 and the desktop-bundled 0.153.3 binary. The scoped plugin is
globally disabled and enabled only here. Shared cc/tc local builds provide shell
policy evaluation and authoritative QA completion checks through the normal
machine launchers. Four dead legacy registrations were retired; agent files,
legacy scripts, and existing plugin customizations were preserved.

The activation and rollback record is
`knowledge-copilot-internal/docs/40-initiatives/01-codex-shared-enforcement/retrospectives/02-local-activation.md`.
Exact backups and execution evidence are in
`/Users/pabs/.copilot/enforcement-backup.WblNqF/`. Start a fresh project session to
load the configuration; hot reload in existing conversations is unverified.
Managed ecosystem updates may replace the local build until upstream promotion.

---

## Original investigation (historical; corrections and outcome above)

The following records the original proposal, not the current activation state.
Its exact July cessation claim was not established by the timestamp evidence.

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
