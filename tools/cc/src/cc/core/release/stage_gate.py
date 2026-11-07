"""Stage acceptance at the immutable release activation boundary.

Old signed snapshots remain usable. New framework snapshots opt in through their
signed VERSION.json; omission of the caller's evidence cannot downgrade that policy.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .engine import layout, schema


def candidate_inputs_sha256(manifest: schema.Manifest) -> str:
    """Bind selected identities, independent of machine checkout locations."""
    keys = ("name", "tier", "kind", "version", "ref", "commit", "signer")
    rows = [{key: getattr(item, key) for key in keys}
            for item in sorted(manifest.components, key=lambda item: item.name)]
    return hashlib.sha256(json.dumps(rows, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def require_activation(release_root: Path, *, packet: Path | str | None = None,
                       packet_sha256: str | None = None) -> dict:
    manifest = schema.load(release_root)
    component = manifest.component(layout.COMPONENT_CLAUDE)
    root = release_root / component.path
    if root.is_symlink() or not root.resolve().is_relative_to(release_root.resolve()):
        raise ValueError("stage authority must be an immutable component inside the release")
    version_file = root / "VERSION.json"
    if not version_file.is_file():
        raise ValueError("framework VERSION.json is missing; cannot determine stage policy")
    version = json.loads(version_file.read_text(encoding="utf-8"))
    if not isinstance(version, dict):
        raise ValueError("framework VERSION.json must be an object")
    framework = version.get("framework")
    if not isinstance(framework, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", framework):
        raise ValueError("framework version is missing or malformed")
    recorded = component.version.removeprefix("v")
    if recorded != framework:
        raise ValueError("framework VERSION does not match the verified component version")
    governed = tuple(map(int, framework.split("."))) >= (5, 36, 0)
    policy = version.get("stagePolicyVersion")
    if policy is None and not governed:
        return {"approved": True, "assurance": "legacy-unenrolled"}
    if type(policy) is not int or policy != 1:
        raise ValueError("unsupported stage policy; upgrade stage-capable tooling")
    if component.kind != layout.KIND_SIGNED or not component.signer or not component.commit:
        raise ValueError("stage policy needs a verified signed framework component")
    if not packet or not packet_sha256:
        raise ValueError("activation requires --stage-packet and --stage-packet-sha256")
    from tc.services.cycle_stages import verify_packet
    result = verify_packet(file=Path(packet), sha256=packet_sha256, root=root,
                           phase="activate-ready", source_commit=component.commit,
                           candidate_inputs_sha256=candidate_inputs_sha256(manifest))
    if not isinstance(result, dict) or result.get("approved") is not True:
        raise ValueError("stage authority did not approve activation")
    return result
