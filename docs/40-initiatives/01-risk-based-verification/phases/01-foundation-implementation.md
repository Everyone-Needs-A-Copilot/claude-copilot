# Foundation implementation and local operation

Execution context: Claude PRD-5 / TASK-60–63; Codex PRD-12 / TASK-29.
These are unreleased source changes, not a machine installation or consumer rollout.
Local verification results and final task-bound QA live in `tc`; the source is
not a fully green distribution or a completed adoption trial.

## What is implemented

- Claude and Codex engineering/QA rules select checks by behavior and affected
  consumers. Missing behavior coverage still needs tests; an edited file alone
  does not require a new test or another complete suite.
- `cc verify plan`, `run` and `status` provide opt-in local execution. The runner
  starts ordinary processes, not agents or model inference. It never approves a
  task, changes a task's status, starts a service, or uploads artifacts.
- A versioned, repository-owned `verification.json` declares named argument arrays,
  working directories, input identities and execution caps. It is executable
  project configuration: inspect it before running it in an unfamiliar checkout.
- Legacy root QA assertions exercise stored tc v2 evidence and rejection cases.
  Fitness negative controls use disposable copies, not the author's live files.
- Portable conformance pytest has one Linux owner. Its named CI status depends on
  successful full portable cc execution, including failure/skip handling. Distinct
  macOS coverage remains. Hosted execution and branch-rule compatibility still
  require verification before remote adoption.
- Codex smoke discovers its Python tests once, with named progress, a bounded cap,
  empty-inventory rejection and failure/timeout propagation before later steps.

## Use from this source checkout

Use the repository's development environment with its declared dependencies. The
already-installed `cc` may still be an older immutable snapshot; no machine CLI
installation is implied by editing the source.

From the Claude Copilot repository root:

```sh
tools/cc/.venv/bin/python -m cc.main verify plan --base HEAD --task 63 --json
```

Planning executes no manifest test command. Inspect the selected lanes, reasons,
exclusions and caps, then save that JSON outside declared source inputs, for example
as `.copilot/verification-plan.json`. Execute the saved plan explicitly:

```sh
tools/cc/.venv/bin/python -m cc.main verify run --plan .copilot/verification-plan.json --json
tools/cc/.venv/bin/python -m cc.main verify status --run RUN_ID --json
```

For a deliberate focused check, select a named lane:

```sh
tools/cc/.venv/bin/python -m cc.main verify plan --lane instruction-context --task 63 --json
```

An explicit lane is a recorded scope decision, not proof that all changed behavior
is covered. `--changed PATH` can be repeated when supplying a known change list;
`--base` also includes dirty and untracked nonignored paths. Any unmapped path in
a mixed change list adds the broad fallback. No supplied change information also
selects broad checks. Planning is intentionally conservative, not a dependency
graph or a semantic understanding of arbitrary code changes.

The manifest's broad fallback covers complete discovered portable cc, tc and root
pytest directories plus the actual QA-gate and SubagentStop shell consumers.
Caps total 900 seconds of test execution: cc 600, tc 60, root 120, and each lifecycle
shell suite 60. These are operational limits, not delivery estimates; preparation
and identity checks are separate overhead. Other platform, vendored TUI, skill
self-test and release checks retain their existing CI owners. This local fallback
does not replace every CI job or certify a distribution.

## Visibility, failure and privacy

The first progress message publishes the run ID and artifact directory so another
terminal can inspect status while the command is still running. Progress on stderr
names the lane, elapsed time, cap and log bytes at least every
30 seconds. JSON stdout stays machine-readable. This initial adapter does not
promise live per-test progress: JUnit case IDs, pass/fail/skip counts and reasons
are available after a command writes its report. Shell output remains in logs.

Each run has a unique private local directory under `.copilot/verification/` with
the exact plan, atomic status updates and per-lane stdout/stderr. Reports retain
exit codes, process IDs, elapsed time and artifact hashes. Normal summaries omit
environment values and raw command output; raw logs and media can still contain
application data and require private handling. There is no automatic upload.

Failures stay failed. Timeout, cancellation, excessive output, missing required
JUnit, zero executed tests, or changing inputs are incomplete, not green. The
runner signals only its own process group, including remaining child processes;
it never kills unrelated Python/browser processes by name. Execution currently
requires POSIX (macOS/Linux). Process control is not a sandbox: a trusted manifest
command still has the invoking user's filesystem and network permissions.

## Evidence and reuse

Plans bind the selected commands to the current manifest and declared source,
test, dependency, runtime and environment identities. Modified plans and stale
inputs are rejected. A new plan is required after relevant changes.

Reuse is explicit (`run --reuse`) and limited to declared hermetic lanes with an
identical execution fingerprint and intact successful artifacts. All lanes in
this initial foundation manifest are deliberately **non-hermetic**, so they do
not reuse automatically or under that flag. The repository has not yet proven
that its source-derived installation and machine-sensitive fixtures are safely
cacheable. This conservative default is preferable to claiming reuse we cannot
justify. Agents may reference unchanged prior check artifacts when explaining
their scoped verification; each task still requires its own current acceptance
mapping and tc identity.

## What remains separate

The real frontend/defect and test-data reset have not been selected. The runner
can execute an explicit Playwright command and parse JUnit, but that is not a
completed UI pilot, browser installation, or proof of visual behavior. Application
owners must supply the scenario, equivalent before/after data, semantic assertions,
private trace/video configuration and retained regression.

Context-budget/deployed-source fitness failures are not erased by narrowing
negative controls to the behavior they exercise. Broader instruction deduplication,
installer-fixture profiling, Codex structural-evaluation artifact retention and
safe cache adoption remain separate work. No context baseline was raised.

The matched adoption trial and target reduction in verification-cycle time are
still unperformed. No token savings, defect-rate improvement or cross-machine
performance result is claimed. Source review and local checks are not hosted CI,
a release tag, package signing or project propagation.

## Recorded local checks

One supervised portable batch (`fe1dce89179b4c2ba1bc95e0d5c79f07`) completed with
cc **3,144 passed / 11 skipped** (324.506 seconds), root **279 passed / 1 skipped**
(36.882 seconds), tc **585 passed** (14.614 seconds), and passing QA-gate and
SubagentStop shell lanes (4.866 and 10.478 seconds). These are local observations
under concurrent work, not matched performance benchmarks. Machine tests and the
full fitness/smoke release gates are separate; root pytest passing does not mean
context-budget/deployed-source fitness passed.

Independent review reproduced and repaired stale Git change selection, malformed
status acceptance and contradictory JUnit acceptance; the same three scenarios
then rejected safely. A final related refinement binds explicitly changed file
content even when a broad fallback handles an otherwise unmapped path. That
refinement and expanded manifest input coverage followed the broad batch and use
focused runner/integration checks; unchanged suites are not represented as freshly
rerun against those final edits. See TASK-62/63 for exact identities and outcomes.

Codex's actual smoke discovery block found **54 tests**, with **53 passed / 1
failed** in 16.84 seconds and correctly returned failure before later smoke steps.
The unchanged parity roundtrip test compares adopted framework/cc versions
5.15.0/2.13.0 with the live upstream 5.15.1/2.13.1, despite updating only a temporary
content baseline. That upstream adoption mismatch remains explicit; no release
pin or baseline was reset. The new policy/integrity/smoke checks separately passed
**14 tests** in 6.457 seconds, including default rejection of unreviewed changes,
exact receipt validation, discovered failure, empty inventory and timeout cleanup.

Remaining implementation and pilot work is retained in TASK-64–66; this document
is not a duplicate live task board. Consumer configuration, the installed CLI and
Claude's vendored Codex plugin were not propagated from these source edits.

Recovery: stop using the opt-in runner and use the existing direct test commands;
retain its evidence. Revert policy/CI changes through normal reviewed Git changes
if required detection regresses; do not delete failing tests or reset shared history.
