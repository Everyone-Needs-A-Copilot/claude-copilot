"""Transactional Codex plugin convergence for an immutable framework snapshot."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

PLUGIN_NAME = "codex-copilot"
MARKETPLACE_NAME = "codex-copilot-project"
MARKETPLACE_PATH = ".agents/plugins/marketplace.json"
PLUGIN_PATH = "plugins/codex-copilot"


class CodexPluginError(RuntimeError):
    """A fail-closed Codex plugin installation error."""


@dataclass(frozen=True)
class PluginArtifact:
    relative_path: str
    kind: str
    executable: bool = False
    checksum: str = ""
    link_target: str = ""


@dataclass(frozen=True)
class CodexPluginReceipt:
    plugin_id: str
    marketplace: str
    marketplace_source: str
    plugin_source: str
    installed_path: str
    manifest_sha256: str
    tree_sha256: str


@dataclass
class CodexPluginTransaction:
    receipt: CodexPluginReceipt
    changed: int
    _rollback: Callable[[], None]

    def rollback(self) -> None:
        self._rollback()


CodexRunner = Callable[[Sequence[str], Path], Mapping[str, Any]]


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _regular_bytes(path: Path) -> bytes:
    try:
        metadata = path.lstat()
        payload = path.read_bytes()
    except OSError as exc:
        raise CodexPluginError(f"Codex plugin file is unavailable: {path}") from exc
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise CodexPluginError(f"Codex plugin file is not regular: {path}")
    if metadata.st_mode & 0o222:
        raise CodexPluginError(f"Codex plugin file is writable: {path}")
    return payload


def _tree_identity(root: Path) -> tuple[PluginArtifact, ...]:
    try:
        metadata = root.lstat()
    except OSError as exc:
        raise CodexPluginError(f"Codex plugin root is unavailable: {root}") from exc
    if not stat.S_ISDIR(metadata.st_mode) or root.is_symlink():
        raise CodexPluginError(f"Codex plugin root must be a real directory: {root}")

    artifacts: list[PluginArtifact] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode) and not path.is_symlink():
            continue
        if stat.S_ISREG(metadata.st_mode) and not path.is_symlink():
            artifacts.append(
                PluginArtifact(
                    relative_path=relative,
                    kind="file",
                    executable=bool(metadata.st_mode & 0o111),
                    checksum=_sha256(path.read_bytes()),
                )
            )
        elif stat.S_ISLNK(metadata.st_mode):
            artifacts.append(
                PluginArtifact(
                    relative_path=relative,
                    kind="symlink",
                    link_target=os.readlink(path),
                )
            )
        else:
            raise CodexPluginError(
                f"Codex plugin contains an unsupported entry: {relative}"
            )
    if not artifacts:
        raise CodexPluginError("Codex plugin tree is empty")
    return tuple(artifacts)


def _tree_sha256(artifacts: Sequence[PluginArtifact]) -> str:
    rows = [
        {
            "executable": item.executable,
            "kind": item.kind,
            "link_target": item.link_target,
            "path": item.relative_path,
            "sha256": item.checksum,
        }
        for item in artifacts
    ]
    return _sha256(
        (json.dumps(rows, separators=(",", ":"), sort_keys=True) + "\n").encode()
    )


def validate_snapshot_plugin(snapshot: Path) -> tuple[tuple[PluginArtifact, ...], str]:
    marketplace_payload = _regular_bytes(snapshot / MARKETPLACE_PATH)
    try:
        marketplace = json.loads(marketplace_payload)
        plugins = marketplace["plugins"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise CodexPluginError("Codex marketplace descriptor is invalid") from exc
    if marketplace.get("name") != MARKETPLACE_NAME:
        raise CodexPluginError("Codex marketplace name is not canonical")
    if not isinstance(plugins, list) or len(plugins) != 1:
        raise CodexPluginError("canonical Codex marketplace must contain one plugin")
    plugin = plugins[0]
    if (
        not isinstance(plugin, dict)
        or plugin.get("name") != PLUGIN_NAME
        or plugin.get("source") != {"source": "local", "path": f"./{PLUGIN_PATH}"}
    ):
        raise CodexPluginError("canonical Codex plugin source is invalid")

    plugin_root = snapshot / PLUGIN_PATH
    artifacts = _tree_identity(plugin_root)
    manifest_payload = _regular_bytes(plugin_root / ".codex-plugin/plugin.json")
    try:
        manifest = json.loads(manifest_payload)
    except json.JSONDecodeError as exc:
        raise CodexPluginError("Codex plugin manifest is invalid") from exc
    if not isinstance(manifest, dict) or manifest.get("name") != PLUGIN_NAME:
        raise CodexPluginError("Codex plugin manifest name is not canonical")
    return artifacts, _sha256(manifest_payload)


def run_codex_plugin(arguments: Sequence[str], home: Path) -> Mapping[str, Any]:
    codex = shutil.which("codex")
    if codex is None:
        raise CodexPluginError("Codex CLI is required to install its plugin")
    codex_home = home / ".codex"
    codex_home.mkdir(parents=True, exist_ok=True, mode=0o700)
    if codex_home.is_symlink() or not codex_home.is_dir():
        raise CodexPluginError("Codex home must be a real directory")
    environment = {**os.environ, "HOME": str(home), "CODEX_HOME": str(codex_home)}
    try:
        result = subprocess.run(
            (codex, "plugin", *arguments),
            check=False,
            capture_output=True,
            text=True,
            env=environment,
            timeout=60.0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CodexPluginError("Codex plugin command could not run") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise CodexPluginError(f"Codex plugin command failed: {detail}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise CodexPluginError("Codex plugin command returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise CodexPluginError("Codex plugin command returned a non-object result")
    return payload


class _Manager:
    def __init__(self, home: Path, runner: CodexRunner) -> None:
        self.home = home
        self.runner = runner

    def run(self, *args: str) -> Mapping[str, Any]:
        return self.runner(args, self.home)

    def inventory(self) -> tuple[dict[str, str], list[dict[str, Any]]]:
        marketplace_rows = self.run("marketplace", "list", "--json").get("marketplaces")
        plugin_rows = self.run("list", "--json").get("installed")
        if not isinstance(marketplace_rows, list) or not isinstance(plugin_rows, list):
            raise CodexPluginError("Codex plugin inventory is malformed")
        marketplaces: dict[str, str] = {}
        for item in marketplace_rows:
            if not isinstance(item, dict):
                raise CodexPluginError("Codex marketplace inventory is malformed")
            name, root = item.get("name"), item.get("root")
            source = item.get("marketplaceSource")
            if not isinstance(name, str) or not isinstance(root, str):
                raise CodexPluginError("Codex marketplace inventory is malformed")
            if name in marketplaces:
                raise CodexPluginError(f"duplicate Codex marketplace name: {name}")
            if source is not None and (
                not isinstance(source, dict)
                or source.get("sourceType") != "local"
                or source.get("source") != root
            ):
                raise CodexPluginError(f"Codex marketplace is not local: {name}")
            marketplaces[name] = root
        plugins: list[dict[str, Any]] = []
        for item in plugin_rows:
            if not isinstance(item, dict) or not all(
                isinstance(item.get(field), str)
                for field in ("name", "marketplaceName", "pluginId")
            ):
                raise CodexPluginError("Codex installed plugin inventory is malformed")
            plugins.append(item)
        return marketplaces, plugins

    @staticmethod
    def matching(plugins: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        return [item for item in plugins if item["name"] == PLUGIN_NAME]

    def remove_plugin(self, marketplace: str) -> None:
        self.run("remove", f"{PLUGIN_NAME}@{marketplace}", "--json")

    def remove_marketplace(self) -> None:
        self.run("marketplace", "remove", MARKETPLACE_NAME, "--json")

    def add_marketplace(self, source: Path) -> None:
        result = self.run("marketplace", "add", str(source), "--json")
        if result.get("marketplaceName") != MARKETPLACE_NAME:
            raise CodexPluginError("Codex registered an unexpected marketplace")

    def add_plugin(self, marketplace: str = MARKETPLACE_NAME) -> Mapping[str, Any]:
        return self.run("add", f"{PLUGIN_NAME}@{marketplace}", "--json")

    @staticmethod
    def assert_replaceable_marketplace(root: str) -> None:
        try:
            marketplace = json.loads((Path(root) / MARKETPLACE_PATH).read_bytes())
            plugins = marketplace["plugins"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise CodexPluginError(
                "existing canonical marketplace cannot be replaced safely"
            ) from exc
        if (
            marketplace.get("name") != MARKETPLACE_NAME
            or not isinstance(plugins, list)
            or len(plugins) != 1
            or not isinstance(plugins[0], dict)
            or plugins[0].get("name") != PLUGIN_NAME
        ):
            raise CodexPluginError(
                "existing canonical marketplace contains unrelated plugins"
            )

    def verify(
        self,
        snapshot: Path,
        expected: tuple[PluginArtifact, ...],
        add_result: Mapping[str, Any],
    ) -> Path:
        marketplaces, plugins = self.inventory()
        matching = self.matching(plugins)
        expected_id = f"{PLUGIN_NAME}@{MARKETPLACE_NAME}"
        if len(matching) != 1 or (
            matching[0].get("pluginId") != expected_id
            or matching[0].get("enabled") is not True
            or matching[0].get("installed") is not True
        ):
            raise CodexPluginError("Codex plugin registration is not canonical")
        snapshot = snapshot.resolve(strict=True)
        source = matching[0].get("source")
        if (
            Path(marketplaces.get(MARKETPLACE_NAME, "")).resolve(strict=True)
            != snapshot
            or not isinstance(source, dict)
            or source.get("source") != "local"
            or Path(str(source.get("path", ""))).resolve(strict=True)
            != (snapshot / PLUGIN_PATH).resolve(strict=True)
        ):
            raise CodexPluginError("Codex plugin source is not the active snapshot")
        raw_path = add_result.get("installedPath")
        if not isinstance(raw_path, str):
            raise CodexPluginError("Codex plugin add omitted installedPath")
        installed_path = Path(raw_path).resolve(strict=True)
        cache_root = (self.home / ".codex/plugins/cache").resolve(strict=True)
        try:
            installed_path.relative_to(cache_root)
        except ValueError as exc:
            raise CodexPluginError("Codex plugin cache is outside Codex home") from exc
        if _tree_identity(installed_path) != expected:
            raise CodexPluginError("Codex plugin cache differs from snapshot bytes")
        return installed_path

    def restore(
        self, marketplaces: Mapping[str, str], plugins: Sequence[dict[str, Any]]
    ) -> None:
        current_marketplaces, current_plugins = self.inventory()
        for item in self.matching(current_plugins):
            self.remove_plugin(item["marketplaceName"])
        current_marketplaces, current_plugins = self.inventory()
        if any(item["marketplaceName"] == MARKETPLACE_NAME for item in current_plugins):
            raise CodexPluginError("cannot restore occupied canonical marketplace")
        if MARKETPLACE_NAME in current_marketplaces:
            self.remove_marketplace()
        old_target = marketplaces.get(MARKETPLACE_NAME)
        if old_target is not None:
            self.add_marketplace(Path(old_target))
        for item in plugins:
            self.add_plugin(item["marketplaceName"])
        restored_marketplaces, restored_plugins = self.inventory()
        if (
            sorted(item["pluginId"] for item in self.matching(restored_plugins))
            != sorted(item["pluginId"] for item in plugins)
            or restored_marketplaces.get(MARKETPLACE_NAME) != old_target
        ):
            raise CodexPluginError("Codex plugin rollback did not restore prior state")


def normalize_codex_plugin(
    snapshot: Path,
    expected: tuple[PluginArtifact, ...],
    manifest_sha256: str,
    home: Path,
    runner: CodexRunner = run_codex_plugin,
) -> CodexPluginTransaction:
    manager = _Manager(home, runner)
    old_marketplaces, all_plugins = manager.inventory()
    old_plugins = manager.matching(all_plugins)
    for item in old_plugins:
        if item["marketplaceName"] not in old_marketplaces or (
            item.get("enabled") is not True or item.get("installed") is not True
        ):
            raise CodexPluginError(
                f"Codex plugin is not restorable: {item['pluginId']}"
            )
    if any(
        item["marketplaceName"] == MARKETPLACE_NAME and item["name"] != PLUGIN_NAME
        for item in all_plugins
    ):
        raise CodexPluginError("canonical marketplace has unrelated installed plugins")
    old_target = old_marketplaces.get(MARKETPLACE_NAME)
    if old_target is not None:
        manager.assert_replaceable_marketplace(old_target)

    snapshot_source = str(snapshot.resolve(strict=True))
    aligned = (
        len(old_plugins) == 1
        and old_plugins[0]["marketplaceName"] == MARKETPLACE_NAME
        and old_marketplaces.get(MARKETPLACE_NAME) == snapshot_source
    )
    mutated = False
    try:
        if aligned:
            add_result = manager.add_plugin()
            installed_path = manager.verify(snapshot, expected, add_result)
            changed = 0
        else:
            mutated = True
            for item in old_plugins:
                manager.remove_plugin(item["marketplaceName"])
            if MARKETPLACE_NAME in old_marketplaces:
                manager.remove_marketplace()
            manager.add_marketplace(snapshot)
            add_result = manager.add_plugin()
            installed_path = manager.verify(snapshot, expected, add_result)
            changed = 1
    except BaseException as error:
        if mutated:
            try:
                manager.restore(old_marketplaces, old_plugins)
            except BaseException as rollback_error:
                raise CodexPluginError(
                    f"normalization failed and rollback was incomplete: {rollback_error}"
                ) from error
        raise

    rolled_back = False

    def rollback() -> None:
        nonlocal rolled_back
        if changed and not rolled_back:
            manager.restore(old_marketplaces, old_plugins)
            rolled_back = True

    receipt = CodexPluginReceipt(
        plugin_id=f"{PLUGIN_NAME}@{MARKETPLACE_NAME}",
        marketplace=MARKETPLACE_NAME,
        marketplace_source=snapshot_source,
        plugin_source=str((snapshot / PLUGIN_PATH).resolve(strict=True)),
        installed_path=str(installed_path),
        manifest_sha256=manifest_sha256,
        tree_sha256=_tree_sha256(expected),
    )
    return CodexPluginTransaction(receipt, changed, rollback)
