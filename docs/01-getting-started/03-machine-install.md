# Install the framework once per machine

**Diátaxis mode:** How-to

Goal: make a new machine resolve the framework centrally, then add any project with `cc project init`. After this, you never copy framework files into a project. Design: [ADR-001](../40-initiatives/06-central-resolution/decisions/ADR-001-central-release-pointer.md).

Status: delivered in framework 5.35.0 (cc 2.19.0). `cc release build` builds a release (add `--flip` to switch to it); `cc release publish` does build, flip, links, marketplace refresh and doctor in one command.

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

### Signer fingerprints for pinned tiers

Every tier pinned to a signed tag (foundation, organization and department tiers) is verified against the `policy.allowed_signers` list of its layer in `~/.config/copilot/copilot.layers.yml`. Each entry is the SSH signing-key fingerprint of an allowed signer, in the form `SHA256:<base64>` as printed by `ssh-keygen -lf <public key>`. A pinned tier with an empty or missing list cannot be verified and the build refuses it, so add the fingerprint of every key that signs release tags before running `cc release publish`. Personal tiers are live links to your own checkouts, are not signature-checked, and keep `allowed_signers: []`. Check a tag by hand with `git tag -v <tag>`; the signer it reports must match a listed fingerprint.

### Isolated runs

`COPILOT_HOME` names the copilot directory (it must end in `.copilot`) and applies to every `cc release` command and the `copilot` launcher; its parent plays the home, so `~/.claude`, `~/.codex` and the `~/.local/bin` shims move with it. Use it to rehearse a flip, rollback or publish without touching the real machine. A value that does not end in `.copilot` is refused before any command runs. `--home` overrides it.

## 4. Trust the Codex hooks

Codex asks for trust once per hook definition, not per release. Open Codex, run `/hooks`, and trust the `codex-copilot@enac-materialized` hooks, including `codex-copilot@enac-materialized:hooks/hooks.json:pre_tool_use:1:0` (the coordinator guard). Hook definitions stay byte-identical across releases (the Codex plugin is a frozen core), and the trust gate refuses a release flip that would change plugin content and force a re-trust, so later releases do not ask again.

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

Takes seconds. It writes the `copilot.project.json` marker, adds thin project sections to `CLAUDE.md` and `AGENTS.md` only if absent, registers Codex trust for the path and updates `.gitignore`. It works in a non-Git folder or returns a clean JSON error. To convert an already synced project use `cc project migrate` (dry run; add `--apply`), and `cc project migrate --scan <roots>` reports remaining copies and locks across projects.

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
