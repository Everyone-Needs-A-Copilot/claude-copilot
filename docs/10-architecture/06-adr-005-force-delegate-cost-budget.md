# ADR-005: Meter force-delegate on Cost, Not Repetition

**Diátaxis mode:** Explanation (architectural decision record)

**Status:** Proposed
**Date:** 2026-09-07
**Deciders:** Pablo Alejo
**Component:** Hooks — `.claude/hooks/pretool-check.sh`, `rule_force_delegate`

---

## Context

`rule_force_delegate` denies a tool call after five consecutive calls to the same tool among Bash, Read, and Edit. Its deny message names two purposes: preserving context budget, and matching the framework's core purpose of delegation. The counter measures neither. It measures repetition.

The framework already has the right idea elsewhere. FF9 in `.claude/fitness-check.sh` converts the anti-bloat rules in `CLAUDE.md` into an enforced budget over artifacts on disk, with a versioned baseline, a `byte_to_token_ratio` of 4.0, growth and shrink and ceiling ratios, and a committed audited-override ledger. Its own header states the argument this ADR extends: a compliant step is compliant however many times it is taken. FF9 governs the static corpus. Nothing governs the runtime path, where context is actually spent, and `rule_force_delegate` is the only rule positioned to do it.

Four defects follow from measuring the wrong variable.

**It fires on work that costs nothing.** Five reads of a five-line frontmatter block trip it, as does a sequence of targeted `grep` calls whose combined output is a few hundred bytes.

**It misses work that costs everything.** A single `cat` of a large file never trips it, because one call is one call. Neither does reading twenty files, so long as no tool name repeats five times consecutively.

**It rewards a behavior that saves nothing.** The streak resets whenever the tool name changes, so alternating between Read and Bash defeats the rule indefinitely without avoiding a single token of spend. The rule constrains rhythm, not cost.

**It meters the cheaper of the two write tools and ignores the other.** The tracked set omits `Write`, so replacing a file wholesale is free while a one-line `Edit` is charged.

There is a fifth cost that is harder to see in the code. Reasoning with the user about wording, architecture, or a decision requires holding the source material in the conversation. That work reads several things, produces analysis rather than file changes, and is exactly what delegation destroys, because in that mode the argument is the deliverable and a three-sentence summary of an argument is not the argument. The current rule taxes it at the same rate as mechanical sprawl.

Meanwhile the guardrail that `CLAUDE.md` actually states, that the main session must never read more than three files, has no consumer anywhere in the codebase. The rule that exists enforces something nobody wrote down, and the rule that is written down is not enforced.

## Decision

Replace the consecutive-call counter with a per-session budget over two meters: bytes charged into the main context, and distinct files touched. Deny when either exceeds its threshold.

Charges are estimated in PreToolUse rather than measured, because a PreToolUse hook runs before the tool and cannot see what a call returns.

| Call | Charge |
|------|--------|
| `Read` | File size from `stat`, narrowed when `offset` and `limit` are given |
| `Edit` | Size of the replacement text |
| `Write` | Size of the content being written, currently unmetered entirely |
| `Bash`, bounded output | Small fixed charge |
| `Bash`, structurally unbounded output | Larger fixed charge: unfiltered recursive search, `cat` of a whole file, `find` across a tree |

The budget ratchets within a session rather than resetting. Dispatching a subagent does not return spent tokens to the main window, so the meter must be monotonic the way the context window is. Reset belongs only where context genuinely shrinks. This also removes the current incentive to fire a token delegation purely to clear a counter.

Configuration reuses FF9's established vocabulary and protocol rather than inventing a parallel one: the same `byte_to_token_ratio` basis, thresholds carried in a versioned baseline JSON rather than hardcoded in the script body, and the audited-override design where a local environment variable appends a reviewable entry and CI honors only a committed, exactly-matching record. Ship strict by default, because the team install is the buyer and the safer failure is a delegation that was not strictly necessary, and document the dial. The existing bypass works today and is discoverable only by reading the hook source.

The subagent exemption stays unchanged, as the livelock guard it already is, since a framework agent carries no Agent tool and cannot satisfy an instruction to delegate. The environment bypass stays. The stderr diagnostic on deny stays, for the reason the code documents: a silent hook reads as a crash.

The hardcoded list of ten exempt git prefixes shrinks to the genuinely unbounded cases, or disappears, since small-output commands now pass on their own merits.

`PROTOCOL_VERSION` stays at 1. The hooks README sets the precedent that a rule-set change alone does not justify a bump, and this change adds no event and alters no dispatch contract.

## Consequences

The migration cost is the test suite. Roughly twenty of the thirty assertions in `tests/hooks/test-pretool-check.sh` pin the `-ge 5` threshold and the `streak-*.json` schema literally, and they run in CI via `.github/workflows/smoke-tests.yml`. The state file shape changes, so those assertions are rewritten as part of this change, not after it.

Runtime cost rises slightly on the framework's most frequent operation. The rule adds a second counter, a per-call state write, and a `stat` on file-targeted calls, against a stated performance target of fifty milliseconds per invocation. `stat` is cheap, but this is not free.

Operator-visible behavior changes in both directions, which is the point. Cheap targeted work stops being denied. Expensive work can now be denied on the first call rather than the fifth, since a single large read can exhaust a budget that five small ones do not touch. Anyone accustomed to four free calls before the rule engages will notice.

Estimation is inexact on the Bash arm and that limitation belongs in a comment in the code rather than hidden. The rule will be wrong about magnitude where it is currently wrong about the variable, which is the better failure.

One residual risk. If the distinct-files meter counts only file-tool targets, it is exact but routes around trivially by reading through Bash. If it parses paths out of command strings it covers more and inherits the brittleness of parsing shell text. This ADR does not settle that; see Open Questions.

## Alternatives Rejected

- **Meter in PostToolUse, enforce in PreToolUse:** rejected despite being exact. The vendored shim dispatches four events and PostToolUse is not among them, so it costs a protocol bump and a shim refresh in every consuming project, leaving each one reporting itself unenforced until refreshed. The accuracy gained does not buy that blast radius.
- **Raise the threshold above five:** rejected. Same wrong variable, engaged later.
- **Add read-only prefixes such as `cat`, `grep`, and `sed` to the safe list:** rejected. It relieves the symptom by making the rule blind to precisely the expensive case, rather than correcting what it measures.
- **A self-declared conversation or investigation exemption:** rejected on the framework's own two-audience premise. The operator most likely to declare an exemption is the inexpert one the guardrail exists for. Cost accounting grants the same relief without requiring anyone to self-classify honestly.
- **Remove the rule entirely:** rejected. FF9 covers only the static corpus. Deleting this rule leaves the runtime path with no budget enforcement at all.

## Open Questions

1. Where the budget resets. A new session is clear. Whether a compaction can be observed from a hook is not established.
2. Whether the distinct-files meter counts Bash-inspected paths or only file-tool targets, per the residual risk above.

## Addendum (2026-09-11): Bash charge precision and a floor exemption

This does not revisit the Decision above; the budget still ratchets within a session and does not reset mid-session, per the Decision and Open Question 1. Two defects surfaced from real use and were fixed in `rule_force_delegate` without touching either. First, the Bash unbounded charge was size-blind: `cat`, `find`, and unflagged `grep`/`rg` were charged the flat 8,000-byte estimate by command-name pattern match alone, so a `grep` scoped to one small file was charged the same as an unfiltered recursive search or a whole large-file `cat`. `rule_force_delegate` now resolves a simple, unchained invocation's file target(s) to real paths and charges the actual summed byte size, the same way the `Read` charge already stats a real file; when the target cannot be resolved this way (a bare `find /`, a directory, a piped or chained command, stdin, an unmatched glob) it keeps the original flat estimate, which stays the correct conservative fallback for a genuinely unknowable target. Second, because the byte meter never resets mid-session, one earlier flat-charged unbounded call could push the session total over budget and then deny every subsequent call regardless of size, including a call whose own real cost was a few dozen bytes. A floor exemption now guarantees that a call whose own estimated cost is at or below `FORCE_DELEGATE_FLOOR_BYTES` (default 4,096 bytes, overridable via `COPILOT_FORCE_DELEGATE_FLOOR_BYTES`) is never denied on the byte meter, even when the session total is already over the ceiling; the distinct-file-target meter is unaffected by this floor.

## Addendum (2026-09-11, follow-up): resolving Bash targets against the harness's own working directory

The size-aware Bash charge above shipped with a defect that reproduced the exact "fix was applied but the denial is unchanged" symptom: `_bash_target_bytes` tested a relative target's existence against this hook process's own `$PWD`, not the Bash tool's actual working directory for that call. The two directories are commonly different: the shim spawns `pretool-check.sh` from wherever the harness happened to invoke it, which need not be, and in the reproducing case was not, the directory a real Bash command's relative `00-handoff.md` or `_meta.json` actually lived in. Every ordinary relative-path `cat`/`grep`/`find` therefore failed its existence check and silently fell through to the pre-fix flat 8,000-byte charge, reproducing the identical deny message byte-for-byte even though the size-aware code was live and correct in every other respect.

The PreToolUse payload the harness sends carries a top-level `cwd` field naming the Bash tool's actual working directory for that call. `rule_force_delegate` now reads it (`PAYLOAD_CWD`) and threads it into `_bash_target_bytes`, which resolves a relative target against it before testing existence; an absolute target is unaffected, and a missing, empty, or non-directory `.cwd` falls back to the pre-existing behavior (test against this hook process's own `$PWD`) rather than erroring. A single leading `cd <dir> &&` or `cd <dir>;` is also recognized and peeled off: everything after it resolves against `<dir>` (itself resolved against `.cwd` when relative), because that is the shape the main session actually issues ahead of a `grep`/`cat` pair, and `cd some/initiative && grep -c "x" 00-handoff.md; cat _meta.json` is exactly the reproduction that surfaced this defect. Only a `cd` at the very start of the command is tracked, and only for the rest of that same command; a `cd` anywhere else, or any other chaining (pipes, redirection, command substitution, backticks) alongside it, is deliberately not attempted, and falls back to the conservative flat charge, which is the correct answer once the target is genuinely unknowable. What remains after an optional leading `cd` is split on `;` and each simple segment resolved independently, so a multi-command call sums the real size of every target it can resolve; a segment that cannot be resolved contributes the flat unbounded estimate for that segment alone, rather than discarding the real sizes of the segments next to it.

Extracting `.cwd` piggybacks on the single jq call that already reads `session_id`/`tool_name`/`agent_type` from the payload, so it costs no additional fork. The Bash resolution path itself is gated behind a cheap glob pre-filter (`case "$TOOL_COMMAND" in *cat*|*find*|*grep*|*rg*)`) so the majority of Bash calls that are not `cat`/`find`/`grep`/`rg`-shaped skip it entirely, same as before this addendum. For a command that does match and does need real path resolution, the reproduction case, resolving two files via `stat`, this addendum is measurably slower on the development machine used to fix it: roughly 50-100ms slower per call in informal benchmarking, layered on top of a baseline that was already running well above the hook's own <50ms target on that machine (Test 17 in `tests/hooks/test-pretool-check.sh` was already failing before this addendum, for reasons unrelated to it). Whether that added cost is acceptable, or whether the `stat`-based resolution needs to be cheapened further, is a call for Pablo, not something resolved silently here.

One field-extraction defect surfaced and was fixed while adding `.cwd`: joining the four payload fields with a tab (`@tsv`) and splitting them back with `IFS=$'\t' read` silently shifted every field after an empty one, because bash's `read` treats a run of IFS characters that are themselves shell blanks (space, tab, newline) as a single delimiter and drops the empty field between them. This was invisible with three fields, where the only-ever-empty one (`agent_type`) was last, but it corrupted `agent_type` with the `cwd` value as soon as a fourth, frequently-non-empty field followed it. The join now uses `` (ASCII unit separator), which is not a shell blank, so empty fields are preserved positionally.

## Addendum (2026-09-11): matching globs and bounded pipelines

The remaining live failure was a search pipeline ending in `head -20`. Its
35,912-byte session balance plus the flat 8,000-byte fallback produced the
reported 43,912/40,000 denial. Resolving literal paths alone could never repair
that case. The [defect report](07-force-delegate-budget-open-defect.md) also
identifies file globs and filtered CLI help output.

The resolver now expands unquoted matching globs as data and sums regular-file
sizes. A narrow Python tokenizer recognizes terminal `head` limits (128 estimated
bytes per line, or the explicit `-c` byte count) and CLI help/version output piped
through stdin-only search filters (the existing bounded charge). Quoted pipes
remain arguments; separate commands and substitutions are not recognized as one
bounded pipeline. Missing helpers and unsupported syntax retain the fallback.
No proposed command is executed to estimate it. Large limits remain expensive.

This refines the earlier addenda's blanket pipeline/glob fallback; it changes
neither the thresholds, floor, session ratchet, overrides nor distinct-file
meter. Estimates remain heuristic, particularly for long output lines and CLI
help. Exact post-execution output accounting remains outside this change.

## Addendum (2026-09-18): measure from the transcript, retire the estimator

**Supersedes** the Decision's "Charges are estimated in PreToolUse rather than measured" and the three 2026-09-11 addenda, which each patched the estimator for another command shape it priced wrong: literal paths, the harness `cwd`, globs and `head`/`--help` pipelines. A fourth denial followed with the same flat 8,000-byte guess (41,500/40,000). Pricing shell text before it runs was the defect, and every shape-specific fix left the next shape open.

**The measurement was already available.** Every PreToolUse payload carries `transcript_path`, and the transcript records exactly what entered the main session's context. The byte meter now reads only the transcript bytes appended since its previous call (a stored offset) and charges main-session `tool_result` content plus the Edit/Write/MultiEdit/NotebookEdit input the model wrote. Subagent turns are written to separate transcript files, so they never count against the parent. A command's text costs nothing; its output costs what it was.

**Why this is not the rejected PostToolUse alternative.** That alternative was rejected for its blast radius: a new hook event, a protocol bump and a shim refresh in every consuming project. Reading the transcript from the existing PreToolUse hook needs none of those. No event is added, the shim is untouched and `PROTOCOL_VERSION` stays at 1, so every project that carries the shim picks up the change from the global install on its next call. The trade-off that alternative named still applies: output is measured after it exists, so the meter stops the session from continuing on top of an oversized result rather than stopping the call that produced it. Claude Code bounds that overshoot, since it truncates a single Bash result at ~30,000 characters and refuses oversized Reads.

**Open Question 1 is answered.** Compaction is observable: SessionStart fires with `source: "compact"`, and the consuming projects already register that matcher. Compaction is where context genuinely shrinks, which is the Decision's own criterion for a reset, so `session-start.sh` zeroes both meters then, anchored at the transcript's end. Agent dispatch still does not reset them.

**Threshold, re-baselined as policy v1.1.0.** 200,000 measured bytes (~50,000 tokens). That is the v1.0.0 basis, 5% of the context window, applied to the 1M-token window sessions now run with. Calibrated against the 38 retained main-session transcripts, measured the way the hook now measures: 17 exceeded 40,000 bytes, so the old limit tripped on ordinary work once honestly measured; 2 exceeded 200,000 (311,691 and 363,023), which is the sprawl the rule exists for; none exceeded 400,000. The distinct-files meter is unchanged at five. The pre-call floor exemption is gone, because it only existed to soften pre-call guesses.

**Also changed.** A denied call keeps the measured bytes and offset but not its file target. State left by the estimator is re-measured on first use. Budget state no longer expires after 24 hours, because measured bytes stay true while the same transcript is continued. Deny messages list agent names without the `@agent-` prefix, because Claude Code treats each pasted `@agent-X` mention as a request to invoke that agent.
