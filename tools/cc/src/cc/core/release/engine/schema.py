"""release.json schema 1: dataclasses plus a strict validator."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import layout

RELEASE_ID = re.compile(r"[0-9]{8}T[0-9]{6}Z-[0-9a-z]{1,40}")
_ENTRY_KEYS = {"name", "tier", "kind", "version", "ref", "commit", "source", "path", "signer"}


class ReleaseSchemaError(ValueError):
    """release.json is missing, malformed or incomplete."""


@dataclass(frozen=True)
class Component:
    """One release.json component entry.

    `path` is relative to the release directory (empty for record entries);
    `signer` is the verified SSH fingerprint, empty for live/record entries.
    """

    name: str
    tier: str
    kind: str
    version: str
    ref: str
    commit: str
    source: str
    path: str
    signer: str = ""


@dataclass(frozen=True)
class Manifest:
    release_id: str
    created: str
    previous: str | None
    components: tuple[Component, ...] = field(default_factory=tuple)

    def component(self, name: str) -> Component:
        for item in self.components:
            if item.name == name:
                return item
        raise KeyError(name)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": layout.SCHEMA_VERSION,
            "release": self.release_id,
            "created": self.created,
            "previous": self.previous,
            "components": [asdict(item) for item in self.components],
        }


def validate(data: Any) -> Manifest:
    if not isinstance(data, dict) or data.get("schema") != layout.SCHEMA_VERSION:
        raise ReleaseSchemaError("release.json schema must be 1")
    release_id = data.get("release")
    if not isinstance(release_id, str) or not RELEASE_ID.fullmatch(release_id):
        raise ReleaseSchemaError("release.json release id is invalid")
    created = data.get("created")
    previous = data.get("previous")
    if not isinstance(created, str) or not created:
        raise ReleaseSchemaError("release.json created is invalid")
    if previous is not None and not (
        isinstance(previous, str) and RELEASE_ID.fullmatch(previous)
    ):
        raise ReleaseSchemaError("release.json previous is invalid")
    rows = data.get("components")
    if not isinstance(rows, list):
        raise ReleaseSchemaError("release.json components must be a list")
    components: list[Component] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != _ENTRY_KEYS:
            raise ReleaseSchemaError("release.json component has wrong keys")
        if not all(isinstance(row[key], str) for key in _ENTRY_KEYS):
            raise ReleaseSchemaError("release.json component fields must be strings")
        if row["kind"] not in layout.KINDS:
            raise ReleaseSchemaError(f"unknown component kind {row['kind']!r}")
        path = row["path"]
        if path.startswith("/") or ".." in Path(path).parts:
            raise ReleaseSchemaError("component path must stay inside the release")
        if row["kind"] == layout.KIND_SIGNED and not (row["commit"] and row["signer"]):
            raise ReleaseSchemaError(f"{row['name']}: signed entry needs commit and signer")
        components.append(Component(**row))
    names = [item.name for item in components]
    if len(set(names)) != len(names):
        raise ReleaseSchemaError("duplicate component names")
    missing = [name for name in layout.all_component_names() if name not in names]
    if missing:
        raise ReleaseSchemaError("missing components: " + ", ".join(missing))
    return Manifest(release_id, created, previous, tuple(components))


def load(release_directory: Path) -> Manifest:
    path = release_directory / layout.MANIFEST_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReleaseSchemaError(f"cannot read {path}: {exc}") from exc
    manifest = validate(data)
    if manifest.release_id != release_directory.name:
        raise ReleaseSchemaError("release id does not match its directory")
    return manifest
