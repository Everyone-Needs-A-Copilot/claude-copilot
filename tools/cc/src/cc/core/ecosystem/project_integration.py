"""Authoritative, fail-closed project integration inspection.

The workspace surface used to infer readiness from a few marker files.  This
module replaces that blended inference with two independent component
assessments.  A component is ready only when its generated lock entry, every
recorded framework-owned checksum, and its component-specific entry evidence
all verify.

Inspection is read-only.  It never follows a project symlink outside the
repository, never returns file contents, and never treats capability counts as
proof.  Counts exist only so a person or coding agent understands what must be
preserved during a guided integration.
"""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Optional

from cc.core.config import resolve_key
from cc.core.ecosystem.project_locking import (
    fingerprint_file_payload,
    fingerprint_symlink,
)
from cc.core.ecosystem.projects import PROJECT_LOCK_FILENAME

INTEGRATION_CONTRACT_ID = "project-integration"
INTEGRATION_CONTRACT_VERSION = "1"
SUPPORTED_COMPONENTS = ("claude", "codex")

_CLASSIFICATION_PRECEDENCE = {
    "ready": 0,
    "safe-finish": 1,
    "guided-integration": 2,
    "owner-decision": 3,
    "could-not-verify": 4,
}

_PROHIBITED_BASE = (
    "overwrite-project-instructions",
    "delete-project-capabilities",
    "rename-project-capabilities",
    "flatten-project-model",
    "modify-verified-component",
    "follow-external-symlink",
    "trust-assistant-self-report",
    "skip-verification",
)

_CLAUDE_REQUIRED_LOCK_PATHS = (
    ".claude/commands/protocol.md",
    ".claude/commands/continue.md",
    ".claude/fitness-check.sh",
)

_CODEX_REQUIRED_LOCK_PATHS = (
    "plugins/codex-copilot/.codex-plugin/plugin.json",
    "scripts/copilot-gate.sh",
)

_MANAGED_OUTPUT_TARGET_KINDS = {
    "claude": {
        "CLAUDE.md": "managed-text",
        ".mcp.json": "merged-json",
        "copilot.project.json": "merged-json",
    },
    "codex": {
        "AGENTS.md": "managed-text",
        ".codex-copilot.json": "merged-json",
        ".claude/skills/codex-copilot": "internal-symlink",
        "copilot.project.json": "merged-json",
    },
}

_CLAUDE_RELEVANT_PATHS = (
    "CLAUDE.md",
    ".mcp.json",
    ".claude/commands/protocol.md",
    ".claude/commands/continue.md",
    ".claude/fitness-check.sh",
    ".claude/agents",
)

_CODEX_RELEVANT_PATHS = (
    "AGENTS.md",
    ".codex-copilot.json",
    "plugins/codex-copilot",
    ".claude/skills/codex-copilot",
    "scripts/copilot-gate.sh",
    ".agents/plugins/marketplace.json",
)

_CLAUDE_ACTION_TARGETS = (
    "CLAUDE.md",
    ".mcp.json",
    ".claude/commands/protocol.md",
    ".claude/commands/continue.md",
    ".claude/fitness-check.sh",
    ".claude/agents",
    ".claude/cc/config.json",
    ".claude/memory/entries/.gitkeep",
    ".claude/memory/.gitignore",
)

_CODEX_ACTION_TARGETS = (
    "AGENTS.md",
    "plugins/codex-copilot",
    ".claude/skills/codex-copilot",
    "scripts/copilot-gate.sh",
    ".agents/plugins/marketplace.json",
    ".codex-copilot.json",
    ".claude/cc/config.json",
    ".claude/memory/entries/.gitkeep",
    ".claude/memory/.gitignore",
    "SOUL.md",
    "docs/01-architecture/12-architecture-guiding-principles.md",
    "docs/40-initiatives",
)


def _opaque_id(payload: Any) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _checksum(path: Path) -> str:
    if path.is_symlink():
        payload = ("symlink:" + str(path.readlink())).encode("utf-8")
    else:
        payload = path.read_bytes()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _managed_output_fingerprint(root: Path, relative: str) -> Optional[str]:
    target, _ = _safe_relative_target(root, relative)
    if target is None:
        return None
    try:
        metadata = target.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if stat.S_ISREG(metadata.st_mode):
            return fingerprint_file_payload(target.read_bytes(), mode=mode)
        if stat.S_ISLNK(metadata.st_mode):
            return fingerprint_symlink(str(target.readlink()))
    except OSError:
        return None
    return None


def _evidence(kind: str, path: str, state: str, detail: str) -> dict[str, str]:
    return {"kind": kind, "path": path, "state": state, "detail": detail}


def _artifact(kind: str, path: str, detail: str) -> dict[str, str]:
    return {"kind": kind, "path": path, "detail": detail}


def _verification(project: Path, component: Optional[str] = None) -> dict[str, Any]:
    subject = f"{component.title()} and the project" if component else "The project"
    return {
        "command": [
            "cc",
            "workspace",
            "verify",
            "--project",
            str(project),
            "--json",
        ],
        "expected": f"{subject} classify ready from machine-verifiable evidence.",
        "stop_conditions": [
            "Stop if required evidence is missing, mismatched, or unreadable.",
            "Stop if any preserved project-owned path would be changed.",
        ],
    }


def _safe_relative_target(root: Path, raw_path: Any) -> tuple[Optional[Path], str]:
    if not isinstance(raw_path, str) or not raw_path:
        return None, "The recorded path is empty or not a string."
    pure = PurePosixPath(raw_path)
    if (
        pure.is_absolute()
        or ".." in pure.parts
        or "\\" in raw_path
        or pure.as_posix() != raw_path
        or any(ord(character) < 32 or ord(character) == 127 for character in raw_path)
    ):
        return None, "The recorded path escapes the project."
    target = root
    for index, part in enumerate(pure.parts):
        target = target / part
        try:
            metadata = target.lstat()
        except FileNotFoundError:
            # A missing leaf or ancestor is safe to classify as missing.  No
            # subsequent path is read after this point.
            return root.joinpath(*pure.parts), ""
        except OSError:
            return None, "The recorded path could not be inspected safely."
        if index < len(pure.parts) - 1:
            if stat.S_ISLNK(metadata.st_mode):
                return None, "The recorded path has a symlink ancestor."
            if not stat.S_ISDIR(metadata.st_mode):
                return None, "The recorded path has a non-directory ancestor."
    return target, ""


def _read_json_object(path: Path) -> tuple[str, Optional[dict[str, Any]]]:
    try:
        if not path.exists():
            return "missing", None
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "unreadable", None
    if not isinstance(raw, dict):
        return "unreadable", None
    return "verified", raw


def _read_text(path: Path) -> tuple[str, Optional[str]]:
    try:
        if not path.exists():
            return "missing", None
        return "verified", path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return "unreadable", None


def _path_exists(path: Path) -> tuple[bool, bool]:
    """Return (exists-or-link, readable-metadata)."""
    try:
        path.lstat()
        return True, True
    except FileNotFoundError:
        return False, True
    except OSError:
        return False, False


def _framework_root(component: str, supplied: Optional[Path | str]) -> Optional[Path]:
    raw = supplied
    if raw is None:
        raw = resolve_key(f"paths.{component}_copilot_root")
    if not raw:
        return None
    path = Path(str(raw)).expanduser()
    try:
        return path.resolve() if path.is_dir() else None
    except OSError:
        return None


def _claude_source_files(source: Path) -> Optional[dict[str, Path]]:
    try:
        version = json.loads((source / "VERSION.json").read_text(encoding="utf-8"))
        roster = list(version["components"]["agents"]["frameworkAgents"])
        if any(not isinstance(agent, str) or not agent for agent in roster):
            return None
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, OSError):
        return None
    roster.append("kc")
    files = {
        ".claude/commands/protocol.md": source / ".claude/commands/protocol.md",
        ".claude/commands/continue.md": source / ".claude/commands/continue.md",
        ".claude/fitness-check.sh": source / ".claude/fitness-check.sh",
    }
    files.update(
        {
            f".claude/agents/{agent}.md": source / f".claude/agents/{agent}.md"
            for agent in roster
        }
    )
    if any(not path.is_file() for path in files.values()):
        return None
    return files


def _codex_source_files(source: Path) -> Optional[dict[str, Path]]:
    plugin = source / "plugins/codex-copilot"
    gate = source / "scripts/copilot-gate.sh"
    try:
        if not plugin.is_dir() or not gate.is_file():
            return None
        files = {
            path.relative_to(source).as_posix(): path
            for path in sorted(plugin.rglob("*"))
            if path.is_file()
        }
    except OSError:
        return None
    files["scripts/copilot-gate.sh"] = gate
    return files


def _source_files(component: str, source: Optional[Path]) -> Optional[dict[str, Path]]:
    if source is None:
        return None
    return (
        _claude_source_files(source)
        if component == "claude"
        else _codex_source_files(source)
    )


def _lock_state(root: Path) -> tuple[str, dict[str, dict[str, Any]], list[Any]]:
    path = root / PROJECT_LOCK_FILENAME
    try:
        if path.is_symlink():
            return "unreadable", {}, ["lock", "unsafe-symlink"]
        if not path.exists():
            return "missing", {}, ["lock", "missing"]
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "unreadable", {}, ["lock", "unreadable"]
    if (
        not isinstance(raw, dict)
        or raw.get("schema_version") != "1.0"
        or not isinstance(raw.get("components"), list)
    ):
        return "unreadable", {}, ["lock", "unsupported"]
    entries: dict[str, dict[str, Any]] = {}
    for entry in raw["components"]:
        if not isinstance(entry, dict):
            return "unreadable", {}, ["lock", "invalid-entry"]
        component = entry.get("component")
        if component not in SUPPORTED_COMPONENTS or component in entries:
            return "unreadable", {}, ["lock", "duplicate-or-unknown-component"]
        entries[component] = entry
    return "verified", entries, ["lock", sorted(entries)]


def _verify_lock_entry(
    root: Path, component: str, entry: dict[str, Any]
) -> tuple[bool, list[dict[str, str]], list[dict[str, str]], list[Any]]:
    evidence = [
        _evidence(
            "lock-record",
            PROJECT_LOCK_FILENAME,
            "verified",
            f"The lock contains one {component} component record.",
        )
    ]
    missing: list[dict[str, str]] = []
    fingerprint: list[Any] = [component, entry.get("version"), entry.get("release_tag")]
    files = entry.get("files")
    if (
        not isinstance(entry.get("version"), str)
        or not isinstance(files, list)
        or not files
    ):
        missing.append(
            {
                "id": "valid-lock-entry",
                "detail": f"The {component} lock record is incomplete.",
            }
        )
        return False, evidence, missing, fingerprint

    recorded: set[str] = set()
    for file_info in files:
        if (
            not isinstance(file_info, dict)
            or file_info.get("ownership") != "framework"
            or not isinstance(file_info.get("checksum"), str)
        ):
            missing.append(
                {
                    "id": "valid-framework-record",
                    "detail": f"The {component} lock contains an invalid file record.",
                }
            )
            return False, evidence, missing, fingerprint
        rel_path = file_info.get("path")
        target, path_error = _safe_relative_target(root, rel_path)
        if target is None or rel_path in recorded:
            missing.append(
                {
                    "id": "safe-recorded-path",
                    "detail": (f"{rel_path}: {path_error}" if path_error else "")
                    or f"The {component} lock repeats {rel_path}.",
                }
            )
            return False, evidence, missing, fingerprint
        recorded.add(rel_path)
        try:
            actual = _checksum(target)
        except (FileNotFoundError, OSError):
            actual = None
        expected = file_info["checksum"]
        fingerprint.append([rel_path, expected, actual])
        if actual != expected:
            state = "missing" if actual is None else "mismatch"
            evidence.append(
                _evidence(
                    "framework-file",
                    rel_path,
                    state,
                    f"The recorded {component} framework file did not verify.",
                )
            )
            missing.append(
                {
                    "id": "verified-framework-file",
                    "detail": f"{rel_path} is {state}.",
                }
            )

    managed_outputs = entry.get("managed_outputs", [])
    if not isinstance(managed_outputs, list):
        missing.append(
            {
                "id": "valid-managed-output",
                "detail": f"The {component} lock managed-output evidence is invalid.",
            }
        )
        return False, evidence, missing, fingerprint
    managed_paths: set[str] = set()
    allowed_managed = _MANAGED_OUTPUT_TARGET_KINDS[component]
    for output in managed_outputs:
        if (
            not isinstance(output, dict)
            or set(output) != {"path", "kind", "fingerprint"}
            or not isinstance(output.get("path"), str)
            or output.get("path") not in allowed_managed
            or output.get("kind") != allowed_managed.get(output.get("path"))
            or not isinstance(output.get("fingerprint"), str)
            or not output["fingerprint"].startswith("sha256:")
            or len(output["fingerprint"]) != 71
            or any(
                character not in "0123456789abcdef"
                for character in output["fingerprint"][7:]
            )
            or output["path"] in managed_paths
            or output["path"] in recorded
        ):
            missing.append(
                {
                    "id": "valid-managed-output",
                    "detail": f"The {component} lock contains an invalid managed-output record.",
                }
            )
            return False, evidence, missing, fingerprint
        rel_path = str(output["path"])
        managed_paths.add(rel_path)
        actual = _managed_output_fingerprint(root, rel_path)
        expected = str(output["fingerprint"])
        fingerprint.append(
            ["managed-output", rel_path, output["kind"], expected, actual]
        )
        if actual != expected:
            evidence.append(
                _evidence(
                    "managed-output",
                    rel_path,
                    "missing" if actual is None else "mismatch",
                    f"The recorded {component} managed output did not verify.",
                )
            )
            missing.append(
                {
                    "id": "verified-managed-output",
                    "detail": f"{rel_path} is missing or mismatched.",
                }
            )

    required = (
        _CLAUDE_REQUIRED_LOCK_PATHS
        if component == "claude"
        else _CODEX_REQUIRED_LOCK_PATHS
    )
    absent_required = [path for path in required if path not in recorded]
    if component == "claude" and not any(
        path.startswith(".claude/agents/") for path in recorded
    ):
        absent_required.append(".claude/agents/<framework-agent>.md")
    for path in absent_required:
        missing.append(
            {
                "id": "required-lock-path",
                "detail": f"The {component} lock does not record {path}.",
            }
        )
    return not missing, evidence, missing, fingerprint


def _verify_claude_entry(
    root: Path,
) -> tuple[bool, list[dict[str, str]], list[dict[str, str]], list[Any]]:
    evidence: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []
    fingerprint: list[Any] = []

    text_state, text = _read_text(root / "CLAUDE.md")
    compatible = bool(text and "## Claude Copilot" in text)
    evidence.append(
        _evidence(
            "project-file",
            "CLAUDE.md",
            text_state
            if text_state != "verified"
            else ("verified" if compatible else "mismatch"),
            "The Claude project entry is compatible."
            if compatible
            else "The Claude project entry is missing, unreadable, or not a recognized variant.",
        )
    )
    fingerprint.append(["CLAUDE.md", text_state, _opaque_id(text) if text else None])
    if not compatible:
        missing.append(
            {
                "id": "compatible-claude-entry",
                "detail": "CLAUDE.md must expose the recognized Claude Copilot entry.",
            }
        )

    mcp_state, mcp = _read_json_object(root / ".mcp.json")
    mcp_valid = bool(mcp is not None and isinstance(mcp.get("mcpServers"), dict))
    evidence.append(
        _evidence(
            "marker",
            ".mcp.json",
            mcp_state
            if mcp_state != "verified"
            else ("verified" if mcp_valid else "mismatch"),
            "The Claude MCP marker is valid."
            if mcp_valid
            else "The Claude MCP marker is missing or invalid.",
        )
    )
    fingerprint.append([".mcp.json", mcp_state, mcp])
    if not mcp_valid:
        missing.append(
            {
                "id": "valid-mcp-marker",
                "detail": ".mcp.json must contain an mcpServers object.",
            }
        )
    return not missing, evidence, missing, fingerprint


def _verify_internal_skill_link(root: Path) -> tuple[bool, str, list[Any]]:
    link = root / ".claude/skills/codex-copilot"
    expected = (root / "plugins/codex-copilot/skills").resolve()
    try:
        if not link.is_symlink():
            return (
                False,
                "The Codex skill bridge is missing or is not a symlink.",
                [
                    "skill-link",
                    "missing",
                ],
            )
        resolved = link.resolve(strict=True)
        if resolved != expected or (resolved != root and root not in resolved.parents):
            return (
                False,
                "The Codex skill bridge points outside its project plugin.",
                [
                    "skill-link",
                    str(link.readlink()),
                    str(resolved),
                ],
            )
        return (
            True,
            "The project-local Codex skill bridge was verified.",
            [
                "skill-link",
                str(link.readlink()),
            ],
        )
    except OSError:
        return (
            False,
            "The Codex skill bridge could not be resolved safely.",
            [
                "skill-link",
                "unreadable",
            ],
        )


def _verify_legacy_linked_codex_setup(
    root: Path,
) -> tuple[bool, list[dict[str, str]], list[Any]]:
    """Recognize the bounded pre-portable Codex installation topology.

    Earlier setup tooling wrote ``installType: symlink`` and linked both the
    project plugin and its Claude skill bridge to one shared checkout.  That
    topology can keep working while its moving target invalidates the project
    lock.  It is migration evidence, never readiness evidence.
    """
    config_state, config = _read_json_object(root / ".codex-copilot.json")
    plugin = root / "plugins/codex-copilot"
    bridge = root / ".claude/skills/codex-copilot"
    gate = root / "scripts/copilot-gate.sh"
    fingerprint: list[Any] = ["legacy-linked-codex", config_state, config]
    if not (
        config_state == "verified"
        and config is not None
        and config.get("installType") == "symlink"
        and config.get("pluginPath") == "./plugins/codex-copilot"
    ):
        return False, [], fingerprint

    try:
        if not plugin.is_symlink() or not bridge.is_symlink():
            return False, [], [*fingerprint, "missing-links"]
        plugin_target = plugin.resolve(strict=True)
        bridge_target = bridge.resolve(strict=True)
        expected_bridge = (plugin_target / "skills").resolve(strict=True)
        plugin_is_external = plugin_target != root and root not in plugin_target.parents
        if not plugin_is_external or bridge_target != expected_bridge:
            return (
                False,
                [],
                [
                    *fingerprint,
                    str(plugin.readlink()),
                    str(bridge.readlink()),
                    "unrecognized-targets",
                ],
            )
        manifest_state, manifest = _read_json_object(
            plugin_target / ".codex-plugin/plugin.json"
        )
        if not (
            manifest_state == "verified"
            and manifest is not None
            and manifest.get("name") == "codex-copilot"
        ):
            return False, [], [*fingerprint, "invalid-plugin-manifest"]
        if gate.is_symlink():
            expected_gate = (
                plugin_target.parents[1] / "scripts/copilot-gate.sh"
            ).resolve(strict=True)
            if gate.resolve(strict=True) != expected_gate:
                return False, [], [*fingerprint, "unrecognized-gate-link"]
    except OSError:
        return False, [], [*fingerprint, "unreadable-links"]

    evidence = [
        _evidence(
            "marker",
            ".codex-copilot.json",
            "verified",
            "This project uses the recognized earlier linked Codex setup.",
        ),
        _evidence(
            "link",
            "plugins/codex-copilot",
            "verified",
            "The legacy project plugin link and skill bridge resolve to the same Codex plugin.",
        ),
    ]
    return (
        True,
        evidence,
        [
            *fingerprint,
            str(plugin.readlink()),
            str(bridge.readlink()),
            str(gate.readlink()) if gate.is_symlink() else None,
            "recognized",
        ],
    )


def _verify_codex_entry(
    root: Path,
) -> tuple[bool, list[dict[str, str]], list[dict[str, str]], list[Any]]:
    evidence: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []
    fingerprint: list[Any] = []

    text_state, text = _read_text(root / "AGENTS.md")
    compatible = bool(
        text and "## Codex Copilot" in text and "./plugins/codex-copilot" in text
    )
    evidence.append(
        _evidence(
            "project-file",
            "AGENTS.md",
            text_state
            if text_state != "verified"
            else ("verified" if compatible else "mismatch"),
            "The Codex project entry is compatible."
            if compatible
            else "The Codex project entry is missing, unreadable, or not a recognized variant.",
        )
    )
    fingerprint.append(["AGENTS.md", text_state, _opaque_id(text) if text else None])
    if not compatible:
        missing.append(
            {
                "id": "compatible-codex-entry",
                "detail": "AGENTS.md must expose the recognized project-local Codex plugin.",
            }
        )

    config_state, config = _read_json_object(root / ".codex-copilot.json")
    config_valid = bool(
        config
        and config.get("installType") in ("copy", "link")
        and config.get("pluginPath") == "./plugins/codex-copilot"
    )
    evidence.append(
        _evidence(
            "marker",
            ".codex-copilot.json",
            config_state
            if config_state != "verified"
            else ("verified" if config_valid else "mismatch"),
            "The Codex project configuration is valid."
            if config_valid
            else "The Codex project configuration is missing or invalid.",
        )
    )
    fingerprint.append([".codex-copilot.json", config_state, config])
    if not config_valid:
        legacy_linked_config = bool(
            config_state == "verified"
            and config is not None
            and config.get("installType") == "symlink"
            and config.get("pluginPath") == "./plugins/codex-copilot"
        )
        missing.append(
            {
                "id": "valid-codex-config",
                "detail": (
                    ".codex-copilot.json records an earlier linked installation; "
                    "it needs a reviewed migration to a portable project-local plugin."
                    if legacy_linked_config
                    else ".codex-copilot.json must name the project-local plugin."
                ),
            }
        )

    manifest_state, manifest = _read_json_object(
        root / "plugins/codex-copilot/.codex-plugin/plugin.json"
    )
    manifest_valid = bool(manifest and manifest.get("name") == "codex-copilot")
    evidence.append(
        _evidence(
            "manifest",
            "plugins/codex-copilot/.codex-plugin/plugin.json",
            manifest_state
            if manifest_state != "verified"
            else ("verified" if manifest_valid else "mismatch"),
            "The Codex plugin manifest is valid."
            if manifest_valid
            else "The Codex plugin manifest is missing or invalid.",
        )
    )
    fingerprint.append(["plugin-manifest", manifest_state, manifest])
    if not manifest_valid:
        missing.append(
            {
                "id": "valid-plugin-manifest",
                "detail": "The project-local Codex plugin manifest must identify codex-copilot.",
            }
        )

    link_valid, link_detail, link_fingerprint = _verify_internal_skill_link(root)
    evidence.append(
        _evidence(
            "link",
            ".claude/skills/codex-copilot",
            "verified" if link_valid else "mismatch",
            link_detail,
        )
    )
    fingerprint.append(link_fingerprint)
    if not link_valid:
        missing.append({"id": "internal-skill-link", "detail": link_detail})
    return not missing, evidence, missing, fingerprint


def _project_capabilities(root: Path) -> tuple[dict[str, Any], list[Any]]:
    integration_paths: list[str] = []
    fingerprint: list[Any] = []

    def existing(path: str) -> bool:
        present, readable = _path_exists(root / path)
        if present:
            integration_paths.append(path)
        fingerprint.append([path, present, readable])
        return present and readable

    instructions = sum(existing(path) for path in ("CLAUDE.md", "AGENTS.md"))

    def count_files(path: str, pattern: str) -> int:
        target = root / path
        present, readable = _path_exists(target)
        if not present:
            return 0
        if path not in integration_paths:
            integration_paths.append(path)
        if not readable:
            fingerprint.append([path, "unreadable"])
            return 0
        try:
            files = [
                item
                for item in target.rglob(pattern)
                if item.is_file() and "codex-copilot" not in item.parts
            ]
            fingerprint.append(
                [
                    path,
                    [
                        [
                            item.relative_to(root).as_posix(),
                            _checksum(item),
                        ]
                        for item in sorted(files)
                    ],
                ]
            )
            return len(files)
        except OSError:
            fingerprint.append([path, "unreadable"])
            return 0

    agents = count_files(".claude/agents", "*.md") + count_files(
        ".agents/agents", "*.md"
    )
    skills = count_files(".claude/skills", "SKILL.md") + count_files(
        ".agents/skills", "SKILL.md"
    )
    commands = count_files(".claude/commands", "*.md") + count_files(
        ".agents/commands", "*.md"
    )
    plugins = 0
    plugins_root = root / "plugins"
    try:
        if plugins_root.is_dir():
            plugins = sum(
                1
                for child in plugins_root.iterdir()
                if child.name != "codex-copilot"
                and not child.is_symlink()
                and child.is_dir()
            )
            if plugins:
                integration_paths.append("plugins")
    except OSError:
        fingerprint.append(["plugins", "unreadable"])
    capabilities = {
        "instructions": instructions,
        "agents": agents,
        "skills": skills,
        "commands": commands,
        "plugins": plugins,
        "integration_paths": sorted(set(integration_paths)),
    }
    return capabilities, fingerprint


def _preservation(root: Path, capabilities: dict[str, Any]) -> dict[str, Any]:
    must_preserve: list[dict[str, str]] = []
    for path, kind, detail in (
        ("CLAUDE.md", "instruction", "Preserve the project Claude instructions."),
        ("AGENTS.md", "instruction", "Preserve the project Codex instructions."),
        (".claude/agents", "agent", "Preserve project-owned Claude agents."),
        (".agents/agents", "agent", "Preserve project-owned shared agents."),
        (".claude/skills", "skill", "Preserve project-owned Claude skills."),
        (".agents/skills", "skill", "Preserve project-owned shared skills."),
        (".claude/commands", "command", "Preserve project-owned Claude commands."),
        (".agents/commands", "command", "Preserve project-owned shared commands."),
        ("plugins", "plugin", "Preserve project-owned plugins."),
        (
            ".copilot/project-owner.json",
            "config",
            "Preserve the project ownership declaration.",
        ),
    ):
        present, readable = _path_exists(root / path)
        if present and readable:
            must_preserve.append(_artifact(kind, path, detail))
    return {
        "must_preserve": must_preserve,
        "prohibited_actions": list(_PROHIBITED_BASE),
    }


def _owner_state(root: Path) -> tuple[str, list[Any]]:
    path = root / ".copilot/project-owner.json"
    state, payload = _read_json_object(path)
    if state == "missing":
        return "absent", ["owner", "absent"]
    if state != "verified" or payload is None:
        return "unreadable", ["owner", "unreadable"]
    if (
        payload.get("decision_required") is True
        or payload.get("integration") == "owner-decision"
    ):
        return "decision-required", ["owner", payload]
    return "unsupported", ["owner", payload]


def _existing_component_paths(root: Path, component: str) -> tuple[list[str], bool]:
    existing_paths: list[str] = []
    readable = True
    paths = _CLAUDE_RELEVANT_PATHS if component == "claude" else _CODEX_RELEVANT_PATHS
    for path in paths:
        present, path_readable = _path_exists(root / path)
        if present:
            existing_paths.append(path)
        readable = readable and path_readable
    return existing_paths, readable


def _missing_action_targets(
    root: Path,
    component: str,
    source_files: dict[str, Path],
) -> list[str]:
    targets = _CLAUDE_ACTION_TARGETS if component == "claude" else _CODEX_ACTION_TARGETS
    missing = [path for path in targets if not (root / path).exists()]
    if component == "claude":
        if (
            any(
                rel_path.startswith(".claude/agents/")
                and not (root / rel_path).exists()
                for rel_path in source_files
            )
            and ".claude/agents" not in missing
        ):
            missing.append(".claude/agents")
    elif (
        any(
            rel_path.startswith("plugins/codex-copilot/")
            and not (root / rel_path).exists()
            for rel_path in source_files
        )
        and "plugins/codex-copilot" not in missing
    ):
        missing.append("plugins/codex-copilot")
    return sorted(set(missing))


def _known_untracked_component(
    root: Path,
    component: str,
    source_files: Optional[dict[str, Path]],
) -> tuple[
    str,
    Optional[dict[str, Any]],
    list[dict[str, str]],
    list[dict[str, str]],
    list[Any],
    list[str],
]:
    existing_paths, paths_readable = _existing_component_paths(root, component)
    fingerprint: list[Any] = [component, "untracked", existing_paths]
    if not paths_readable:
        return (
            "could-not-verify",
            None,
            [
                {
                    "id": "readable-component-evidence",
                    "detail": f"{component.title()} evidence could not be inspected.",
                }
            ],
            [
                _evidence(
                    "marker",
                    existing_paths[0] if existing_paths else f".{component}",
                    "unreadable",
                    f"{component.title()} evidence could not be inspected.",
                )
            ],
            fingerprint,
            [],
        )

    if not existing_paths:
        if source_files is None:
            return (
                "could-not-verify",
                None,
                [
                    {
                        "id": "available-component-source",
                        "detail": f"The {component.title()} installer could not be verified.",
                    }
                ],
                [
                    _evidence(
                        "marker",
                        f".{component}",
                        "unreadable",
                        f"The {component.title()} installer is unavailable.",
                    )
                ],
                fingerprint,
                [],
            )
        return (
            "safe-finish",
            None,
            [
                {
                    "id": "component-setup",
                    "detail": f"The {component.title()} project integration is not present.",
                }
            ],
            [],
            fingerprint,
            _missing_action_targets(root, component, source_files),
        )

    entry_ok, entry_evidence, entry_missing, entry_fingerprint = (
        _verify_claude_entry(root)
        if component == "claude"
        else _verify_codex_entry(root)
    )
    fingerprint.extend(entry_fingerprint)
    unreadable = any(item["state"] == "unreadable" for item in entry_evidence)
    if component == "codex" and source_files is not None and not unreadable:
        legacy_linked, legacy_evidence, legacy_fingerprint = (
            _verify_legacy_linked_codex_setup(root)
        )
        entry_requirement_ids = {item["id"] for item in entry_missing}
        if legacy_linked and entry_requirement_ids <= {
            "valid-codex-config",
            "internal-skill-link",
        }:
            recognized = {
                "variant_id": "codex-legacy-linked-v1",
                "version": INTEGRATION_CONTRACT_VERSION,
                "evidence": [*entry_evidence, *legacy_evidence],
            }
            return (
                "guided-integration",
                recognized,
                [
                    *entry_missing,
                    {
                        "id": "lock-record",
                        "detail": "The earlier linked Codex setup is not recorded in the project lock.",
                    },
                ],
                [*entry_evidence, *legacy_evidence],
                [*fingerprint, legacy_fingerprint],
                [],
            )
    unsafe_link = any(
        item["kind"] == "link"
        and item["state"] != "verified"
        and ("outside" in item["detail"] or "resolved safely" in item["detail"])
        for item in entry_evidence
    )
    if unreadable or unsafe_link:
        return (
            "could-not-verify",
            None,
            entry_missing,
            entry_evidence,
            fingerprint,
            [],
        )

    if source_files is None:
        return (
            "could-not-verify",
            None,
            [
                {
                    "id": "available-component-source",
                    "detail": f"The existing {component.title()} setup cannot be compared with an authoritative source.",
                }
            ],
            entry_evidence,
            fingerprint,
            [],
        )

    mismatched: list[str] = []
    exact_existing: list[str] = []
    for rel_path, source_path in source_files.items():
        target = root / rel_path
        present, readable = _path_exists(target)
        if not present:
            continue
        if not readable:
            return (
                "could-not-verify",
                None,
                [
                    {
                        "id": "readable-framework-file",
                        "detail": f"{rel_path} could not be inspected.",
                    }
                ],
                entry_evidence,
                fingerprint,
                [],
            )
        try:
            source_checksum = _checksum(source_path)
            target_checksum = _checksum(target)
        except OSError:
            source_checksum = target_checksum = None
        fingerprint.append([rel_path, source_checksum, target_checksum])
        if source_checksum is None or source_checksum != target_checksum:
            mismatched.append(rel_path)
        else:
            exact_existing.append(rel_path)

    if component == "claude":
        known_paths = set(source_files) | {"CLAUDE.md", ".mcp.json"}
        unknown_agents = [
            path
            for path in (root / ".claude/agents").glob("*.md")
            if path.relative_to(root).as_posix() not in known_paths
        ]
        mismatched.extend(path.relative_to(root).as_posix() for path in unknown_agents)
    else:
        plugin = root / "plugins/codex-copilot"
        try:
            if plugin.is_dir():
                for path in plugin.rglob("*"):
                    if (
                        path.is_file()
                        and path.relative_to(root).as_posix() not in source_files
                    ):
                        mismatched.append(path.relative_to(root).as_posix())
        except OSError:
            return (
                "could-not-verify",
                None,
                [
                    {
                        "id": "readable-plugin-tree",
                        "detail": "The project-local Codex plugin could not be inspected.",
                    }
                ],
                entry_evidence,
                fingerprint,
                [],
            )

    if mismatched or not entry_ok:
        return (
            "guided-integration",
            None,
            [
                *entry_missing,
                *(
                    [
                        {
                            "id": "project-owned-component-content",
                            "detail": "Existing component paths are custom or do not match a recognized framework variant.",
                        }
                    ]
                    if mismatched
                    else []
                ),
            ],
            entry_evidence,
            fingerprint,
            [],
        )

    missing_paths = _missing_action_targets(root, component, source_files)
    evidence = entry_evidence or [
        _evidence(
            "framework-file",
            exact_existing[0],
            "verified",
            f"The existing {component.title()} framework files match the authoritative source.",
        )
    ]
    recognized = {
        "variant_id": f"{component}-compatible-untracked-v1",
        "version": INTEGRATION_CONTRACT_VERSION,
        "evidence": evidence,
    }
    requirements = [
        {
            "id": "lock-record",
            "detail": f"The verified {component.title()} setup is not recorded in the project lock.",
        }
    ]
    kind = "adopt-existing" if not missing_paths else "repair-known"
    fingerprint.append(["safe-kind", kind, missing_paths])
    return (
        "safe-finish",
        recognized,
        requirements,
        evidence,
        fingerprint,
        missing_paths,
    )


def _component_draft(
    root: Path,
    component: str,
    *,
    lock_state: str,
    lock_entry: Optional[dict[str, Any]],
    source_files: Optional[dict[str, Path]],
    owner_state: str,
) -> tuple[dict[str, Any], list[Any], Optional[str], list[str]]:
    verification = _verification(root, component)
    if lock_state == "unreadable":
        draft = {
            "component": component,
            "expected": True,
            "expected_contract": {
                "id": INTEGRATION_CONTRACT_ID,
                "version": INTEGRATION_CONTRACT_VERSION,
            },
            "classification": "could-not-verify",
            "recognized_setup": None,
            "missing_requirements": [
                {
                    "id": "readable-project-lock",
                    "detail": "The project lock is unreadable or uses an unsupported shape.",
                }
            ],
            "responsible_actor": "person",
            "safe_action": None,
            "verification": verification,
        }
        return draft, [component, "unreadable-lock"], None, []

    if lock_entry is not None:
        lock_ok, lock_evidence, lock_missing, lock_fingerprint = _verify_lock_entry(
            root, component, lock_entry
        )
        entry_ok, entry_evidence, entry_missing, entry_fingerprint = (
            _verify_claude_entry(root)
            if component == "claude"
            else _verify_codex_entry(root)
        )
        ok = lock_ok and entry_ok
        guided_variant: Optional[str] = None
        guided_evidence: list[dict[str, str]] = []
        guided_fingerprint: list[Any] = []
        lock_requirement_ids = {item["id"] for item in lock_missing}
        entry_requirement_ids = {item["id"] for item in entry_missing}

        legacy_claude_lock = bool(lock_missing) and all(
            item["id"] == "required-lock-path"
            and item["detail"].endswith(".claude/fitness-check.sh.")
            for item in lock_missing
        )
        if (
            component == "claude"
            and (lock_ok or legacy_claude_lock)
            and entry_requirement_ids <= {"compatible-claude-entry"}
            and all(item["state"] != "unreadable" for item in entry_evidence)
            and (lock_missing or entry_missing)
        ):
            guided_variant = (
                "claude-legacy-lock-v1"
                if legacy_claude_lock
                else "claude-legacy-entry-v1"
            )
        elif component == "codex":
            legacy_linked, legacy_evidence, legacy_fingerprint = (
                _verify_legacy_linked_codex_setup(root)
            )
            guided_fingerprint = legacy_fingerprint
            linked_lock_drift = bool(lock_missing) and all(
                (
                    item["id"] == "verified-framework-file"
                    and item["detail"].startswith(
                        ("plugins/codex-copilot/", "scripts/copilot-gate.sh")
                    )
                )
                or (
                    item["id"] == "required-lock-path"
                    and item["detail"].endswith("scripts/copilot-gate.sh.")
                )
                or (
                    item["id"] == "safe-recorded-path"
                    and item["detail"].startswith(
                        ("plugins/codex-copilot/", "scripts/copilot-gate.sh:")
                    )
                    and "symlink" in item["detail"]
                )
                for item in lock_missing
            )
            legacy_entry_only = bool(entry_missing) and entry_requirement_ids <= {
                "valid-codex-config",
                "internal-skill-link",
            }
            if (
                legacy_linked
                and (lock_ok or linked_lock_drift)
                and (entry_ok or legacy_entry_only)
                and lock_requirement_ids
                <= {
                    "verified-framework-file",
                    "required-lock-path",
                    "safe-recorded-path",
                }
            ):
                guided_variant = "codex-legacy-linked-v1"
                guided_evidence = legacy_evidence

        classification = (
            "ready"
            if ok
            else ("guided-integration" if guided_variant else "could-not-verify")
        )
        actor = {
            "ready": "none",
            "guided-integration": "project-author",
            "could-not-verify": "person",
        }[classification]
        recognized = (
            {
                "variant_id": guided_variant or f"{component}-tracked-lock-v1",
                "version": INTEGRATION_CONTRACT_VERSION,
                "evidence": [*lock_evidence, *entry_evidence, *guided_evidence],
            }
            if ok or guided_variant
            else None
        )
        draft = {
            "component": component,
            "expected": True,
            "expected_contract": {
                "id": INTEGRATION_CONTRACT_ID,
                "version": INTEGRATION_CONTRACT_VERSION,
            },
            "classification": classification,
            "recognized_setup": recognized,
            "missing_requirements": [*lock_missing, *entry_missing],
            "responsible_actor": actor,
            "safe_action": None,
            "verification": verification,
        }
        return (
            draft,
            [
                component,
                lock_fingerprint,
                entry_fingerprint,
                guided_variant,
                guided_fingerprint,
            ],
            None,
            [],
        )

    (
        classification,
        recognized,
        missing,
        evidence,
        fingerprint,
        missing_paths,
    ) = _known_untracked_component(root, component, source_files)
    safe_kind: Optional[str] = None
    if classification == "safe-finish":
        safe_kind = (
            "add-missing"
            if recognized is None
            else ("adopt-existing" if not missing_paths else "repair-known")
        )
    if owner_state == "decision-required" and classification != "ready":
        classification = "owner-decision"
        recognized = None
        safe_kind = None
        missing_paths = []
        missing = [
            {
                "id": "owner-direction",
                "detail": f"The project owner must choose the {component.title()} integration direction.",
            }
        ]
    elif owner_state in ("unreadable", "unsupported") and classification != "ready":
        classification = "could-not-verify"
        recognized = None
        safe_kind = None
        missing_paths = []
        missing = [
            {
                "id": "valid-owner-declaration",
                "detail": "The project ownership declaration is unreadable or unsupported.",
            }
        ]

    actor = {
        "ready": "none",
        "safe-finish": "cli",
        "guided-integration": "project-author",
        "owner-decision": "project-owner",
        "could-not-verify": "person",
    }[classification]
    draft = {
        "component": component,
        "expected": True,
        "expected_contract": {
            "id": INTEGRATION_CONTRACT_ID,
            "version": INTEGRATION_CONTRACT_VERSION,
        },
        "classification": classification,
        "recognized_setup": recognized,
        "missing_requirements": missing,
        "responsible_actor": actor,
        "safe_action": None,
        "verification": verification,
    }
    return draft, [fingerprint, evidence, owner_state], safe_kind, missing_paths


def _artifact_kind(path: str) -> str:
    if path in ("CLAUDE.md", "AGENTS.md"):
        return "instruction"
    if path.endswith("plugin.json") or "marketplace" in path:
        return "manifest"
    if "agents" in PurePosixPath(path).parts:
        return "agent"
    if "skills" in PurePosixPath(path).parts:
        return "skill"
    if "commands" in PurePosixPath(path).parts:
        return "command"
    if path.endswith(".json"):
        return "config"
    return "project-file"


def _safe_action(
    root: Path,
    inspection_id: str,
    component_kinds: dict[str, str],
    missing_paths: dict[str, list[str]],
    preservation: dict[str, Any],
) -> dict[str, Any]:
    components = [
        component for component in SUPPORTED_COMPONENTS if component in component_kinds
    ]
    kinds = set(component_kinds.values())
    kind = next(iter(kinds)) if len(kinds) == 1 else "composite"
    paths = sorted(
        {path for component in components for path in missing_paths.get(component, [])}
    )
    paths.append(PROJECT_LOCK_FILENAME)
    will_add = [
        _artifact(
            _artifact_kind(path),
            path,
            "Add only this missing, recognized integration target.",
        )
        for path in sorted(set(paths))
    ]
    stable = {
        "inspection_id": inspection_id,
        "kind": kind,
        "components": components,
        "will_add": will_add,
    }
    return {
        "id": _opaque_id(stable),
        "inspection_id": inspection_id,
        "kind": kind,
        "components": components,
        "detail": "Finish only the exact recognized component targets, preserve project-owned work, then verify again.",
        "apply_verb": "finish",
        "will_add": will_add,
        "will_preserve": preservation["must_preserve"],
        "will_not_change": preservation["must_preserve"],
        "verification": _verification(root),
    }


def _integration_plan(
    root: Path,
    inspection_id: str,
    classification: str,
    actor: str,
    components: list[dict[str, Any]],
    capabilities: dict[str, Any],
    preservation: dict[str, Any],
) -> dict[str, Any]:
    detected = [
        f"Detected {capabilities['instructions']} instruction entries, "
        f"{capabilities['agents']} agents, {capabilities['skills']} skills, "
        f"{capabilities['commands']} commands, and {capabilities['plugins']} project plugins."
    ]
    if capabilities["integration_paths"]:
        detected.append(
            "Integration paths: " + ", ".join(capabilities["integration_paths"])
        )
    missing = [
        requirement["detail"]
        for component in components
        if component["classification"] != "ready"
        for requirement in component["missing_requirements"]
    ]
    preserve = [
        f"{artifact['path']}: {artifact['detail']}"
        for artifact in preservation["must_preserve"]
    ] or ["Preserve every existing project-owned path."]
    prohibited = [
        action.replace("-", " ") for action in preservation["prohibited_actions"]
    ]
    prompt = None
    owner_handoff = None
    legacy_variants = {
        component["recognized_setup"]["variant_id"]
        for component in components
        if isinstance(component.get("recognized_setup"), dict)
        and component["recognized_setup"]["variant_id"].startswith(
            ("claude-legacy-", "codex-legacy-")
        )
    }
    if classification == "guided-integration":
        if legacy_variants:
            prompt_text = (
                "Migrate the recognized earlier linked project integration to "
                "project-integration contract version 1. Treat this as a reviewed "
                "project-author change, not an automatic repair. Preserve all "
                "project-owned instructions, agents, commands, skills, and plugin "
                "siblings. Stage a fresh project-local Codex plugin from the "
                "authoritative configured source; do not copy through or modify the "
                "external link. Replace only the recognized legacy Codex plugin link, "
                "point the internal skill bridge at that project-local copy, replace "
                "the recognized linked gate with the project-local gate when present, "
                "update the install metadata to the portable copy form, merge the "
                "recognized Claude Copilot entry when it is missing, and refresh "
                "helper-owned lock evidence. Stop on any ownership conflict. Finish by running the "
                "exact verification command; assistant self-report is not proof of "
                "readiness."
            )
        else:
            prompt_text = (
                "Integrate project-integration contract version 1 for Claude and "
                "Codex. Preserve every path named by this plan. Add compatible "
                "routing or metadata without overwriting, renaming, deleting, or "
                "flattening project capabilities. Stop on any ownership conflict. "
                "Finish by running the exact verification command; assistant "
                "self-report is not proof of readiness."
            )
        prompt = {
            "version": INTEGRATION_CONTRACT_VERSION,
            "text": prompt_text,
        }
    else:
        owner_handoff = {
            "version": INTEGRATION_CONTRACT_VERSION,
            "text": (
                "A project integration decision is ready for the project owner. "
                "Nothing was changed. Please choose how Claude and Codex should "
                "coexist with the preserved project instructions and capabilities, "
                "then run the included verification command. Only its machine "
                "verdict can mark the project ready."
            ),
        }
    stable = {
        "inspection_id": inspection_id,
        "classification": classification,
        "actor": actor,
        "detected": detected,
        "missing": missing,
        "preserve": preserve,
    }
    return {
        "id": _opaque_id(stable),
        "inspection_id": inspection_id,
        "responsible_actor": actor,
        "detected": detected,
        "missing": missing or ["The complete component contract is not verified."],
        "preserve": preserve,
        "prohibited": prohibited,
        "prompt": prompt,
        "owner_handoff": owner_handoff,
        "verification": _verification(root),
        "stop_conditions": [
            "Stop before changing a project-owned capability path.",
            "Stop for an owner decision when project instructions conflict.",
            "Stop if authoritative verification does not return Ready.",
        ],
    }


def _diagnostic(
    root: Path,
    inspection_id: str,
    components: list[dict[str, Any]],
    capabilities: dict[str, Any],
    preservation: dict[str, Any],
) -> dict[str, Any]:
    """Build a content-free, read-only diagnostic route for an uncertain project."""
    verification = _verification(root)
    evidence_lines: list[str] = []
    for component in components:
        label = component["component"].title()
        recognized = component.get("recognized_setup")
        if recognized:
            for evidence in recognized.get("evidence", []):
                evidence_lines.append(
                    f"- {label} recognized {evidence['path']}: {evidence['detail']}"
                )
        for requirement in component.get("missing_requirements", []):
            evidence_lines.append(
                f"- {label} could not confirm {requirement['id']}: "
                f"{requirement['detail']}"
            )
    if not evidence_lines:
        evidence_lines.append(
            "- The helper could not produce component evidence that proves readiness."
        )

    prohibited = [
        action.replace("-", " ") for action in preservation["prohibited_actions"]
    ]
    prompt = "\n".join(
        [
            "Diagnose project-integration contract version 1 in READ-ONLY mode.",
            f"Project: {root}",
            (
                "Capabilities: "
                f"{capabilities['instructions']} instruction entries, "
                f"{capabilities['agents']} agents, "
                f"{capabilities['skills']} skills, "
                f"{capabilities['commands']} commands, and "
                f"{capabilities['plugins']} project plugins."
            ),
            "",
            "Authoritative helper evidence:",
            *evidence_lines,
            "",
            "Constraints:",
            "- Do not create, edit, rename, move, or delete project files.",
            "- Do not install, link, or reconfigure project capabilities.",
            "- Do not reinterpret assistant self-report as proof of readiness.",
            *[f"- Do not {action}." for action in prohibited],
            "",
            "Explain the mismatch in plain language and identify the smallest next "
            "inspection needed. Run only the exact read-only verification command:",
            " ".join(verification["command"]),
            "",
            "Return to Copilot Control Tower after diagnosis. Only the helper may "
            "reclassify this project or produce a reviewed integration plan.",
        ]
    )
    stable = {
        "inspection_id": inspection_id,
        "project": str(root),
        "mode": "read-only",
        "evidence": evidence_lines,
    }
    return {
        "id": _opaque_id(stable),
        "inspection_id": inspection_id,
        "mode": "read-only",
        "prompt": {
            "version": INTEGRATION_CONTRACT_VERSION,
            "text": prompt,
        },
        "verification": verification,
        "stop_conditions": [
            "Stop before any project write.",
            "Stop before changing a project-owned capability path.",
            "Stop if the evidence is insufficient to explain the mismatch.",
        ],
    }


def inspect_project_integration(
    project: Path | str,
    *,
    claude_root: Optional[Path | str] = None,
    codex_root: Optional[Path | str] = None,
    detail: bool = True,
    owner_hold: bool = False,
) -> dict[str, Any]:
    """Inspect one project and return schema-1.1 integration fields."""
    root = Path(project).expanduser().resolve()
    lock_state, lock_entries, lock_fingerprint = _lock_state(root)
    owner_state, owner_fingerprint = _owner_state(root)
    if owner_hold and owner_state == "absent":
        owner_state = "decision-required"
        owner_fingerprint = ["owner", "machine-local-hold"]
    capabilities, capability_fingerprint = _project_capabilities(root)
    preservation = _preservation(root, capabilities)
    sources = {
        "claude": _source_files("claude", _framework_root("claude", claude_root)),
        "codex": _source_files("codex", _framework_root("codex", codex_root)),
    }

    components: list[dict[str, Any]] = []
    fingerprints: list[Any] = [
        lock_fingerprint,
        owner_fingerprint,
        capability_fingerprint,
    ]
    component_kinds: dict[str, str] = {}
    component_missing_paths: dict[str, list[str]] = {}
    for component in SUPPORTED_COMPONENTS:
        draft, fingerprint, safe_kind, missing_paths = _component_draft(
            root,
            component,
            lock_state=lock_state,
            lock_entry=lock_entries.get(component),
            source_files=sources[component],
            owner_state=owner_state,
        )
        components.append(draft)
        fingerprints.append(fingerprint)
        if safe_kind is not None:
            component_kinds[component] = safe_kind
            component_missing_paths[component] = missing_paths

    classification = max(
        (component["classification"] for component in components),
        key=lambda value: _CLASSIFICATION_PRECEDENCE[value],
    )
    actor = {
        "ready": "none",
        "safe-finish": "cli",
        "guided-integration": "project-author",
        "owner-decision": "project-owner",
        "could-not-verify": "person",
    }[classification]
    inspection_id = _opaque_id(
        {
            "contract": [
                INTEGRATION_CONTRACT_ID,
                INTEGRATION_CONTRACT_VERSION,
            ],
            "project": str(root),
            "fingerprints": fingerprints,
            "classification": classification,
        }
    )
    action = None
    if classification == "safe-finish":
        action = _safe_action(
            root,
            inspection_id,
            component_kinds,
            component_missing_paths,
            preservation,
        )
        for component in components:
            if component["classification"] == "safe-finish":
                component["safe_action"] = action

    plan_available = classification in ("guided-integration", "owner-decision")
    integration_plan = (
        _integration_plan(
            root,
            inspection_id,
            classification,
            actor,
            components,
            capabilities,
            preservation,
        )
        if detail and plan_available
        else None
    )
    diagnostic = (
        _diagnostic(
            root,
            inspection_id,
            components,
            capabilities,
            preservation,
        )
        if detail and classification == "could-not-verify"
        else None
    )
    return {
        "classification": classification,
        "responsible_actor": actor,
        "inspection": {
            "id": inspection_id,
            "contract_id": INTEGRATION_CONTRACT_ID,
            "contract_version": INTEGRATION_CONTRACT_VERSION,
            "scope": "detail" if detail else "summary",
            "complete": True,
        },
        "components": components,
        "capabilities": capabilities,
        "preservation": preservation,
        "safe_action": action,
        "plan_available": plan_available,
        "integration_plan": integration_plan,
        "diagnostic": diagnostic,
        "verified_components": [
            component["component"]
            for component in components
            if component["classification"] == "ready"
        ],
        "safe_component_kinds": component_kinds,
        "safe_missing_paths": component_missing_paths,
    }
