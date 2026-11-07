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
| Inspect one project's wiring | `cc project status /path/to/project --json` | Reads exactly that folder and its registration/trust metadata; returns `initialized`, `needs-init` or `blocked`. Machine health is separate. |
| List registered and approved projects | `cc project status --all --json` | Reads registered paths and bounded discovery inside approved folders; never searches home or unapproved candidates. |
| Connect a project to both runtimes | `cc project init /path/to/project --json` | Writes the marker, thin instruction sections, Codex trust and registration while preserving project rules. Copies no framework files; inspect project status afterward. |

## Inputs and outputs

Structured output is per-command: use `--json` only where its help lists it, after the appropriate subcommand. `cc env` normally emits shell exports; `cc env --json` emits structured data. Help, tables and diagnostic text are human interfaces. Usage errors and failed commands can exit nonzero; doctor/probe results must also be read for individual check status. Published ecosystem schemas remain the authority for their versioned outputs.

## Effects and verification

Skill/config reads and project status inspection are local reads. Memory store, config set, connect and project init write state; auth and docs fallback can use the network. Project init is the single writer for thin Claude and Codex integration. `initialized` confirms local wiring; use `cc release doctor` for machine health. Project migration prints a plan by default and writes only with `--apply`; releases and machine-wide updates change the central installation. Reconciliation and per-project copy/update workflows are retired and exit 2 with replacement guidance.

## Errors and recovery

If `cc` is the compiler, select the installed Copilot executable from `~/.local/bin`. Missing config: inspect `cc config where KEY` and the configuration README before changing the appropriate scope. Missing skill: check `cc skill list` and the configured tier. A `blocked` project status names the malformed settings, unavailable folder or existing Codex access decision to review; preserved state is not silently overwritten. Inspect status again after resolving that issue. An interrupted migration uses its retained backup manifest: `cc project migrate --rollback --manifest /path/to/manifest` restores recorded state and reports conflicts for review.

## Maintenance

Follow the [shared CLI creation standard](https://github.com/Everyone-Needs-A-Copilot/cli-copilot/blob/main/docs/04-cli-standard.md). [Full command and configuration guide](README.md). Regenerate this command reference from the selected source and parser environment with the foundation's `scripts/export-cli-reference.py`; verify offline help and example parsing, then run `scripts/check-cli-guide.py` on this guide. References describe the checked-out source, not a claim that a release is installed.

Fast documentation check from this repository: `CLI_STANDARD_ROOT=/path/to/cli-copilot sh scripts/check-cli-docs.sh`. Select the foundation checkout containing the standard; `PYTHON_BIN` selects a working Python 3.
