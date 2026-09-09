# Start a foundation task once

Use one entry path: **set up the project through the existing adapter, start with
`/protocol`, verify the agreed behavior, then stop when task-bound QA passes.**
This is a shorter operating path, not another installer or a partial installation
profile. The complete local Claude + Codex reference remains the setup contract.

## First project setup

Open the target Git repository in Claude Code and run `/setup-project`. That
adapter checks the real Copilot `cc` and `tc`, builds an exact read-only
`cc reconcile plan`, asks for confirmation, applies that plan, and runs fresh
`cc reconcile verify`. Follow the adapter's reported holds; do not copy framework
files manually or reset project-owned work to make setup appear complete.

If the CLIs are absent, follow the existing `/setup` machine prerequisite route,
then return to this project. `cc onboard` is ecosystem discovery/onboarding, not
an extra project installer; its `--apply` can create repositories and is not part
of ordinary task verification. Do not run machine-wide reconciliation as a shortcut
for setting up one selected project.

The former `minimal`/`quick start` partial profile is retired. Required reference
files and QA authority are not optional. Organization/private knowledge, extra
skills, model evaluations and frontend pilots are separate explicit choices.
Codex capability packs remain opt-in in their native foundation.

## The normal task

Start with `/protocol` and the concrete result you need. Agree on the deliverable,
acceptance criteria, affected consumers, verification scope/cap and exclusions
before implementation. Keep live work and evidence in `tc`, not another task board.

The specialist route selects existing meaningful checks and fills missing behavior
coverage. A new source file does not automatically require another test or a full
suite. An unrelated discovery becomes separate recorded work; a defect blocking a
required criterion still blocks completion. When the required source-bound QA is
approved, close the task and stop—not another audit or improvement loop.

## Shared verification in either runtime

Claude and Codex use the same local `cc verify` commands; no second runner or
agent chain is required. Confirm the actual binary has the capability:

```sh
cc --version
cc verify --help
cc status --help
```

Bare `cc` can be the system C compiler. Use the verified Copilot executable, often
`$HOME/.local/bin/cc`; a version label alone does not prove the installed snapshot
contains `verify`. From a prepared Claude foundation development checkout, the
explicit source invocation is `tools/cc/.venv/bin/python -m cc.main verify ...`.
Do not install or replace machine CLIs merely to run a source check.

For the local overview, use `cc status --project /absolute/path/to/project --json`.
It reports observed installation/registration and the latest verification
plan/lane/cap/artifact; activated, running and blocked state remains unknown unless
observed. This command is a source-only addition in the development `cc 2.13.1`,
not a capability proven present in an earlier published/tagged `2.13.1` snapshot.

In a project with a reviewed, project-owned `verification.json`:

```sh
mkdir -p .copilot
cc verify plan --base HEAD --task TASK_ID --json > .copilot/verification-plan.json
# Inspect the saved lanes, reasons, inputs and caps before execution.
cc verify run --plan .copilot/verification-plan.json --json
cc verify status --run RUN_ID --json
```

Replace `TASK_ID` with the current task and `RUN_ID` with the emitted run ID.
`HEAD` means the current uncommitted change; use the actual review base for a
committed batch. A plan only selects checks; it executes no manifest command.
Status reads private local artifacts and does not mutate the task.

Setup does **not** invent an application's assertions or automatically install a
verification manifest. If the project has none, the engineer and QA select the
project's real commands and explicitly author/review that small manifest; until
then run the selected commands directly and store their results in `tc`. Do not
copy the foundation's broad suite into an unrelated application or call missing
verification green. Manifest commands have the user's permissions; inspect them
before running an unfamiliar checkout.

For example, an existing Python project that already uses unittest could declare:

```json
{
  "schemaVersion": 1,
  "inputs": ["src", "tests", "pyproject.toml"],
  "fallbackLanes": ["project-tests"],
  "lanes": [{
    "id": "project-tests",
    "description": "Project-owned behavior checks",
    "paths": ["src/**", "tests/**"],
    "argv": ["{python}", "-m", "unittest", "discover", "-s", "tests", "-v"],
    "cwd": ".",
    "timeoutSeconds": 60,
    "hermetic": false
  }]
}
```

Adapt inputs, interpreter/environment and commands to the real project. This is
an example contract, not a bundled application test or evidence of adequate coverage.
An explicitly chosen lane is a scope decision, not whole-change coverage proof.

## What passing means

The runner preserves logs, status, exit codes and elapsed time under
`.copilot/verification/`; keep artifacts local/private. Failure remains failure.
A timeout or missing required evidence is incomplete and needs an explicit next
scope/cap decision, not automatic retries. `cc verify` never grants approval:
current criteria, exact source identity, observations and artifacts still go
through the existing `tc` QA gate.

This operating path does not certify machine installation, hosted CI, a release,
hook trust, optional model effectiveness or a consuming UI pilot. See the
[implemented verification boundary](../40-initiatives/01-risk-based-verification/phases/01-foundation-implementation.md)
and [source integration record](15-source-integration-5.15.1.md).
