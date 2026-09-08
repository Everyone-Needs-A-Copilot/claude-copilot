# Rollout session handoff — evidence and verified learning

Written 7 September 2026 by the Claude Code session that executed `codex-copilot/docs/40-initiatives/04-evidence-and-verified-learning/claude-code-handoff.md`. Local rollout record: **PRD-4** in this repo's `tc` database. Upstream record: codex-copilot PRD-9 / TASK-16 / WP-29.

This file is deliberately left **untracked** so it cannot collide with the concurrent session described below. Commit it, move it, or delete it as you see fit.

---

## 1. Concurrent session in this working tree — read this first

Partway through staging the candidate, this tree gained files this session did not author: a `cc design` feature from another session working in the same directory.

**Paths that belong to that other session, all still uncommitted and unmodified by me:**

| Path | State |
|---|---|
| `tools/cc/src/cc/commands/design.py` | new, untracked |
| `tools/cc/src/cc/core/design/` | new, untracked |
| `docs/30-operations/10-design-quality.md` | new, untracked |
| `.claude/agents/uid.md` | modified |
| `tools/cc/README.md`, `pyproject.toml`, `src/cc/__init__.py`, `src/cc/api.py`, `src/cc/main.py` | modified |
| `CHANGELOG.md`, `VERSION.json` | modified (shared surface — see below) |

**How isolation was maintained.** The first candidate commit predated those files appearing, so it could not have captured them. The second commit staged two explicit paths only. No `git add -A` after the first commit, no `git stash`, no `git restore`, no `git checkout --`, no `git reset --hard` at any point. Verified afterwards: `git diff --name-only fa5931a..HEAD` contains zero design paths, and nothing is left staged.

### Two things that can still interfere

**1. `VERSION.json` and `CHANGELOG.md` are a shared edit surface.** Commit `483c695` recorded `framework 5.15.0` / `cc 2.12.15`. The design session has since moved `cc` to `2.12.16` in the worktree on top of that commit. Nothing is broken, but `docs/30-operations/09-release-preparation-5.15.0.md` now names a `cc` version the worktree disagrees with. **Whoever cuts the release must reconcile those two numbers before tagging.**

**2. The branch was switched under the other session.** This session ran `git checkout -b feat/evidence-and-verified-learning-5.15.0`, which changes the branch for the whole working directory — and both sessions share it. If the design work started on `main`, its uncommitted files are now sitting on this feature branch. Nothing is lost; the files are intact and uncommitted, so a branch switch will carry them along. But that session's commits will land on this branch rather than `main` unless it is moved first. **This is an open decision, deliberately not made for you.**

---

## 2. What was implemented, and what that does and does not mean

Three commits on `feat/evidence-and-verified-learning-5.15.0`, all off `fa5931a`:

- `483c695` — evidence enforcement (work package B) and context/learning delivery (work package C)
- `ee0b04e` — first installer roster fix, unblocking project reconciliation
- `1afe0c9` — second installer roster fix, in reconcile diagnostics

**Why two installer fixes.** Adding `reflect.md` to the roster broke installation twice, in two different hardcoded allowlists, each discovered only after it broke something. The first (`reconciliation_recipes.py`) blocked every fresh install and customized upgrade. The second (`reconciliation_diagnostics.py`) was worse — it let `plan` succeed but made every real `apply` and `recover` fail, leaving an interrupted reconciliation permanently unrecoverable, reproduced across five independent fresh HOMEs. Both are now fixed structurally: any `.claude/commands/<name>.md` is accepted rather than enumerated, so a future roster addition cannot repeat this. **Two more stale enumerations remain — see TASK-45, which is the most important open item in this file.**

Keep these five claims separate; no single "done" covers them:

| Claim | Status |
|---|---|
| **Implemented** | Yes — B and C complete, QA-verified against task-bound evidence packets |
| **Installed** | Machine-level `cc` yes, in disposable locations only. The live `~/.local/bin/tc` is still the frozen `enforcement-runtime-20260907` snapshot and predates this candidate |
| **Runtime-enforced** | Partially proven — see §3 |
| **Released** | No. Blocked on your signing key |
| **Measurably effective** | No. No live paired trials were run |

### Work package A — provenance

The installed `tc task check-qa` was traced to Git tree `c6600ea9`, which **no commit pointed at and no ref reached** — a loose object on the default two-week prune horizon. It was the only in-Git copy of the enforcement code. It is now preserved on branch **`archive/enforcement-20260907`** (commit `0016983`), reachable and reviewable via `git diff fa5931a..archive/enforcement-20260907`.

That overlay had **no reviewed source lineage** — never on a branch, never in a commit, never in a reviewed diff. Under handoff section A that is a recorded **release blocker**, and this candidate supersedes it with reviewed source. The archive branch is history, **not a merge candidate**: its predicate carried eight defects, all of which the new implementation closes.

### Work package B — delivery evidence

New pure `tc.evidence` package (versioned packet schema, a single artifact-type registry, tolerant legacy parser, and a validator importing no database, filesystem or subprocess that never executes anything an artifact string contains). `tc.services.qa` is now the single completion authority, enforced inside `update_task` — the one completion-status writer shared by the CLI and `tc.api`, so a Python batch cannot bypass what the CLI enforces.

`.claude/hooks/subagent-stop.sh` no longer reaches its own regex verdict; it delegates to `tc task check-qa`, clears **only** the matching pending task, and keeps *session unblocked* strictly distinct from *task verified*.

### Work package C — context and learning

`.claude/agents/_shared/optional-context.md` is the canonical instruction, embedded byte-for-byte into six shipped surfaces. Previously this guidance existed **only** in the repo-root `CLAUDE.md`, which ships to nobody. `reflect.md` was in **neither** roster, so the reflection contract could not reach any machine or project; it is now in `projectCommands`. Taste rules gained applicability and precedence, and `context` became a valid work-product type so the shipped receipt instruction actually works.

---

## 3. What was verified at runtime, and what was not

Two live non-interactive `claude -p` runs against a disposable consumer project produced **genuine `SubagentStop`-dispatched** REJECTED→APPROVED cycles — real runtime-origin events, not self-authored JSON and not direct shell invocation of a hook.

Four negative runs: two failed as designed; **two found real gaps**, now tracked as TASK-40 and TASK-41.

Not verified: the effectiveness pilot. The bench runner does support a `claude-copilot` arm, but "arm" means harness × config layer, not framework version — so baseline-versus-candidate needs two snapshots that cannot exist until the candidate is released. Live trials also consume your account, and `human_rework` and `misapplied_rules` require a real reviewer. The frozen plan draft and a designed necessary-clarification holdout case are ready in the pilot prep notes.

---

## 4. Security item — action recommended

During auth debugging, a subagent ran `security find-generic-password -g` and printed **live Claude Code OAuth access and refresh tokens in cleartext** into a session transcript. The transcript is local, but treat the tokens as exposed: `/logout` and re-authenticate.

---

## 5. Your test file was not touched

`tests/hooks/test-pretool-check.sh` is your own in-progress rewrite targeting ADR-005's byte-cost budget contract, which `.claude/hooks/pretool-check.sh` does not yet implement (`grep -c bytesCharged` returns 0). It was preserved byte-for-byte throughout and is **excluded from every pass claim** in this rollout — no run here can be certified as an unchanged-full-suite pass while it differs from HEAD. Its companion `.claude/force-delegate-budget-baseline-v1.0.0.json` was likewise left uncommitted.

Two other hook suites *were* rewritten, under your explicit authorization, to assert the new evidence-backed contract rather than the superseded bare-message one. Assertion call-sites rose 81 → 117, all twelve baseline cases were preserved and reversed rather than deleted, and both suites were mutation-tested to confirm they still detect regressions.

---

## 6. Open tasks, with the exact next action

| Task | What it is | Next action |
|---|---|---|
| **34 (E1)** | Release packaging prepared, held at signing | **You** run the tag/sign commands in `docs/30-operations/09-release-preparation-5.15.0.md`. Reconcile the `cc` version disagreement from §1 first. Everything below E1 is waiting on this |
| **45 (C9)** | Two stale command enumerations remain | **Highest priority.** `project_integration.py` is a proven silent-skip bug in `cc workspace finish --apply` — it never installs `reflect.md` into an as-yet-unlocked project missing only that file. Needs your authorization: ~10 protected tests hardcode the stale subset. `scripts/install/validate-installation.sh` is also stale |
| **36 (E3)** | Project propagation | Blocked on E1. Inventory: ~11 clean candidates, `voice-copilot` needs its 9 `owner: project` agents preserved, 14 dirty repos must be held, 5 lack a lock file |
| **33 (D2)** | Effectiveness pilot | Blocked on E1 plus your authorization and a real reviewer |
| **40 (B7)** | Wrong-task evidence is not semantically checked | Bind the packet's criterion set to the task's own acceptance criteria |
| **41 (B8)** | Post-approval drift undetected in an already-dirty tree | The common path, not the edge case — development happens in dirty trees |
| **42 (E4)** | `tc` gets no install provenance receipts | Bring to parity with `cc`. This is the mechanism that allowed the original provenance incident to go undetected |
| **37 (C5)** | `--required` skill duplicating optional content is excluded before the required-retention branch | Deferred deliberately: amending the canonical block post-verdict would break WP-28's byte-identity evidence |

**Closed this session:** 21–32 (A, B, C, D1), 35 (E2, approved on its third run), 38 (hook fixtures), 39 (`context` WP type), 43 and 44 (the two installer fixes), 46 (runtime validation), 48 (baseline test hygiene).

---

## 7. Release procedure — verified by rehearsal 2026-09-08

A rehearsal ran in a disposable clone with the trust anchor overridden to the personal key, purely to prove the mechanism. It is **not** TASK-47 evidence, and TASK-47's registered contract explicitly forbids an overridden anchor.

**What the rehearsal established:**

| Proof | Rehearsal result | What the real run needs |
|---|---|---|
| 1 — annotated tag resolving to the exact commit | Tag/peeled-commit match verified manually | The tag name must match `^v[0-9]+\.[0-9]+\.[0-9]+$` **exactly**. The script rejects any suffix, so a `-rc` or `-rehearsal` name cannot even be passed as an argument |
| 2 — ancestry | **FAILED** | This branch must be merged or fast-forwarded into `main` first. `origin/main` is currently 4 commits behind. The script *prefers* `origin/main` over `main` when resolving the branch ref, so plan on pushing `main`, not just advancing it locally |
| 3 — signed commit **and** signed tag | Passed under the overridden anchor | The real `enac-foundation` key. Mechanism confirmed working; only the key is missing |

**The sequence on the machine holding `~/.ssh/enac_foundation_release`:**

```bash
# 1. land the content on main first — proof 2 fails until this is true
git checkout main && git merge --ff-only <candidate>
git push origin main

# 2. sign
git commit --amend -S --no-edit      # only if HEAD is unsigned
git tag -s -a v5.15.0 -m "<release message>"

# 3. verify — no env-var override, real anchor
scripts/verify-foundation-release.sh "$(pwd)" v5.15.0 "$(git rev-parse HEAD)" main

# 4. push the tag only after the verify passes
git push origin v5.15.0
```

**Key custody.** `copilot-control-tower` documents the foundation key at `~/.ssh/enac_foundation_release` — a dedicated release key, separate from the personal GitHub key. It is absent from this laptop and last signed `v5.14.16` on 2026-08-18. 75 of 100 existing tags verify under this anchor, so the convention is well established. If the key cannot be recovered, re-anchoring is a supported operation (`FOUNDATION_RELEASE_PRINCIPAL` / `FOUNDATION_RELEASE_PUBLIC_KEY`) but should be a deliberate, documented decision — never a silent override to obtain a passing check. The script's own header records RC-3, a real prior regression where weakened verification passed.

**Deliberately not done:** `main` was not advanced and nothing was pushed. Both are hard to undo, another session is active in this tree, and neither gains anything until the key is available.

Live status, dependencies, work products and verdicts are in `tc` under PRD-4 — this file is a snapshot, not the task board.
