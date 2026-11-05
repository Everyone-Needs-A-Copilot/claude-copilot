"""Keep the machine config's framework source pointing at the installed snapshot.

`cc reconcile` reads `paths.claude_copilot_root` / `paths.codex_copilot_root`
as the framework source. A value that names a framework snapshot goes stale the
moment a newer snapshot is installed, and every project then reconciles to the
old release. Both installation paths repoint it: the snapshot installer
(`scripts/install-framework-snapshot.py`, which carries a standard-library copy
of `config_with_snapshot_roots()`; keep the two in step, a test compares them)
and `cc update` (`sync_machine_config_to_active_runtime()`).

Only values that already name a snapshot move. A path the owner chose (a
checkout, `~/.claude/copilot`, a mirror) is never touched.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

# Only the Claude root is a framework snapshot. `codex_copilot_root` must be the
# Codex foundation (see `codex_foundation_root`); a Claude snapshot only bundles
# whatever older Codex plugin its release shipped, so it is never a valid target.
SNAPSHOT_ROOT_KEYS = ("claude_copilot_root",)
_TILDE_SNAPSHOTS = "~/.copilot/framework-snapshots/"
_OBJECT_ID = re.compile(r"[0-9a-f]{40}")


_CLAUDE_SNAPSHOT_DIR = re.compile(r"claude-copilot-[0-9a-f]{40}")


def names_claude_snapshot(raw: object) -> bool:
    """Whether `raw` is, or lies inside, a Claude framework snapshot directory."""
    parts = Path(str(raw)).expanduser().parts
    return any(
        _CLAUDE_SNAPSHOT_DIR.fullmatch(part) and index > 0
        and parts[index - 1] == "framework-snapshots"
        for index, part in enumerate(parts)
    )


def codex_foundation_root(manifest_path: object = None) -> Path | None:
    """The pinned `codex-foundation` layer's local source, only if it is at its pinned ref.

    This is the checkout whose signed tree the reconcile binding verifies, so
    the files delivered by install/migrate/setup and the version reconcile
    records come from the same release. None when the layer, its path or its
    ref cannot be established.
    """
    import subprocess

    from cc.core.config import resolve_key
    from cc.core.ecosystem.manifest import ManifestError, load_layers
    from cc.core.ecosystem.mirror import synthesize_effective_layers

    configured = resolve_key("layers.manifest") if manifest_path is None else manifest_path
    if not configured:
        return None
    try:
        layers = load_layers(configured)
        base = Path(str(resolve_key("paths.mirrors_root"))).expanduser()
        effective = synthesize_effective_layers(layers, mirror_root_base=base)
    except (ManifestError, OSError, ValueError):
        return None
    layer = next(
        (
            row for row in effective
            if row.get("product") == "codex" and row.get("role") == "foundation"
        ),
        None,
    )
    source = (layer or {}).get("source") or {}
    path, ref = source.get("path"), source.get("ref")
    if not path or not isinstance(ref, str):
        return None
    root = Path(str(path)).expanduser()
    if not root.is_dir():
        return None
    try:
        head, pinned = (
            subprocess.run(
                ("git", "-C", str(root), "rev-parse", f"{rev}^{{commit}}"),
                check=True, capture_output=True, text=True, timeout=30,
            ).stdout.strip()
            for rev in ("HEAD", ref)
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return root if head == pinned else None


def effective_codex_root(raw: object, manifest_path: object = None) -> object:
    """`raw`, unless it names a Claude snapshot; then the pinned Codex foundation (or None)."""
    if raw and names_claude_snapshot(raw):
        return codex_foundation_root(manifest_path)
    return raw


class ConfigRepointError(ValueError):
    """The machine config cannot be safely rewritten."""


def config_with_snapshot_roots(
    existing: bytes, snapshots_root: Path, snapshot: Path
) -> bytes:
    """`existing` with snapshot-pinned `paths.*_copilot_root` moved to `snapshot`.

    Returns `existing` unchanged when nothing needs to move. Indent style is
    preserved when it is a simple space indent or compact JSON.
    """
    try:
        config = json.loads(existing.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigRepointError(
            "~/.claude/cc/config.json is not valid JSON; refusing to repoint the framework source"
        ) from exc
    paths = config.get("paths") if isinstance(config, dict) else None
    if not isinstance(paths, dict):
        return existing
    prefixes = (str(snapshots_root) + "/", _TILDE_SNAPSHOTS)
    changed = False
    for key in SNAPSHOT_ROOT_KEYS:
        value = paths.get(key)
        if isinstance(value, str) and value.startswith(prefixes) and value != str(snapshot):
            paths[key] = str(snapshot)
            changed = True
    if not changed:
        return existing
    match = re.search(rb"^\{\s*\n([ \t]+)\S", existing)
    indent: str | int | None = match.group(1).decode("ascii") if match else None
    text = json.dumps(config, indent=indent)
    return (text + ("\n" if existing.endswith(b"\n") or indent else "")).encode("utf-8")


def sync_machine_config_to_active_runtime(
    *, config_path: Path, copilot_root: Path
) -> bool:
    """Repoint snapshot-pinned roots at the installed runtime's snapshot.

    Reads `framework-runtime.json` (written atomically by the snapshot
    installer). Returns True when the config was rewritten. A missing config,
    missing/unreadable manifest or a snapshot outside the snapshots directory
    changes nothing.
    """
    try:
        manifest = json.loads((copilot_root / "framework-runtime.json").read_text("utf-8"))
        snapshot = Path(str(manifest["snapshot"]))
        existing = config_path.read_bytes()
    except (OSError, ValueError, KeyError, TypeError):
        return False
    snapshots_root = copilot_root / "framework-snapshots"
    if (
        snapshot.parent != snapshots_root
        or not _OBJECT_ID.fullmatch(snapshot.name.removeprefix("claude-copilot-"))
        or not snapshot.is_dir()
    ):
        return False
    updated = config_with_snapshot_roots(existing, snapshots_root, snapshot)
    if updated == existing:
        return False
    mode = config_path.stat().st_mode & 0o777
    fd, tmp = tempfile.mkstemp(dir=config_path.parent, prefix=".config-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, config_path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return True
