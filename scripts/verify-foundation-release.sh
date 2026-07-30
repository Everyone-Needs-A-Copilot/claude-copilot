#!/usr/bin/env bash
# Verify the trust properties required by cc before a foundation release can
# be packaged: an exact annotated semver tag over a signed, parentless snapshot
# commit. A signed tag alone is insufficient because materialization verifies
# the commit that introduced executable content.

set -euo pipefail

REPO="${1:-}"
SOURCE_REF="${2:-}"
SOURCE_COMMIT="${3:-}"

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

read -r -a commit_line <<<"$(git -C "${REPO}" rev-list --parents -n 1 "${SOURCE_COMMIT}")"
[[ "${#commit_line[@]}" -eq 1 ]] ||
    die "${SOURCE_COMMIT} must be a parentless foundation snapshot commit"

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
git "${verify_args[@]}" verify-tag "${tag_ref}" >/dev/null 2>&1 ||
    die "${SOURCE_REF} does not have a valid foundation release signature"
git "${verify_args[@]}" verify-commit "${SOURCE_COMMIT}" >/dev/null 2>&1 ||
    die "commit ${SOURCE_COMMIT} does not have a valid foundation release signature"

echo "foundation release signatures: verified (${SOURCE_REF} -> ${SOURCE_COMMIT})"
