# Handoff: remaining CSE work, and a testing rethink

Written 2026-09-08. Supersedes the status sections of `11-rollout-session-handoff.md` and the "Remaining work" section of `12-cse-gap-closure-and-release-handoff.md`, both of which are now stale. Execution record: **Claude Copilot PRD-4** (34 tasks, 26 completed, 8 open). Upstream: codex-copilot PRD-9 / TASK-16 / WP-29 and PRD-11.

Read this, then the live `tc` tasks. This document is the durable specification; `tc` is the task board.

---

## 1. State, verified 2026-09-08

| Fact | Value |
|---|---|
| `main` | `0311bf4` — "merge: reconcile origin/main (776691c) into main" |
| `origin/main` | `0311bf4` — **pushed and in sync**, ahead=0 behind=0 |
| Working branch | `feat/evidence-and-verified-learning-5.15.0`, 80 uncommitted paths |
| Versions | framework 5.15.0 · cc 2.13.0 · tc 2.0.0 · `package.json` synced to 5.15.0 |
| Preserved refs | `refs/preserved/task49-bytescharged-rewrite` · `refs/heads/archive/enforcement-20260907` |

**Do not delete either preserved ref.** The first holds the owner's 76-case ADR-005 test rewrite (blob `ebf9e4aa25`, sha256 `63e12600de…`). The second holds the unreviewed enforcement overlay whose original copy was a dangling, prunable tree — a real near-loss incident. Both were dangling and were deliberately pinned.

**The 80 uncommitted paths are not all one thing.** They include another session's `cc design` work and this session's task-52/53 changes. Establish ownership before committing anything; do not `git add -A`.

---

## 2. What is done

Keep these five claims distinct; no single word covers them.

| Claim | Status |
|---|---|
| Implemented | Yes — evidence enforcement, context delivery, verified-learning wiring, installer fixes |
| Installed | Development-mode only. `cc`/`tc` shims resolve into the live repo, so "installed" cannot drift from source — but there is no immutable installed artifact either |
| Runtime-enforced | Yes for native dispatch (TASK-46 + Codex TASK-23, hash-verified, genuine `claude -p` and Codex TUI sessions). **Not** for `.claude/hooks/` enforcement on the Codex side |
| Released | No |
| Measurably effective | No. Zero live paired trials |

Substantive completions: the `tc.evidence` validator package and single completion authority in `update_task`; the Claude hook delegating its verdict to `tc task check-qa` with task-bound clearing; the optional-context instruction delivered byte-identically to six shipped surfaces; `reflect.md` finally in the distribution roster; `context` as a valid WP type; two installer roster fixes; the machine-verification decoupling (task 52).

---

## 3. Open work

### Blocked on the owner

**TASK-47 — signed release for macOS packaging.** Re-scoped: signing is load-bearing *only* for `scripts/package-cc-macos-release.sh:126,160`. It does **not** gate configuration distribution — verified: `reconciliation.py`, `project_integration.py` and `canonical_transaction.py` never import `policy`, and `reconciliation_recipes.py:2686` applies the signed binding only when `component == "codex"`. The foundation key is `~/.ssh/enac_foundation_release` (documented in `copilot-control-tower`), absent from this laptop, last used for `v5.14.16` on 2026-08-18. 75 of 100 tags verify under that anchor. Do **not** substitute a different anchor via `FOUNDATION_RELEASE_PRINCIPAL`/`FOUNDATION_RELEASE_PUBLIC_KEY` to obtain a pass; the script's header documents RC-3, a real prior regression from exactly that.

**TASK-33 — effectiveness pilot.** Needs a real human reviewer for `human_rework` and `misapplied_rules`; synthesized scores are explicitly disallowed. Six task families, two repetitions, twelve pairs, plus a necessary-clarification holdout that must be designed (the six existing families do not cover ask-vs-guess). Keep evaluation cases disjoint from learning inputs. A blocked outcome is an acceptable recorded result.

### Unblocked, ready to run

**TASK-36 — propagation.** The dependency on TASK-47 was removed on evidence. Task 52 cleared the machine-wide gate; `cc reconcile plan` for `flow` now produces a real 22-operation plan. **Nothing has been propagated — zero projects touched.**

Two corrections to the inventory the earlier handoffs carried:
- The five CSE candidates (`claude-copilot-accounting`, `claude-copilot-internal`, `cli-copilot`, `cli-copilot-internal`, `knowledge-copilot-internal`) are **manifest-declared ecosystem repositories that `cc reconcile` hard-rejects as targets.** They were never valid candidates.
- Remaining real candidates are the COPILOT set: `convoco`, `drip-copilot`, `flow`, `force-readiness-assessment`, `insights-copilot`, `pipeline-copilot`, `research-copilot`.

Hold: any dirty repo; the five without a `copilot.lock.json` (`method-copilot`, `everyone-needs-knowledge-management`, `preflight-copilot`, `sow-copilot`, `docs`); and `voice-copilot` unless its nine `owner: project` agents are proven byte-for-byte safe first. Do one project end to end and verify before touching the rest.

**TASK-50 — codex layer resolution.** Partly overtaken. Task 52 removed `source.path` from `codex-foundation` and `claude-foundation` so pinned layers resolve from their immutable mirrors. Re-verify whether anything remains. Note the owner's framing, which reverses earlier analysis: **codex is not drifting, it is evolving, and its direction is where the ecosystem is going.** Codex's difference from `v0.7.0` is the pin being stale, not codex being wrong. The lifecycle is: codex evolves → cut a signed codex release → bump the pin. Never freeze or revert codex to make a check pass.

**TASK-53 / TASK-54 — a regression this session introduced, not pre-existing.** Removing the literal `source.path` broke code that assumed it. TASK-53 fixed `conformance/root_causes.py` by falling back to a new shared `mirror.mirror_content_root()`; 6 of 11 failures cleared, and it is **implemented but not QA-verified** (WP-95 stored, gate correctly refused). TASK-54 covers the remaining 5 failures from a **third** copy of the same assumption in `conformance/stack.py` — specified but **not implemented**; its agent was killed mid-run. Reuse the shared helper; do not write a fourth implementation.

**TASK-49** — implement ADR-005 `bytesCharged` metering in `.claude/hooks/pretool-check.sh`. The owner's parked 76-case suite is its specification. **TASK-51** — stale `REFERENCE_COMMANDS` fixture, 3 failures, same family as TASK-45.

### Owner action, no task

The credential incident remains **unremediated**: live Claude Code OAuth access and refresh tokens were printed in cleartext into a session transcript via `security find-generic-password -g`. Rotate through the provider. Never run that command.

---

## 4. The pattern behind most of this session's bugs

Nine distinct bugs traced to **the same root cause: duplicated knowledge that diverged when one copy changed and the others did not.**

- Four independent enumerations of the distributable command set (TASK-45; two still open)
- Two independent reconcile allowlists (TASK-43, TASK-44)
- Three independent layer-source-path resolvers (TASK-52, 53, 54)

Each surfaced only when something upstream moved. Each was found by a rejected rehearsal, a real install, or a config change — **never by the test suite.** `VERSION.json`'s rosters are the declared source of truth and `canonical_transaction.claude_reference_roster()` already reads them; every duplicate should collapse onto that, and where it genuinely cannot, a divergence test should fail when two copies disagree.

---

## 5. The testing rethink — a hypothesis, explicitly not a conclusion

The suite is ~3,000 tests in `cc` plus 585 in `tc`. It dominates runtime and it caught none of the nine bugs above.

### The hypothesis

**This system's failures are relational, not computational.** A unit test asks whether a function computes the right value; almost nothing here breaks that way. What breaks is two places disagreeing: four rosters, two allowlists, three resolvers, `package.json` vs `VERSION.json`, a pinned tag vs a live checkout, installed `tc` vs its source, a claude-only request depending on codex state. So organize tests around invariants and relations rather than modules.

Sketched tiers: **invariants** (single-source, cross-implementation agreement, declared-equals-actual, import direction, component coupling — fast, no I/O); **contract tests** on real seams (QA predicate, reconcile transaction, evidence validator); **one real install** into a disposable project; and **quarantined** machine-dependent tests (`/Volumes/Dev`, mirror state, `classification.toml`) kept out of the default run.

### Why you should not act on this yet

The hypothesis is fitted to one session and has serious holes, stated plainly:

1. **Selection bias.** Only bugs that *escaped* the suite were observed. "The bugs that got through weren't caught by unit tests" is close to a tautology and is not evidence that unit tests are low-value here.
2. **Unrepresentative sample.** This initiative was overwhelmingly installation, distribution and roster plumbing — exactly where relational bugs dominate. Work inside the evidence parser or substance gate would likely have surfaced computational bugs instead.
3. **Nothing was measured.** Where the 3,000 tests live, what they cover, their real runtime and failure rate — all unknown. The architecture was proposed from a narrative, not data.
4. **The exemplar has a known defect.** TASK-44's divergence test — the evidence that this shape works — was flagged by QA for a fixed probe list that misses length and extension mutations. Invariant tests can also go tautological (asserting X derives from Y by reading Y).
5. **Quarantining is how suites rot.** Moving failures to opt-in is the standard mechanism by which a suite stops being trusted. The proposal risks prescribing the disease.
6. **Probably not uniform waste.** Much of the 3,000 is likely `cc`'s ecosystem code — reconciliation, workspaces, materialization — which is genuinely complex stateful transaction logic and may deserve heavy testing. `tc`'s 585 pass reliably over a smaller surface and may be fine as-is.

### The measurement that would settle it

Before designing anything: sample bug-fix commits from the repo's history, classify each by failure class, and check whether a test existed that could have caught it. That converts one session's anecdote into evidence, and will either confirm the relational pattern dominates or show it was an artifact of what this session happened to touch. Pair it with a map of where tests actually live and what they cost.

**Do the measurement first. Do not rewrite the suite on the strength of section 5's hypothesis.**

### A related tension worth resolving

The test-integrity rule — never weaken a test to make a feature pass — is correct and caught real problems. But it fired twice on tests encoding a *superseded* contract, where updating them was the right answer, and each became an owner-authorization event. Consider sharpening it to distinguish *weakening* a test from *updating a test whose contract legitimately changed*, the latter requiring the new contract to be stated explicitly.

---

## 6. Working notes for whoever picks this up

- `tc` is 2.0.0 with a new completion contract. Register `tc task contract <id> --file <f> --json` (schemaVersion 2, criteria with ids, project-relative sources), then `tc task evidence-identity <id>` **before** running checks, then store a `test` WP, then `tc task check-qa`, then complete. Identity capture refuses without a contract. Tasks 33, 36 and 47 already have contracts registered.
- Source paths in a contract must be canonical, project-relative, no trailing slash, and must not traverse a symlink or leave the repo. Cross-repo paths (e.g. copilot-bench fixtures) cannot be cited as sources — name them in the evidence packet instead.
- Removing a dependency is not enough to unblock a task: TASK-36's *contract* separately re-gated it through a criterion. Check both.
- Machine config backup from task 52: `copilot.layers.yml` sha256 `933fd79e…` before, `39dde75c…` after. Backup in the session scratchpad; re-copy somewhere durable if it still matters.
- A peer session (`job-finder-86`) has been editing this tree throughout. Verify ownership of uncommitted files before acting on them.
