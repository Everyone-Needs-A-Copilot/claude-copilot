#!/usr/bin/env bash
# Build cc from an exact immutable foundation tag as a universal macOS
# executable, sign it under the upstream Claude Copilot authority, submit it
# to Apple's notary service, and emit the artifact plus provenance metadata.
#
# This is the producing side of Control Tower's verify-not-resign contract:
# Control Tower pins and verifies this artifact; it never signs it again.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RELEASE_HOME="${HOME:?HOME must be set for the Finder-environment release probe}"

PYTHON_VERSION="3.13.13"
PYTHON_PACKAGE="python-${PYTHON_VERSION}-macos11.pkg"
PYTHON_URL="https://www.python.org/ftp/python/${PYTHON_VERSION}/${PYTHON_PACKAGE}"
PYTHON_SHA256="a909cb655af5db67d5a90b3603437a1d58bec3446d624e4034e278ac62023cc9"
PYINSTALLER_VERSION="6.21.0"

SOURCE_REF=""
SOURCE_COMMIT=""
OUTPUT_DIR=""

usage() {
    cat <<'EOF'
Usage: scripts/package-cc-macos-release.sh \
  --source-ref REF \
  --source-commit SHA \
  [--output-dir PATH]

Required environment:
  CT_SIGN_IDENTITY              Developer ID Application identity
  CT_NOTARY_KEYCHAIN_PROFILE    notarytool Keychain profile

Or use the API-key notarization form:
  CT_NOTARY_KEY_ID
  CT_NOTARY_KEY_ISSUER
  CT_NOTARY_KEY_PATH

The source ref must resolve to SOURCE_COMMIT at origin. The output directory
must not already exist. The script never installs Python system-wide.
EOF
}

die() {
    echo "error: $*" >&2
    exit 1
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "$1 is required but was not found"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --source-ref)
            [[ $# -ge 2 ]] || die "--source-ref requires a value"
            SOURCE_REF="$2"
            shift 2
            ;;
        --source-commit)
            [[ $# -ge 2 ]] || die "--source-commit requires a value"
            SOURCE_COMMIT="$2"
            shift 2
            ;;
        --output-dir)
            [[ $# -ge 2 ]] || die "--output-dir requires a value"
            OUTPUT_DIR="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "unknown option: $1"
            ;;
    esac
done

[[ -n "${SOURCE_REF}" ]] || die "--source-ref is required"
[[ "${SOURCE_COMMIT}" =~ ^[0-9a-f]{40}$ ]] ||
    die "--source-commit must be a full lowercase 40-character SHA"
[[ -n "${CT_SIGN_IDENTITY:-}" ]] ||
    die "CT_SIGN_IDENTITY is not set"
if [[ -z "${CT_NOTARY_KEYCHAIN_PROFILE:-}" &&
      ( -z "${CT_NOTARY_KEY_ID:-}" ||
        -z "${CT_NOTARY_KEY_ISSUER:-}" ||
        -z "${CT_NOTARY_KEY_PATH:-}" ) ]]; then
    die "notarization credentials are not configured"
fi

for command in \
    arch awk codesign curl ditto file git install_name_tool lipo otool pkgutil \
    shasum unzip uv xcrun
do
    require_cmd "${command}"
done

[[ -n "${OUTPUT_DIR}" ]] || OUTPUT_DIR="${REPO_ROOT}/dist/cc-macos-release"
case "${OUTPUT_DIR}" in
    /*) ;;
    *) OUTPUT_DIR="${REPO_ROOT}/${OUTPUT_DIR}" ;;
esac
[[ ! -e "${OUTPUT_DIR}" ]] ||
    die "output directory already exists: ${OUTPUT_DIR}"

remote_url="$(git -C "${REPO_ROOT}" remote get-url origin)"
release_tool_commit="$(git -C "${REPO_ROOT}" rev-parse HEAD)"
git -C "${REPO_ROOT}" diff --quiet HEAD -- \
    scripts/package-cc-macos-release.sh \
    scripts/verify-foundation-release.sh \
    tools/cc/scripts/cc_frozen_entry.py ||
    die "release packaging files must be committed before building"
remote_commit="$(
    git ls-remote --exit-code "${remote_url}" \
        "refs/tags/${SOURCE_REF}^{}" "refs/tags/${SOURCE_REF}" \
        "refs/heads/${SOURCE_REF}" |
        awk '
            NR == 1 { first = $1 }
            $2 ~ /\^\{\}$/ { peeled = $1 }
            END { print peeled ? peeled : first }
        '
)"
[[ -n "${remote_commit}" ]] || die "origin does not advertise ${SOURCE_REF}"
[[ "${remote_commit}" == "${SOURCE_COMMIT}" ]] ||
    die "${SOURCE_REF} resolves to ${remote_commit}, not ${SOURCE_COMMIT}"

scratch="$(mktemp -d "${TMPDIR:-/tmp}/claude-cc-release.XXXXXX")"
cleanup() {
    rm -rf "${scratch}"
}
trap cleanup EXIT

source_checkout="${scratch}/source"
git clone --quiet --branch "${SOURCE_REF}" --single-branch \
    "${remote_url}" "${source_checkout}"
cloned_commit="$(git -C "${source_checkout}" rev-parse HEAD)"
[[ "${cloned_commit}" == "${SOURCE_COMMIT}" ]] ||
    die "cloned source changed during release preparation"
"${source_checkout}/scripts/verify-foundation-release.sh" \
    "${source_checkout}" "${SOURCE_REF}" "${SOURCE_COMMIT}"

python_package="${scratch}/${PYTHON_PACKAGE}"
echo "cc release: fetching pinned Python ${PYTHON_VERSION} universal2 toolchain"
curl --fail --location --silent --show-error \
    "${PYTHON_URL}" --output "${python_package}"
printf '%s  %s\n' "${PYTHON_SHA256}" "${python_package}" |
    shasum -a 256 -c - >/dev/null

expanded_package="${scratch}/python-package"
pkgutil --expand-full "${python_package}" "${expanded_package}"
python_root="$(
    printf '%s/Python_Framework.pkg/Payload/Versions/%s\n' \
        "${expanded_package}" "${PYTHON_VERSION%.*}"
)"
python_executable="${python_root}/bin/python3"
[[ -x "${python_executable}" ]] ||
    die "the verified Python package did not contain ${python_executable}"
python_arches="$(lipo -archs "${python_executable}")"
[[ " ${python_arches} " == *" arm64 "* &&
   " ${python_arches} " == *" x86_64 "* ]] ||
    die "the pinned Python interpreter is not universal2: ${python_arches}"

# The official installer is a framework build with absolute /Library load
# paths. Relocate every dependency inside the verified temporary payload before
# launching Python. PyInstaller uses child interpreters, and macOS deliberately
# strips DYLD_* variables for some signed subprocesses; relative loader paths
# keep both the parent and all children isolated from /Library.
python_install_prefix="/Library/Frameworks/Python.framework/Versions/${PYTHON_VERSION%.*}/"
while IFS= read -r -d '' macho_file; do
    file "${macho_file}" | grep -q "Mach-O" || continue
    changed=false
    while IFS= read -r dependency; do
        case "${dependency}" in
            "${python_install_prefix}"*)
                dependency_target="${dependency#"${python_install_prefix}"}"
                absolute_target="${python_root}/${dependency_target}"
                relative_target="$(
                    /usr/bin/python3 -c \
                        'import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' \
                        "${absolute_target}" \
                        "$(dirname "${macho_file}")"
                )"
                same_file="$(
                    /usr/bin/python3 -c \
                        'import os,sys; print(os.path.realpath(sys.argv[1]) == os.path.realpath(sys.argv[2]))' \
                        "${absolute_target}" "${macho_file}"
                )"
                if [[ "${same_file}" == "True" ]]; then
                    install_name_tool \
                        -id "@loader_path/$(basename "${macho_file}")" \
                        "${macho_file}"
                else
                    install_name_tool \
                        -change "${dependency}" "@loader_path/${relative_target}" \
                        "${macho_file}"
                fi
                changed=true
                ;;
        esac
    done < <(
        otool -L "${macho_file}" |
            awk 'index($1, "/Library/Frameworks/Python.framework/") == 1 {print $1}' |
            sort -u
    )
    if [[ "${changed}" == true ]]; then
        codesign --sign - --force "${macho_file}" >/dev/null
    fi
done < <(find "${python_root}" -type f -print0)

remaining_absolute_loads="$(
    find "${python_root}" -type f -print0 |
        while IFS= read -r -d '' candidate; do
            file "${candidate}" | grep -q "Mach-O" || continue
            otool -L "${candidate}" 2>/dev/null |
                awk 'index($1, "/Library/Frameworks/Python.framework/") == 1 {print $1}'
        done |
        sort -u
)"
[[ -z "${remaining_absolute_loads}" ]] ||
    die "temporary Python relocation left absolute framework loads: ${remaining_absolute_loads}"

framework_shim="${scratch}/frameworks"
mkdir -p "${framework_shim}/Python.framework/Versions"
ln -s "${python_root}" \
    "${framework_shim}/Python.framework/Versions/${PYTHON_VERSION%.*}"

run_python() {
    env \
        PYTHONHOME="${python_root}" \
        DYLD_FRAMEWORK_PATH="${framework_shim}" \
        DYLD_LIBRARY_PATH="${python_root}/lib" \
        PYTHONPATH="${site_packages:-}:${source_checkout}/tools/cc/src" \
        "${python_executable}" "$@"
}

echo "cc release: bootstrapping pip inside the temporary toolchain"
run_python -m ensurepip --upgrade >/dev/null

requirements="${scratch}/requirements.txt"
(
    cd "${source_checkout}/tools/cc"
    uv export --locked --no-dev --format requirements-txt
) | awk '$0 != "-e ."' > "${requirements}"

site_packages="${scratch}/site-packages"
mkdir -p "${site_packages}"
echo "cc release: installing locked runtime and pinned freezer"
run_python -m pip install \
    --disable-pip-version-check \
    --require-hashes \
    --target "${site_packages}" \
    -r "${requirements}" >/dev/null
run_python -m pip install \
    --disable-pip-version-check \
    --upgrade \
    --target "${site_packages}" \
    "pyinstaller==${PYINSTALLER_VERSION}" >/dev/null

merge_x86_wheel_binary() {
    local distribution="$1"
    local version="$2"
    local relative_glob="$3"
    local wheel_dir="${scratch}/x86-wheel-${distribution}"
    local expanded_dir="${wheel_dir}/expanded"
    local arm_binary
    local x86_binary
    local merged

    mkdir -p "${wheel_dir}"
    run_python -m pip download \
        --disable-pip-version-check \
        --no-deps \
        --only-binary=:all: \
        --platform macosx_11_0_x86_64 \
        --python-version 313 \
        --implementation cp \
        --abi cp313 \
        --dest "${wheel_dir}" \
        "${distribution}==${version}" >/dev/null

    mkdir -p "${expanded_dir}"
    unzip -q "${wheel_dir}"/*.whl -d "${expanded_dir}"
    arm_binary="$(find "${site_packages}" -path "${site_packages}/${relative_glob}" -type f -print -quit)"
    x86_binary="$(find "${expanded_dir}" -path "${expanded_dir}/${relative_glob}" -type f -print -quit)"
    [[ -n "${arm_binary}" && -n "${x86_binary}" ]] ||
        die "could not locate both architecture slices for ${distribution}"

    merged="${scratch}/$(basename "${arm_binary}").universal2"
    lipo -create "${arm_binary}" "${x86_binary}" -output "${merged}"
    merged_arches="$(lipo -archs "${merged}")"
    [[ " ${merged_arches} " == *" arm64 "* &&
       " ${merged_arches} " == *" x86_64 "* ]] ||
        die "${distribution} did not merge to universal2: ${merged_arches}"
    mv "${merged}" "${arm_binary}"
    codesign --sign - --force "${arm_binary}" >/dev/null
}

pydantic_core_version="$(
    run_python -c 'import pydantic_core; print(pydantic_core.__version__)'
)"
pyyaml_version="$(
    run_python -c 'import yaml; print(yaml.__version__)'
)"
echo "cc release: merging native dependency slices"
merge_x86_wheel_binary \
    "pydantic-core" "${pydantic_core_version}" \
    "pydantic_core/_pydantic_core*.so"
merge_x86_wheel_binary \
    "pyyaml" "${pyyaml_version}" \
    "yaml/_yaml*.so"

entry_point="${REPO_ROOT}/tools/cc/scripts/cc_frozen_entry.py"
[[ -f "${entry_point}" ]] || die "missing frozen entry point: ${entry_point}"

pyinstaller_dist="${scratch}/pyinstaller-dist"
echo "cc release: freezing universal2 helper"
run_python -m PyInstaller \
    --clean \
    --noconfirm \
    --onefile \
    --console \
    --name cc \
    --target-arch universal2 \
    --codesign-identity "${CT_SIGN_IDENTITY}" \
    --paths "${source_checkout}/tools/cc/src" \
    --paths "${site_packages}" \
    --distpath "${pyinstaller_dist}" \
    --workpath "${scratch}/pyinstaller-work" \
    --specpath "${scratch}/pyinstaller-spec" \
    "${entry_point}" >/dev/null

artifact="${pyinstaller_dist}/cc"
[[ -x "${artifact}" ]] || die "PyInstaller did not produce ${artifact}"
artifact_arches="$(lipo -archs "${artifact}")"
[[ " ${artifact_arches} " == *" arm64 "* &&
   " ${artifact_arches} " == *" x86_64 "* ]] ||
    die "frozen cc is not universal2: ${artifact_arches}"

# PyInstaller signs collected native code and the generated executable. Apply
# the upstream hardened-runtime signature once more to the final outer binary
# after its archive is complete; Control Tower will only verify this signature.
codesign --force \
    --options runtime \
    --timestamp \
    --sign "${CT_SIGN_IDENTITY}" \
    "${artifact}"
codesign --verify --strict --verbose=2 "${artifact}"

expected_version="$(
    awk -F '"' '/^__version__ = / { print $2; exit }' \
        "${source_checkout}/tools/cc/src/cc/__init__.py"
)"
actual_version="$("${artifact}" --version)"
[[ "${actual_version}" == "cc version ${expected_version}" ]] ||
    die "arm64 helper returned unexpected version: ${actual_version}"
if /usr/sbin/sysctl -n sysctl.proc_translated >/dev/null 2>&1 ||
   arch -x86_64 /usr/bin/true >/dev/null 2>&1; then
    x86_version="$(arch -x86_64 "${artifact}" --version)"
    [[ "${x86_version}" == "cc version ${expected_version}" ]] ||
        die "x86_64 helper returned unexpected version: ${x86_version}"
fi

# Exercise the exact first network boundary the Control Tower User app needs.
# Version and signature checks alone cannot detect a frozen interpreter that
# omitted its CA bundle. Use an isolated HOME, request (but never poll or
# persist) one short-lived device code, and validate the machine contract
# without printing the code into release logs.
probe_home="${scratch}/device-flow-probe-home"
mkdir -p "${probe_home}"
device_flow_probe="${scratch}/device-flow-probe.json"
env HOME="${probe_home}" \
    "${artifact}" auth login \
    --org Everyone-Needs-A-Copilot \
    --json > "${device_flow_probe}"
/usr/bin/python3 - "${device_flow_probe}" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
required = {
    "schema_version": str,
    "user_code": str,
    "verification_uri": str,
    "device_code": str,
    "interval": int,
    "expires_in": int,
}
for key, expected_type in required.items():
    value = payload.get(key)
    if not isinstance(value, expected_type) or (
        expected_type is str and not value.strip()
    ):
        raise SystemExit(
            f"device-flow HTTPS probe returned invalid {key}: {value!r}"
        )
PY

# Exercise the next app boundary under the PATH a Finder-launched macOS app
# actually receives. Preserve the signed-in user session and override PATH
# only: Finder does not erase HOME, Keychain access, or every launchd-provided
# variable. `cc onboard` is a plan unless `--apply` is present, so this reads
# the release operator's existing setup without changing it.
finder_onboard_probe="${scratch}/finder-onboard-probe.json"
set +e
env \
    HOME="${RELEASE_HOME}" \
    PATH="/usr/bin:/bin:/usr/sbin:/sbin" \
    "${artifact}" onboard \
    --org auto \
    --products claude,codex \
    --json > "${finder_onboard_probe}"
finder_onboard_exit=$?
set -e
[[ "${finder_onboard_exit}" -eq 0 || "${finder_onboard_exit}" -eq 1 ]] ||
    die "Finder-environment onboarding probe exited ${finder_onboard_exit}"
/usr/bin/python3 - "${finder_onboard_probe}" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
if payload.get("scope") != "ecosystem":
    raise SystemExit("Finder-environment probe did not return an ecosystem report")
if payload.get("mode") != "plan":
    raise SystemExit("Finder-environment probe did not remain read-only")
if payload.get("org") != "Everyone-Needs-A-Copilot":
    raise SystemExit("Finder-environment probe did not resolve the ENAC handoff")
if payload.get("products") != ["claude", "codex"]:
    raise SystemExit("Finder-environment probe did not cover both products")
if payload.get("error") is not None:
    raise SystemExit(f"Finder-environment probe returned an error: {payload['error']}")
layer_manifest = next(
    (
        item
        for item in payload.get("inventory", [])
        if item.get("id") == "layer-manifest"
    ),
    None,
)
if layer_manifest is None:
    raise SystemExit("Finder-environment probe did not inspect the layer manifest")
if "copilot` command is unavailable" in layer_manifest.get("detail", ""):
    raise SystemExit("Finder-environment probe could not resolve copilot")
codex_plugin = next(
    (
        stage
        for stage in payload.get("stages", [])
        if stage.get("stage") == "codex-plugin"
    ),
    None,
)
if codex_plugin is None:
    raise SystemExit("Finder-environment probe did not inspect Codex plugins")
if codex_plugin.get("result") == "blocked":
    raise SystemExit(
        "Finder-environment probe could not run Codex: "
        f"{codex_plugin.get('detail', 'unknown failure')}"
    )
PY

# Exercise the complete read-only Phase 9 boundary from the frozen artifact.
# Exit 1 is a valid, structured assessment when this Mac needs attention; exit
# 2 is a transport/contract failure and must stop the release.
finder_reconcile_probe="${scratch}/finder-reconcile-probe.json"
set +e
env \
    HOME="${RELEASE_HOME}" \
    PATH="/usr/bin:/bin:/usr/sbin:/sbin" \
    "${artifact}" reconcile assess \
    --json > "${finder_reconcile_probe}"
finder_reconcile_exit=$?
set -e
[[ "${finder_reconcile_exit}" -eq 0 || "${finder_reconcile_exit}" -eq 1 ]] ||
    die "Finder-environment reconciliation probe exited ${finder_reconcile_exit}"
/usr/bin/python3 - "${finder_reconcile_probe}" "${expected_version}" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
if payload.get("schema_version") != "1.0":
    raise SystemExit("reconciliation probe returned an incompatible schema")
if payload.get("phase") != "assess":
    raise SystemExit("reconciliation probe did not remain read-only")
if payload.get("result") not in {"ready", "action-required", "blocked"}:
    raise SystemExit("reconciliation probe returned an invalid result")
if payload.get("machine", {}).get("helper", {}).get("version") != sys.argv[2]:
    raise SystemExit("reconciliation probe did not execute the frozen helper version")
projects = payload.get("projects")
summary = payload.get("summary", {}).get("project_counts", {})
if not isinstance(projects, list) or summary.get("total") != len(projects):
    raise SystemExit("reconciliation project counts do not match project records")
paths = [item.get("path") for item in projects if isinstance(item, dict)]
if len(paths) != len(projects) or len(paths) != len(set(paths)):
    raise SystemExit("reconciliation project census is incomplete or repeated")
if not isinstance(payload.get("next_actions"), list):
    raise SystemExit("reconciliation probe omitted Python-authored next actions")
PY

# Exercise the exact frozen helper's bounded Claude lifecycle against a clean,
# disposable customized project. The inert Claude double receives only opaque
# candidate ids; the probe stops after Python issues and plans the proposal, so
# no project mutation is authorized or performed.
assistant_root="${scratch}/assistant-fixture-root"
assistant_project="${assistant_root}/customized-project"
assistant_machine_root="${scratch}/assistant-machine"
assistant_fake="${scratch}/fake-claude"
assistant_capture="${scratch}/assistant-claude-capture.json"
assistant_request="${scratch}/assistant-request.json"
assistant_prepare_probe="${scratch}/assistant-prepare-probe.json"
assistant_run_probe="${scratch}/assistant-run-probe.json"
assistant_status_probe="${scratch}/assistant-status-probe.json"
assistant_plan_probe="${scratch}/assistant-plan-probe.json"
assistant_proposal_request="${scratch}/assistant-proposal-request.json"
mkdir -p "${assistant_root}" "${assistant_machine_root}"
assistant_root="$(cd "${assistant_root}" && pwd -P)"
assistant_machine_root="$(cd "${assistant_machine_root}" && pwd -P)"
chmod 700 "${assistant_root}" "${assistant_machine_root}"
assistant_project="${assistant_root}/customized-project"
mkdir -p \
    "${assistant_project}/.claude/agents" \
    "${assistant_project}/.claude/commands" \
    "${assistant_machine_root}"
printf '%s\n' '# Project-owned Claude instructions' > "${assistant_project}/CLAUDE.md"
printf '%s\n' 'project-owned agent' > "${assistant_project}/.claude/agents/me.md"
printf '%s\n' 'project-owned command' > "${assistant_project}/.claude/commands/project.md"
git -C "${assistant_project}" init -q
git -C "${assistant_project}" config user.email release-probe@example.invalid
git -C "${assistant_project}" config user.name 'Release Probe'
git -C "${assistant_project}" add -A
git -C "${assistant_project}" commit -qm 'assistant release fixture'
install -m 700 \
    "${source_checkout}/tools/cc/tests/fixtures/reconciliation/fake_claude.py" \
    "${assistant_fake}"
codex_source="$({ /usr/bin/python3 - "${finder_reconcile_probe}" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
for framework in payload.get("machine", {}).get("frameworks", []):
    if framework.get("component") == "codex" and framework.get("state") == "ready":
        print(framework["path"])
        break
else:
    raise SystemExit("assistant probe could not resolve the verified Codex source")
PY
} )"
/usr/bin/python3 - \
    "${assistant_machine_root}/config.json" \
    "${assistant_root}" \
    "${source_checkout}" \
    "${codex_source}" \
    "${RELEASE_HOME}/.claude/cc/config.json" \
    "${assistant_request}" \
    "${assistant_project}" <<'PY'
import json
import pathlib
import sys

(
    config_path,
    approved_root,
    claude_source,
    codex_source,
    base_config_path,
    request_path,
    project,
) = sys.argv[1:]
config = json.load(open(base_config_path, encoding="utf-8"))
config["projects"] = {"roots": [approved_root]}
config.setdefault("paths", {}).update(
    {
        "claude_copilot_root": claude_source,
        "codex_copilot_root": codex_source,
    }
)
pathlib.Path(config_path).write_text(
    json.dumps(config, sort_keys=True),
    encoding="utf-8",
)
pathlib.Path(request_path).write_text(
    json.dumps(
        {
            "schema_version": "1.0",
            "roots": [approved_root],
            "projects": [
                {"path": project, "components": ["claude", "codex"]}
            ],
        },
        sort_keys=True,
    ),
    encoding="utf-8",
)
PY
chmod 600 "${assistant_machine_root}/config.json" "${assistant_request}"
assistant_env=(
    HOME="${RELEASE_HOME}"
    PATH="/usr/bin:/bin:/usr/sbin:/sbin"
    CC_MACHINE_ROOT="${assistant_machine_root}"
)
env "${assistant_env[@]}" \
    "${artifact}" reconcile assistant-prepare \
    --request "${assistant_request}" --json > "${assistant_prepare_probe}" ||
    die "frozen helper assistant-prepare probe failed: $(<"${assistant_prepare_probe}")"
assistant_session="$({ /usr/bin/python3 - "${assistant_prepare_probe}" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
if payload.get("result") != "ready":
    raise SystemExit("frozen helper did not prepare an assistant session")
print(payload["session_id"])
PY
} )"
assistant_session_file="${assistant_machine_root}/diagnostics/reconciliation/assistant/sessions/${assistant_session}/session.json"
assistant_payload="$({ /usr/bin/python3 - "${assistant_session_file}" <<'PY'
import json
import sys

session = json.load(open(sys.argv[1], encoding="utf-8"))
chosen = {}
for candidate in session["candidates"]:
    chosen.setdefault(
        (candidate["project_ref"], candidate["component"]),
        candidate["candidate_id"],
    )
if not chosen:
    raise SystemExit("assistant probe produced no bounded candidates")
print(json.dumps({"selections": [{"candidate_id": value} for value in chosen.values()]}))
PY
} )"
env "${assistant_env[@]}" \
    CC_ASSISTANT_TEST_MODE=1 \
    CC_ASSISTANT_CLAUDE_PATH="${assistant_fake}" \
    HTTPS_PROXY="https://release-probe:credential-canary@example.invalid:443" \
    FAKE_CLAUDE_CAPTURE="${assistant_capture}" \
    FAKE_CLAUDE_MODE=valid \
    FAKE_CLAUDE_PAYLOAD_JSON="${assistant_payload}" \
    "${artifact}" reconcile assistant-run \
    --session-id "${assistant_session}" --json > "${assistant_run_probe}" ||
    die "frozen helper assistant-run probe failed: $(<"${assistant_run_probe}")"
env "${assistant_env[@]}" \
    "${artifact}" reconcile assistant-status \
    --session-id "${assistant_session}" --json > "${assistant_status_probe}" ||
    die "frozen helper assistant-status probe failed: $(<"${assistant_status_probe}")"
/usr/bin/python3 - \
    "${assistant_request}" \
    "${assistant_status_probe}" \
    "${assistant_proposal_request}" <<'PY'
import json
import pathlib
import sys

request = json.load(open(sys.argv[1], encoding="utf-8"))
status = json.load(open(sys.argv[2], encoding="utf-8"))
proposal = status.get("proposal_id")
if status.get("result") != "ready" or not isinstance(proposal, str):
    raise SystemExit("frozen helper did not validate the assistant proposal")
request["assistant_proposal_id"] = proposal
pathlib.Path(sys.argv[3]).write_text(json.dumps(request, sort_keys=True), encoding="utf-8")
PY
chmod 600 "${assistant_proposal_request}"
env "${assistant_env[@]}" \
    "${artifact}" reconcile plan \
    --request "${assistant_proposal_request}" --json > "${assistant_plan_probe}" ||
    die "frozen helper assistant-plan probe failed: $(<"${assistant_plan_probe}")"
/usr/bin/python3 - \
    "${assistant_prepare_probe}" \
    "${assistant_run_probe}" \
    "${assistant_status_probe}" \
    "${assistant_plan_probe}" \
    "${assistant_capture}" \
    "${assistant_project}" \
    "${assistant_machine_root}" <<'PY'
import base64
import json
import pathlib
import re
import stat
import subprocess
import sys

prepare, run, status, plan, capture = [
    json.load(open(path, encoding="utf-8")) for path in sys.argv[1:6]
]
project = sys.argv[6]
machine_root = pathlib.Path(sys.argv[7]).resolve()
if prepare.get("result") != "ready" or run.get("result") != "ready":
    raise SystemExit("frozen assistant prepare/run probe failed")
if status.get("result") != "ready" or not re.fullmatch(
    r"proposal_[0-9a-f]{32}", status.get("proposal_id", "")
):
    raise SystemExit("frozen assistant status probe did not issue an opaque proposal")
plans = plan.get("plans")
if plan.get("phase") != "plan" or not isinstance(plans, list) or len(plans) != 1:
    raise SystemExit("frozen assistant proposal did not produce one Python plan")
if plans[0].get("path") != project or not plans[0].get("operations"):
    raise SystemExit("frozen assistant proposal plan did not cover the fixture")
argv = capture.get("argv")
expected_argv_prefix = [
    "--safe-mode",
    "--tools", "",
    "--permission-mode", "plan",
    "--strict-mcp-config",
    "--disable-slash-commands",
    "--no-session-persistence",
    "--no-chrome",
    "--print",
    "--input-format", "text",
    "--output-format", "json",
    "--json-schema",
]
if not isinstance(argv, list) or argv[:-1] != expected_argv_prefix:
    raise SystemExit("frozen assistant Claude invocation was not exactly guarded")
try:
    schema = json.loads(argv[-1])
except (IndexError, TypeError, json.JSONDecodeError) as exc:
    raise SystemExit("frozen assistant Claude invocation omitted its JSON schema") from exc
selections_schema = schema.get("properties", {}).get("selections", {})
selection_item_schema = selections_schema.get("items", {})
candidate_schema = selection_item_schema.get("properties", {}).get(
    "candidate_id", {}
)
candidate_ids = candidate_schema.get("enum")
if (
    schema.get("type") != "object"
    or schema.get("additionalProperties") is not False
    or schema.get("required") != ["selections"]
    or selections_schema.get("type") != "array"
    or not isinstance(selections_schema.get("minItems"), int)
    or selections_schema.get("minItems") < 1
    or selections_schema.get("maxItems") != selections_schema.get("minItems")
    or selection_item_schema.get("type") != "object"
    or selection_item_schema.get("additionalProperties") is not False
    or selection_item_schema.get("required") != ["candidate_id"]
    or candidate_schema.get("type") != "string"
    or not isinstance(candidate_ids, list)
    or not candidate_ids
    or len(candidate_ids) != len(set(candidate_ids))
    or any(
        not isinstance(value, str)
        or re.fullmatch(r"candidate_[0-9a-f]{64}", value) is None
        for value in candidate_ids
    )
):
    raise SystemExit("frozen assistant Claude invocation used an open output schema")
prompt = base64.b64decode(capture["stdin_base64"]).decode("utf-8")
private_values = {
    project,
    pathlib.Path(project).name,
    "# Project-owned Claude instructions",
    "project-owned agent",
    "project-owned command",
}
invocation_text = json.dumps(argv)
if any(value in prompt or value in invocation_text for value in private_values):
    raise SystemExit("frozen assistant leaked project identity or content to Claude")
payload = json.loads(prompt)
expected_instruction = (
    "Select exactly one offered candidate for every component group. "
    "Return only the required structured output. Do not author or infer "
    "commands, paths, content, patches, operations, or guidance."
)
packet = payload.get("packet") if isinstance(payload, dict) else None
if (
    not isinstance(payload, dict)
    or set(payload) != {"instruction", "packet"}
    or payload.get("instruction") != expected_instruction
    or not isinstance(packet, dict)
    or set(packet) != {"schema_version", "task", "projects", "rules"}
    or packet.get("schema_version") != "1.0"
    or packet.get("task") != "select-bounded-project-reconciliation-candidates"
    or packet.get("rules")
    != {
        "select_exactly_one_candidate_per_component": True,
        "author_commands_paths_content_patches_operations": False,
    }
    or not isinstance(packet.get("projects"), list)
    or not packet["projects"]
):
    raise SystemExit("frozen assistant prompt was not the closed opaque packet")
packet_candidate_ids = []
packet_component_count = 0
project_refs = set()
for packet_project in packet["projects"]:
    if (
        not isinstance(packet_project, dict)
        or set(packet_project) != {"project_ref", "components"}
        or re.fullmatch(
            r"project_[0-9a-f]{32}", packet_project.get("project_ref", "")
        )
        is None
        or packet_project["project_ref"] in project_refs
        or not isinstance(packet_project.get("components"), list)
        or not packet_project["components"]
    ):
        raise SystemExit("frozen assistant prompt exposed an invalid project packet")
    project_refs.add(packet_project["project_ref"])
    for packet_component in packet_project["components"]:
        if (
            not isinstance(packet_component, dict)
            or set(packet_component)
            != {"component", "candidate_ids", "evidence_codes"}
            or packet_component.get("component") not in {"claude", "codex"}
            or packet_component.get("evidence_codes")
            != ["customized-setup-present"]
            or not isinstance(packet_component.get("candidate_ids"), list)
            or not packet_component["candidate_ids"]
            or any(
                not isinstance(value, str)
                or re.fullmatch(r"candidate_[0-9a-f]{64}", value) is None
                for value in packet_component["candidate_ids"]
            )
        ):
            raise SystemExit("frozen assistant prompt exposed an invalid component packet")
        packet_component_count += 1
        packet_candidate_ids.extend(packet_component["candidate_ids"])
if (
    len(packet_candidate_ids) != len(set(packet_candidate_ids))
    or set(packet_candidate_ids) != set(candidate_ids)
    or packet_component_count != selections_schema["minItems"]
):
    raise SystemExit("frozen assistant prompt and output schema were not bound")
prohibited = {"command", "path", "content", "patch", "operation"}
def walk(value):
    if isinstance(value, dict):
        if prohibited & set(value):
            raise SystemExit("frozen assistant prompt contained prohibited authority")
        for item in value.values():
            walk(item)
    elif isinstance(value, list):
        for item in value:
            walk(item)
walk(payload)
cwd = pathlib.Path(capture["cwd"]).resolve()
if machine_root not in cwd.parents or project in str(cwd):
    raise SystemExit("frozen assistant did not run from its private workspace")
allowed_environment_names = {
    "HOME", "USER", "LOGNAME", "SHELL", "PATH", "TMPDIR", "LANG",
    "LC_ALL", "LC_CTYPE", "TERM", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS",
    "CLAUDE_CONFIG_DIR", "FAKE_CLAUDE_CAPTURE", "FAKE_CLAUDE_MODE",
    "FAKE_CLAUDE_PAYLOAD_JSON",
    # Apple's /usr/bin/python3 shebang launcher adds these after exec. They are
    # not present in the environment authored by the frozen helper.
    "CPATH", "LIBRARY_PATH", "MANPATH", "SDKROOT", "__CF_USER_TEXT_ENCODING",
}
environment_names = set(capture.get("environment_keys", []))
unexpected_environment = environment_names - allowed_environment_names
if unexpected_environment:
    raise SystemExit(
        "frozen assistant inherited unexpected environment names: "
        + ", ".join(sorted(unexpected_environment))
    )
if "HTTPS_PROXY" in environment_names:
    raise SystemExit("frozen assistant inherited a credential-bearing proxy URL")

project_root = pathlib.Path(project)
expected_files = {
    "CLAUDE.md": b"# Project-owned Claude instructions\n",
    ".claude/agents/me.md": b"project-owned agent\n",
    ".claude/commands/project.md": b"project-owned command\n",
}
actual_files = {}
actual_directories = set()
for path in project_root.rglob("*"):
    relative = path.relative_to(project_root)
    if ".git" in relative.parts:
        continue
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not (
        stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)
    ):
        raise SystemExit("frozen assistant changed the fixture to an unsafe file type")
    if stat.S_ISREG(metadata.st_mode):
        actual_files[str(relative)] = path.read_bytes()
    elif stat.S_ISDIR(metadata.st_mode):
        actual_directories.add(str(relative))
expected_directories = {".claude", ".claude/agents", ".claude/commands"}
if actual_files != expected_files or actual_directories != expected_directories:
    raise SystemExit("frozen assistant changed the project-owned fixture tree")
git_status = subprocess.run(
    ["/usr/bin/git", "-C", project, "status", "--porcelain=v1", "--untracked-files=all"],
    check=True,
    capture_output=True,
    text=True,
)
if git_status.stdout:
    raise SystemExit("frozen assistant changed the clean fixture Git state")

assistant_state = machine_root / "diagnostics/reconciliation/assistant"
if not assistant_state.is_dir():
    raise SystemExit("frozen assistant did not create its private state root")
session_path = assistant_state / "sessions" / prepare["session_id"] / "session.json"
proposal_path = assistant_state / "proposals" / f"{status['proposal_id']}.json"
if not session_path.is_file() or not proposal_path.is_file():
    raise SystemExit("frozen assistant omitted private session or proposal state")
for path in (assistant_state, *assistant_state.rglob("*")):
    metadata = path.lstat()
    mode = stat.S_IMODE(metadata.st_mode)
    if stat.S_ISDIR(metadata.st_mode):
        if mode != 0o700:
            raise SystemExit("frozen assistant state directory was not mode 0700")
    elif stat.S_ISREG(metadata.st_mode):
        if mode != 0o600 or metadata.st_nlink != 1:
            raise SystemExit("frozen assistant state file was not private and single-link")
    else:
        raise SystemExit("frozen assistant state contained a symlink or special file")
PY

# Exercise the frozen helper's DEFAULT `claude` resolution -- registry and
# PATH, with `CC_ASSISTANT_CLAUDE_PATH` unset -- rather than the operator
# override the lifecycle probe above always sets. The regression this closes
# (cc 2.7.1, `_resolved_claude_candidate()` in
# `tools/cc/src/cc/core/ecosystem/reconciliation_assistant.py`) was narrower
# than "PATH is unchecked": 2.7.1 disabled PATH consultation entirely and
# resolved only through `core/executables.py`'s closed HOME-relative/absolute
# registry, so a real `claude` install anywhere else -- including under a
# sandboxed or non-default `$HOME`, exactly what Control Tower's release
# gates run -- silently produced a clean but wrong `claude-code-unavailable`
# refusal. A leg that only places `claude` inside the registry does not
# reproduce that: registry resolution was never broken, and this was
# confirmed empirically by running it against both the 2.7.1 and 2.7.2 frozen
# artifacts before writing this. The leg that actually reproduces the
# regression is the PATH-fallback leg below, where the registry has no answer
# under the probe's disposable `$HOME` and only PATH can find `claude`.
# Because every probe above sets `CC_ASSISTANT_CLAUDE_PATH` explicitly, this
# regression shipped signed and notarized -- all four release probes,
# including the lifecycle probe above, "passed" -- and was only caught
# downstream. A helper must not be able to self-certify a broken default
# resolution path, so the three legs below run the bounded lifecycle through
# default resolution alone: once succeeding via the registry, once succeeding
# via the PATH fallback with nothing in the registry, and once failing closed
# with nothing resolvable anywhere. Each leg gets its own disposable
# HOME/machine-root pair so none depends on or pollutes the others or the
# lifecycle probe above; all three reuse that probe's fixture project
# (`${assistant_project}`), already forensically proven above to be left
# untouched by the assistant lifecycle, rather than re-authoring one.

write_assistant_config_and_request() {
    local config_path="$1"
    local request_path="$2"
    local project_path="$3"
    /usr/bin/python3 - \
        "${config_path}" \
        "${assistant_root}" \
        "${source_checkout}" \
        "${codex_source}" \
        "${RELEASE_HOME}/.claude/cc/config.json" \
        "${request_path}" \
        "${project_path}" <<'PY'
import json
import pathlib
import sys

(
    config_path,
    approved_root,
    claude_source,
    codex_source,
    base_config_path,
    request_path,
    project,
) = sys.argv[1:]
config = json.load(open(base_config_path, encoding="utf-8"))
config["projects"] = {"roots": [approved_root]}
config.setdefault("paths", {}).update(
    {
        "claude_copilot_root": claude_source,
        "codex_copilot_root": codex_source,
    }
)
pathlib.Path(config_path).write_text(
    json.dumps(config, sort_keys=True),
    encoding="utf-8",
)
pathlib.Path(request_path).write_text(
    json.dumps(
        {
            "schema_version": "1.0",
            "roots": [approved_root],
            "projects": [
                {"path": project, "components": ["claude", "codex"]}
            ],
        },
        sort_keys=True,
    ),
    encoding="utf-8",
)
PY
    chmod 600 "${config_path}" "${request_path}"
}

assistant_prepared_session_id() {
    local prepare_probe="$1"
    local label="$2"
    /usr/bin/python3 - "${prepare_probe}" "${label}" <<'PY'
import json
import sys

path, label = sys.argv[1:3]
payload = json.load(open(path, encoding="utf-8"))
if payload.get("result") != "ready":
    raise SystemExit(f"{label} did not prepare an assistant session")
print(payload["session_id"])
PY
}

assistant_selection_payload() {
    local session_file="$1"
    /usr/bin/python3 - "${session_file}" <<'PY'
import json
import sys

session = json.load(open(sys.argv[1], encoding="utf-8"))
chosen = {}
for candidate in session["candidates"]:
    chosen.setdefault(
        (candidate["project_ref"], candidate["component"]),
        candidate["candidate_id"],
    )
if not chosen:
    raise SystemExit("assistant probe produced no bounded candidates")
print(json.dumps({"selections": [{"candidate_id": value} for value in chosen.values()]}))
PY
}

# Leg 1 of 3: default resolution succeeds via the closed registry when a real
# `claude` sits at the exact location `resolve_executable()` checks first
# (`~/.local/bin/claude`; see `core/executables.py`'s `claude` entries). PATH
# is restricted to system directories, exactly as the Finder-environment
# probes above restrict it, and no other resolvable `claude` exists anywhere
# under this disposable HOME, so a ready run here is only possible if default
# resolution actually walked the registry and found this one. This leg alone
# would NOT have caught the 2.7.1 regression -- registry resolution was never
# broken -- it guards the registry-first half of default resolution.
default_resolution_home="${scratch}/assistant-default-resolution-home"
default_resolution_machine_root="${scratch}/assistant-default-resolution-machine"
default_resolution_request="${scratch}/assistant-default-resolution-request.json"
default_resolution_capture="${scratch}/assistant-default-resolution-capture.json"
default_resolution_prepare_probe="${scratch}/assistant-default-resolution-prepare-probe.json"
default_resolution_run_probe="${scratch}/assistant-default-resolution-run-probe.json"
default_resolution_status_probe="${scratch}/assistant-default-resolution-status-probe.json"
mkdir -p "${default_resolution_home}/.local/bin" "${default_resolution_machine_root}"
default_resolution_home="$(cd "${default_resolution_home}" && pwd -P)"
default_resolution_machine_root="$(cd "${default_resolution_machine_root}" && pwd -P)"
chmod 700 "${default_resolution_home}" "${default_resolution_machine_root}"
install -m 700 \
    "${source_checkout}/tools/cc/tests/fixtures/reconciliation/fake_claude.py" \
    "${default_resolution_home}/.local/bin/claude"

write_assistant_config_and_request \
    "${default_resolution_machine_root}/config.json" \
    "${default_resolution_request}" \
    "${assistant_project}"

default_resolution_env=(
    HOME="${default_resolution_home}"
    PATH="/usr/bin:/bin:/usr/sbin:/sbin"
    CC_MACHINE_ROOT="${default_resolution_machine_root}"
)
env "${default_resolution_env[@]}" \
    "${artifact}" reconcile assistant-prepare \
    --request "${default_resolution_request}" --json > "${default_resolution_prepare_probe}" ||
    die "frozen helper registry-resolution assistant-prepare probe failed: $(<"${default_resolution_prepare_probe}")"
default_resolution_session="$(
    assistant_prepared_session_id \
        "${default_resolution_prepare_probe}" \
        "frozen helper registry-resolution prepare"
)"
default_resolution_session_file="${default_resolution_machine_root}/diagnostics/reconciliation/assistant/sessions/${default_resolution_session}/session.json"
default_resolution_payload="$(assistant_selection_payload "${default_resolution_session_file}")"
env "${default_resolution_env[@]}" \
    CC_ASSISTANT_TEST_MODE=1 \
    FAKE_CLAUDE_CAPTURE="${default_resolution_capture}" \
    FAKE_CLAUDE_MODE=valid \
    FAKE_CLAUDE_PAYLOAD_JSON="${default_resolution_payload}" \
    "${artifact}" reconcile assistant-run \
    --session-id "${default_resolution_session}" --json > "${default_resolution_run_probe}" ||
    die "frozen helper registry-resolution assistant-run probe failed (default claude resolution did not reach a ready run): $(<"${default_resolution_run_probe}")"
env "${default_resolution_env[@]}" \
    "${artifact}" reconcile assistant-status \
    --session-id "${default_resolution_session}" --json > "${default_resolution_status_probe}" ||
    die "frozen helper registry-resolution assistant-status probe failed: $(<"${default_resolution_status_probe}")"
/usr/bin/python3 - \
    "${default_resolution_prepare_probe}" \
    "${default_resolution_run_probe}" \
    "${default_resolution_status_probe}" \
    "${default_resolution_capture}" <<'PY'
import json
import re
import sys

prepare_path, run_path, status_path, capture_path = sys.argv[1:5]
prepare, run, status = (
    json.load(open(path, encoding="utf-8"))
    for path in (prepare_path, run_path, status_path)
)
if prepare.get("phase") != "assistant-prepare" or prepare.get("result") != "ready":
    raise SystemExit("registry-resolution probe did not prepare an assistant session")
if run.get("phase") != "assistant-run" or run.get("result") != "ready":
    raise SystemExit(
        "registry-resolution probe did not reach a ready run: default claude "
        "resolution likely failed to locate the closed-registry install"
    )
if status.get("phase") != "assistant-status" or status.get("result") != "ready":
    raise SystemExit("registry-resolution probe did not validate its proposal")
if re.fullmatch(r"proposal_[0-9a-f]{32}", status.get("proposal_id", "")) is None:
    raise SystemExit("registry-resolution probe did not issue an opaque proposal")
capture = json.load(open(capture_path, encoding="utf-8"))
if capture.get("schema_version") != "fake-claude.capture.v1":
    raise SystemExit(
        "registry-resolution probe reported a ready run without ever invoking "
        "the closed-registry claude double; the run report cannot be trusted"
    )
PY

# Leg 2 of 3: default resolution succeeds via the PATH fallback when `claude`
# is NOT anywhere in the closed registry -- this is the leg that actually
# reproduces the 2.7.1 regression. The fake executable sits in an arbitrary
# scratch directory that matches none of `core/executables.py`'s registry
# entries or Node version-manager globs; the disposable HOME has nothing
# under any registry path either, so a ready run is only possible if
# resolution fell through the registry and used PATH.
path_fallback_home="${scratch}/assistant-path-fallback-home"
path_fallback_bin="${scratch}/assistant-path-fallback-bin"
path_fallback_machine_root="${scratch}/assistant-path-fallback-machine"
path_fallback_request="${scratch}/assistant-path-fallback-request.json"
path_fallback_capture="${scratch}/assistant-path-fallback-capture.json"
path_fallback_prepare_probe="${scratch}/assistant-path-fallback-prepare-probe.json"
path_fallback_run_probe="${scratch}/assistant-path-fallback-run-probe.json"
path_fallback_status_probe="${scratch}/assistant-path-fallback-status-probe.json"
mkdir -p "${path_fallback_home}" "${path_fallback_bin}" "${path_fallback_machine_root}"
path_fallback_home="$(cd "${path_fallback_home}" && pwd -P)"
path_fallback_bin="$(cd "${path_fallback_bin}" && pwd -P)"
path_fallback_machine_root="$(cd "${path_fallback_machine_root}" && pwd -P)"
chmod 700 "${path_fallback_home}" "${path_fallback_machine_root}"
install -m 700 \
    "${source_checkout}/tools/cc/tests/fixtures/reconciliation/fake_claude.py" \
    "${path_fallback_bin}/claude"

write_assistant_config_and_request \
    "${path_fallback_machine_root}/config.json" \
    "${path_fallback_request}" \
    "${assistant_project}"

path_fallback_env=(
    HOME="${path_fallback_home}"
    PATH="${path_fallback_bin}:/usr/bin:/bin:/usr/sbin:/sbin"
    CC_MACHINE_ROOT="${path_fallback_machine_root}"
)
env "${path_fallback_env[@]}" \
    "${artifact}" reconcile assistant-prepare \
    --request "${path_fallback_request}" --json > "${path_fallback_prepare_probe}" ||
    die "frozen helper path-fallback assistant-prepare probe failed: $(<"${path_fallback_prepare_probe}")"
path_fallback_session="$(
    assistant_prepared_session_id \
        "${path_fallback_prepare_probe}" \
        "frozen helper path-fallback prepare"
)"
path_fallback_session_file="${path_fallback_machine_root}/diagnostics/reconciliation/assistant/sessions/${path_fallback_session}/session.json"
path_fallback_payload="$(assistant_selection_payload "${path_fallback_session_file}")"
env "${path_fallback_env[@]}" \
    CC_ASSISTANT_TEST_MODE=1 \
    FAKE_CLAUDE_CAPTURE="${path_fallback_capture}" \
    FAKE_CLAUDE_MODE=valid \
    FAKE_CLAUDE_PAYLOAD_JSON="${path_fallback_payload}" \
    "${artifact}" reconcile assistant-run \
    --session-id "${path_fallback_session}" --json > "${path_fallback_run_probe}" ||
    die "frozen helper path-fallback assistant-run probe failed (this is the exact 2.7.1 regression shape: a claude install outside the closed registry, reachable only via PATH, did not reach a ready run): $(<"${path_fallback_run_probe}")"
env "${path_fallback_env[@]}" \
    "${artifact}" reconcile assistant-status \
    --session-id "${path_fallback_session}" --json > "${path_fallback_status_probe}" ||
    die "frozen helper path-fallback assistant-status probe failed: $(<"${path_fallback_status_probe}")"
/usr/bin/python3 - \
    "${path_fallback_prepare_probe}" \
    "${path_fallback_run_probe}" \
    "${path_fallback_status_probe}" \
    "${path_fallback_capture}" <<'PY'
import json
import re
import sys

prepare_path, run_path, status_path, capture_path = sys.argv[1:5]
prepare, run, status = (
    json.load(open(path, encoding="utf-8"))
    for path in (prepare_path, run_path, status_path)
)
if prepare.get("phase") != "assistant-prepare" or prepare.get("result") != "ready":
    raise SystemExit("path-fallback probe did not prepare an assistant session")
if run.get("phase") != "assistant-run" or run.get("result") != "ready":
    raise SystemExit(
        "path-fallback probe did not reach a ready run: this is the exact "
        "2.7.1 regression shape (a non-registry claude install reachable "
        "only via PATH)"
    )
if status.get("phase") != "assistant-status" or status.get("result") != "ready":
    raise SystemExit("path-fallback probe did not validate its proposal")
if re.fullmatch(r"proposal_[0-9a-f]{32}", status.get("proposal_id", "")) is None:
    raise SystemExit("path-fallback probe did not issue an opaque proposal")
capture = json.load(open(capture_path, encoding="utf-8"))
if capture.get("schema_version") != "fake-claude.capture.v1":
    raise SystemExit(
        "path-fallback probe reported a ready run without ever invoking the "
        "PATH-only claude double; the run report cannot be trusted"
    )
PY

# Leg 3 of 3: default resolution fails closed -- a structured
# `claude-code-unavailable` refusal, not a hang or a crash -- when no
# `claude` is resolvable anywhere: not on PATH, not in the closed registry,
# and no `CC_ASSISTANT_CLAUDE_PATH` override set. Resolution failure raises
# before any subprocess is spawned, so there is no lifecycle step here that
# could hang; this leg proves the refusal is exactly the documented
# `claude-code-unavailable` error and not a bare crash or timeout.
unresolved_home="${scratch}/assistant-unresolved-home"
unresolved_machine_root="${scratch}/assistant-unresolved-machine"
unresolved_request="${scratch}/assistant-unresolved-request.json"
unresolved_prepare_probe="${scratch}/assistant-unresolved-prepare-probe.json"
unresolved_run_probe="${scratch}/assistant-unresolved-run-probe.json"
mkdir -p "${unresolved_home}" "${unresolved_machine_root}"
unresolved_home="$(cd "${unresolved_home}" && pwd -P)"
unresolved_machine_root="$(cd "${unresolved_machine_root}" && pwd -P)"
chmod 700 "${unresolved_home}" "${unresolved_machine_root}"

write_assistant_config_and_request \
    "${unresolved_machine_root}/config.json" \
    "${unresolved_request}" \
    "${assistant_project}"

unresolved_env=(
    HOME="${unresolved_home}"
    PATH="/usr/bin:/bin:/usr/sbin:/sbin"
    CC_MACHINE_ROOT="${unresolved_machine_root}"
)
env "${unresolved_env[@]}" \
    "${artifact}" reconcile assistant-prepare \
    --request "${unresolved_request}" --json > "${unresolved_prepare_probe}" ||
    die "frozen helper unresolved-claude assistant-prepare probe failed: $(<"${unresolved_prepare_probe}")"
unresolved_session="$(
    assistant_prepared_session_id \
        "${unresolved_prepare_probe}" \
        "frozen helper unresolved-claude prepare"
)"
set +e
env "${unresolved_env[@]}" \
    "${artifact}" reconcile assistant-run \
    --session-id "${unresolved_session}" --json > "${unresolved_run_probe}"
unresolved_run_exit=$?
set -e
[[ "${unresolved_run_exit}" -eq 1 ]] ||
    die "frozen helper unresolved-claude assistant-run probe exited ${unresolved_run_exit}, expected the fail-closed exit code 1: $(<"${unresolved_run_probe}")"
/usr/bin/python3 - "${unresolved_run_probe}" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
if payload.get("phase") != "error" or payload.get("result") != "error":
    raise SystemExit("unresolved-claude probe did not fail closed with a structured error")
error = payload.get("error", {})
if error.get("code") != "claude-code-unavailable":
    raise SystemExit(
        f"unresolved-claude probe failed with the wrong error code: {error.get('code')!r}"
    )
PY

archive="${scratch}/cc-macos-universal.zip"
ditto -c -k --keepParent "${artifact}" "${archive}"
notary_args=()
if [[ -n "${CT_NOTARY_KEYCHAIN_PROFILE:-}" ]]; then
    notary_args=(--keychain-profile "${CT_NOTARY_KEYCHAIN_PROFILE}")
else
    notary_args=(
        --key "${CT_NOTARY_KEY_PATH}"
        --key-id "${CT_NOTARY_KEY_ID}"
        --issuer "${CT_NOTARY_KEY_ISSUER}"
    )
fi

echo "cc release: submitting helper to Apple notarization"
notary_result="${scratch}/notary-result.json"
xcrun notarytool submit "${archive}" \
    "${notary_args[@]}" \
    --wait \
    --output-format json > "${notary_result}"
notary_status="$(
    /usr/bin/python3 -c \
        'import json,sys; print(json.load(open(sys.argv[1]))["status"])' \
        "${notary_result}"
)"
[[ "${notary_status}" == "Accepted" ]] ||
    die "Apple notarization status was ${notary_status}"
notary_id="$(
    /usr/bin/python3 -c \
        'import json,sys; print(json.load(open(sys.argv[1]))["id"])' \
        "${notary_result}"
)"
notary_log="${scratch}/notary-log.json"
xcrun notarytool log "${notary_id}" "${notary_log}" "${notary_args[@]}"
/usr/bin/python3 - "${notary_log}" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
errors = [
    issue
    for issue in payload.get("issues") or []
    if issue.get("severity") == "error"
]
if errors:
    raise SystemExit(f"notary log contains errors: {errors}")
PY

mkdir -p "${OUTPUT_DIR}"
final_artifact="${OUTPUT_DIR}/cc"
ditto "${artifact}" "${final_artifact}"
chmod 755 "${final_artifact}"
artifact_sha="$(shasum -a 256 "${final_artifact}" | awk '{print $1}')"
printf '%s  cc\n' "${artifact_sha}" > "${OUTPUT_DIR}/cc.sha256"
archive_sha="$(shasum -a 256 "${archive}" | awk '{print $1}')"
ditto "${archive}" "${OUTPUT_DIR}/cc-macos-universal.zip"
ditto "${notary_result}" "${OUTPUT_DIR}/notary-result.json"
ditto "${notary_log}" "${OUTPUT_DIR}/notary-log.json"

cat > "${OUTPUT_DIR}/release-metadata.json" <<EOF
{
  "schema_version": "1.0",
  "product": "claude-copilot-cc",
  "version": "${expected_version}",
  "foundation_ref": "${SOURCE_REF}",
  "source_commit": "${SOURCE_COMMIT}",
  "release_tool_commit": "${release_tool_commit}",
  "architectures": ["arm64", "x86_64"],
  "python_version": "${PYTHON_VERSION}",
  "python_package_sha256": "${PYTHON_SHA256}",
  "pyinstaller_version": "${PYINSTALLER_VERSION}",
  "developer_id_identity": "${CT_SIGN_IDENTITY}",
  "notarization_id": "${notary_id}",
  "notarization_status": "${notary_status}",
  "notarization_container": "cc-macos-universal.zip",
  "notarization_container_sha256": "${archive_sha}",
  "standalone_ticket_staple": "unsupported-by-apple",
  "device_flow_https_probe": "passed",
  "finder_onboard_probe": "passed",
  "finder_reconciliation_probe": "passed",
  "finder_reconciliation_assistant_probe": "passed",
  "finder_reconciliation_assistant_default_resolution_probe": "passed",
  "sha256": "${artifact_sha}"
}
EOF

echo "cc release: ready"
echo "  artifact: ${final_artifact}"
echo "  sha256: ${artifact_sha}"
echo "  notarization: ${notary_status} (${notary_id})"
