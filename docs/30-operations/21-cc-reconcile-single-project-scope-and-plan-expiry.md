# cc reconcile: single-project setup scans the whole machine and outlives its plan (2026-11-06)

**Diátaxis mode:** Explanation (findings and fix directions)

**Status:** Moot. `cc reconcile` and the project recipe engine it described were removed in the retire-copy-model task (PRD-16 task 211); every `cc reconcile` subcommand now refuses and points at `cc project init` and `cc release`. Kept as a historical record.

**Update (2026-11-06, historical):** [Central-resolution ADR-001](../40-initiatives/06-central-resolution/decisions/ADR-001-central-release-pointer.md) retires project reconcile recipes after the fleet migration. `cc project init` and `cc project migrate` do not use reconcile, so fix directions 1 (single-project census) and 6 (non-Git crash) are not applied to reconcile; init carries its own non-Git criterion and runs in seconds. Fix directions 2 to 5 are expected to become moot with the retirement and are re-checked at initiative closeout (PRD-16 parked tasks). Treat the findings below as historical.
**Date:** 2026-11-06
**Component:** `tools/cc` (cc 2.18.0, framework 5.34.8, snapshot `claude-copilot-e4578de8f1269d5968356008b0db535cf7ada1f2`): `cc reconcile request | plan | apply | verify`

All file:line references below are to `tools/cc/src/cc/` in that snapshot (the installed `~/.local/bin/cc` runs `/Users/pabs/.copilot/framework-snapshots/claude-copilot-e4578de8f1269d5968356008b0db535cf7ada1f2/tools/cc/.venv/bin/python`).

## Symptom

Setting up one brand-new, empty Git repo (`/Volumes/Dev/Sites/COPILOT/dsnr`, branch `main`, no commits) with `/setup-project` took about 5 minutes per `cc reconcile plan` and produced a 587 KB plan that covered 84 repositories (69 product projects and 15 ecosystem repositories, among them PERSONAL/thoughts, TSM/h3, COPILOT/knktr-serve and preflight-copilot), although the request selected only dsnr. The machine's `projects.roots` is `['/Volumes/Dev/Sites', '/Volumes/Dev/Sites/PERSONAL/dossier-builder']`.

The reviewed plan (`plan_e3342faa2d1d9a440aeffa975cb6981d`, issued 12:08:28Z, expiring 12:23:28Z) could not be used. Apply started at 12:13:34Z, spent about 9.5 minutes, and ended at 12:23:04Z with `blocked` and "The project or request changed after review. Create and review a fresh plan." No file in dsnr changed. A human confirmation round trip on top of a 5-minute plan and a 5-minute apply preflight does not fit comfortably inside the plan lifetime.

## Reproduction

1. Have `projects.roots` include a broad folder such as `/Volumes/Dev/Sites` holding dozens of Git repos.
2. `cc reconcile request --project <new empty repo> --output req.json` (writes `"roots": ["/Volumes/Dev/Sites"]`, the nearest configured root).
3. `time cc reconcile plan --request req.json --json > plan.json`
4. Optionally profile: `<cc venv python> -m cProfile -o plan.prof ~/.local/bin/cc reconcile plan --request req.json --json`.

## Measurements (facts)

| Run | Scope | Wall time | Plan size | Projects in plan |
| --- | --- | --- | --- | --- |
| `reconcile request` | n/a | 1.0 s | n/a | n/a |
| First plan (12:04:07 to 12:08:28Z, no profiler) | `/Volumes/Dev/Sites` | about 4 min 21 s | 587 KB | 84 |
| Profiled plan (cProfile) | `/Volumes/Dev/Sites` | 293 s (user 111 s, sys 116 s) | 601 KB | 84 |
| Failed apply of the first plan | `/Volumes/Dev/Sites` | about 9.5 min | n/a | n/a |
| Plan with `CC_PROJECTS_ROOTS=/Volumes/Dev/Sites/COPILOT/dsnr` | dsnr only | 27 s | 34 KB | 1 |
| Apply of that plan | dsnr only | 52 s | n/a | n/a |
| Verify of that plan | dsnr only | 22 s | n/a | n/a |

cProfile breakdown of the 293 s full-scope plan:

- 24,153 `subprocess.run` calls account for 274 s. Most of the high sys time is process spawning.
- `project_reconciliation.py:1030 assess_project` runs 70 times, 266 s cumulative, about 3.8 s per project.
- `codex_plugin_source.py:86 resolve_codex_plugin_source_with_bindings` runs 195 times, 252 s cumulative, about 2.8 times per project. Nothing caches the result, though every call resolves the same framework source.
- `policy.py:189 read_git_tree_snapshot` runs 195 times. It spawns 21,060 git processes and takes 219 s: one `git ls-tree` plus one `git cat-file blob` per file (`policy.py:233`), about 108 processes per call.
- Callers on that path include `reconciliation_recipes.py:991 _codex_plugin_binding` (174 s), `reconciliation_recipes.py:1038 _lock_entry` (90 s), `reconciliation_recipes.py:1184 authoritative_source_available` (88 s) and `project_reconciliation.py:683 _source_available` / `:711` (87 s).
- The machine assessment (`machine_assessment.py:1053 build_machine_assessment_with_verification`) takes 22 s. Of that, `commands/doctor.py:863 build_doctor_report` takes 18 s, mostly 32 `git ls-remote` probes (`mirror.py:267 probe_remote_ref`, 17 s) for the 16 layers.
- Repository discovery is cheap: `workspaces.py:141 _scan_root` takes under 0.01 s.

## Root cause (facts from source)

1. **A one-project request inspects every project under the root.** `cc reconcile request` puts the nearest configured root into the request (`core/ecosystem/canonical_transaction.py:261-272`, `_containing_root` at `:212-226`). Its comment says this choice "avoids silently widening a one-project request", but with `/Volumes/Dev/Sites` the nearest root already covers 84 repos. `prepare_reconciliation` (`core/ecosystem/reconciliation.py:1428`, census call at `:1463-1469`) then calls `build_project_census(roots=request.roots, selections=..., detail=True)`. That function's docstring says "Discover every Git project under approved roots and assess it exactly once" (`core/ecosystem/project_reconciliation.py:1357-1407`), and it runs a full `assess_project(..., detail=True)` on each discovered repo (`:1399-1406`), whether or not that repo was selected. `build_plan_report` returns all of them in `projects` (`reconciliation.py:1650-1671`), which is why the plan is 587 KB.
2. **Each project assessment re-verifies the Codex plugin source from scratch.** `resolve_codex_plugin_source*` (`core/ecosystem/codex_plugin_source.py:68, 86`) has no memoization. Each call reads the whole plugin tree through `read_git_tree_snapshot` (`core/ecosystem/policy.py:189-252`), one git subprocess per blob. This per-project constant (about 3.8 s) multiplied by the number of projects under the root accounts for about 90% of plan time.
3. **Apply and verify do the same full inspection again.** `build_apply_report` calls `prepare_reconciliation` again before claiming (`reconciliation.py:1718-1723`, claim at `:1805-1810`). After execution it runs a second full machine assessment and full census (`reconciliation.py:1949-1960`). `build_verify_report` (`reconciliation.py:2385`) runs one more (census at `:2403`). So one full-scope apply costs about two plan runs (about 9.5 min observed).

## Plan lifetime (TTL)

- **Fact:** The TTL is 900 s (15 minutes). `issue_plan(..., ttl_seconds: int = 900)` is at `core/ecosystem/project_plan_store.py:434`, and `expires_at = created + ttl` at `:468`. `build_plan_report` does not override it (`reconciliation.py:1609-1618`).
- **Fact:** Apply enforces the TTL inside `claim_plan` (`project_plan_store.py:479-502`): `if now >= expires_at: state = "expired"; raise PlanExpired`. Apply calls `claim_plan` only after its own full re-inspection (`reconciliation.py:1718` and then `:1805`). The expiry clock therefore keeps running during the apply preflight. With a full-scope apply preflight of about 5 minutes, a person has about 10 minutes, not 15, between the end of `plan` and starting `apply`.
- **Fact:** The value 900 has no written rationale. The module docstring (`project_plan_store.py:1-10`) says plans are "Private, expiring, single-use" and "neither a reusable state hash nor an authority that survives changed inspection evidence". `tools/cc/README.md:338` says "`plan` capabilities expire and are single-use", and CHANGELOG (cc 2.6.0) says "opaque expiring plan capabilities". None of these explains why the number is 15 minutes.
- **Fact:** The real safety check is the binding, not the clock. `claim_plan` also requires `request_fingerprint` and `fresh_plan_fingerprint` to match (`project_plan_store.py:503-509`, `PlanBindingMismatch`). The fresh fingerprint (`reconciliation.py:1554-1575`) hashes the request, the selected projects, the public plans, the entitlement bindings and **the entire machine assessment**. Apply then requires the claimed stored plans to equal the freshly recomputed ones (`reconciliation.py:1829-1837`). Each project is re-inspected under its own lock during execution.

## How the slowness and the TTL interact

- **Fact:** The 12:23:04Z failure was not an expiry. The plan record still has `state: "reviewed"`; an expiry would have set it to `expired`. The diagnostic records `stale-plan`, and the next action is the `PlanBindingMismatch` text. Compared with the 12:08 plan, the apply-time machine assessment had flipped from `ready` to `action-required` with blocker `layers-not-ready`: "claude/claude-foundation: local checkout contains the managed remote revision plus authored commits".
- **Fact:** `claude-foundation` is this repository (`claude-copilot`). Commit `3bd992a` ("docs: handoff for orchestration and Codex parity completion") was made locally at 12:17:41Z, between plan and apply, by unrelated work, and was not pushed.
- **Hypothesis (strongly supported by timing, not proven by a controlled rerun):** That unrelated commit changed the machine assessment, which changed the fingerprint, which made the dsnr plan stale. Because the fingerprint binds the entire machine, a commit in any of the 16 layer checkouts during the 10 to 15 minute plan/apply window invalidates every outstanding single-project plan. The longer plan and apply take, the more likely this is on a machine where other sessions are committing.

## Secondary defect: non-Git folder crashes `reconcile request`

- **Fact, reproduced 2026-11-06:** `cc reconcile request --project <non-git folder> --output x.json` prints an uncaught Rich traceback ending in `ProjectIdentityMismatch: The selected folder is not a readable Git project.` The raise is at `core/ecosystem/project_locking.py:301` (`_git_path`), reached via `inspect_project_identity` (`project_locking.py:379/397`) from `canonical_transaction.py:245`. `commands/reconcile.py:161-170` catches only `RequestValidationError` and `OSError`. `ProjectIdentityMismatch` derives from `ProjectLockError(RuntimeError)` (`project_locking.py:39, 47`), not from `RequestValidationError(ValueError)` (`reconciliation_types.py:185`), so the user gets a traceback instead of the `invalid-request` JSON error.

## What was done in dsnr, and its current state

- No leftover cc processes were running when this was investigated. Nothing was killed.
- The first full-scope apply left dsnr unchanged. No pending run intent or stale lock remained: all 106 run intents are `finalized`, and lock files are zero-byte `flock` targets.
- Setup was then completed with dsnr-only scope through cc's documented environment-variable config layer (`core/config.py:398-406` and `resolve_key` at `:441-447`, where `CC_PROJECTS_ROOTS` overrides `projects.roots` for that process only). Machine config was not edited.
  - `CC_PROJECTS_ROOTS=/Volumes/Dev/Sites/COPILOT/dsnr cc reconcile request ...` produced `roots: ["/Volumes/Dev/Sites/COPILOT/dsnr"]`.
  - The resulting plan `plan_8334a9f278d661a52fe2e3bff8724fd5` had route `safe-setup-available`, no project blockers, and 56 operations (51 Claude, 5 Codex; recipes `claude-project-setup-v1` and `codex-project-setup-v1`) with operation ids identical to the approved full-scope plan.
  - It was applied at once with the same environment and returned `applied`, verification `ready`, 56 of 56 operations.
- `cc reconcile verify` shows dsnr route `ready` with Claude and Codex both `ready`. Its overall result is `action-required` only because of the unrelated machine item above. `cc workspace verify --project /Volumes/Dev/Sites/COPILOT/dsnr --json` returns `ready`.
- `.claude/hooks/copilot-hook.sh` exists and is executable. It is registered for five events in `.claude/settings.json` and recorded in `copilot.lock.json` with a matching sha256 checksum.
- dsnr is not committed or pushed. Its setup files are untracked.
- An unused full-scope plan (`plan_8508c82c115ace1ded18493a87d5d598`) from the profiling run remains `reviewed` in the private store and will expire on its own.

## Suggested fix directions (suggestions, not decisions)

1. **Scope the census to the selected projects.** When a request selects projects, `build_project_census` could assess only those (plus whatever cheap discovery is needed to prove containment and ecosystem-repository exclusion), and `build_plan_report` could return only the selected projects. Alternatively, `reconcile request` could emit the project path itself as the authority root, as the `CC_PROJECTS_ROOTS` workaround does. That needs a decision on whether a project may be its own approved root.
2. **Memoize framework-source resolution per process.** Cache `resolve_codex_plugin_source*` and `read_git_tree_snapshot` by (repository root, tree oid). A tree oid is content-addressed, so a cache keyed on it cannot go stale within one run.
3. **Read blobs in one process.** Replace the per-blob `git cat-file blob` loop (`policy.py:233`, and the twin at `policy.py:123`) with one `git cat-file --batch`, or with `git archive` for the tree.
4. **Narrow the fingerprint.** Bind only the machine facts the selected components depend on (for example the framework source revisions the recipes read) instead of the whole machine assessment, so an unrelated layer commit does not invalidate a one-project plan.
5. **Make the TTL honest about preflight.** Check expiry before the apply re-inspection, or extend the deadline by the preflight time. Write down the reason for 900 s, or make it configurable within the existing 1 to 86,400 s bound.
6. **Catch `ProjectIdentityMismatch` in `reconcile request`** and emit `invalid-request` JSON with exit 2, matching the other validation failures.

## Open questions

- Is the full-machine census a deliberate safety property (for example proving that no other project claims the same path, or that a selection is not an ecosystem repository), or a by-product of sharing the `assess` code path? If it is deliberate, which facts does it need from unselected projects?
- Should the plan fingerprint keep binding the entire machine assessment, or is that stricter than the threat model requires?
- What was the intended human window for the 900 s TTL, given that apply's own preflight consumes part of it?
- Should `CC_PROJECTS_ROOTS` scoping become a documented, supported `/setup-project` option (for example `cc reconcile request --scope project`), or should it stay an operator workaround?
- How many `assess_project` calls per project are expected? The profile shows about 2.8 Codex source resolutions per project in one plan.

## Resolution under central resolution (2026-11-07)

Central resolution (framework 5.35.0, [ADR-001](../40-initiatives/06-central-resolution/decisions/ADR-001-central-release-pointer.md)) resolves this brief by removal rather than repair. `cc reconcile` is retired (every subcommand exits 2), `cc project init` sets up a single project in seconds without a census or plan, and `cc project migrate --scan <roots>` replaces reconcile's machine census as an explicit, read-only scan. Plan expiry no longer applies because there are no plans or apply steps for projects. Still open: `cc project migrate --apply` across the 71 projects is not covered by this brief's scoping fix and its runtime on very broad roots has not been timed; the sixth direction (non-Git crash) is covered by init's own criterion, not by a reconcile fix.
