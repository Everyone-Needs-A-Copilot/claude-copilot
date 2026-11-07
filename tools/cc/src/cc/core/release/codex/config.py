"""Atomic, backed-up edits of `~/.codex/config.toml` for the single marketplace.

The file is edited as text, one table block at a time, so owner content and
comments outside the touched tables stay byte-identical. Every write validates
with tomllib, takes a backup first, and goes through temp file + rename.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import tempfile
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from cc.core.release.engine import layout

from .marketplace import MARKETPLACE_NAME

RETIRED_MARKETPLACES = ("codex-copilot-project", "codex-copilot-local")
RECEIPT_NAME = "codex-config-receipt.json"


class ConfigError(RuntimeError):
    pass


def config_path(codex_home: Path | str) -> Path:
    return Path(codex_home) / "config.toml"


def receipt_path(home: Path | str | None = None) -> Path:
    return layout.copilot_home(home) / RECEIPT_NAME


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def plugin_key(plugin: str) -> str:
    return f"{plugin}@{MARKETPLACE_NAME}"


def _header_path(line: str) -> tuple[str, ...] | None:
    text = line.strip()
    if not text.startswith("[") or text.startswith("[["):
        return None
    try:
        data = tomllib.loads(text + "\n")
    except tomllib.TOMLDecodeError:
        return None
    path: list[str] = []
    while isinstance(data, dict) and len(data) == 1:
        ((key, data),) = data.items()
        path.append(key)
    return tuple(path)


def _split(text: str) -> list[tuple[tuple[str, ...] | None, list[str]]]:
    """Blocks of (header path or None for the preamble, lines)."""
    blocks: list[tuple[tuple[str, ...] | None, list[str]]] = [(None, [])]
    for line in text.splitlines(keepends=True):
        path = _header_path(line)
        if path is not None:
            blocks.append((path, [line]))
        else:
            blocks[-1][1].append(line)
    return blocks


def edit(text: str, *, source: str, plugins: Iterable[str], prune_trust: bool = False) -> str:
    """Return `text` with the single marketplace registered and duplicates removed."""
    ours = {plugin_key(p) for p in plugins}
    names = sorted(p.partition("@")[0] for p in ours)
    kept = []
    for path, lines in _split(text):
        drop = False
        if path and len(path) == 2 and path[0] == "marketplaces":
            drop = path[1] in RETIRED_MARKETPLACES or path[1] == MARKETPLACE_NAME
        elif path and len(path) == 2 and path[0] == "plugins":
            drop = path[1].rpartition("@")[2] in RETIRED_MARKETPLACES or path[1] in ours
        elif prune_trust and path and len(path) == 3 and path[:2] == ("hooks", "state"):
            drop = path[2].partition(":")[0].rpartition("@")[2] in RETIRED_MARKETPLACES
        if not drop:
            kept.append("".join(lines))
    out = "".join(kept).rstrip("\n")
    new = f'[marketplaces.{MARKETPLACE_NAME}]\nsource_type = "local"\nsource = {json.dumps(source)}\n'
    new += "".join(f"\n[plugins.{json.dumps(plugin_key(n))}]\nenabled = true\n" for n in names)
    return (out + "\n\n" if out else "") + new


@dataclass(frozen=True)
class ConfigResult:
    changed: bool
    backup: str | None
    before_sha: str
    after_sha: str
    removed: list[str] = field(default_factory=list)


def _atomic_write(path: Path, data: bytes) -> None:
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            shutil.copymode(path, temp)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def apply(codex_home: Path | str, home: Path | str | None, *, source: str,
          plugins: Iterable[str], prune_trust: bool = False) -> ConfigResult:
    """Back up then rewrite config.toml; record a rollback receipt under ~/.copilot."""
    plugins = list(plugins)
    path = config_path(codex_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.parent / "config.toml.lock", "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        before = path.read_bytes() if path.exists() else b""
        try:
            old = tomllib.loads(before.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"{path} is not valid TOML; refusing to edit: {exc}") from exc
        after_text = edit(before.decode("utf-8"), source=source, plugins=plugins,
                          prune_trust=prune_trust)
        try:
            parsed = tomllib.loads(after_text)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"edit would produce invalid TOML: {exc}") from exc
        if parsed["marketplaces"][MARKETPLACE_NAME]["source"] != source:
            raise ConfigError("edit did not register the marketplace source")
        after = after_text.encode("utf-8")
        removed = sorted(
            [f"marketplaces.{m}" for m in RETIRED_MARKETPLACES if m in old.get("marketplaces", {})]
            + [f"plugins.{k}" for k in old.get("plugins", {})
               if k.rpartition("@")[2] in RETIRED_MARKETPLACES]
        )
        if after == before:
            return ConfigResult(False, None, _sha(before), _sha(after), removed)
        backup = None
        if path.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup = str(path.with_name(f"config.toml.bak-release-{stamp}"))
            shutil.copy2(path, backup)
        receipt = receipt_path(home)
        receipt.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(receipt, (json.dumps({
            "config": str(path), "backup": backup, "beforeSha256": _sha(before),
            "afterSha256": _sha(after), "removed": removed,
        }, indent=2) + "\n").encode())
        # Persist recovery authority before mutating config; receipt failure must
        # not leave an untracked configuration write behind.
        _atomic_write(path, after)
        return ConfigResult(True, backup, _sha(before), _sha(after), removed)


def rollback(home: Path | str | None = None, *, force: bool = False) -> str:
    """Restore the config saved by the last `apply`; refuse if edited since unless forced."""
    try:
        record = json.loads(receipt_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"no config rollback receipt: {exc}") from exc
    target = Path(record["config"])
    current = target.read_bytes() if target.exists() else b""
    if _sha(current) != record["afterSha256"] and not force:
        raise ConfigError(f"{target} changed since the release step; use force to overwrite")
    backup = record.get("backup")
    if backup is None:  # the file did not exist before
        target.unlink(missing_ok=True)
        return str(target)
    data = Path(backup).read_bytes()
    if _sha(data) != record["beforeSha256"]:
        raise ConfigError(f"backup {backup} no longer matches the recorded hash")
    _atomic_write(target, data)
    return str(target)


def read(codex_home: Path | str) -> dict:
    path = config_path(codex_home)
    return tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
