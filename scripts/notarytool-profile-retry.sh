#!/usr/bin/env bash
# Run one notarytool command with a stored Data Protection Keychain profile.
# Retry only the transient local lookup failure that notarytool can report from
# detached or newly launched process contexts. Remote authentication failures,
# rejected submissions, and every other error remain fail-closed.

set -euo pipefail

PROFILE=""
ATTEMPTS="${CT_NOTARY_PROFILE_ATTEMPTS:-3}"
RETRY_DELAY="${CT_NOTARY_PROFILE_RETRY_DELAY:-1}"

die() {
    echo "error: $*" >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile)
            [[ $# -ge 2 ]] || die "--profile requires a value"
            PROFILE="$2"
            shift 2
            ;;
        --)
            shift
            break
            ;;
        *)
            die "unknown option before --: $1"
            ;;
    esac
done

[[ -n "${PROFILE}" ]] || die "--profile is required"
[[ $# -gt 0 ]] || die "a notarytool command is required after --"
[[ "${ATTEMPTS}" =~ ^[1-9][0-9]*$ ]] ||
    die "CT_NOTARY_PROFILE_ATTEMPTS must be a positive integer"
[[ "${RETRY_DELAY}" =~ ^[0-9]+([.][0-9]+)?$ ]] ||
    die "CT_NOTARY_PROFILE_RETRY_DELAY must be a non-negative number"
command -v xcrun >/dev/null 2>&1 || die "xcrun is required but was not found"

scratch="$(mktemp -d "${TMPDIR:-/tmp}/notarytool-profile.XXXXXX")"
cleanup() {
    rm -rf "${scratch}"
}
trap cleanup EXIT

attempt=1
while (( attempt <= ATTEMPTS )); do
    stdout_path="${scratch}/stdout-${attempt}"
    stderr_path="${scratch}/stderr-${attempt}"
    set +e
    xcrun notarytool "$@" --keychain-profile "${PROFILE}" \
        >"${stdout_path}" 2>"${stderr_path}"
    status=$?
    set -e

    if [[ "${status}" -eq 0 ]]; then
        cat "${stdout_path}"
        cat "${stderr_path}" >&2
        exit 0
    fi

    if ! grep -Eqi \
        'No Keychain password item found|specified item could not be found in the keychain' \
        "${stderr_path}"; then
        cat "${stdout_path}"
        cat "${stderr_path}" >&2
        exit "${status}"
    fi

    if (( attempt < ATTEMPTS )); then
        echo "release: notarization profile '${PROFILE}' was temporarily unavailable to this process (attempt ${attempt}/${ATTEMPTS}); retrying" >&2
        if [[ "${RETRY_DELAY}" != "0" ]]; then
            sleep "${RETRY_DELAY}"
        fi
    fi
    attempt=$((attempt + 1))
done

cat "${stderr_path}" >&2
echo "error: notarytool could not access profile '${PROFILE}' after ${ATTEMPTS} attempts." >&2
echo "       This does not prove the Data Protection Keychain item was deleted." >&2
echo "       Re-run 'xcrun notarytool history --keychain-profile ${PROFILE}' from the logged-in user's fresh Terminal session; if it succeeds, continue without recreating credentials." >&2
exit "${status}"
