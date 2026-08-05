"""Read-only composition of authoritative machine and ecosystem truth.

The reconciliation coordinator consumes :func:`build_machine_assessment` and
does not re-interpret doctor, connection, configuration, authentication, or
workspace-root state.  This module only reads those established sources and
normalizes them into the frozen ``MachineAssessment`` contract.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from cc import __version__
from cc.core.ecosystem.reconciliation_types import Blocker, Evidence, MachineAssessment

ReportBuilder = Callable[[], dict[str, Any]]
ConfigReader = Callable[[], dict[str, Any]]
PathGetter = Callable[[], Path]
RootsBuilder = Callable[[], list[dict[str, Any]]]
IdentityReader = Callable[[], dict[str, Any]]
CredentialReader = Callable[..., str | None]
ExecutableResolver = Callable[[str], Path | None]
ExecutableVersionReader = Callable[[str, Path], str | None]
FrameworkVersionReader = Callable[[Path, str], str | None]
FrameworkSourceValidator = Callable[[str, Path], bool]

_MINIMUM_HELPER_VERSION = "2.8.0"
_MINIMUM_FRAMEWORK_VERSIONS = {"claude": "5.13.3", "codex": "0.6.1"}
_FRAMEWORK_CONFIG_KEYS = {
    "claude": "paths.claude_copilot_root",
    "codex": "paths.codex_copilot_root",
}
_DEPENDENCIES = ("git", "gh", "copilot", "claude", "codex")
_REQUIRED_DEPENDENCIES = frozenset({"git", "copilot"})
_VERSION_PATTERN = re.compile(r"(?<!\d)(\d+)\.(\d+)(?:\.(\d+))?")


def _evidence(identifier: str, state: str, detail: str) -> Evidence:
    return {"id": identifier, "state": state, "detail": detail}


def _blocker(
    code: str,
    actor: str,
    detail: str,
    next_action: str,
    *,
    evidence_id: str | None = None,
    evidence_state: str = "blocked",
) -> Blocker:
    return {
        "code": code,
        "responsible_actor": actor,
        "evidence": [_evidence(evidence_id or code, evidence_state, detail)],
        "next_action": next_action,
    }


def _lookup(config: dict[str, Any], dotted_key: str) -> Any:
    if dotted_key in config:
        return config[dotted_key]
    value: Any = config
    for part in dotted_key.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _normalized_paths(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value] if value else []
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        if not isinstance(item, (str, os.PathLike)):
            continue
        path = str(Path(item).expanduser())
        if path not in seen:
            seen.add(path)
            result.append(path)
    return result


def _readable(path: Path, *, directory: bool = False) -> bool:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return False
    readable = bool(mode & (stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH))
    searchable = not directory or bool(
        mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    )
    return readable and searchable and os.access(path, os.R_OK)


def _missing_private_directory_is_creatable(path: Path) -> bool:
    """Return whether the CLI can safely create a missing owned state leaf."""
    candidate = path
    while True:
        try:
            metadata = candidate.lstat()
            break
        except FileNotFoundError:
            parent = candidate.parent
            if parent == candidate:
                return False
            candidate = parent
        except OSError:
            return False

    effective_uid = os.geteuid()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != effective_uid:
        return False
    mode = stat.S_IMODE(metadata.st_mode)
    required_owner_access = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR
    if mode & required_owner_access != required_owner_access:
        return False

    trusted_owners = {0, effective_uid}
    for existing in reversed((candidate, *candidate.parents)):
        try:
            existing_metadata = existing.lstat()
            if (
                stat.S_ISLNK(existing_metadata.st_mode)
                or not stat.S_ISDIR(existing_metadata.st_mode)
                or existing_metadata.st_uid not in trusted_owners
            ):
                return False
        except OSError:
            return False
    return True


def _diagnostics_readiness(path_getter: PathGetter) -> tuple[list[Blocker], bool]:
    """Inspect the diagnostic boundary without creating or repairing it."""
    path: Path | None = None
    try:
        path = Path(path_getter()).expanduser()
        if not path.is_absolute():
            raise ValueError("diagnostics boundary is not absolute")
        path = Path(os.path.normpath(os.fspath(path)))
        if path == Path("/"):
            raise ValueError("diagnostics boundary is too broad")
        path_stat = path.lstat()
    except FileNotFoundError:
        if path is not None and _missing_private_directory_is_creatable(path):
            return [], False
        return (
            [
                _blocker(
                    "diagnostics-location-missing",
                    "person",
                    "The private diagnostics location is missing.",
                    "Restore the private diagnostics location, then run assessment again.",
                )
            ],
            False,
        )
    except Exception:
        return (
            [
                _blocker(
                    "diagnostics-location-unavailable",
                    "person",
                    "The private diagnostics boundary could not be inspected safely.",
                    "Restore the private diagnostics boundary, then run assessment again.",
                )
            ],
            True,
        )

    effective_uid = os.geteuid()
    trusted_owners = {0, effective_uid}
    try:
        ancestry = [
            (candidate, candidate.lstat())
            for candidate in reversed((path, *path.parents))
        ]
    except OSError:
        return (
            [
                _blocker(
                    "diagnostics-location-unavailable",
                    "person",
                    "The private diagnostics boundary could not be inspected safely.",
                    "Restore the private diagnostics boundary, then run assessment again.",
                )
            ],
            True,
        )

    if any(stat.S_ISLNK(metadata.st_mode) for _, metadata in ancestry):
        return (
            [
                _blocker(
                    "diagnostics-location-symlinked",
                    "person",
                    "The private diagnostics boundary is a symbolic link and is not trusted.",
                    "Replace the symbolic link with the real private diagnostics directory, then run assessment again.",
                )
            ],
            False,
        )
    if any(not stat.S_ISDIR(metadata.st_mode) for _, metadata in ancestry):
        return (
            [
                _blocker(
                    "diagnostics-location-unavailable",
                    "person",
                    "The private diagnostics location is not a directory.",
                    "Restore the private diagnostics directory, then run assessment again.",
                )
            ],
            False,
        )
    if path_stat.st_uid != effective_uid or any(
        metadata.st_uid not in trusted_owners for _, metadata in ancestry[:-1]
    ):
        return (
            [
                _blocker(
                    "diagnostics-location-untrusted-owner",
                    "person",
                    "The private diagnostics boundary or one of its ancestors has an untrusted owner.",
                    "Restore current-user ownership of the private diagnostics boundary, then run assessment again.",
                )
            ],
            False,
        )

    mode = stat.S_IMODE(path_stat.st_mode)
    readable = bool(mode & (stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH))
    writable = bool(mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    searchable = bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
    if not (
        readable
        and writable
        and searchable
        and os.access(path, os.R_OK | os.W_OK | os.X_OK)
    ):
        return (
            [
                _blocker(
                    "diagnostics-location-unwritable",
                    "person",
                    "The private diagnostics location cannot save durable reconciliation evidence.",
                    "Restore read, write, and search permission for the private diagnostics directory, then run assessment again.",
                )
            ],
            False,
        )
    return [], False


def _semantic_version(value: str | None) -> tuple[int, int, int] | None:
    if not value:
        return None
    match = _VERSION_PATTERN.search(value)
    if match is None:
        return None
    return tuple(int(part or 0) for part in match.groups())


def _version_at_least(value: str | None, minimum: str) -> bool:
    actual = _semantic_version(value)
    required = _semantic_version(minimum)
    return actual is not None and required is not None and actual >= required


def _default_framework_version(path: Path, component: str) -> str | None:
    try:
        if component == "claude":
            payload = json.loads((path / "VERSION.json").read_text(encoding="utf-8"))
            for key in ("framework", "version", "frameworkVersion"):
                value = payload.get(key)
                if isinstance(value, str) and value:
                    return value
            return None
        payload = json.loads(
            (path / "plugins/codex-copilot/.codex-plugin/plugin.json").read_text(
                encoding="utf-8"
            )
        )
        value = payload.get("version")
        return value if isinstance(value, str) and value else None
    except (FileNotFoundError, json.JSONDecodeError, OSError, AttributeError):
        return None


def _default_executable_version(command: str, path: Path) -> str | None:
    try:
        result = subprocess.run(
            [str(path), "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    output = (result.stdout or result.stderr).strip().splitlines()
    return output[0][:160] if output else None


def _configured_roots(
    config: dict[str, Any], root_entries: list[dict[str, Any]]
) -> list[str]:
    roots = _normalized_paths(_lookup(config, "projects.roots"))
    for entry in root_entries:
        path = entry.get("path")
        if isinstance(path, str) and path not in roots:
            roots.append(path)
    return roots


def _configuration_assessment(
    config: dict[str, Any],
    config_path: Path,
    root_entries: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[Blocker], bool]:
    blockers: list[Blocker] = []
    could_not_verify = False
    config_state = "ready"

    if config_path.is_symlink():
        config_state = "unreadable"
        could_not_verify = True
        blockers.append(
            _blocker(
                "machine-config-symlinked",
                "person",
                "The machine configuration path is a symbolic link, so its boundary is not trusted.",
                "Replace the symbolic link with the real machine configuration file, then run assessment again.",
            )
        )
    elif not config_path.is_file():
        config_state = "missing"
        blockers.append(
            _blocker(
                "machine-config-missing",
                "person",
                "The machine configuration file is missing.",
                "Complete Copilot machine setup, then run assessment again.",
            )
        )
    else:
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("configuration is not an object")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            config_state = "unreadable"
            could_not_verify = True
            blockers.append(
                _blocker(
                    "machine-config-unreadable",
                    "person",
                    "The machine configuration file could not be read as a configuration object.",
                    "Restore a readable machine configuration file, then run assessment again.",
                )
            )

    roots = _configured_roots(config, root_entries)
    root_states = {entry.get("path"): entry.get("state") for entry in root_entries}
    if not roots:
        if config_state == "ready":
            config_state = "roots-missing"
        blockers.append(
            _blocker(
                "approved-roots-missing",
                "person",
                "No project folder is approved for bounded discovery.",
                "Choose a project folder to approve, then run assessment again.",
            )
        )

    for raw_path in roots:
        root = Path(raw_path)
        injected_state = root_states.get(raw_path)
        if root.is_symlink() or injected_state == "symlinked":
            config_state = "roots-unsafe"
            blockers.append(
                _blocker(
                    "approved-root-symlinked",
                    "person",
                    f"The approved project folder {root.name or 'selected folder'} is a symbolic link.",
                    "Approve the real project folder itself instead of its symbolic link.",
                )
            )
        elif not root.is_dir() or injected_state == "missing":
            if config_state == "ready":
                config_state = "roots-missing"
            blockers.append(
                _blocker(
                    "approved-root-missing",
                    "person",
                    f"The approved project folder {root.name or 'selected folder'} is not available.",
                    "Reconnect or restore that project folder, then run assessment again.",
                )
            )
        elif not _readable(root, directory=True) or injected_state == "unreadable":
            config_state = "roots-unreadable"
            could_not_verify = True
            blockers.append(
                _blocker(
                    "approved-root-unreadable",
                    "person",
                    f"The approved project folder {root.name or 'selected folder'} cannot be read safely.",
                    "Restore read and search permission for that project folder, then run assessment again.",
                )
            )

    if blockers:
        detail = "Machine configuration or an approved project folder needs attention."
    else:
        detail = f"Machine configuration is readable and {len(roots)} project folder(s) are approved."
    return (
        {
            "state": config_state,
            "path": str(config_path),
            "approved_roots": roots,
            "detail": detail,
        },
        blockers,
        could_not_verify,
    )


def _helper_assessment(
    resolver: ExecutableResolver,
    helper_version: str | None,
    *,
    use_process_fallback: bool,
) -> tuple[dict[str, Any], list[Blocker]]:
    path = resolver("cc")
    if path is None and use_process_fallback:
        candidate = Path(sys.argv[0]).expanduser()
        try:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                path = candidate.resolve()
        except OSError:
            path = None

    if helper_version is None or path is None:
        return (
            {
                "state": "missing",
                "version": helper_version,
                "path": str(path) if path else None,
                "detail": "The reconciliation helper is not available from a supported executable path.",
            },
            [
                _blocker(
                    "helper-missing",
                    "person",
                    "The reconciliation helper is missing or cannot be launched safely.",
                    "Install the supported cc helper, then run assessment again.",
                )
            ],
        )
    if not _version_at_least(helper_version, _MINIMUM_HELPER_VERSION):
        return (
            {
                "state": "incompatible",
                "version": helper_version,
                "path": str(path),
                "detail": f"cc {helper_version} is older than the required {_MINIMUM_HELPER_VERSION} reconciliation contract.",
            },
            [
                _blocker(
                    "helper-incompatible",
                    "person",
                    f"cc {helper_version} cannot provide the required reconciliation contract.",
                    f"Install cc {_MINIMUM_HELPER_VERSION} or newer, then run assessment again.",
                )
            ],
        )
    return (
        {
            "state": "ready",
            "version": helper_version,
            "path": str(path),
            "detail": f"cc {helper_version} is available from a supported executable path.",
        },
        [],
    )


def _framework_assessments(
    config: dict[str, Any],
    version_reader: FrameworkVersionReader,
    source_validator: FrameworkSourceValidator,
) -> tuple[list[dict[str, Any]], list[Blocker], bool]:
    rows: list[dict[str, Any]] = []
    blockers: list[Blocker] = []
    could_not_verify = False
    for component, key in _FRAMEWORK_CONFIG_KEYS.items():
        raw_path = _lookup(config, key)
        path = Path(str(raw_path)).expanduser() if raw_path else None
        version: str | None = None
        state = "ready"
        if path is None or not path.is_dir():
            state = "missing"
            detail = f"The configured {component.title()} framework source is missing."
            blockers.append(
                _blocker(
                    f"{component}-framework-missing",
                    "ecosystem-owner",
                    detail,
                    f"Restore the authoritative {component.title()} framework source, then run assessment again.",
                )
            )
        elif not _readable(path, directory=True):
            state = "could-not-verify"
            could_not_verify = True
            detail = f"The configured {component.title()} framework source cannot be inspected safely."
            blockers.append(
                _blocker(
                    f"{component}-framework-unreadable",
                    "ecosystem-owner",
                    detail,
                    f"Restore a readable {component.title()} framework source, then run assessment again.",
                )
            )
        elif not source_validator(component, path):
            state = "could-not-verify"
            could_not_verify = True
            detail = f"The configured {component.title()} framework source cannot supply a verified reconciliation recipe."
            blockers.append(
                _blocker(
                    f"{component}-framework-recipe-source-unverified",
                    "ecosystem-owner",
                    detail,
                    f"Restore the authoritative {component.title()} recipe source, then run assessment again.",
                )
            )
        else:
            version = version_reader(path, component)
            minimum = _MINIMUM_FRAMEWORK_VERSIONS[component]
            if version is None:
                state = "could-not-verify"
                could_not_verify = True
                detail = (
                    f"The {component.title()} framework version could not be verified."
                )
                blockers.append(
                    _blocker(
                        f"{component}-framework-version-unverified",
                        "ecosystem-owner",
                        detail,
                        f"Restore version evidence for the {component.title()} framework source, then run assessment again.",
                    )
                )
            elif not _version_at_least(version, minimum):
                state = "incompatible"
                detail = f"The {component.title()} framework is {version}; reconciliation requires {minimum} or newer."
                blockers.append(
                    _blocker(
                        f"{component}-framework-incompatible",
                        "ecosystem-owner",
                        detail,
                        f"Update the {component.title()} framework source to {minimum} or newer, then run assessment again.",
                    )
                )
            else:
                detail = (
                    f"The {component.title()} framework source is version {version}."
                )
        rows.append(
            {
                "component": component,
                "state": state,
                "path": str(path) if path else None,
                "version": version,
                "detail": detail,
            }
        )
    return rows, blockers, could_not_verify


def _authentication_assessment(
    doctor: dict[str, Any] | None,
    config: dict[str, Any],
    identity_reader: IdentityReader,
    credential_reader: CredentialReader,
) -> tuple[dict[str, Any], list[Blocker], bool]:
    try:
        identity = identity_reader()
    except Exception:  # a failed presence probe is an honest unknown, never signed out
        detail = "The local sign-in identity store could not be inspected."
        return (
            {
                "state": "could-not-verify",
                "credential_state": "store-unreachable",
                "detail": detail,
            },
            [
                _blocker(
                    "identity-store-unreachable",
                    "person",
                    detail,
                    "Restore access to the local sign-in store, then run assessment again.",
                )
            ],
            True,
        )

    bad_auth = next(
        (
            entry
            for entry in (doctor or {}).get("auth", [])
            if isinstance(entry, dict) and entry.get("state") in {"expired", "revoked"}
        ),
        None,
    )
    if bad_auth is not None:
        state = str(bad_auth["state"])
        detail = (
            "The saved sign-in has expired."
            if state == "expired"
            else "The saved sign-in no longer has a credential in the local credential store."
        )
        return (
            {
                "state": state,
                "credential_state": state if state == "expired" else "absent",
                "detail": detail,
            },
            [
                _blocker(
                    f"authentication-{state}",
                    "person",
                    detail,
                    "Sign in to Copilot again, then run assessment again.",
                )
            ],
            False,
        )

    login = identity.get("login") if isinstance(identity, dict) else None
    if not isinstance(login, str) or not login:
        detail = "No Copilot sign-in is recorded on this Mac."
        return (
            {"state": "signed-out", "credential_state": "absent", "detail": detail},
            [
                _blocker(
                    "authentication-signed-out",
                    "person",
                    detail,
                    "Sign in to Copilot, then run assessment again.",
                )
            ],
            False,
        )

    expires_at = identity.get("expires_at")
    if isinstance(expires_at, str):
        try:
            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry <= datetime.now(timezone.utc):
                detail = "The saved Copilot sign-in has expired."
                return (
                    {
                        "state": "expired",
                        "credential_state": "expired",
                        "detail": detail,
                    },
                    [
                        _blocker(
                            "authentication-expired",
                            "person",
                            detail,
                            "Sign in to Copilot again, then run assessment again.",
                        )
                    ],
                    False,
                )
        except ValueError:
            pass

    service = _lookup(config, "auth.keychain_service") or (
        "com.everyoneneedsacopilot.copilot.github"
    )
    try:
        credential = credential_reader(login, service=str(service))
    except Exception:  # keychain availability failures must not become "absent"
        detail = "The local credential store could not be reached to confirm sign-in."
        return (
            {
                "state": "could-not-verify",
                "credential_state": "store-unreachable",
                "detail": detail,
            },
            [
                _blocker(
                    "credential-store-unreachable",
                    "person",
                    detail,
                    "Restore access to the macOS credential store, then run assessment again.",
                )
            ],
            True,
        )
    if credential is None:
        detail = "A sign-in identity exists, but its credential is absent."
        return (
            {"state": "revoked", "credential_state": "absent", "detail": detail},
            [
                _blocker(
                    "authentication-revoked",
                    "person",
                    detail,
                    "Sign in to Copilot again, then run assessment again.",
                )
            ],
            False,
        )
    return (
        {
            "state": "signed-in",
            "credential_state": "present",
            "detail": "A Copilot sign-in and its credential are present.",
        },
        [],
        False,
    )


def _layer_assessment(
    doctor: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[Blocker], bool]:
    if doctor is None:
        detail = (
            "Layer readiness could not be inspected because doctor was unavailable."
        )
        return (
            {"state": "could-not-verify", "ready": 0, "total": 0, "detail": detail},
            [
                _blocker(
                    "layers-unavailable",
                    "ecosystem-owner",
                    detail,
                    "Restore the machine health assessment source, then run assessment again.",
                )
            ],
            True,
        )
    checkers = [item for item in doctor.get("checkers", []) if isinstance(item, dict)]
    layer_rows = [item for item in checkers if item.get("layer")]
    ready = sum(item.get("severity") == "pass" for item in layer_rows)
    total = len(layer_rows)
    manifest_failure = next(
        (
            item
            for item in checkers
            if item.get("id") == "ecosystem-layer-manifest"
            and item.get("severity") == "fail"
        ),
        None,
    )
    if total == 0:
        detail = (
            "The ecosystem layer manifest is missing or invalid."
            if manifest_failure
            else "No ecosystem layers are configured for assessment."
        )
        state = "could-not-verify" if manifest_failure else "not-configured"
        return (
            {"state": state, "ready": 0, "total": 0, "detail": detail},
            [
                _blocker(
                    "layers-manifest-unavailable"
                    if manifest_failure
                    else "layers-not-configured",
                    "ecosystem-owner",
                    detail,
                    "Restore the authoritative ecosystem layer manifest, then run assessment again.",
                )
            ],
            bool(manifest_failure),
        )
    non_ready = [item for item in layer_rows if item.get("severity") != "pass"]
    if not non_ready:
        return (
            {
                "state": "ready",
                "ready": ready,
                "total": total,
                "detail": f"All {total} configured ecosystem layer(s) passed their readiness checks.",
            },
            [],
            False,
        )
    evidence = [
        _evidence(
            str(item.get("id") or "layer-readiness"),
            str(item.get("severity") or "fail"),
            str(
                item.get("detail")
                or "An ecosystem layer did not pass its readiness check."
            ),
        )
        for item in non_ready
    ]
    detail = f"{len(non_ready)} of {total} ecosystem layer(s) need attention."
    item_label = "item that is" if len(non_ready) == 1 else "items that are"
    blocker: Blocker = {
        "code": "layers-not-ready",
        "responsible_actor": "ecosystem-owner",
        "evidence": evidence,
        "next_action": (
            f"Update the {len(non_ready)} Copilot setup {item_label} behind, "
            "then check again."
        ),
    }
    return (
        {"state": "action-required", "ready": ready, "total": total, "detail": detail},
        [blocker],
        False,
    )


def _connectivity_assessment(
    doctor: dict[str, Any] | None,
    connections: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[Blocker], bool]:
    if doctor is not None and doctor.get("offline") is True:
        detail = "This Mac is offline from at least one required ecosystem source."
        return (
            {"state": "offline", "detail": detail},
            [
                _blocker(
                    "connectivity-offline",
                    "person",
                    detail,
                    "Reconnect this Mac to the network, then run assessment again.",
                )
            ],
            False,
        )
    layer_checked = bool(
        doctor
        and any(
            isinstance(item, dict) and item.get("layer")
            for item in doctor.get("checkers", [])
        )
    )
    connection_checked = bool(
        connections and connections.get("result") != "copilot-unavailable"
    )
    if layer_checked or connection_checked:
        return (
            {
                "state": "online",
                "detail": "Required remote connectivity checks completed without an offline result.",
            },
            [],
            False,
        )
    detail = "Connectivity could not be checked independently from local configuration."
    return (
        {"state": "could-not-verify", "detail": detail},
        [
            _blocker(
                "connectivity-unavailable",
                "person",
                detail,
                "Restore the Copilot CLI connection probe, then run assessment again.",
            )
        ],
        True,
    )


def _dependency_assessments(
    resolver: ExecutableResolver,
    version_reader: ExecutableVersionReader,
) -> tuple[list[dict[str, Any]], list[Blocker]]:
    rows: list[dict[str, Any]] = []
    blockers: list[Blocker] = []
    for dependency in _DEPENDENCIES:
        path = resolver(dependency)
        required = dependency in _REQUIRED_DEPENDENCIES
        if path is None:
            state = "missing"
            detail = (
                f"Required dependency {dependency} is missing."
                if required
                else f"Optional {dependency} integration is not installed."
            )
            if required:
                blockers.append(
                    _blocker(
                        f"dependency-{dependency}-missing",
                        "person",
                        detail,
                        f"Install {dependency} from a supported location, then run assessment again.",
                    )
                )
        else:
            version = version_reader(dependency, path)
            state = "ready"
            detail = (
                f"{dependency} is available at {path} ({version})."
                if version
                else f"{dependency} is available at {path}; its version could not be read."
            )
        rows.append({"id": dependency, "state": state, "detail": detail})
    return rows, blockers


def _connection_blockers(
    connections: dict[str, Any] | None,
) -> tuple[list[Blocker], bool]:
    if connections is None:
        return (
            [
                _blocker(
                    "connections-unavailable",
                    "ecosystem-owner",
                    "Declared connection and credential readiness could not be inspected.",
                    "Restore the connections assessment source, then run assessment again.",
                )
            ],
            True,
        )
    blockers: list[Blocker] = []
    result = connections.get("result")
    if result == "copilot-unavailable":
        blockers.append(
            _blocker(
                "connections-cli-unavailable",
                "person",
                "The Copilot CLI could not provide the declared connection roster.",
                "Restore the supported Copilot CLI, then run assessment again.",
            )
        )
    elif result == "org-config-unavailable":
        blockers.append(
            _blocker(
                "organization-config-unavailable",
                "ecosystem-owner",
                "The inherited organization configuration is not available on this Mac.",
                "Restore the inherited organization configuration, then run assessment again.",
            )
        )
    store = connections.get("store")
    if result == "ok" and isinstance(store, dict) and not store.get("reachable", False):
        blockers.append(
            _blocker(
                "shared-credential-store-unreachable",
                "ecosystem-owner",
                "The organization credential store is configured but unreachable.",
                "Restore the organization credential-store connection, then run assessment again.",
            )
        )
    for row in connections.get("connections", []):
        if not isinstance(row, dict):
            continue
        state = row.get("secret_state")
        if state not in {"needs-connect", "no-store"}:
            continue
        service_id = str(row.get("id") or "declared service")
        detail = (
            f"{service_id} is missing one or more required credentials."
            if state == "needs-connect"
            else f"{service_id} cannot confirm its required credentials because no store is available."
        )
        blockers.append(
            _blocker(
                f"connection-{state}-{service_id}",
                "person" if state == "needs-connect" else "ecosystem-owner",
                detail,
                f"Run cc connect {service_id}, then run assessment again."
                if state == "needs-connect"
                else "Restore the organization credential store, then run assessment again.",
            )
        )
    return blockers, result == "copilot-unavailable"


def build_machine_assessment(
    *,
    doctor_builder: ReportBuilder | None = None,
    connections_builder: ReportBuilder | None = None,
    config_reader: ConfigReader | None = None,
    config_path_getter: PathGetter | None = None,
    diagnostics_path_getter: PathGetter | None = None,
    roots_builder: RootsBuilder | None = None,
    identity_reader: IdentityReader | None = None,
    credential_reader: CredentialReader | None = None,
    executable_resolver: ExecutableResolver | None = None,
    framework_version_reader: FrameworkVersionReader | None = None,
    framework_source_validator: FrameworkSourceValidator | None = None,
    helper_version: str | None = __version__,
    executable_version_reader: ExecutableVersionReader | None = None,
) -> MachineAssessment:
    """Return the complete read-only machine portion of reconciliation truth.

    Every collaborator is injectable for deterministic fixture coverage.  The
    production defaults are resolved inside the function so monkeypatching the
    established source modules remains effective in command-level tests.
    """
    if doctor_builder is None:
        from cc.commands.doctor import build_doctor_report

        doctor_builder = build_doctor_report
    if connections_builder is None:
        from cc.commands.connections import build_connections_report

        connections_builder = build_connections_report
    if config_reader is None:
        from cc.core.config import get_resolved_config

        def read_effective_machine_config() -> dict[str, Any]:
            return get_resolved_config(_project={})

        config_reader = read_effective_machine_config
    if config_path_getter is None:
        from cc.core.config_paths import machine_config_path

        config_path_getter = machine_config_path
    if diagnostics_path_getter is None:
        from cc.core.config_paths import machine_diagnostics_root

        diagnostics_path_getter = machine_diagnostics_root
    if roots_builder is None:
        from cc.core.ecosystem.workspaces import list_configured_roots

        roots_builder = list_configured_roots
    if identity_reader is None:
        from cc.core.authstore import read_identity

        identity_reader = read_identity
    if credential_reader is None:
        from cc.core.keychain import get_secret

        credential_reader = get_secret
    using_default_resolver = executable_resolver is None
    if executable_resolver is None:
        from cc.core.executables import resolve_executable

        executable_resolver = resolve_executable
    if framework_version_reader is None:
        framework_version_reader = _default_framework_version
    if framework_source_validator is None:
        from cc.core.ecosystem.reconciliation_recipes import (
            authoritative_source_available,
        )

        framework_source_validator = authoritative_source_available
    if executable_version_reader is None:
        executable_version_reader = _default_executable_version

    blockers: list[Blocker] = []
    could_not_verify = False

    try:
        config = config_reader()
        if not isinstance(config, dict):
            raise TypeError("configuration source did not return an object")
    except Exception:
        config = {}
        could_not_verify = True
        blockers.append(
            _blocker(
                "configuration-source-unavailable",
                "person",
                "The effective machine configuration could not be inspected.",
                "Restore the machine configuration source, then run assessment again.",
            )
        )
    try:
        root_entries = roots_builder()
    except Exception:
        root_entries = []
        could_not_verify = True
        blockers.append(
            _blocker(
                "approved-roots-source-unavailable",
                "person",
                "Approved project folders could not be enumerated.",
                "Restore the approved-root registry, then run assessment again.",
            )
        )

    helper, helper_blockers = _helper_assessment(
        executable_resolver,
        helper_version,
        use_process_fallback=using_default_resolver,
    )
    blockers.extend(helper_blockers)

    try:
        config_path = config_path_getter()
    except Exception:
        config_path = Path("/unavailable/machine-config.json")
        could_not_verify = True
        blockers.append(
            _blocker(
                "machine-config-path-unavailable",
                "person",
                "The machine configuration boundary could not be resolved.",
                "Restore the machine configuration boundary, then run assessment again.",
            )
        )
    configuration, configuration_blockers, configuration_unknown = (
        _configuration_assessment(config, config_path, root_entries)
    )
    blockers.extend(configuration_blockers)
    could_not_verify = could_not_verify or configuration_unknown

    diagnostics_blockers, diagnostics_unknown = _diagnostics_readiness(
        diagnostics_path_getter
    )
    blockers.extend(diagnostics_blockers)
    could_not_verify = could_not_verify or diagnostics_unknown

    frameworks, framework_blockers, framework_unknown = _framework_assessments(
        config, framework_version_reader, framework_source_validator
    )
    blockers.extend(framework_blockers)
    could_not_verify = could_not_verify or framework_unknown

    try:
        doctor = doctor_builder()
        if not isinstance(doctor, dict):
            raise TypeError("doctor source did not return an object")
    except Exception:
        doctor = None
        could_not_verify = True
        blockers.append(
            _blocker(
                "doctor-unavailable",
                "ecosystem-owner",
                "The authoritative machine health report could not be produced.",
                "Restore cc doctor, then run assessment again.",
            )
        )
    try:
        connections = connections_builder()
        if not isinstance(connections, dict):
            raise TypeError("connections source did not return an object")
    except Exception:
        connections = None
        could_not_verify = True

    authentication, authentication_blockers, authentication_unknown = (
        _authentication_assessment(doctor, config, identity_reader, credential_reader)
    )
    blockers.extend(authentication_blockers)
    could_not_verify = could_not_verify or authentication_unknown

    connectivity, connectivity_blockers, connectivity_unknown = (
        _connectivity_assessment(doctor, connections)
    )
    blockers.extend(connectivity_blockers)
    could_not_verify = could_not_verify or connectivity_unknown

    layers, layer_blockers, layers_unknown = _layer_assessment(doctor)
    blockers.extend(layer_blockers)
    could_not_verify = could_not_verify or layers_unknown

    dependencies, dependency_blockers = _dependency_assessments(
        executable_resolver, executable_version_reader
    )
    blockers.extend(dependency_blockers)

    connection_blockers, connections_unknown = _connection_blockers(connections)
    blockers.extend(connection_blockers)
    could_not_verify = could_not_verify or connections_unknown

    state = (
        "could-not-verify"
        if could_not_verify
        else "action-required"
        if blockers
        else "ready"
    )
    next_action = (
        blockers[0]["next_action"]
        if blockers
        else "No machine action is required. Select projects to review or reconcile."
    )
    return {
        "state": state,
        "helper": helper,
        "frameworks": frameworks,
        "configuration": configuration,
        "authentication": authentication,
        "connectivity": connectivity,
        "layers": layers,
        "dependencies": dependencies,
        "blockers": blockers,
        "next_action": next_action,
    }


__all__ = ["build_machine_assessment"]
