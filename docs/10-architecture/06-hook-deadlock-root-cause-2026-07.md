# Hook Deadlock Root Cause & Fix — TASK-106 / C-6 (2026-07)

**Diátaxis mode:** Explanation

**Status:** Fixed in this repo (`claude-copilot`) on 2026-07-12. Rollout to consumer repos is a separate, staged effort — see [Rollout Readiness](#rollout-readiness) at the end of this document. Do not widen `PreToolUse` matchers in other repos until that section's conditions hold.

---

## Summary

`claude-copilot`'s "mechanical delegation enforcement" was never actually enforcing anything on `Read`, `Edit`, or `Agent` from 2026-04-22 through 2026-07-12. The `PreToolUse` hook matcher shipped as `Bash|Read|Edit|Agent` in commit `20097d9` and was narrowed to `Bash`-only in commit `23c02c0` **four hours later, the same day**, under the label "resolve hook deadlock." It stayed `Bash`-only for over two months. This document identifies the actual deadlock mechanism (confirmed empirically, not just theorized), the fix, and the proof.

## Root Cause

**Confirmed hypothesis: shared `session_id` between a main session and its subagents, with no signal the original hook logic used to tell them apart, combined with framework agents having no escape hatch to satisfy the resulting deny.**

Claude Code's `PreToolUse` hook payload includes `session_id`, but **a subagent spawned via the `Agent`/`Task` tool shares the exact same `session_id` as the session that spawned it.** The only field that distinguishes "this call originated inside a subagent" is `agent_type` / `agent_id`, both non-empty only for sidechain calls.

This was confirmed two ways:

1. **Static analysis** of the installed Claude Code binary (`/Users/pabs/.local/bin/claude`, a compiled Bun binary). The PreToolUse hook-input constructor (`Iwt`) builds its payload via a shared helper (`wf`):
   ```js
   function wf(e,t,r){
     let n=t??xt(), o=r?.agentType??MB(), ...
     return { session_id:n, transcript_path:oH(n), cwd:Ct(), prompt_id:xht()??void 0,
              permission_mode:e, agent_id:r?.agentId, agent_type:o, effort:a }
   }
   ```
   `xt()` resolves to the current session's id regardless of whether that "current" context is the main session or a subagent's toolUseContext — there is no separate session_id allocated for a subagent's own PreToolUse calls. `agent_id`/`agent_type` are the only fields that vary.

2. **Live replay.** A throwaway `claude -p` session (outside this repo, in a scratch project) with a debug hook that logs every raw `PreToolUse` payload showed, verbatim:
   - Main-session `Read` calls: `{"session_id":"0937fb09-...","tool_name":"Read",...}` — no `agent_type` key at all.
   - The *same* session's Task-spawned subagent's `Read` calls: `{"session_id":"0937fb09-...","agent_id":"a0b7d816a721ff778","agent_type":"general-purpose","tool_name":"Read",...}` — identical `session_id`, new `agent_id`/`agent_type` fields.

### Why this deadlocks

`rule_force_delegate` in `pretool-check.sh` keys its consecutive-call streak counter (`.claude/hooks/state/streak-<session_id>.json`) **solely on `session_id`**, with no notion of `agent_type`. Sequence, pre-fix:

1. Main session issues 4 consecutive `Read` calls → streak=4 (not yet denied).
2. Main session calls `Agent` to delegate (correctly exempt from the streak — `Agent` is never tracked). Streak state is untouched: still `{lastTool: "Read", streak: 4}`.
3. The spawned subagent's **first** `Read` call arrives with the *same* `session_id`. The hook has no way to know this call came from a different "actor" — it sees `lastTool == "Read"`, increments to streak=5, and **denies** with: *"Main session has issued 5+ consecutive Read calls. Delegate to a framework agent instead."*
4. The subagent has no escape. `.claude/agents/qa.md` and `.claude/agents/me.md` both declare `tools: Read, Grep, Glob, Edit, Write, Bash` — **no `Agent`/`Task` tool**. The deny message's own instruction ("delegate to a framework agent instead") is unsatisfiable from inside a subagent. This is the literal self-sealing deadlock described in `20097d9`'s own commit message.

The same blind spot existed a second time in `rule_qa_gate`: once QA gate is active and `@agent-qa` is correctly dispatched (`Agent` + `subagent_type=="qa"` is allowed), the qa subagent's own subsequent `Read`/`Edit` calls — needed to actually verify the fix — share the gated session's `session_id` and hit the gate's "deny everything else" branch, since the gate only special-cased `TOOL_NAME=="Agent"` and specific `tc` Bash prefixes, never Read/Edit made *by* the already-dispatched subagent.

### Counterfactual proof (not just static reasoning)

The original `20097d9` script (unmodified, `git show 20097d9:.claude/hooks/pretool-check.sh`) was replayed live against the exact scenario above (main session: 4 `Read` calls, then delegates to a `general-purpose` subagent that reads 7 files sequentially). Subagent transcript (`subagents/agent-<id>.jsonl`), verbatim: <!-- claim-check: hook-deadlock-fix-verified -->

```
TOOL_USE Read readme6.txt
TOOL_RESULT is_error=True  PreToolUse:Read hook error: [...]: No stderr output
ASSISTANT: The first Read call was denied by a pre-tool hook. Let me try readme7.txt.
... (readme7-10 succeed) ...
TOOL_USE Read readme11.txt
TOOL_RESULT is_error=True  PreToolUse:Read hook error: [...]: No stderr output
ASSISTANT: The read for readme11.txt was denied by the hook. Let me try readme12.txt.
```

Two of the seven requested reads (`readme6.txt`, `readme11.txt` — the 5th consecutive `Read` in the shared streak, twice) were silently denied. The `general-purpose` built-in agent is unusually resilient and worked around it by skipping files and reporting `SUBDONE` anyway — masking the failure from the main session. A framework agent (`@agent-qa`, `@agent-me`) running under its stricter iteration/completion-promise protocol (see `.claude/agents/qa.md` `iteration.maxIterations: 12`) is far more likely to either retry the same denied call repeatedly (burning its iteration budget) or attempt the literal instruction in the deny message (call `Agent`, which isn't in its tool list, producing a second class of error) — i.e., the mechanism generalizes to a genuine stuck/degraded state for real framework agents, not just a silently-skipped file for a generalist one.

**Eliminated hypotheses:**

- **"The hook denies Read/Edit inside SUBAGENT sessions too because hooks don't run for sidechains at all."** False — confirmed empirically that project `PreToolUse` hooks DO fire for subagent tool calls (see replay payloads above). The mechanism isn't hooks-skip-subagents; it's hooks-can't-tell-subagents-apart-from-the-parent.
- **"The hook (a bash script) reads state files via tools that re-trigger PreToolUse."** False — `pretool-check.sh` reads/writes state via plain shell (`cat`, `jq`, `mv`, `mkdir`), never through the model's Read/Edit/Bash tool machinery. There is no re-entrancy path here.
- **A second, independent mechanism did contribute on 2026-04-22**: the original `settings.json` registered the hook command as `$CLAUDE_PROJECT_DIR/.claude/hooks/pretool-check.sh` (unexpanded-variable risk in the hook subprocess environment) and the script ran under bare `set -euo pipefail` with no `ERR` trap — any script crash (e.g. from that path failing to resolve) would produce a harness-visible tool-call error rather than a clean allow. `23c02c0` fixed *this* half (absolute paths, `ERR`/`PIPE` traps that `exit 0`) the same day, which is real and still in place. But it narrowed the matcher back to `Bash` rather than also fixing the shared-`session_id` blind spot above — so the fix addressed one deadlock mechanism and masked the other by turning off the tools it affected.

## The Fix

`.claude/hooks/pretool-check.sh` and `.claude/settings.json`, TASK-106/C-6:

1. **Matcher widened**: `Bash` → `Bash|Read|Edit|Agent`. `Agent` is included (not left optional) because `rule_qa_gate`'s core mechanism — blocking `@agent-me`/other dispatch while a task awaits QA — operates entirely on `TOOL_NAME=="Agent"` and was therefore *also* dead code for the entire `Bash`-only window, not just force-delegate's Read/Edit tracking.
2. **Subagent exemption in `rule_force_delegate`**: a payload carrying non-empty `agent_type` returns `0` (allow) immediately, before touching the streak state at all. Subagent tool calls neither get denied by, nor pollute, the parent session's streak.
3. **Subagent exemption in `rule_qa_gate`**: once the gate has correctly allowed a subagent to be dispatched, that subagent's own non-`Agent` tool calls (`agent_type` non-empty, `tool_name != "Agent"`) are exempt from the gate's "deny everything else" branch. The `Agent`-tool dispatch decision itself remains fully gated regardless of caller, so this doesn't weaken the "you can't start new work while QA is pending" guarantee — it only stops the gate from blocking the QA subagent's own investigation once dispatch has already been allowed. <!-- claim-check: hook-deadlock-fix-verified -->
4. **Global kill switch**: `CC_HOOK_ENFORCE=off` bypasses every rule set in the file (present and future), checked before any state is touched. This is in addition to the existing per-rule hatches (`COPILOT_FORCE_DELEGATE=off`, `COPILOT_QA_GATE=off`, `COPILOT_SAFETY=off`, `COPILOT_FREEZE=off`, `COPILOT_CAREFUL=off`).
5. **Streak-value hardening** (found while building the replay tests below, fixed alongside): a corrupted/hand-edited state file with a non-numeric `streak` value caused bash's nested-arithmetic variable dereferencing (`$((streak + 1))` treating `"not-a-number"` as `not - a - number`) to trip `set -u`'s unbound-variable abort, which **bypasses the `ERR` trap** and exits 1 instead of failing open. `rule_force_delegate` now coerces any non-numeric `streak` to `0` before the arithmetic runs.
6. **Fail-open was already correct** for ordinary script errors (the `set -uEo pipefail` + `ERR`/`PIPE` traps from `23c02c0`, plus absolute `SCRIPT_DIR` resolution) — this was verified, not re-implemented.

Streak thresholds (deny at 5 consecutive same-tool calls) are unchanged. No new dependencies.

## Proof

### Replay test suite

`tests/hooks/test-pretool-check.sh` — synthetic stdin JSON fixtures, run via `bash tests/hooks/test-pretool-check.sh`. Full pre-existing suite (37 assertions) plus 6 new TASK-106/C-6 replay scenarios (14 new assertions):

| Fixture | Verdict |
|---|---|
| Main session: 4 `Read` calls, then subagent's 1st `Read` (5th same-tool call overall, `agent_type` set) | **Allow** |
| Same, subagent's 2nd `Read` | **Allow** (exemption isn't one-time) |
| Same session, main session's next `Read` (agent_type empty) after the subagent calls | **Deny** (parent streak untouched by subagent calls — proves no cross-contamination either direction) |
| Subagent alone, 6 consecutive `Read` calls, fresh session | **Allow**, all 6 |
| QA gate active + qa subagent's own `Read` | **Allow** |
| QA gate active + qa subagent's own `Edit` | **Allow** |
| QA gate active + main session's own `Read` (control) | **Deny** (gate still active for the main session) |
| QA gate active + nested `Agent(ta)` dispatch carrying `agent_type` | **Deny** (Agent-tool gating not weakened by the subagent exemption) |
| `CC_HOOK_ENFORCE=off` with streak=4 AND QA gate pending simultaneously | **Allow** |
| Same call without the kill switch (control) | **Deny** |
| Corrupted non-numeric `streak` value in state file | **Allow** (fails open, does not crash) |

All pre-existing 37 assertions plus the 14 new ones pass (48/49 total in the file; the one failure is a pre-existing, unrelated `<50ms` performance-timing flake present before this change — see Notes). <!-- claim-check: hook-deadlock-fix-verified -->

### Live smoke test

Ran against a real, throwaway `claude -p` headless session (outside this repo — `/private/tmp/.../scratchpad/deadlock-test`, never pushed anywhere) with the actual (fixed) `pretool-check.sh` and widened matcher copied in:

- **Scenario A** (enforcement still works): main session issues 5 consecutive `Read` calls with no delegation. The 5th was denied with the expected reason (`"Main session has issued 5+ consecutive Read calls..."`), confirming the widened matcher still enforces the guardrail it's meant to.
- **Scenario B** (livelock fixed): main session reads 4 files, delegates via `Task`/`general-purpose` to a subagent that reads 7 more files sequentially (2 more than the deny threshold). The subagent completed all 7 reads with zero denials (confirmed via the subagent's own sidechain transcript and via `.claude/hooks/state/streak-<session_id>.json` ending at `streak: 4` — i.e. only the 4 main-session reads were ever counted; the 7 subagent reads never touched state). <!-- claim-check: hook-deadlock-fix-verified -->
- **Counterfactual** (same Scenario B, original unfixed `20097d9` script): 2 of the 7 subagent reads were denied (`readme6.txt`, `readme11.txt` — the 5th consecutive `Read` in the shared streak, hit twice), reproducing the exact failure this fix addresses.

## Rollout Readiness

This fix is proven **in `claude-copilot` only**. Per the owner's C-3 staging directive, before widening `PreToolUse` matchers in any consumer repo (copilot-control-tower, convoco, insights-copilot, cli-copilot, or any other of the 27 repos with `.claude/agents/` present per the `framework-enforcement-not-wired` finding): <!-- claim-check: enforcement-hook-wiring-ratio -->

1. This repo's live `.claude/settings.json` (used for the owner's real sessions) must run with the widened matcher for a full working session with no unexpected denials or false-positive blocks.
2. The consumer repo's own framework agents must be audited for `tools:` lists that omit `Agent`/`Task` (the exact condition that makes a force-delegate/qa-gate deny unsatisfiable) — if any exist, either add the escape hatch awareness to their prompts or confirm the subagent exemption in this fix covers them before enabling.
3. `CC_HOOK_ENFORCE=off` must be documented in that repo's onboarding/README as the emergency bypass, not discovered ad hoc.
4. This is explicitly **not** part of the C-6 commit — rollout is separately tracked (C-3) and staged repo-by-repo.
