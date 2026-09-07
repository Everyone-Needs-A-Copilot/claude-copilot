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
