# Install the framework once per machine

**Diátaxis mode:** How-to

Goal: make a new machine resolve the framework centrally, then add any project with `cc project init`. After this, you never copy framework files into a project. Design: [ADR-001](../40-initiatives/06-central-resolution/decisions/ADR-001-central-release-pointer.md).

Status: the `cc release` and `cc project` commands below are delivered by the central-resolution initiative (PRD-16). Until the first release is published, use the commands in [the user journey](01-user-journey.md).

## Prerequisites

- macOS with Git, Python 3, and the Claude Code and Codex CLIs installed and signed in.
- Access to the CSE repositories, with the signing keys needed to verify company-tier tags.
- `~/.config/copilot/copilot.layers.yml` listing the pinned tags for the foundation, organization and department tiers.
- Existing owner content in `~/.claude` and `~/.codex` is fine: links are per item and only links the tool created are ever removed.

## 1. Clone the CSE repositories

Clone `claude-copilot`, `codex-copilot`, `cli-copilot`, `product-creation-copilot` and your knowledge tier repositories under `/Volumes/Dev/Sites/CSE/` (or your machine's equivalent root).

## 2. Install the tools

```bash
cd /Volumes/Dev/Sites/CSE/claude-copilot
bash tools/cc/install.sh
```

Confirm `cc --help` and `tc --help` run.

## 3. Publish the first release

```bash
cc release publish
```

This builds an immutable release under `~/.copilot/releases/<release-id>/`, verifies tier signatures, flips `~/.copilot/current` to it, links agents, commands and skills into `~/.claude` and `~/.codex`, refreshes the single Codex marketplace `enac-materialized`, runs `cc doctor --release` and appends `~/.copilot/release-history.jsonl`. If any step fails, `current` is unchanged or rolled back and the command says which step failed.

## 4. Trust the Codex hooks

Codex asks for trust once per hook definition, not per release. Open Codex, run `/hooks`, and trust the `codex-copilot@enac-materialized` hooks, including `codex-copilot@enac-materialized:hooks/hooks.json:pre_tool_use:1:0` (the coordinator guard). Hook definitions stay byte-identical across releases, so later releases do not ask again.

## 5. Verify

```bash
cc doctor --release
```

Expected: `current` resolves to a valid release, every link resolves inside `current` or a personal checkout, none targets a `.worktrees/` path, the Codex cache version equals `release.json`, and `codex-copilot@enac-materialized` is the only enabled Copilot Codex plugin source.

## 6. Add a project

```bash
cd /path/to/project
cc project init
```

Takes seconds. It writes the `copilot.project.json` marker, adds thin project sections to `CLAUDE.md` and `AGENTS.md` only if absent, registers Codex trust for the path and updates `.gitignore`. It works in a non-Git folder or returns a clean JSON error.

## Roll back

```bash
cc release rollback            # previous release
cc release rollback --to <id>  # a named release
```

Rollback flips `current` back, refreshes the Codex marketplace (old versions stay cached) and reruns doctor. Releases are immutable, so nothing is rebuilt. Pruning old releases is separate: `cc release prune --keep 5` lists exact paths and runs only with owner approval.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Framework hooks silent in a project | No `copilot.project.json` marker | Run `cc project init` |
| `cc` or `tc` shim prints a line naming `cc release status` | `current` missing or dangling | Run `cc release publish` or `cc release rollback` |
| `cc doctor --release` reports Codex cache version mismatch | Marketplace refresh failed | Treat the release as failed; roll back, then retry |
| Codex asks for hook trust again | A hook definition or the marketplace name changed | Re-trust once; check the release notes declared it |
| Project fails closed | `.claude/copilot-required` is present and the machine install is missing | Complete steps 1 to 5 |
