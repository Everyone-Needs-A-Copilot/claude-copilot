# CSE gap closure and remaining release work

Recorded 2026-09-08. Execution authority: Claude Copilot PRD-4 and Codex Copilot
PRD-11. Read their current `tc` tasks before continuing; this is durable migration
and handoff guidance, not a second task board.

## What is implemented

The shared development installation now uses **cc 2.13.0 and tc 2.0.0** from
`/Users/pabs/Sites/CSE/claude-copilot`. Native Codex instructions require these
versions. Framework 5.15.0 and the Codex working-tree additions remain unpublished.

| Gap | Result | Execution record |
| --- | --- | --- |
| Wrong-task evidence | Approval binds the actual database/task, registered criterion IDs and exact expected behavior | Claude TASK-40 |
| Drift in an already dirty tree | Content manifests are recaptured at completion; edits, additions and deletions invalidate evidence | Claude TASK-41 |
| Required duplicate skills | Every explicitly required name remains selected; duplicate content is emitted once | Claude TASK-37 |
| Missing `reflect` during workspace finish | Discovery and validation use the authoritative roster, including future entries | Claude TASK-45 |
| Unverifiable `tc` installation | Source, dependency, runtime and enforcement receipts; snapshot cc/tc publication is checked together with rollback | Claude TASK-42 |
| Design evidence disconnected from task criteria | Design review/report bind criteria and source coverage to the project's actual task acceptance contract | Claude TASK-40 / Codex TASK-25 |
| Native edit feedback | Claude native dispatch observed; Codex payload adapter accepts `tool_input.command`; final runtime evidence belongs to Codex TASK-23 | Codex TASK-23 |

Source changes were developed in an isolated worktree on
`codex/cse-gap-closure-20260908`, seeded with the earlier design work. Reviewed
files were transferred back with before/after hashes and exact-byte backups;
the original source branch and unrelated work were preserved. The initial signed
candidate is `2a1734f08338067c4420d8b55a62ab5cf8f7b1e4`; subsequent candidate
identity and validation are recorded in TASK-42/46 work products. A development
receipt identifies mutable source explicitly; it is not an immutable release pin.

## Required migration for pending QA work

`tc 2.0.0` deliberately changes the current completion contract. For each pending
QA-required task, register its acceptance criteria and explicit project-relative
source scope. Include implementation, relevant runtime configuration, tests and
design authority. Do not include transient `.copilot` state or symlink aliases.

```json
{
  "schemaVersion": 2,
  "criteria": [{"id": "C1", "expected": "Retry preserves the entered draft"}],
  "sources": ["src", "tests", "design", "package.json"]
}
```

Run in that task's project, replacing `ID` with its actual local task ID:

```bash
tc task contract ID --file acceptance.json --json
tc task evidence-identity ID --json
# Retain identity_line BEFORE running the checks; record actual observations.
tc wp store --task ID --type test --title "Source-bound QA" --file qa-evidence.md --json
tc task check-qa ID --json
scripts/copilot-gate.sh --task ID
tc task update ID --status completed --json
```

The evidence file carries the exact captured `IDENTITY:` line, `BASELINE:`, each
registered `CRITERION:` / `EXPECTED:` / actual `OBSERVED:`, evidence-bound
`ARTIFACT:` markers, `UNTESTED:` and an honest `VERDICT:`. Source changes require
new verification; do not replace a stale identity around old observations.
Implementation work products precede QA. Unfinished dependencies now prevent
persisted completion. Existing QA-required tasks cannot downgrade `requiresQa`.
Completed pre-contract history remains readable as historical evidence; reopening
requires fresh verification. No evidence or task database was bulk rewritten.

Hashes and criterion coverage establish structural binding. They do not prove
that a reviewer actually exercised behavior, authenticate a reviewer, or discover
an omitted dependency. Scope selection and real QA judgment remain necessary.

## Validation and test integrity

The active shared source passed 585 `tc` tests, 47 focused `cc` tests and the
canonical optional-context surface check. The isolated combined candidate passed
24 snapshot installer tests, including a real isolated-HOME installation; final
candidate revalidation is attached to TASK-42. Native Codex's complete smoke
suite passed with its graded files unchanged.

The owner explicitly authorized the scoped QA-contract and installation fixture
changes and new regressions. Those passes are not represented as unchanged-suite
results. Original assertions were retained. Two separate baseline issues remain:

- `tests/hooks/test-pretool-check.sh` was already modified; it was preserved and
  excluded from the candidate. Its byte-budget disagreement is not resolved here.
- The unchanged workspace tier-ladder test supplies a 22,826-byte override for an
  unchanged original 47,742-byte protocol, below its existing 50% threshold.
  Original-source reproduction is recorded; a fixture-only correction was asked
  separately and must not be made without that authorization. Preserve the
  production threshold and all assertions.

Evidence, transfer backups and source manifests are under
`/Users/pabs/Sites/CSE/codex-copilot/.copilot/gap-closure/`; the corresponding `tc`
work products contain verdicts and artifact hashes. Do not infer a whole-Claude
suite pass or fleet readiness from these scoped results.

## Remaining work and ownership

**Runtime validation — Codex TASK-23, Claude TASK-46.** Native sessions must run
the exact registered hook after project trust and exact-hook review. Codex CLI's
`/hooks` view distinguishes registration, review and active status. The installed
0.153.4 runtime normalizes patches into `tool_input.command`, now supported by the
adapter. A direct JSON replay proves the adapter, not native dispatch; preserve
failed/unsupported runs. No trust-bypass flag is part of the procedure. See
[official hook documentation](https://learn.chatgpt.com/docs/hooks).

**Release — Claude TASK-47, then propagation TASK-36.** The initial candidate's
SSH signature verifies under the user's configured signer, but fails the existing
foundation trust anchor with “No principal matched”; it is also not an ancestor
of `main` or `origin/main`, and `v5.15.0` is absent. These were measured separately.
No private key availability is inferred from those checks. The release owner must
land the reviewed final content on the release branch through the existing route,
sign the resulting commit and annotated tag with the authorized foundation key,
then run `scripts/verify-foundation-release.sh` against the original repository,
exact tag, full commit and intended branch. Preserve both signature checks and
ancestry. Do not substitute a different trust anchor to get a pass. Rebuild and
revalidate after content changes; preparation TASK-34 is not release approval.

Only after TASK-47 passes should the developer run fresh per-project canonical
plan/apply/independent-verify cycles from TASK-36's inventory. Hold dirty or
customized projects with exact reasons and preserve project-owned agents. Updating
the framework source and machine CLI does not update every consumer project.

**Effectiveness — Claude TASK-33 and Codex TASK-22.** A real reviewer must supply
corrective-work and judgment outcomes. Use the existing
`copilot-bench/docs/pilots/cse-effectiveness/README.md` and root plan example.
Freeze same-framework baseline/candidate snapshots, exact model/effort/runtime,
configuration and source pins, unchanged task fixtures and review rubrics. Use the
six existing families with two repetitions per variant and a separate necessary-
clarification holdout before judgment claims. Review the two `bench run --dry-run`
plans before execution; do not treat these native dispatch probes as effectiveness
trials. Feed complete real observations to `cc eval adoption-check`; retain the
baseline if benefit or required evidence is absent. Mechanical readiness is not
measured effectiveness, and evaluation cases must remain outside learning inputs.

**Credential incident — owner.** The original handoff reports exposed OAuth
tokens. Remediation has not been confirmed in this session. Revoke/rotate through
the provider and verify reauthentication without printing token values. Code
hardening does not remediate that incident; no secret or transcript search is
needed to complete this handoff.

## Prompt for the next developer session

Read this document and current Claude PRD-4 TASK-46/47/36/33 plus Codex PRD-11
TASK-23/25/22. Continue only their remaining work; do not reimplement completed
fixes, overwrite user changes, fabricate QA observations, or mark preparation as
release. Preserve the scoped test authorization boundary. Resolve runtime evidence
from actual native events, then validate the final immutable candidate. Carry
foundation signing, credential remediation and real human review as explicit owner
dependencies until the corresponding evidence exists. Store detailed results in
`tc`, run the task authority before closure, and report verified outcomes separately
from remaining holds.
