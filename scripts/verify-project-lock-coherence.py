#!/usr/bin/env python3
"""Verify that the closed root project lock exactly matches the release tree."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_MAX_FILE_BYTES = 32 * 1024 * 1024
_MAX_LOCK_BYTES = 2 * 1024 * 1024
_LOCK_MODE = 0o644
_ROOT_KEYS = {"schema_version", "components", "mutations"}
_COMPONENT_KEYS = {
    "component",
    "version",
    "release_tag",
    "ownership_mode",
    "files",
}
_FILE_KEYS = {"path", "ownership", "checksum"}


def _fail(message: str) -> NoReturn:
    raise SystemExit(f"project lock coherence: {message}")


def _stable_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_uid,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _canonical_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        _fail("component file path must be a non-empty string")
    candidate = PurePosixPath(value)
    if (
        candidate.is_absolute()
        or value != candidate.as_posix()
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        _fail(f"component file path is not canonical: {value!r}")
    return value


def _open_directory(root_descriptor: int, relative_path: str) -> int:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if no_follow is None or directory_flag is None:
        _fail("platform lacks no-follow directory protections")
    descriptor = os.dup(root_descriptor)
    try:
        for part in PurePosixPath(relative_path).parts:
            opened = os.open(
                part,
                os.O_RDONLY | directory_flag | no_follow,
                dir_fd=descriptor,
            )
            metadata = os.fstat(opened)
            if not stat.S_ISDIR(metadata.st_mode):
                os.close(opened)
                _fail(f"path parent is not a directory: {relative_path}")
            os.close(descriptor)
            descriptor = opened
        return descriptor
    except OSError as exc:
        os.close(descriptor)
        _fail(f"cannot open directory safely: {relative_path}: {exc}")
    except BaseException:
        os.close(descriptor)
        raise


def _named_identity(root_descriptor: int, relative_path: str) -> tuple[int, ...]:
    parts = PurePosixPath(relative_path).parts
    parent = _open_directory(root_descriptor, PurePosixPath(*parts[:-1]).as_posix())
    try:
        metadata = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
    except OSError as exc:
        _fail(f"cannot revalidate named path: {relative_path}: {exc}")
    finally:
        os.close(parent)
    return _stable_identity(metadata)


def _read_exact_file_snapshot(
    root_descriptor: int,
    relative_path: str,
    *,
    maximum: int = _MAX_FILE_BYTES,
    required_mode: int | None = None,
) -> tuple[bytes, tuple[int, ...]]:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        _fail("platform lacks O_NOFOLLOW")
    parts = PurePosixPath(relative_path).parts
    parent = _open_directory(root_descriptor, PurePosixPath(*parts[:-1]).as_posix())
    descriptor: int | None = None
    try:
        descriptor = os.open(parts[-1], os.O_RDONLY | no_follow, dir_fd=parent)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.getuid()
            or before.st_size > maximum
            or (
                required_mode is not None
                and stat.S_IMODE(before.st_mode) != required_mode
            )
        ):
            _fail(f"path is not an exact bounded owner file: {relative_path}")
        payload = bytearray()
        while len(payload) <= maximum:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            payload.extend(chunk)
        after = os.fstat(descriptor)
        if (
            len(payload) > maximum
            or _stable_identity(before) != _stable_identity(after)
            or _named_identity(root_descriptor, relative_path)
            != _stable_identity(before)
        ):
            _fail(f"path changed while it was read: {relative_path}")
        return bytes(payload), _stable_identity(after)
    except OSError as exc:
        _fail(f"cannot open path safely: {relative_path}: {exc}")
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent)


def _read_exact_file(
    root_descriptor: int,
    relative_path: str,
    *,
    maximum: int = _MAX_FILE_BYTES,
    required_mode: int | None = None,
) -> bytes:
    payload, _identity = _read_exact_file_snapshot(
        root_descriptor,
        relative_path,
        maximum=maximum,
        required_mode=required_mode,
    )
    return payload


def _closed_json(raw: bytes, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                _fail(f"{label} contains a duplicate key")
            value[key] = item
        return value

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"{label} is not valid UTF-8 JSON: {exc}")


def _load_lock(
    root_descriptor: int,
) -> tuple[dict[str, Any], bytes, tuple[int, ...]]:
    raw, identity = _read_exact_file_snapshot(
        root_descriptor,
        "copilot.lock.json",
        maximum=_MAX_LOCK_BYTES,
        required_mode=_LOCK_MODE,
    )
    value = _closed_json(raw, "copilot.lock.json")
    if (
        not isinstance(value, dict)
        or set(value) != _ROOT_KEYS
        or value.get("schema_version") != "1.0"
        or value.get("mutations") != []
    ):
        _fail("copilot.lock.json has an invalid closed schema")
    canonical = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if raw != canonical:
        _fail("copilot.lock.json is not canonical JSON")
    return value, raw, identity


def _source_versions(
    root_descriptor: int,
) -> tuple[
    str,
    str,
    dict[str, Any],
    dict[str, tuple[tuple[int, ...], str]],
]:
    version_raw, version_identity = _read_exact_file_snapshot(
        root_descriptor,
        "VERSION.json",
    )
    plugin_path = "plugins/codex-copilot/.codex-plugin/plugin.json"
    plugin_raw, plugin_identity = _read_exact_file_snapshot(
        root_descriptor,
        plugin_path,
    )
    version = _closed_json(version_raw, "VERSION.json")
    plugin = _closed_json(plugin_raw, "Codex plugin manifest")
    try:
        claude_version = version["framework"]
        codex_version = plugin["version"]
    except (KeyError, TypeError) as exc:
        _fail(f"release version source is incomplete: {exc}")
    if (
        not isinstance(claude_version, str)
        or not _VERSION.fullmatch(claude_version)
        or not isinstance(codex_version, str)
        or not _VERSION.fullmatch(codex_version)
        or not isinstance(version, dict)
    ):
        _fail("release version source is invalid")
    return (
        claude_version,
        codex_version,
        version,
        {
            "VERSION.json": (
                version_identity,
                hashlib.sha256(version_raw).hexdigest(),
            ),
            plugin_path: (
                plugin_identity,
                hashlib.sha256(plugin_raw).hexdigest(),
            ),
        },
    )


def _claude_roster(version: dict[str, Any]) -> set[str]:
    try:
        components = version["components"]
        commands = components["commands"]["projectCommands"]
        agents = components["agents"]["frameworkAgents"]
    except (KeyError, TypeError) as exc:
        _fail(f"Claude roster source is incomplete: {exc}")
    if (
        not isinstance(commands, list)
        or not commands
        or len(commands) != len(set(commands))
        or any(
            not isinstance(item, str)
            or PurePosixPath(item).name != item
            or not item.endswith(".md")
            for item in commands
        )
        or not isinstance(agents, list)
        or not agents
        or len(agents) != len(set(agents))
        or any(
            not isinstance(item, str) or PurePosixPath(item).name != item or "/" in item
            for item in agents
        )
    ):
        _fail("Claude roster source is invalid")
    return {
        *(f".claude/commands/{item}" for item in commands),
        ".claude/fitness-check.sh",
        ".claude/hooks/copilot-hook.sh",
        *(f".claude/agents/{item}.md" for item in (*agents, "kc")),
    }


def _scan_regular_tree(root_descriptor: int, relative_path: str) -> set[str]:
    descriptor = _open_directory(root_descriptor, relative_path)
    before = os.fstat(descriptor)
    result: set[str] = set()
    try:
        names = sorted(os.listdir(descriptor))
        for name in names:
            if not name or name in {".", ".."} or "/" in name or "\\" in name:
                _fail(f"source tree name is not canonical: {relative_path}/{name}")
            child = f"{relative_path}/{name}"
            metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                result.update(_scan_regular_tree(root_descriptor, child))
            elif stat.S_ISREG(metadata.st_mode):
                result.add(child)
            else:
                _fail(f"source tree contains a non-file entry: {child}")
        if _stable_identity(before) != _stable_identity(
            os.fstat(descriptor)
        ) or _named_identity(root_descriptor, relative_path) != _stable_identity(
            before
        ):
            _fail(f"source tree changed while it was enumerated: {relative_path}")
    except OSError as exc:
        _fail(f"source tree cannot be enumerated safely: {relative_path}: {exc}")
    finally:
        os.close(descriptor)
    return result


def _scan_top_level_agent_files(root_descriptor: int) -> set[str]:
    relative_path = ".claude/agents"
    descriptor = _open_directory(root_descriptor, relative_path)
    before = os.fstat(descriptor)
    result: set[str] = set()
    try:
        for name in sorted(os.listdir(descriptor)):
            if not name.endswith(".md"):
                continue
            metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode):
                _fail(f"Claude agent source is not a regular file: {name}")
            result.add(f"{relative_path}/{name}")
        if _stable_identity(before) != _stable_identity(
            os.fstat(descriptor)
        ) or _named_identity(root_descriptor, relative_path) != _stable_identity(
            before
        ):
            _fail("Claude agent source directory changed during enumeration")
    except OSError as exc:
        _fail(f"Claude agent source directory cannot be read safely: {exc}")
    finally:
        os.close(descriptor)
    return result


def _tree_directory_generations(
    root_descriptor: int,
    relative_path: str,
) -> dict[str, tuple[int, ...]]:
    descriptor = _open_directory(root_descriptor, relative_path)
    before = os.fstat(descriptor)
    result = {relative_path: _stable_identity(before)}
    try:
        for name in sorted(os.listdir(descriptor)):
            metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                result.update(
                    _tree_directory_generations(
                        root_descriptor,
                        f"{relative_path}/{name}",
                    )
                )
        if _stable_identity(before) != _stable_identity(
            os.fstat(descriptor)
        ) or _named_identity(root_descriptor, relative_path) != _stable_identity(
            before
        ):
            _fail(
                f"source directory changed during generation capture: {relative_path}"
            )
    except OSError as exc:
        _fail(f"source directory generation is unavailable: {relative_path}: {exc}")
    finally:
        os.close(descriptor)
    return result


def _release_directory_generations(
    root: Path,
    root_descriptor: int,
) -> dict[str, tuple[int, ...]]:
    result: dict[str, tuple[int, ...]] = {}
    for relative_path in (
        ".claude",
        ".claude/commands",
        ".claude/hooks",
        ".claude/agents",
        "plugins",
        "scripts",
    ):
        descriptor = _open_directory(root_descriptor, relative_path)
        try:
            result[relative_path] = _stable_identity(os.fstat(descriptor))
        finally:
            os.close(descriptor)
    result.update(_tree_directory_generations(root_descriptor, "plugins/codex-copilot"))
    retained_root = _stable_identity(os.fstat(root_descriptor))
    named_root = _stable_identity(root.lstat())
    if retained_root != named_root:
        _fail("repository root name changed during generation capture")
    result["."] = retained_root
    return result


def _expected_rosters(
    root_descriptor: int,
    version: dict[str, Any],
) -> dict[str, set[str]]:
    claude = _claude_roster(version)
    expected_agents = {item for item in claude if item.startswith(".claude/agents/")}
    actual_agents = _scan_top_level_agent_files(root_descriptor)
    if actual_agents != expected_agents:
        _fail(
            "Claude agent source roster differs: "
            f"missing={sorted(expected_agents - actual_agents)}, "
            f"extra={sorted(actual_agents - expected_agents)}"
        )
    codex = _scan_regular_tree(root_descriptor, "plugins/codex-copilot")
    codex.add("scripts/copilot-gate.sh")
    return {"claude": claude, "codex": codex}


def verify(root: Path) -> tuple[int, int]:
    root_expected = root.lstat()
    root_descriptor = os.open(
        root,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    root_actual = os.fstat(root_descriptor)
    if not stat.S_ISDIR(root_expected.st_mode) or _stable_identity(
        root_expected
    ) != _stable_identity(root_actual):
        os.close(root_descriptor)
        _fail("repository root identity is invalid")
    try:
        initial_generations = _release_directory_generations(root, root_descriptor)
        value, raw_lock, lock_identity = _load_lock(root_descriptor)
        (
            claude_version,
            codex_version,
            version,
            authority_leaves,
        ) = _source_versions(root_descriptor)
        expected_versions = {"claude": claude_version, "codex": codex_version}
        expected_rosters = _expected_rosters(root_descriptor, version)
        components = value.get("components")
        if (
            not isinstance(components, list)
            or len(components) != 2
            or [item.get("component") for item in components if isinstance(item, dict)]
            != ["claude", "codex"]
        ):
            _fail("components must be exactly claude then codex")
        checked = 0
        seen_paths: set[str] = set()
        initial_leaves: dict[str, tuple[tuple[int, ...], str]] = {}
        for component in components:
            if not isinstance(component, dict) or set(component) != _COMPONENT_KEYS:
                _fail("component entry fields are not closed")
            name = component["component"]
            version_value = component["version"]
            if (
                version_value != expected_versions[name]
                or component["release_tag"] != f"v{version_value}"
                or component["ownership_mode"] != "full"
            ):
                _fail(f"component {name} release identity is invalid")
            files = component["files"]
            if not isinstance(files, list):
                _fail(f"component {name} files must be a list")
            actual_roster: set[str] = set()
            for item in files:
                if not isinstance(item, dict) or set(item) != _FILE_KEYS:
                    _fail(f"component {name} file fields are not closed")
                relative_path = _canonical_relative_path(item["path"])
                if (
                    relative_path in seen_paths
                    or relative_path in actual_roster
                    or item["ownership"] != "framework"
                ):
                    _fail(
                        f"locked path is duplicate or not framework-owned: {relative_path}"
                    )
                seen_paths.add(relative_path)
                actual_roster.add(relative_path)
                checksum = item["checksum"]
                match = (
                    _DIGEST.fullmatch(checksum) if isinstance(checksum, str) else None
                )
                if match is None:
                    _fail(f"locked path has an invalid checksum: {relative_path}")
                payload, identity = _read_exact_file_snapshot(
                    root_descriptor,
                    relative_path,
                )
                digest = hashlib.sha256(payload).hexdigest()
                if digest != match.group(1):
                    _fail(
                        f"locked path checksum differs from release tree: {relative_path}"
                    )
                initial_leaves[relative_path] = (identity, digest)
                checked += 1
            missing = sorted(expected_rosters[name] - actual_roster)
            extra = sorted(actual_roster - expected_rosters[name])
            if missing or extra:
                _fail(
                    f"component {name} roster differs: missing={missing}, extra={extra}"
                )
        final_lock, final_lock_identity = _read_exact_file_snapshot(
            root_descriptor,
            "copilot.lock.json",
            maximum=_MAX_LOCK_BYTES,
            required_mode=_LOCK_MODE,
        )
        if final_lock != raw_lock or final_lock_identity != lock_identity:
            _fail("copilot.lock.json changed during verification")
        final_rosters = _expected_rosters(root_descriptor, version)
        if final_rosters != expected_rosters:
            _fail("release source roster changed during verification")
        for relative_path in sorted(initial_leaves):
            payload, identity = _read_exact_file_snapshot(
                root_descriptor,
                relative_path,
            )
            if (identity, hashlib.sha256(payload).hexdigest()) != initial_leaves[
                relative_path
            ]:
                _fail(
                    "locked source leaf changed during verification: "
                    f"{relative_path}"
                )
        for relative_path, expected in sorted(authority_leaves.items()):
            payload, identity = _read_exact_file_snapshot(
                root_descriptor,
                relative_path,
            )
            if (identity, hashlib.sha256(payload).hexdigest()) != expected:
                _fail(
                    "release authority changed during verification: " f"{relative_path}"
                )
        final_generations = _release_directory_generations(root, root_descriptor)
        if final_generations != initial_generations:
            _fail("release source directory generation changed during verification")
        return len(components), checked
    finally:
        os.close(root_descriptor)


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve(strict=True)
    if len(sys.argv) > 2:
        _fail("usage: verify-project-lock-coherence.py [REPOSITORY]")
    components, files = verify(root)
    print(f"project lock coherence: verified {components} components / {files} files")


if __name__ == "__main__":
    main()
