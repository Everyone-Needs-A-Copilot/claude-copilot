"""Build an immutable release directory (ADR-001 decisions 1 and 8).

The directory is valid only once `release.json` exists; it is written last.
Any failure removes the partial directory and never touches `current`.
Company-tier and framework entries are materialised from signature-verified
tags; personal entries are symlinks to live checkouts; control-tower is a
version record. Verification, extraction and post-build steps are injectable.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import stat
import subprocess
import tarfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from . import layout, pointer, schema


class ReleaseBuildError(RuntimeError):
    pass


@dataclass(frozen=True)
class ComponentSource:
    """Where one release.json entry comes from."""

    name: str
    tier: str
    kind: str
    version: str = ""
    ref: str = ""
    source: str = ""  # repo/checkout path or URL, recorded verbatim
    subpath: str = ""
    allowed_signers: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class VerifiedTag:
    commit: str
    signer: str


Verifier = Callable[[ComponentSource], VerifiedTag]
Extractor = Callable[[ComponentSource, VerifiedTag, Path], None]
PostBuild = Callable[[Path, Sequence[schema.Component]], None]


def default_verifier(src: ComponentSource) -> VerifiedTag:
    """Verify a signed tag with the foundation trust policy; fail closed."""
    from cc.core.ecosystem.policy import verify_git_tree_release

    relative = src.subpath
    if not relative:
        listing = subprocess.run(
            ["git", "-C", src.source, "ls-tree", "-d", "--name-only", f"{src.ref}^{{commit}}"],
            capture_output=True, text=True, check=False,
        )
        names = listing.stdout.split()
        if not names:
            raise ReleaseBuildError(f"{src.name}: cannot inspect {src.ref}")
        relative = names[0]  # the tag signature covers the whole commit
    result = verify_git_tree_release(src.source, relative, src.allowed_signers, ref=src.ref)
    if result is None:
        raise ReleaseBuildError(f"{src.name}: signature verification failed for {src.ref}")
    return VerifiedTag(commit=result.release.commit, signer=result.signer)


def default_extractor(src: ComponentSource, tag: VerifiedTag, destination: Path) -> None:
    treeish = f"{tag.commit}:{src.subpath}" if src.subpath else tag.commit
    archive = subprocess.run(
        ["git", "-C", src.source, "archive", "--format=tar", treeish],
        capture_output=True, check=False,
    )
    if archive.returncode != 0:
        raise ReleaseBuildError(f"{src.name}: git archive failed")
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        try:
            tar.extractall(destination, filter="data")
        except TypeError:  # Python without extraction filters
            tar.extractall(destination)


def _release_id(created: datetime, suffix: str) -> str:
    return f"{created.strftime('%Y%m%dT%H%M%SZ')}-{suffix[:12].lower() or 'release'}"


def _lock_down(root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        for name in filenames:
            path = Path(dirpath, name)
            if not path.is_symlink():
                os.chmod(path, stat.S_IMODE(path.stat().st_mode) & ~0o222)
        os.chmod(dirpath, stat.S_IMODE(os.stat(dirpath).st_mode) & ~0o222)


def _remove(root: Path) -> None:
    if not root.exists() and not root.is_symlink():
        return
    for dirpath, _dirs, _files in os.walk(root):
        os.chmod(dirpath, 0o700)
    shutil.rmtree(root, ignore_errors=True)


def build_release(
    sources: Sequence[ComponentSource],
    home: Path | str | None = None,
    *,
    verifier: Verifier = default_verifier,
    extractor: Extractor = default_extractor,
    post_build: PostBuild | None = None,
    now: datetime | None = None,
) -> schema.Manifest:
    """Materialise every source into a new immutable release; return its manifest."""
    created = now or datetime.now(timezone.utc)
    names = [item.name for item in sources]
    missing = [n for n in layout.all_component_names() if n not in names]
    if missing or len(set(names)) != len(names):
        raise ReleaseBuildError("sources must list each component once; missing: " + ", ".join(missing))

    # Verify every signature before creating anything on disk.
    verified: dict[str, VerifiedTag] = {}
    for src in sources:
        if src.kind == layout.KIND_SIGNED:
            try:
                verified[src.name] = verifier(src)
            except ReleaseBuildError:
                raise
            except Exception as exc:  # verifier failures are build failures
                raise ReleaseBuildError(f"{src.name}: verification error: {exc}") from exc
        elif src.kind == layout.KIND_LIVE:
            if not Path(src.source).is_dir():
                raise ReleaseBuildError(f"{src.name}: live checkout {src.source} not found")
            if ".worktrees" in Path(src.source).resolve().parts:
                raise ReleaseBuildError(f"{src.name}: live link may not target a .worktrees path")
        elif src.kind != layout.KIND_RECORD:
            raise ReleaseBuildError(f"{src.name}: unknown kind {src.kind}")

    anchor = verified.get(layout.COMPONENT_CLAUDE)
    release_id = _release_id(created, anchor.commit if anchor else "release")
    target = layout.release_dir(release_id, home)
    if target.exists():
        raise ReleaseBuildError(f"release {release_id} already exists")
    target.mkdir(parents=True)

    components: list[schema.Component] = []
    try:
        for src in sources:
            path = "" if src.kind == layout.KIND_RECORD else src.name
            tag = verified.get(src.name)
            if src.kind == layout.KIND_SIGNED:
                extractor(src, tag, target / path)
            elif src.kind == layout.KIND_LIVE:
                (target / path).parent.mkdir(parents=True, exist_ok=True)
                os.symlink(Path(src.source).resolve(), target / path)
            components.append(
                schema.Component(
                    name=src.name, tier=src.tier, kind=src.kind, version=src.version,
                    ref=src.ref, commit=tag.commit if tag else "",
                    source=src.source, path=path, signer=tag.signer if tag else "",
                )
            )
        if post_build is not None:
            post_build(target, components)
        manifest = schema.Manifest(
            release_id=release_id,
            created=created.strftime("%Y-%m-%dT%H:%M:%SZ"),
            previous=pointer.current_release_id(home),
            components=tuple(components),
        )
        schema.validate(manifest.to_json())
        (target / layout.MANIFEST_NAME).write_text(
            json.dumps(manifest.to_json(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        _lock_down(target)
        return manifest
    except BaseException:
        _remove(target)
        raise


def sources_from_layers(
    layers: dict, framework: dict[str, dict], personal_live: bool = True
) -> list[ComponentSource]:
    """Map a parsed copilot.layers.yml plus framework pins to component sources.

    `framework` maps each framework component name to
    {"source": path-or-url, "ref": tag, "version": str, "allowed_signers": [...]}.
    The control-tower entry is a record (`ref`/`version` only).
    """
    out: list[ComponentSource] = []
    for name in layout.FRAMEWORK_COMPONENTS:
        pin = framework.get(name, {})
        kind = layout.KIND_RECORD if name == layout.COMPONENT_CONTROL_TOWER else layout.KIND_SIGNED
        out.append(ComponentSource(
            name=name, tier="framework", kind=kind, version=pin.get("version", ""),
            ref=pin.get("ref", ""), source=pin.get("source", ""),
            allowed_signers=tuple(pin.get("allowed_signers", ())),
        ))
    by_key = {}
    for row in layers.get("layers", []):
        role, product = row.get("role"), row.get("product")
        tier = layout.TIER_DEPARTMENT_ACCOUNTING if role == "department" and row.get("unit") == "accounting" else role
        by_key[(product, tier)] = row
    wanted = [(layout.KNOWLEDGE_PRODUCT, t) for t in layout.KNOWLEDGE_TIERS]
    wanted += [(p, t) for p in layout.OVERLAY_PRODUCTS for t in layout.OVERLAY_TIERS]
    for product, tier in wanted:
        row = by_key.get((product, tier))
        name = f"{product}/{tier}"
        if row is None:
            raise ReleaseBuildError(f"copilot.layers.yml has no {name} layer")
        src = row.get("source", {})
        ref = src.get("ref", "")
        if tier == layout.TIER_PERSONAL:
            out.append(ComponentSource(name, tier, layout.KIND_LIVE, ref=ref, source=src.get("path", "")))
        else:
            out.append(ComponentSource(
                name, tier, layout.KIND_SIGNED, version=ref, ref=ref,
                source=src.get("path", ""), subpath=src.get("subpath", ""),
                allowed_signers=tuple(row.get("policy", {}).get("allowed_signers", ())),
            ))
    return out


def build_cc_venv(release_directory: Path, _components: Sequence[schema.Component]) -> None:
    """Post-build step: create the cc/tc virtualenv in place via the component's install.sh.

    The venv is built at its final path (the release directory is not renamed),
    so shims resolve `current/claude-copilot/tools/cc/.venv/bin/python`.
    """
    script = release_directory / layout.COMPONENT_CLAUDE / "tools" / "cc" / "install.sh"
    scratch = release_directory / ".cc-shim-scratch"
    environment = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        subprocess.run(
            ["bash", str(script), "--shim-path", str(scratch), "--no-profile-update"],
            check=True, env=environment, timeout=600,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReleaseBuildError("cc virtualenv build failed") from exc
    finally:
        scratch.unlink(missing_ok=True)
