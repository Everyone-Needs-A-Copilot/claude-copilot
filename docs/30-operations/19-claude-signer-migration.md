# Claude foundation signer migration

Owner-authorized on 2026-09-09 (PRD-10 / TASK-79), following the explicit choice
to establish a replacement trusted signer. This is a trust migration, not a
claim that the historical key was compromised or revoked.

## Trust decision

The replacement is the owner's existing GitHub Ed25519 signing identity:

```text
SHA256:Dg6yz1MZ4IgBlm+E1TAC49FlVbQ4aaEsvDY7wHNPG5s
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIDGEZqgcjnCXb5XJQvD5/BKBAdO8CJcKYbteehyzu+i
```

Possession was proved by a disposable signed commit, locally verified against
the owner's configured allowed-signers file. No private key was read or copied.
Reusing this key couples Claude release signing to the owner's GitHub signing
identity; it avoids silently provisioning an unprotected new private key.

The historical fingerprint remains compiled for existing installations:
`SHA256:FIfppOkzwXZUAamELQzYoSUQXiEAmTYiVewHe1ACMZo`.
Claude onboarding knows both keys. Codex onboarding and existing Codex manifest
allowlists remain unchanged. Compiled trust alone does not authorize content:
production verification requires the layer's explicit signer allowlist too.

An old runtime cannot authenticate its own replacement trust root. Bootstrap
therefore requires the owner's explicit authorization, review of this exact
public key/source change, successful CI, and local verification of the new
release commit and tag using the approved key. Never accept a new public key
merely because an untrusted release or manifest supplied it.

## Release procedure

1. Prepare one owner-signed candidate directly on the current main commit.
   Record its exact head/base identities; review the diff and all automatic PR
   checks under the [delivery gate](18-ci-acceptance-and-merge-gates.md).
2. Preserve that signed commit with a normal, non-forced fast-forward merge of
   the reviewed PR. Re-read the exact PR head and base before pushing. GitHub's
   server protections remain authoritative; rejection stops publication.
   Do not use an administrator bypass or weaken a rule.
3. Verify every applicable automatic main workflow on the resulting exact SHA.
   GitHub squash/rebase can replace the original signature, so do not assume
   an ordinary GitHub-signed merge satisfies this foundation's SSH policy.
4. Create a new signed annotated semver tag at that main ancestor. Run
   `scripts/verify-foundation-release.sh <repo> <tag> <commit> main` before
   publishing. Both commit and tag signatures, exact target and main ancestry
   remain mandatory. Never rewrite an existing tag.
5. Verify the published tag again. Only then install the exact immutable
   snapshot and change the selected Claude foundation pin and signer policy.

For historical verification, explicitly supply the historical public key via
the existing `FOUNDATION_RELEASE_PUBLIC_KEY` environment setting. That selects
the expected signer; it does not skip either signature or ancestry verification.

GitHub documents [protected local PR merges](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks)
and [ruleset requirements](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets).
Some combinations disallow local merging without bypass; in that case stop
and request a separate policy decision instead of changing protections.

## Installation acceptance and recovery

Publication is not installation acceptance. TASK-78 owns the explicit Mac and
consumer target list, before/after hashes, tier/customization classification,
recoverable backups outside agent discovery, and actual installed verification.
Claude authoring layers are not disposable consumer installations. Do not
overwrite unknown differences or change Codex pins as part of this migration.

Use `scripts/install-framework-snapshot.py --claude-only` with the verified
source root, commit and tree for this rollout. It installs the shared cc/tc
runtime and declared Claude machine commands without invoking Codex or altering
its plugin registrations. The receipt marks Codex unselected, not verified.
The default combined installer retains its existing Codex normalization and
verification behavior; the scoped option does not weaken selected checks.

Acceptance requires intended tier-resolved agents and commands, preserved
customizations, provenance, no duplicate active names, the existing context
budget, the current proportional-testing/fixed-finish-line instructions, and
a second reconciliation that proposes no changes. Repository CI alone, a
source-directory check, or an agent's self-description cannot prove this.

Keep old snapshots and byte-verified target backups. Recovery restores the
reviewed previous shim, configuration, locks and managed files from that receipt;
it does not rewrite Git history or revoke keys. Record any pre-existing invalid
old pin so restoring old state is not misrepresented as a trusted release.
Once release and installation criteria have current task-bound QA approval,
close those tasks and stop. No unrelated cleanup or additional test platform
is part of this batch.
