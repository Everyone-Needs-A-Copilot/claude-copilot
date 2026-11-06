"""Receipt-scoped prune: plan lists exact paths; deletion needs approval."""

from __future__ import annotations

import json
import os
import shutil
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import layout, pointer


class PruneError(RuntimeError):
    pass


def _protected(home) -> set[str]:
    keep = {item for item in (pointer.current_release_id(home), pointer.previous_release(home)) if item}
    return keep


def plan(home: Path | str | None = None, *, keep: int = layout.DEFAULT_KEEP) -> dict[str, Any]:
    """Write and return a receipt naming the exact release paths a prune would delete."""
    if keep < 1:
        raise PruneError("keep must be at least 1")
    releases = pointer.list_releases(home)  # sorted oldest first (ids start with a timestamp)
    protected = _protected(home)
    newest = set(releases[-keep:])
    candidates = [r for r in releases if r not in protected and r not in newest]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    receipt = {
        "receipt": stamp,
        "keep": keep,
        "protected": sorted(protected | newest),
        "paths": [str(layout.release_dir(r, home)) for r in candidates],
        "approved": False,
    }
    directory = layout.copilot_home(home) / layout.PRUNE_RECEIPTS_DIRNAME
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{stamp}.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt


def _make_writable(root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(root):
        os.chmod(dirpath, 0o700)
        for name in filenames:
            path = Path(dirpath, name)
            if not path.is_symlink():
                os.chmod(path, stat.S_IMODE(path.stat().st_mode) | 0o200)


def execute(
    receipt_id: str, home: Path | str | None = None, *, approved: bool = False
) -> list[str]:
    """Delete only paths named in the saved receipt that are still prunable."""
    if not approved:
        return []
    path = layout.copilot_home(home) / layout.PRUNE_RECEIPTS_DIRNAME / f"{receipt_id}.json"
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PruneError(f"unknown prune receipt {receipt_id}") from exc
    root = layout.releases_dir(home).resolve()
    protected = _protected(home)
    removed = []
    for text in receipt.get("paths", []):
        target = Path(text)
        if (
            target.parent.resolve() != root
            or target.is_symlink()
            or target.name in protected
            or not target.is_dir()
        ):
            continue
        _make_writable(target)
        shutil.rmtree(target)
        removed.append(str(target))
    receipt["approved"] = True
    receipt["removed"] = removed
    path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return removed
