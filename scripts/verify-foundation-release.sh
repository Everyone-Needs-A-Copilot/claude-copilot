#!/usr/bin/env bash
# Verify the trust properties required by cc before a foundation release can
# be packaged: an exact annotated, signed semver tag whose target commit is
# a real, provable ancestor of the branch it was cut from.
#
# RC-3 (fixed 2026-08-10): this script used to REQUIRE the tagged commit to
# be parentless ("a signed, parentless snapshot commit"), because
# `foundation-snapshot-release.py` used to fabricate one via `git
# commit-tree` with no parent. A parentless commit can never satisfy `git
# merge-base --is-ancestor <ref> <branch>` -- it produced 61+ real,
# published tags whose pin-ancestry could never be proven. The release-cut
# tool no longer fabricates a commit at all: it signs the real branch commit
# directly, so the trust anchor is the signed TAG (`verify-tag`), and the
# property this script must prove is ANCESTRY, not parentlessness. See
# `scripts/foundation-snapshot-release.py`'s module docstring in
# copilot-control-tower for the full root-cause writeup.
#
# Security review (2026-08-10): the RC-3 diff that added the ancestry check
# above ALSO silently dropped a second, independent check this script always
# had -- `git verify-commit ${SOURCE_COMMIT}`. Without it, a signed tag
# placed over an UNSIGNED commit passed this preflight (the tag's signature
# alone was treated as sufficient). Both signatures are required: the TAG's
# signature proves someone holding the release key vouched for THIS exact
# commit SHA at cut time; the COMMIT's own signature is an independent proof
# that the release key holder also signed the content itself, so a single
# compromised or misused verification path (tag-only or commit-only) is
# never enough on its own. Restored below, unconditionally, alongside the
# ancestry and tag checks -- no flag can skip any of the three.

set -euo pipefail

REPO="${1:-}"
SOURCE_REF="${2:-}"
SOURCE_COMMIT="${3:-}"
BRANCH="${4:-main}"

die() {
    echo "error: $*" >&2
    exit 1
}

[[ -d "${REPO}/.git" ]] || die "repository is missing: ${REPO}"
[[ "${SOURCE_REF}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] ||
    die "foundation source ref must be an exact vMAJOR.MINOR.PATCH tag"
[[ "${SOURCE_COMMIT}" =~ ^[0-9a-f]{40}$ ]] ||
    die "source commit must be a full lowercase 40-character SHA"

tag_ref="refs/tags/${SOURCE_REF}"
[[ "$(git -C "${REPO}" cat-file -t "${tag_ref}" 2>/dev/null || true)" == "tag" ]] ||
    die "${SOURCE_REF} must be an annotated tag"

resolved_commit="$(git -C "${REPO}" rev-parse "${tag_ref}^{}")"
[[ "${resolved_commit}" == "${SOURCE_COMMIT}" ]] ||
    die "${SOURCE_REF} resolves to ${resolved_commit}, not ${SOURCE_COMMIT}"

branch_ref=""
for candidate in "origin/${BRANCH}" "${BRANCH}"; do
    if git -C "${REPO}" rev-parse --verify "${candidate}^{commit}" >/dev/null 2>&1; then
        branch_ref="${candidate}"
        break
    fi
done
[[ -n "${branch_ref}" ]] ||
    die "neither origin/${BRANCH} nor ${BRANCH} resolves in ${REPO} -- pass a real branch as arg 4"

git -C "${REPO}" merge-base --is-ancestor "${SOURCE_COMMIT}" "${branch_ref}" ||
    die "${SOURCE_COMMIT} is not an ancestor of ${branch_ref} (RC-3: refusing a release-cut step that is not a real descendant of the branch it claims)"

principal="${FOUNDATION_RELEASE_PRINCIPAL:-enac-foundation}"
public_key="${FOUNDATION_RELEASE_PUBLIC_KEY:-ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINah8Gf036FQkhMcUU35m2p7Nqa41oBtVS/QV9tYZX8H}"
trust_file="$(mktemp "${TMPDIR:-/tmp}/foundation-release-signers.XXXXXX")"
cleanup() {
    rm -f "${trust_file}"
}
trap cleanup EXIT
chmod 600 "${trust_file}"
printf '%s namespaces="git" %s\n' "${principal}" "${public_key}" >"${trust_file}"

verify_args=(
    -c gpg.format=ssh
    -c "gpg.ssh.allowedSignersFile=${trust_file}"
    -C "${REPO}"
)
git "${verify_args[@]}" verify-commit "${SOURCE_COMMIT}" >/dev/null 2>&1 ||
    die "commit ${SOURCE_COMMIT} does not have a valid foundation release signature"
git "${verify_args[@]}" verify-tag "${tag_ref}" >/dev/null 2>&1 ||
    die "${SOURCE_REF} does not have a valid foundation release signature"

echo "foundation release signatures: verified (${SOURCE_REF} -> ${SOURCE_COMMIT}, ancestor of ${branch_ref})"
