# Release preparation: framework 5.15.0

Prepared 2026-09-07 under `tc` PRD-4 (Claude Copilot's own rollout database) task E1, upstream codex-copilot PRD-9/TASK-16. This document records the candidate this repository is preparing for release, the three proofs the owner's own release script requires, the exact commands the owner runs to cut and sign the release, and what must be re-run if candidate content changes before that signature happens. It authorizes nothing by itself: no tag, no signature, no push, no install has occurred as a result of preparing this document.

## 1. Version decision

| Component | From | To | Basis |
|---|---|---|---|
| `framework` | `5.14.16` (never tagged, no CHANGELOG entry for `5.14.11`–`5.14.16`) | `5.15.0` | Minor bump — this release adds only additive, non-breaking capabilities (a new completion-authority gate, a new evidence-validation package, distributed `reflect.md`, new agent instruction sections). Framework `5.14.16` is **superseded**, not released in its own right: nobody can produce a signed tag or discrete release note for `5.14.11` through `5.14.15` after the fact, since no work product records what changed at each of those six intermediate bumps. `5.15.0` **absorbs** that content — everything the working tree held at `5.14.16` ships as part of `5.15.0` — but the CHANGELOG entry for `5.15.0` documents only what PRD-4 actually implemented and verified, not invented history for the untraceable intermediate numbers. `5.15.0` is the first coherent, evidenced, signable release since the last one this repository's own `copilot.lock.json` and CHANGELOG agree on: `v5.14.10`.
| `tc` | `1.3.0` | `1.4.0` | Minor bump for the new `tc.evidence` package and the `update_task` completion gate (additive; `requiresQa` stays opt-in, existing no-metadata task completion is unchanged and protected by three existing tests). Explicitly **not** `1.3.0+enforcement.20260907` — that is a local build tag from an unreviewed overlay (task A1's release blocker) and must never ship. See §4 for why `tools/tc/pyproject.toml` and `tools/tc/src/tc/__init__.py` still read `1.3.0` and what that means for signing readiness.
| `cc` | `2.12.15` | `2.12.15` (unchanged) | Already coherent: `tools/cc/pyproject.toml`, `tools/cc/src/cc/__init__.py`, and `VERSION.json` all already agree at `2.12.15`. That bump predates PRD-4 (the handoff records it as already active before this rollout began) and none of PRD-4's work packages touched `tools/cc/**`. Separately noted, not fixed here: `cc`'s own CHANGELOG has no entry for `2.12.9`–`2.12.15` either, the same kind of undocumented-bump gap the framework has for `5.14.11`–`5.14.16`. Out of this task's scope; flagged in §5.
| `agents` | `5.6.0` | `5.7.0` | Already set by work package C (optional-context sections in `ta`/`me`/`qa`; taste precedence clause in `sd`/`ind`/`uxd`/`uids`/`cco`/`cw`/`ta`). Not changed by this task.
| `commands` | `5.3.2` | `5.4.0` | Already set by work package C (`reflect.md` added to `projectCommands`). Not changed by this task.
| `skills` | `3.3.0` | `3.3.0` (unchanged) | No skill content changed in PRD-4.

## 2. Exact candidate contents (snapshot at task E1, HEAD `fa5931ab1af7f88c493a7a183ac2685bed9117b4`)

`git diff --stat HEAD`: 39 tracked files changed (1,736 insertions, 743 deletions), plus new untracked paths. This is **not yet the final immutable candidate** — tasks B6 (update superseded hook fixtures) and C5 (close the `--required`/duplicate-content false negative) are still pending in PRD-4 and will touch candidate content again before tagging. Whoever cuts the tag must re-diff against this list first; if it has grown, re-run the checks in §5 before proceeding to §3.

**Modified, by owner:**
- Work package B (task authority): `tools/tc/src/tc/api.py`, `tools/tc/src/tc/commands/task.py`, `tools/tc/src/tc/services/tasks.py`, `.claude/hooks/subagent-stop.sh`, `.claude/hooks/pretool-check.sh`, `scripts/copilot-gate.sh`.
- Work package C (optional context + taste): `.claude/agents/{ta,me,qa,sd,ind,uxd,uids,cco,cw}.md`, `.claude/commands/{protocol,reflect}.md`, `templates/CLAUDE.template.md`, `plugins/codex-copilot/skills/specialist-agents/references/shared-behaviors.md`, `VERSION.json` (roster only — `commands`/`agents` versions, `projectCommands` list).
- Pre-existing (predates PRD-4, carried by this candidate unchanged): `.codex-copilot.json`, `CLAUDE.md`, `copilot.lock.json`, `docs/30-operations/07-codex-hook-enforcement-gap.md`, `plugins/codex-copilot/agent-catalog.json`, `plugins/codex-copilot/skills/{protocol/SKILL.md,protocol/references/checkpoints.md,qa/SKILL.md,update-project/SKILL.md}`, `tests/hooks/test-pretool-check.sh` (the one file under `tests/` that differs from HEAD — read-only per the owner's test-integrity rule; report the disagreement, do not edit it to match), `tools/cc/{README.md,pyproject.toml,src/cc/{__init__.py,api.py,commands/eval.py,commands/skill.py,core/skill_store.py,main.py}}`.
- This task (E1): `CHANGELOG.md`, `VERSION.json` (`framework`, `tc.version`, `lastUpdated`, `workingTreeAdoption`), this document.

**New (untracked), by owner:**
- Work package B: `tools/tc/src/tc/evidence/` (package: `__init__.py`, `schema.py`, `artifact_types.py`, `parse.py`, `validate.py`), `tools/tc/src/tc/services/qa.py`, `tools/tc/tests/{test_evidence_validate.py,test_qa_completion.py,test_qa_fitness_functions.py,test_qa_legacy_migration.py}`.
- Work package C: `.claude/agents/_shared/optional-context.md`, `tests/instructions/`, `tests/roster/`, `tools/cc/tests/test_skill_select_contract.py`.
- Pre-existing: `.claude/force-delegate-budget-baseline-v1.0.0.json`, `docs/30-operations/08-evidence-and-adoption.md`, `plugins/codex-copilot/hooks/` (four files), `tools/cc/src/cc/core/evaluation/adoption.py`, `tools/cc/src/cc/core/runtime_evidence.py`.
- Excluded from the candidate: `.claude/hooks/state/**` (transient hook runtime state, gitignored, not release content).

**Explicitly not in the candidate:** any content from `archive/enforcement-20260907` (commit `0016983439332167d767c73e766a87bd7d315365`, tree `c6600ea95f5f9021471ee2886fceea84ed78acdb`). Private `knowledge-copilot-private` content is untouched by this candidate and has its own release path.

## 3. Provenance blocker carried forward from work package A

The `tc` currently installed on this machine (`/Users/pabs/.local/bin/tc` → `/Users/pabs/.copilot/enforcement-runtime-20260907/`, reporting `1.3.0+enforcement.20260907`) was built from a Git tree (`c6600ea9`) that was never on a branch, never in a commit, and never reviewed — its only prior in-Git representation was an unreachable, prunable loose object. Task A1 made that tree reachable, non-destructively, as `archive/enforcement-20260907` (commit `0016983439332167d767c73e766a87bd7d315365`) purely so it could be reviewed and diffed; the branch is **history, not a merge candidate** — `git diff fa5931a..archive/enforcement-20260907` documents eight predicate defects (disjoint artifact-type sets, unvalidated evidence fields, opt-in-only `requiresQa`, staleness detected only via work-product ordering, single-latest-WP evidence, verdict-count brittleness, a TOCTOU window, case-sensitivity mismatch) that work package B fixed by reimplementing the module from the enforcement point down, not by merging the branch. `tc` `1.4.0` in this candidate **supersedes** the archived overlay with reviewed source: same enforcement point (`update_task`), a fresh evidence package, and none of the eight defects. Do not merge `archive/enforcement-20260907`; do not delete it either — it remains the reviewable record of what the installed build actually did.

## 4. Coherence gap that must close before tagging

`VERSION.json` now declares `tc` `1.4.0`, but `tools/tc/pyproject.toml` and `tools/tc/src/tc/__init__.py` still read `1.3.0` — this task's file scope explicitly excludes `tools/tc/**`, so it cannot make that edit. Whoever lands the final candidate commit (work package B's owner, or the agent assembling the release commit) must bump both to `1.4.0` before the commit that gets tagged; `scripts/check-versions.sh` and any packaging step that reads the installed `tc --version` will otherwise disagree with the declared component version.

## 5. The three proofs `scripts/verify-foundation-release.sh` requires, and why none can be produced here

The script (`scripts/verify-foundation-release.sh <repo> <tag> <commit> [branch=main]`) requires all three, unconditionally, with no flag to skip any of them:

1. **An annotated, signed tag** matching `^v[0-9]+\.[0-9]+\.[0-9]+$` whose peeled commit equals the declared source commit (`git cat-file -t` must report `tag`, and `rev-parse <tag>^{}` must match).
2. **Provable ancestry**: `git merge-base --is-ancestor <commit> <branch>` — the tagged commit must be a real ancestor of the release branch, not a fabricated parentless commit (the script's own comments document RC-3, a 2026-08-10 regression where a parentless commit could never satisfy this and 61+ tags shipped with unprovable ancestry).
3. **`git verify-commit <commit>`**, independently of the tag's own signature — the script also documents a second regression where dropping this check let a signed tag over an *unsigned* commit pass.

Both signature checks (1 and 3) run against a fixed trust anchor: principal `enac-foundation` and a specific `ssh-ed25519` public key (overridable via `FOUNDATION_RELEASE_PRINCIPAL`/`FOUNDATION_RELEASE_PUBLIC_KEY`, but defaulting to the organization's foundation key). **No agent in this session holds the corresponding private signing key** — this is categorically an owner-only credential, not a missing environment variable or a permissions gap this session could work around. Proof 2 is mechanical and requires no key, but it cannot be meaningfully exercised until proof 1 produces a real tag to check ancestry against. So the release-signing step is a hard stop for automation by design, not an oversight to fix.

## 6. Exact commands the owner runs, in order

Run from `/Users/pabs/Sites/CSE/claude-copilot` on `main`, after §4's coherence gap is closed and the final candidate commit (incorporating this document's changes) exists.

```bash
# 1. Confirm the exact commit being released and that it is genuinely the candidate.
git log -1 --format='%H %s'
git diff --stat fa5931ab1af7f88c493a7a183ac2685bed9117b4..HEAD

# 2. The commit itself must carry a valid signature from the owner's key (proof 3 checks
#    the commit's OWN signature, independently of the tag). If the candidate commit landed
#    unsigned, re-sign it now -- safe only because it is not yet tagged or pushed:
git commit --amend -S --no-edit

# 3. Cut the annotated, signed tag against that commit.
git tag -s -a v5.15.0 -m "Framework 5.15.0 -- task-bound QA authority, optional-context delivery, taste precedence"

# 4. Verify locally, exactly as the release pipeline will, before anything is pushed.
scripts/verify-foundation-release.sh "$(pwd)" v5.15.0 "$(git rev-parse HEAD)" main

# 5. Only after step 4 prints "foundation release signatures: verified", push both.
git push origin main
git push origin v5.15.0
```

Steps 2-5 require the owner's signing key and push authority; none of them were run in preparing this document.

## 7. What must be re-run after this point

- **If the candidate commit changes at all after this document is written** (including landing tasks B6 or C5, or fixing §4's coherence gap): re-run the full `tools/tc` and `tools/cc` test suites, re-diff §2's file list, and update the `IDENTITY` fields in any QA work product that cited the old commit hash. Do not tag a commit this document has not been re-validated against.
- **After the tag is cut and pushed:** re-run `scripts/verify-foundation-release.sh` against the pushed remote tag (not just the local one) to confirm the pushed ref matches what was verified locally.
- **Before any `/update-copilot` run:** task E2 (disposable-location rehearsal: clean install, upgrade, no-op repeat, recovery) must pass against the tagged commit, not the working tree — `/update-copilot` resolves committed `HEAD`/`HEAD^{tree}` and cannot distribute uncommitted content.
- **Before any `/update-project` run against a consuming project:** task E3's inventory (which in-scope projects are clean vs. dirty vs. customized vs. held) must be re-verified if any time has passed, since a project's git state can change between E1 and the actual reconciliation.
- **Before claiming the release is runtime-enforced:** task D1 (Claude lifecycle validation in a disposable consumer project) and D2 (the frozen baseline-vs-candidate effectiveness pilot) must both run against this exact tagged commit's installed artifact, not against the working checkout — see §7 of the handoff and §8 below.

## 8. What is proven and what is not

**Implemented and locally verified (this candidate, against the source checkout):** the `tc.evidence` package and its import-purity/parse/validate tests; the `update_task` completion gate and its TOCTOU fix; `tc task check-qa` as both a CLI command and a `tc.api` export; the Claude hook's delegation to that command with task-bound clearing; the Codex gate's capability-unavailable exit; the reconciled artifact-type registry; the optional-context instruction block, byte-identical across every listed surface; the taste applicability/precedence clause in all seven agents; `reflect.md`'s presence in the distributed command roster, exercised read-only against the actual `project_integration._claude_source_files` code path.

**Not proven, and not claimed here:**
- **Not installed.** The machine's active `tc` is still the unreviewed `1.3.0+enforcement.20260907` build from `enforcement-runtime-20260907`, not this candidate.
- **Not runtime-enforced.** No Claude Code session has yet exercised the new hook adapter through a real lifecycle event (task D1 is pending); the only verification so far is direct invocation of `tc.api`/CLI functions in isolated, disposable databases.
- **Not released.** No annotated signed tag exists; nothing has been pushed; `copilot.lock.json` in this very repository still records the last real install at `v5.14.10`.
- **Not measurably effective.** The frozen baseline-vs-candidate pilot (task D2) has not run; there is no reviewed evidence yet that the new QA gate reduces corrective work or holds correctness/abstention regressions to the predeclared policy.

No statement in this document should be read as satisfying any of the four items above.
