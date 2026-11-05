# cc CLI guide

## Purpose

Discover shared skills, preserve memory, resolve Copilot configuration and manage the local Copilot installation. Use `tc` for task state and `copilot` for service integrations.

## Setup and identity

Install with `bash tools/cc/install.sh` from the framework checkout; verify `command -v cc` selects Copilot rather than a C compiler, then `cc --version`. Run from the intended project so project config and memory scope resolve correctly. [Configuration and installation](README.md) describes machine/project precedence and `cc config where`. Do not use `cc env --include-secrets` for discovery; ordinary help requires no secrets.

## Command discovery

Start with `cc --help`, then `cc skill --help`, then the selected command's `--help`. The [complete parser-generated reference](CLI-commands.md) includes registered groups, commands, aliases and parameters. Optional installed extensions can change the available tree; the installed help is authoritative for that installation.

## Intent and examples

| Intent | Command | Prerequisites, effects and expected result |
|---|---|---|
| Find the right capability | `cc skill search "CLI"` | Reads the configured skill catalog; returns matching skills. |
| Inspect a capability | `cc skill get cli-authoring` | Reads the selected skill; a missing skill is an availability issue, not an invented command. |
| Explain configuration provenance | `cc config where paths.knowledge_repo` | Reads configuration and reports its source. |
| Inspect installation observations | `cc status --json` | Reports recorded observations without running probes. |

## Inputs and outputs

Structured output is per-command: use `--json` only where its help lists it, after the appropriate subcommand. `cc env` normally emits shell exports; `cc env --json` emits structured data. Help, tables and diagnostic text are human interfaces. Usage errors and failed commands can exit nonzero; doctor/probe results must also be read for individual check status. Published ecosystem schemas remain the authority for their versioned outputs.

## Effects and verification

Skill/config reads and status inspection are local reads. Memory store, config set, connect, reconciliation and updates write state; auth and docs fallback can use the network. `doctor` runs probes, unlike `status`. `repair` is explicitly an engine-blocked stub in this release. Reconciliation has assess/plan/apply/recover stages; use its documented plan identity and verify result rather than inventing a universal dry-run.

## Errors and recovery

If `cc` is the compiler, select the installed Copilot executable from `~/.local/bin`. Missing config: inspect `cc config where KEY` and the configuration README before changing the appropriate scope. Missing skill: check `cc skill list` and the configured tier. Interrupted reconciliation: follow the README recovery procedure for the existing transaction; do not replace the lock or discard evidence.

## Maintenance

Follow the [shared CLI creation standard](https://github.com/Everyone-Needs-A-Copilot/cli-copilot/blob/main/docs/04-cli-standard.md). [Full command and configuration guide](README.md). Regenerate this command reference from the selected source and parser environment with the foundation's `scripts/export-cli-reference.py`; verify offline help and example parsing, then run `scripts/check-cli-guide.py` on this guide. References describe the checked-out source, not a claim that a release is installed.

Fast documentation check from this repository: `CLI_STANDARD_ROOT=/path/to/cli-copilot sh scripts/check-cli-docs.sh`. Select the foundation checkout containing the standard; `PYTHON_BIN` selects a working Python 3.
