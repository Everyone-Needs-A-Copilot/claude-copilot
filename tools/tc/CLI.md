# tc CLI guide

## Purpose

Track PRDs, tasks, dependencies, handoffs and work products with persisted acceptance evidence. This is the authority for execution state; Markdown summaries do not replace its records.

## Setup and identity

`tc-limits` is a compatibility alias of the maintained `tc`; it adds no commands or output flags. Its shim is `tools/tc/tc-limits`. Install with `bash tools/tc/install.sh`; inspect `tc version`. Run from the intended project. The database normally lives at `.copilot/tasks.db`; worktree/database resolution and explicit overrides are described in [the README](README.md). `tc init` creates data and is not a discovery command. Help works without a task database.

## Command discovery

Start with `tc --help`, then `tc task --help`, then the selected command's `--help`. The [complete parser-generated reference](CLI-commands.md) includes registered groups, commands, aliases and parameters. Optional installed extensions can change the available tree; the installed help is authoritative for that installation.

## Intent and examples

| Intent | Command | Prerequisites, effects and expected result |
|---|---|---|
| Inspect outstanding work | `tc task list --json` | Reads tasks from the selected project database. |
| Inspect one task | `tc task get 7 --json` | Replace 7 with the intended task ID; returns that task, not a globally unique identity. |
| Understand evidence requirements | `tc task contract --help` | Offline; inspect how to register an acceptance contract. |
| Inspect execution limits | `tc execution status 7` | Reads the selected task ledger; inspect its state before a new attempt. |

## Inputs and outputs

`--json` belongs to individual commands that advertise it, not the root. Tables and dashboard/watch output are human-oriented. Task/WP identifiers are scoped to the selected database. Parser errors exit nonzero; acceptance and execution refusals are not successes. See the README for the programmatic `tc.api` transaction path when chaining operations; preserve its typed exceptions.

## Effects and verification

Create/update/contract/evidence operations write local task state; init creates a database. Archive moves records into history and requires its documented preservation process. `execution run` and `worker` can execute programs; deploy can affect remote services. List/get are inspection paths, but auto-archive policy must be considered when operating the CLI; set `TC_AUTO_ARCHIVE=0` for preservation-sensitive batches. Verify mutations with task get and source-bound evidence; never weaken acceptance to obtain completion.

## Errors and recovery

Missing database: confirm the project path and existing ledger before considering init. Unknown task: confirm both database and ID. QA refusal: inspect `tc task check-qa ID --json`, the registered contract and evidence identity; correct the failed criterion. Execution stop: inspect the ledger and follow its prove/diagnose or owner-authorized reopen procedure. Do not create a new task to reset consumed attempts.

## Maintenance

Follow the [shared CLI creation standard](https://github.com/Everyone-Needs-A-Copilot/cli-copilot/blob/main/docs/04-cli-standard.md). [Workflows, API and execution contracts](README.md). Regenerate this command reference from the selected source and parser environment with the foundation's `scripts/export-cli-reference.py`; verify offline help and example parsing, then run `scripts/check-cli-guide.py` on this guide. References describe the checked-out source, not a claim that a release is installed.

Fast documentation check from this repository: `CLI_STANDARD_ROOT=/path/to/cli-copilot sh scripts/check-cli-docs.sh`. Select the foundation checkout containing the standard; `PYTHON_BIN` selects a working Python 3.
