# Source integration: framework 5.15.1

Date: 2026-09-08. Execution: Claude Copilot PRD-4 / TASK-57; lifecycle fixture
closure TASK-59. Testing redesign plan: PRD-5 / TASK-58.

## Scope and versions

The owner requested all pending Claude Copilot updates committed and integrated
into local `main`, with coherent versions and a concrete testing adoption plan.
This is **source integration**, not a signed foundation package or consumer rollout.

| Component | Integrated source version |
|---|---|
| Framework / root package | 5.15.1 |
| cc Python package / runtime / uv lock | 2.13.1 |
| tc Python package / runtime | 2.0.0 |
| Vendored Codex plugin retained from main | 0.7.0 |

The new `cc` lock identity corrects its stale 2.12.8 entry without changing
dependency versions. `uv lock --check --offline` and the packaging-style locked
requirements export succeed. The old bump script assumes a removed manifest
component, so the exact version-bearing fields were updated directly.

## History and preservation

- Incoming feature base: `4c26a80`.
- Fetched `origin/main` and local `main`: `0311bf4`, five commits ahead of that
  base, already containing the earlier tc/design hardening and Codex plugin sync.
- `04242e0` commits the pending source, tests and documentation, including the
  owner-preserved budget suite and previous session's verified repairs.
- `352aed3` merges existing main into that feature history. The single add/add
  conflict kept the common roster tests plus the new source-driven negative cases.
  Main's plugin version, executable modes and conformance fixture updates remain.
- Final version/docs/fixture changes and merge result are recorded by Git history
  and TASK-57's operations work product; do not copy an earlier candidate hash
  into a new release claim.

All ephemeral hook state is ignored except the tracked `.gitkeep`. Local debug
state was preserved, not deleted or committed. The historical enforcement archive
and preserved owner-test ref remain intact. High-confidence credential-pattern
checks of staged additions found no matches; this is not a comprehensive secret
audit. No private signing material was read.

## Verification and its limits

Artifacts: `.copilot/evidence/source-integration-5.15.1/` (local, not committed).

- Full portable `cc`: **3,095 passed, 11 skipped**, 339.34 seconds; machine-marked
  cases explicitly deselected. Both formerly failing snapshot tests pass.
- Full `tc`: **585 passed**, 15.58 seconds.
- The root sweep: **239 passed, 1 skipped, 8 failed**, 141.07 seconds. This result
  is retained as a failure, not described as a green full repository run.
- TASK-59 shares the real v2 evidence fixture between both lifecycle shell suites.
  It also fixes test-result parsing of multiline JSON advisories (exit code and
  stdout remain separate). SubagentStop: **40 passed**; QA gate: **18 passed**.
  No production authority or assertion was weakened.
- Additional checks pass: budget boundary pytest (3), optional-context assertions
  (22), command distribution (19), hook registration (4), project shim (11),
  user-prompt hook (21), unchanged owner budget suite (68), and smoke assertions
  (67). Version and locked-export checks also pass. Exact logs are in TASK-57.

The root sweep's failure groups are recorded explicitly, with follow-up TASK-60:

1. Four fitness tests assume an entirely passing fitness baseline. Current checks
   report context-budget excess and deployed-source divergence. The agent corpus
   is 232,590 bytes versus the 204,014-byte absolute ceiling; always-loaded content
   is 27,699 versus 26,268 bytes. Main's agent/command/fitness/baseline source is
   byte-identical to this candidate, establishing these are not introduced by the
   remaining merge repairs. No budget override or silent rebaseline was used.
2. A restore test assumes the author's entire worktree is clean. The release
   metadata/docs were legitimately dirty during that run. Its injected instruction
   changes were restored; final diff inspection confirms they did not leak.
3. Three legacy root QA assertions still expect a message artifact/regex to grant
   approval. The accepted task-authority design instead requires stored, source-
   bound evidence. Their contract migration remains explicit follow-up work;
   production enforcement was not reverted to satisfy them.

The fitness negative tests mutate live instruction files before restoring them
and repeatedly invoke the full fitness checker. Future runs should use disposable
checkouts; this is included in the testing redesign. The seven previously recorded
machine-only failures remain in the [earlier review](14-testing-rethink-evidence-and-recommendations.md)
and were not repeated merely because release metadata changed.

The portable batch ran once after integrating main and setting the versions.
Later changes affected only docs and lifecycle test helpers; those helpers were
verified through both actual shell consumers. The portable code/test/runtime
inputs did not change, so that batch's artifacts were reused rather than restarted.

## Distribution boundaries

No remote push, release tag, GitHub release, signed/notarized package, machine
installation or consumer propagation is implied by this local merge. The configured
developer signing path worked for Git commits; it is not the foundation release
principal. TASK-47's actual foundation-key requirement still applies to macOS
packaging, not to ordinary source integration or Claude configuration distribution.

Before distribution, resolve the applicable release checks, choose the exact
source commit/pins, and perform fresh per-project plan/apply/independent verify.
The human baseline/candidate effectiveness trial is still separate and unperformed.

Recovery: preserve the feature branch and existing main ancestry. If reverting is
needed, revert the final integration commits normally after inspecting intervening
work; never reset shared history or delete preserved evidence to hide a failure.
