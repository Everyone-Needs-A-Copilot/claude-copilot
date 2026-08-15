"""Private canonical source authority for live evaluation content.

The public matrix and readiness commands never accept proof dictionaries.
This module derives one Claude projection from the installed manifest,
entitlement ledger, signed Git objects, physical lock, and the real TASK-296
Knowledge resolver. Personal and Codex projections remain unavailable until
their separate release boundaries exist.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import yaml

from cc.core.evaluation.identity import content_receipt_identity
from cc.core.evaluation.models import (
    ContentReceipt,
    LayerContentReceipt,
    LayerVariant,
    RuntimeName,
)
from cc.core.evaluation.schema import canonical_sha256

_AUTHORITY = object()
_ISSUED: weakref.WeakValueDictionary[object, "CanonicalContentProjection"] = (
    weakref.WeakValueDictionary()
)
_TIER_ORDER = ("foundation", "organization", "department", "personal")
_CODEX_SHARED_PLUGIN_BY_TIER = {
    "foundation": "codex-copilot",
    "organization": "codex-copilot-internal",
    "department": "codex-copilot-accounting",
}


class CanonicalContentUnavailable(ValueError):
    """The installed ecosystem cannot issue exact evaluation content."""

    def __init__(self, reason: str) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", reason):
            raise ValueError("Canonical content blocker is invalid.")
        self.reason = reason
        super().__init__(reason)


class _UniqueYamlLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise yaml.YAMLError("duplicate mapping key")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueYamlLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


class _RetainedFile:
    def __init__(self, path: Path, *, maximum_bytes: int) -> None:
        self.path = Path(os.path.abspath(path.expanduser()))
        self.fd = -1
        try:
            self.fd = os.open(
                self.path,
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
            )
            before = os.fstat(self.fd)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != os.geteuid()
                or before.st_size < 1
                or before.st_size > maximum_bytes
                or before.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            ):
                raise CanonicalContentUnavailable("canonical-config-untrusted")
            self._identity = self._stat_identity(before)
            self.content = self._read(before.st_size)
            self.validate()
        except CanonicalContentUnavailable:
            self.close()
            raise
        except OSError as exc:
            self.close()
            raise CanonicalContentUnavailable("canonical-config-unavailable") from exc

    @staticmethod
    def _stat_identity(value: os.stat_result) -> tuple[int, ...]:
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

    def _read(self, size: int) -> bytes:
        os.lseek(self.fd, 0, os.SEEK_SET)
        chunks = []
        remaining = size
        while remaining:
            chunk = os.read(self.fd, min(remaining, 65536))
            if not chunk:
                raise CanonicalContentUnavailable("canonical-config-changed")
            chunks.append(chunk)
            remaining -= len(chunk)
        os.lseek(self.fd, 0, os.SEEK_SET)
        return b"".join(chunks)

    def validate(self) -> None:
        try:
            before = os.fstat(self.fd)
            named = os.stat(self.path, follow_symlinks=False)
            content = self._read(before.st_size)
            after = os.fstat(self.fd)
        except OSError as exc:
            raise CanonicalContentUnavailable("canonical-config-changed") from exc
        if (
            self._stat_identity(before) != self._identity
            or self._stat_identity(after) != self._identity
            or self._stat_identity(named) != self._identity
            or content != self.content
        ):
            raise CanonicalContentUnavailable("canonical-config-changed")

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def __del__(self) -> None:
        if hasattr(self, "_seal"):
            self.close()


@dataclass(frozen=True)
class CanonicalContentProjection:
    content_receipt: ContentReceipt
    knowledge_payload: str
    knowledge_sources: tuple[Mapping[str, object], ...]
    runtime_projection: object
    evidence_sha256: str
    _manifest_capability: _RetainedFile = field(repr=False, compare=False)
    _lock_capability: _RetainedFile = field(repr=False, compare=False)
    _entitlement_bindings: tuple[object, ...] = field(repr=False, compare=False)
    _personal_snapshot_receipt: object | None = field(repr=False, compare=False)
    _seal: object
    _authority: object

    def __post_init__(self) -> None:
        if self._authority is not _AUTHORITY:
            raise ValueError("Canonical content projection is invalid.")

    def close(self) -> None:
        if _ISSUED.get(self._seal) is not self:
            return
        _ISSUED.pop(self._seal, None)
        self._manifest_capability.close()
        self._lock_capability.close()
        close_personal = getattr(self._personal_snapshot_receipt, "close", None)
        if callable(close_personal):
            close_personal()

    def run_authorized(self, action):
        """Hold exact entitlement leases and retained config across runtime use."""

        from cc.core.ecosystem import entitlement

        if not verify_canonical_content_projection(self):
            raise CanonicalContentUnavailable("canonical-config-changed")

        def guarded():
            if not verify_canonical_content_projection(self):
                raise CanonicalContentUnavailable("canonical-config-changed")
            try:
                result = action()
            except BaseException as exc:
                if not verify_canonical_content_projection(self):
                    raise CanonicalContentUnavailable(
                        "canonical-config-changed"
                    ) from exc
                raise
            if not verify_canonical_content_projection(self):
                raise CanonicalContentUnavailable("canonical-config-changed")
            return result

        try:
            valid, result = entitlement.run_under_binding_leases(
                self._entitlement_bindings,
                guarded,
            )
        except BaseException as exc:
            if not verify_canonical_content_projection(self):
                raise CanonicalContentUnavailable("canonical-config-changed") from exc
            lease_valid, _unused = entitlement.run_under_binding_leases(
                self._entitlement_bindings,
                lambda: None,
            )
            if not lease_valid:
                raise CanonicalContentUnavailable("entitlement-changed") from exc
            raise
        if not valid:
            raise CanonicalContentUnavailable("entitlement-changed")
        return result

    def __del__(self) -> None:
        self.close()


@dataclass(frozen=True)
class CanonicalCodexPluginSource:
    """One exact tier-owned plugin or activated pack from a signed release."""

    layer: str
    role: str
    repository: str
    repository_root: Path
    relative_path: str
    plugin_name: str
    source_kind: str
    adapter_version: str
    activation_sha256: str | None
    ref: str
    tree: str
    signer: str
    release_tag: str
    release_commit: str
    release_tree: str
    snapshot: object = field(repr=False, compare=False)


@dataclass(frozen=True)
class CanonicalCodexRuntimeProjection:
    """Exact additive plugin set plus the nearest specialist contribution."""

    matrix_sha256: str
    cell_plan_sha256: str
    plugin_sources: tuple[CanonicalCodexPluginSource, ...]
    content: str
    source_receipt: Mapping[str, str]
    projection_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.source_receipt, Mapping) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in self.source_receipt.items()
        ):
            raise ValueError("Canonical Codex source receipt is invalid.")
        object.__setattr__(
            self,
            "source_receipt",
            MappingProxyType(dict(self.source_receipt)),
        )
        expected = canonical_sha256(_codex_runtime_projection_document(self))
        if self.projection_sha256 != expected:
            raise ValueError("Canonical Codex runtime projection is invalid.")


def _codex_runtime_projection_document(
    value: CanonicalCodexRuntimeProjection,
) -> dict[str, object]:
    return {
        "schema_version": "evaluation-codex-runtime-projection-v1",
        "matrix_sha256": value.matrix_sha256,
        "cell_plan_sha256": value.cell_plan_sha256,
        "plugins": [
            {
                "layer": item.layer,
                "tier": item.role,
                "repository": item.repository,
                "relative_path": item.relative_path,
                "plugin_name": item.plugin_name,
                "source_kind": item.source_kind,
                "adapter_version": item.adapter_version,
                "activation_sha256": item.activation_sha256,
                "ref": _canonical_ref(item.ref),
                "tree": item.tree,
                "signer": item.signer,
                "release_tag": item.release_tag,
                "release_commit": item.release_commit,
                "release_tree": item.release_tree,
            }
            for item in value.plugin_sources
        ],
        "selected_source": dict(value.source_receipt),
        "selected_content_sha256": hashlib.sha256(
            value.content.encode("utf-8")
        ).hexdigest(),
    }


def _runtime_projection_identity(value: object) -> str:
    if isinstance(value, CanonicalCodexRuntimeProjection):
        identity = canonical_sha256(_codex_runtime_projection_document(value))
        if value.projection_sha256 != identity:
            raise ValueError("Canonical Codex runtime projection changed.")
        return identity
    return canonical_sha256(dict(value.source_receipt))


def verify_canonical_content_projection(value: object) -> bool:
    if not isinstance(value, CanonicalContentProjection):
        return False
    issued = _ISSUED.get(value._seal)
    try:
        value._manifest_capability.validate()
        value._lock_capability.validate()
        if (
            value._personal_snapshot_receipt is not None
            and not getattr(
                value._personal_snapshot_receipt,
                "validate",
                lambda: False,
            )()
        ):
            return False
        return issued is value and value.evidence_sha256 == canonical_sha256(
            {
                "schema_version": "evaluation-content-authority-v1",
                "content_receipt_sha256": content_receipt_identity(
                    value.content_receipt
                ),
                "knowledge_payload_sha256": hashlib.sha256(
                    value.knowledge_payload.encode()
                ).hexdigest(),
                "knowledge_sources_sha256": canonical_sha256(
                    [dict(item) for item in value.knowledge_sources]
                ),
                "runtime_projection_sha256": _runtime_projection_identity(
                    value.runtime_projection
                ),
                "personal_materialization_sha256": (
                    None
                    if value._personal_snapshot_receipt is None
                    else value._personal_snapshot_receipt.materialization_sha256
                ),
            }
        )
    except (OSError, ValueError):
        return False


def _variant_tiers(variant: LayerVariant) -> tuple[str, ...]:
    return _TIER_ORDER[
        : _TIER_ORDER.index(
            {
                LayerVariant.FOUNDATION: "foundation",
                LayerVariant.ORGANIZATION: "organization",
                LayerVariant.DEPARTMENT: "department",
                LayerVariant.PERSONAL: "personal",
            }[variant]
        )
        + 1
    ]


def _canonical_ref(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise CanonicalContentUnavailable("signed-source-invalid")
    if re.fullmatch(r"v[0-9]+(?:\.[0-9]+){1,3}(?:[-+][A-Za-z0-9.-]+)?", value):
        return f"refs/tags/{value}"
    if value.startswith("refs/tags/"):
        return value
    raise CanonicalContentUnavailable("signed-source-invalid")


def _origin(root: Path) -> str:
    from cc.core.ecosystem.entitlement import github_repo_slug

    try:
        result = subprocess.run(
            ["git", "-C", str(root), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=8.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CanonicalContentUnavailable("signed-source-invalid") from exc
    slug = github_repo_slug(result.stdout.strip()) if result.returncode == 0 else None
    if slug is None:
        raise CanonicalContentUnavailable("signed-source-invalid")
    return slug


def _manifest_layers(content: bytes) -> list[dict[str, Any]]:
    from cc.core.ecosystem.manifest import load_layers, validate_layers

    try:
        raw = yaml.load(content.decode("utf-8"), Loader=_UniqueYamlLoader)
        if not isinstance(raw, dict) or set(raw) - {"version", "org", "layers"}:
            raise ValueError
        layers = raw.get("layers")
        if not isinstance(layers, list):
            raise ValueError
        return validate_layers(load_layers(layers))
    except (UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
        raise CanonicalContentUnavailable("canonical-manifest-invalid") from exc


def _lock_document(content: bytes) -> dict[str, Any]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(content, object_pairs_hook=unique)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise CanonicalContentUnavailable("canonical-lock-invalid") from exc
    if not isinstance(value, dict):
        raise CanonicalContentUnavailable("canonical-lock-invalid")
    return value


def _release_for_agent(layer: Mapping[str, Any], specialist: str):
    from cc.core.ecosystem.entitlement import github_repo_slug
    from cc.core.ecosystem.policy import verify_git_tree_release

    source = layer.get("source")
    policy = layer.get("policy")
    if not isinstance(source, Mapping) or not isinstance(policy, Mapping):
        raise CanonicalContentUnavailable("signed-source-invalid")
    path = source.get("path")
    repo = github_repo_slug(source.get("repo"))
    signers = policy.get("allowed_signers")
    if (
        not isinstance(path, str)
        or repo is None
        or not isinstance(signers, list)
        or not signers
    ):
        raise CanonicalContentUnavailable("signed-source-invalid")
    root = Path(path).expanduser()
    if _origin(root).casefold() != repo.casefold():
        raise CanonicalContentUnavailable("signed-source-invalid")
    prefix = str(source.get("subpath") or "").strip("/")
    parent = f"{prefix}/agents" if prefix else "agents"
    provenance = verify_git_tree_release(
        root,
        parent,
        signers,
        ref=str(source.get("ref") or ""),
    )
    if provenance is None:
        raise CanonicalContentUnavailable("signed-source-unverified")
    contribution = f"{parent}/{specialist}.md"
    try:
        content = provenance.release.read_blob(contribution)
    except ValueError:
        content = None
    return repo, provenance, contribution, content


def _lock_layer(
    lock: Mapping[str, Any],
    layer: Mapping[str, Any],
    specialist: str,
    content: bytes | None,
    *,
    selected: bool,
) -> Mapping[str, Any]:
    layer_id = str(layer["id"])
    row = lock.get(layer_id)
    if not isinstance(row, Mapping):
        raise CanonicalContentUnavailable("materialized-lock-missing")
    meta = row.get("_meta")
    if not isinstance(meta, Mapping) or (
        meta.get("product") != layer.get("product")
        or meta.get("role") != layer.get("role")
        or meta.get("tier") != layer.get("role")
    ):
        raise CanonicalContentUnavailable("materialized-lock-mismatch")
    agents = row.get("agents", {})
    if not isinstance(agents, Mapping):
        raise CanonicalContentUnavailable("materialized-lock-mismatch")
    recorded = agents.get(specialist)
    expected = (
        hashlib.sha256(content).hexdigest()
        if selected and content is not None
        else None
    )
    if recorded != expected:
        raise CanonicalContentUnavailable("materialized-lock-mismatch")
    return row


def _knowledge_rows(
    *,
    tiers: tuple[str, ...],
    specialist: str,
    runtime: RuntimeName,
    layers_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
    sources: tuple[Mapping[str, object], ...],
    manifest_sha256: str,
    lock_sha256: str,
    lock: Mapping[str, Any],
    resolved_sources: tuple[object, ...],
) -> list[LayerContentReceipt]:
    from cc.core.ecosystem.entitlement import github_repo_slug

    resolved = {
        source.role: source for source in resolved_sources if source.role in tiers
    }
    if set(resolved) != set(tiers):
        raise CanonicalContentUnavailable("signed-knowledge-unavailable")
    resolved_by_layer = {source.layer: source for source in resolved.values()}
    if len(resolved_by_layer) != len(resolved):
        raise CanonicalContentUnavailable("signed-knowledge-mismatch")
    seen_contributions: set[tuple[str, str]] = set()
    for item in sources:
        layer_id = item.get("layer")
        contribution = item.get("contribution")
        source = resolved_by_layer.get(layer_id)
        if (
            source is None
            or not isinstance(contribution, str)
            or (str(layer_id), contribution) in seen_contributions
            or item.get("runtime") != runtime.value
            or item.get("adapter_version") != "knowledge-contribution-v1"
            or str(item.get("repository", "")).casefold()
            != source.repository.casefold()
            or _canonical_ref(item.get("ref")) != _canonical_ref(source.ref)
            or item.get("tree") != source.release.tree
            or item.get("signer") != source.signer
        ):
            raise CanonicalContentUnavailable("signed-knowledge-mismatch")
        seen_contributions.add((str(layer_id), contribution))
    rows = []
    for tier in tiers:
        layer = layers_by_key[("knowledge", tier)]
        source = resolved[tier]
        layer_source = layer.get("source")
        configured_repo = (
            github_repo_slug(layer_source.get("repo"))
            if isinstance(layer_source, Mapping)
            else None
        )
        if (
            source.layer != layer.get("id")
            or configured_repo is None
            or source.repository.casefold() != configured_repo.casefold()
            or source.repository.casefold()
            != _origin(Path(source.repository_root)).casefold()
            or _canonical_ref(source.ref) != _canonical_ref(layer_source["ref"])
        ):
            raise CanonicalContentUnavailable("signed-knowledge-mismatch")
        grouped = sorted(
            (
                str(item["contribution"]),
                str(item["content_sha256"]),
            )
            for item in sources
            if item.get("layer") == source.layer
        )
        try:
            manifest = json.loads(source.release.read_blob("knowledge-manifest.json"))
        except (ValueError, json.JSONDecodeError) as exc:
            raise CanonicalContentUnavailable("signed-knowledge-invalid") from exc
        entries = manifest.get("extensions") if isinstance(manifest, Mapping) else None
        entry = next(
            (
                item
                for item in entries or ()
                if isinstance(item, Mapping) and item.get("agent") == specialist
            ),
            None,
        )
        primary = entry.get("file") if isinstance(entry, Mapping) else None
        primary_content = None
        if isinstance(primary, str):
            try:
                primary_content = source.release.read_blob(primary)
            except ValueError as exc:
                raise CanonicalContentUnavailable("signed-knowledge-invalid") from exc
        for contribution, digest in grouped:
            try:
                raw = source.release.read_blob(contribution)
            except ValueError as exc:
                raise CanonicalContentUnavailable("signed-knowledge-mismatch") from exc
            if hashlib.sha256(raw).hexdigest() != digest:
                raise CanonicalContentUnavailable("signed-knowledge-mismatch")
        action = (
            "accumulated"
            if grouped
            else "shadowed" if primary_content is not None else "authenticated-absence"
        )
        if action == "authenticated-absence":
            contributions: tuple[str, ...] = ()
            digests: tuple[str, ...] = ()
        elif grouped:
            contributions = tuple(item[0] for item in grouped)
            digests = tuple(item[1] for item in grouped)
        else:
            assert isinstance(primary, str) and primary_content is not None
            contributions = (primary,)
            digests = (hashlib.sha256(primary_content).hexdigest(),)
        lock_row_sha256 = _knowledge_lock_row_sha256(layer, source, lock)
        return_ref = _canonical_ref(source.ref)
        rows.append(
            LayerContentReceipt(
                product="knowledge",
                tier=tier,
                source_layer_identifier=source.layer,
                source_runtime=runtime.value,
                source_adapter_version="knowledge-contribution-v1",
                repository_identifier=source.repository,
                immutable_ref=return_ref,
                tree_sha256=canonical_sha256(
                    {
                        "tag": source.release.tag,
                        "commit": source.release.commit,
                        "tree": source.release.tree,
                    }
                ),
                signer_identity=source.signer,
                policy_sha256=canonical_sha256(layer.get("policy") or {}),
                manifest_sha256=manifest_sha256,
                lock_sha256=canonical_sha256(
                    {
                        "lockfile_sha256": lock_sha256,
                        "layer_row_sha256": lock_row_sha256,
                    }
                ),
                contribution_ids=contributions,
                content_digests=digests,
                resolution_action=action,
                materialized_destinations=tuple(
                    f"knowledge/{tier}/{index + 1}"
                    for index, _item in enumerate(contributions)
                ),
                source_tree=source.release.tree,
            )
        )
    return rows


def _knowledge_lock_row_sha256(
    layer: Mapping[str, Any],
    source: object,
    lock: Mapping[str, Any],
) -> str:
    """Bind one complete Knowledge lock row to its signed projection receipt."""

    from cc.core.ecosystem import entitlement
    from cc.core.ecosystem.knowledge_skill_source import (
        KnowledgeSkillSourceError,
        inspect_protected_knowledge_lock_projection,
    )

    layer_id = str(layer.get("id") or "")
    row = lock.get(layer_id)
    meta = row.get("_meta") if isinstance(row, Mapping) else None
    if not isinstance(meta, Mapping) or (
        set(meta) != {"product", "role", "tier"}
        or meta.get("product") != "knowledge"
        or meta.get("role") != layer.get("role")
        or meta.get("tier") != layer.get("role")
    ):
        raise CanonicalContentUnavailable("materialized-lock-missing")
    projection = None
    if entitlement.is_protected_layer(layer):
        try:
            projection = inspect_protected_knowledge_lock_projection(dict(layer))
        except (KnowledgeSkillSourceError, OSError, TypeError, ValueError) as exc:
            raise CanonicalContentUnavailable("materialized-lock-missing") from exc
    projection_document = None
    if projection is None:
        if set(row) != {"_meta"}:
            raise CanonicalContentUnavailable("materialized-lock-mismatch")
    else:
        plugins = row.get("plugins")
        if (
            set(row) != {"_meta", "plugins"}
            or not isinstance(plugins, Mapping)
            or set(plugins) != {"codex-copilot"}
            or plugins.get("codex-copilot") != projection.content_sha256
            or projection.layer != layer_id
            or projection.repository.casefold() != source.repository.casefold()
            or _canonical_ref(projection.ref) != _canonical_ref(source.ref)
            or projection.tree != source.tree
            or projection.signer != source.signer
            or projection.release_tree != source.release.tree
        ):
            raise CanonicalContentUnavailable("materialized-lock-mismatch")
        projection_document = {
            "layer": projection.layer,
            "repository": projection.repository,
            "ref": _canonical_ref(projection.ref),
            "tree": projection.tree,
            "signer": projection.signer,
            "binding": projection.binding,
            "item_tree": projection.item_tree,
            "release_tree": projection.release_tree,
            "content_sha256": projection.content_sha256,
            "dimension": projection.dimension,
            "item": projection.item,
        }
    return canonical_sha256(
        {
            "schema_version": "evaluation-knowledge-lock-row-v1",
            "layer": layer_id,
            "row": dict(row),
            "protected_projection": projection_document,
        }
    )


def _unique_json_object(content: bytes, *, reason: str) -> dict[str, Any]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(content, object_pairs_hook=unique)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise CanonicalContentUnavailable(reason) from exc
    if not isinstance(value, dict):
        raise CanonicalContentUnavailable(reason)
    return value


def _codex_snapshot_digest(snapshot: object) -> str:
    """Reproduce the lock materializer's directory digest from Git bytes."""

    digest = hashlib.sha256()
    try:
        files = sorted(snapshot.files, key=lambda item: item.path)
    except (AttributeError, TypeError) as exc:
        raise CanonicalContentUnavailable("signed-codex-source-invalid") from exc
    if not files:
        raise CanonicalContentUnavailable("signed-codex-source-invalid")
    for item in files:
        digest.update(str(item.path).encode("utf-8"))
        digest.update(item.content)
    return digest.hexdigest()


def _canonical_codex_cell_plan(
    *, case_id: str | None, variant: LayerVariant, specialist: str
) -> tuple[str, str]:
    """Bind one source projection to the exact packaged Codex matrix cell."""

    from cc.core.evaluation.fixtures import _PREREGISTERED_PACKETS
    from cc.core.evaluation.matrix import (
        fixture_packet_document,
        route_contract_document,
    )
    from cc.evaluation_fixtures import PACKAGED_MATRIX_SHA256

    try:
        route = route_contract_document(str(case_id))
        packet = fixture_packet_document(str(case_id))
        preregistered = _PREREGISTERED_PACKETS[(str(case_id), 1)]
        variants = tuple(preregistered[1])
        runtimes = tuple(preregistered[2])
        variant_index = variants.index(variant.value)
    except (KeyError, TypeError, ValueError) as exc:
        raise CanonicalContentUnavailable("canonical-cell-plan-invalid") from exc
    if route.get("specialists") != [specialist] or "codex" not in runtimes:
        raise CanonicalContentUnavailable("canonical-cell-plan-invalid")
    document = {
        "case_id": case_id,
        "revision": 1,
        "variant": variant.value,
        "runtime": RuntimeName.CODEX.value,
        "role": "control" if variant_index == 0 else "layered",
        "fixture_packet_sha256": packet["fixture_packet_sha256"],
        "route_classification": route["classification"],
        "expected_specialist": specialist,
        "route_contract_sha256": route["route_contract_sha256"],
    }
    return PACKAGED_MATRIX_SHA256, canonical_sha256(document)


def _codex_source_from_provenance(
    *,
    layer: Mapping[str, Any],
    repository: str,
    plugin_name: str,
    relative_path: str,
    source_kind: str,
    adapter_version: str,
    activation_sha256: str | None = None,
) -> CanonicalCodexPluginSource:
    from cc.core.ecosystem.policy import (
        read_git_tree_snapshot,
        verify_git_item_provenance,
    )

    source = layer.get("source")
    policy = layer.get("policy")
    if not isinstance(source, Mapping) or not isinstance(policy, Mapping):
        raise CanonicalContentUnavailable("signed-codex-source-invalid")
    root_value = source.get("path")
    signers = policy.get("allowed_signers")
    if not isinstance(root_value, str) or not isinstance(signers, list) or not signers:
        raise CanonicalContentUnavailable("signed-codex-source-invalid")
    provenance = verify_git_item_provenance(
        Path(root_value).expanduser(),
        relative_path,
        signers,
        ref=str(source.get("ref") or ""),
    )
    if provenance is None:
        raise CanonicalContentUnavailable("signed-codex-source-unverified")
    expected_root = Path(os.path.abspath(Path(root_value).expanduser()))
    try:
        exact_provenance = bool(
            Path(provenance.repository_root) == expected_root
            and provenance.relative_path == relative_path
            and _canonical_ref(provenance.ref) == _canonical_ref(source.get("ref"))
            and provenance.release.ref == provenance.ref
            and provenance.release.repository_root == provenance.repository_root
            and provenance.release.signer == provenance.signer
            and _origin(expected_root).casefold() == repository.casefold()
        )
    except (AttributeError, TypeError, ValueError):
        exact_provenance = False
    if not exact_provenance:
        raise CanonicalContentUnavailable("signed-codex-source-mismatch")
    snapshot = read_git_tree_snapshot(provenance.repository_root, provenance.tree)
    if snapshot is None or snapshot.tree != provenance.tree:
        raise CanonicalContentUnavailable("signed-codex-source-invalid")
    return CanonicalCodexPluginSource(
        layer=str(layer["id"]),
        role=str(layer["role"]),
        repository=repository,
        repository_root=Path(provenance.repository_root),
        relative_path=provenance.relative_path,
        plugin_name=plugin_name,
        source_kind=source_kind,
        adapter_version=adapter_version,
        activation_sha256=activation_sha256,
        ref=_canonical_ref(provenance.ref),
        tree=provenance.tree,
        signer=provenance.signer,
        release_tag=provenance.release.tag,
        release_commit=provenance.release.commit,
        release_tree=provenance.release.tree,
        snapshot=snapshot,
    )


def _codex_plugin_inventory(
    layer: Mapping[str, Any],
) -> tuple[CanonicalCodexPluginSource, dict[str, str]]:
    """Verify every signed plugin, then return the tier-owned contribution."""

    from cc.core.ecosystem.entitlement import github_repo_slug
    from cc.core.ecosystem.policy import (
        read_git_tree_snapshot,
        verify_git_tree_release,
    )

    tier = str(layer.get("role") or "")
    expected_plugin = _CODEX_SHARED_PLUGIN_BY_TIER.get(tier)
    source = layer.get("source")
    policy = layer.get("policy")
    if (
        expected_plugin is None
        or not isinstance(source, Mapping)
        or not isinstance(policy, Mapping)
    ):
        raise CanonicalContentUnavailable("signed-codex-source-invalid")
    root_value = source.get("path")
    configured_repository = github_repo_slug(source.get("repo"))
    signers = policy.get("allowed_signers")
    if (
        not isinstance(root_value, str)
        or configured_repository is None
        or not isinstance(signers, list)
        or not signers
        or _origin(Path(root_value).expanduser()).casefold()
        != configured_repository.casefold()
    ):
        raise CanonicalContentUnavailable("signed-codex-source-invalid")
    plugins = verify_git_tree_release(
        Path(root_value).expanduser(),
        "plugins",
        signers,
        ref=str(source.get("ref") or ""),
    )
    if plugins is None:
        raise CanonicalContentUnavailable("signed-codex-source-unverified")
    plugins_snapshot = read_git_tree_snapshot(
        plugins.repository_root,
        plugins.tree,
    )
    if plugins_snapshot is None:
        raise CanonicalContentUnavailable("signed-codex-source-invalid")
    plugin_names = {
        Path(item.path).parts[0]
        for item in plugins_snapshot.files
        if len(Path(item.path).parts) > 1
    }
    if (
        not plugin_names
        or expected_plugin not in plugin_names
        or any(not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", item) for item in plugin_names)
    ):
        raise CanonicalContentUnavailable("signed-codex-source-invalid")

    inventory: dict[str, str] = {}
    owned = None
    for plugin_name in sorted(plugin_names):
        plugin_source = _codex_source_from_provenance(
            layer=layer,
            repository=configured_repository,
            plugin_name=plugin_name,
            relative_path=f"plugins/{plugin_name}",
            source_kind="plugin",
            adapter_version="codex-plugin-v1",
        )
        files = {item.path: item for item in plugin_source.snapshot.files}
        manifest_file = files.get(".codex-plugin/plugin.json")
        if manifest_file is None:
            raise CanonicalContentUnavailable("signed-codex-source-invalid")
        manifest = _unique_json_object(
            manifest_file.content,
            reason="signed-codex-source-invalid",
        )
        manifest_repository = github_repo_slug(manifest.get("repository"))
        if (
            manifest.get("name") != plugin_name
            or manifest.get("skills") != "./skills/"
            or manifest_repository is None
        ):
            raise CanonicalContentUnavailable("signed-codex-source-invalid")
        inventory[plugin_name] = _codex_snapshot_digest(plugin_source.snapshot)
        if plugin_name == expected_plugin:
            if manifest_repository.casefold() != configured_repository.casefold():
                raise CanonicalContentUnavailable("signed-codex-source-mismatch")
            owned = plugin_source
    if owned is None:
        raise CanonicalContentUnavailable("signed-codex-source-invalid")
    return owned, inventory


def _codex_pack_source(
    *,
    foundation_layer: Mapping[str, Any],
    foundation_plugin: CanonicalCodexPluginSource,
    specialist: str,
    variant: LayerVariant,
    case_id: str | None,
) -> CanonicalCodexPluginSource | None:
    """Resolve an optional foundation specialist through its signed pack catalog."""

    from cc.core.evaluation.matrix import route_contract_document
    from cc.evaluation_fixtures import PACKAGED_MATRIX_SHA256

    release = next(
        (
            item
            for item in foundation_plugin.snapshot.files
            if item.path == "agent-catalog.json"
        ),
        None,
    )
    if release is None:
        raise CanonicalContentUnavailable("signed-codex-source-invalid")
    catalog = _unique_json_object(
        release.content,
        reason="signed-codex-source-invalid",
    )
    optional = catalog.get("optionalAgents")
    matches = [
        item
        for item in optional or ()
        if isinstance(item, Mapping) and item.get("id") == specialist
    ]
    if not matches:
        return None
    if len(matches) != 1:
        raise CanonicalContentUnavailable("signed-codex-pack-activation-invalid")
    pack_name = matches[0].get("pack")
    if not isinstance(pack_name, str) or not re.fullmatch(
        r"[a-z][a-z0-9-]{0,63}", pack_name
    ):
        raise CanonicalContentUnavailable("signed-codex-pack-activation-invalid")
    try:
        route = route_contract_document(str(case_id))
    except (KeyError, TypeError, ValueError) as exc:
        raise CanonicalContentUnavailable(
            "signed-codex-pack-activation-invalid"
        ) from exc
    if route.get("specialists") != [specialist]:
        raise CanonicalContentUnavailable("signed-codex-pack-activation-invalid")
    activation_document = {
        "schema_version": "task285-codex-pack-activation-v1",
        "matrix_sha256": PACKAGED_MATRIX_SHA256,
        "case_id": case_id,
        "variant": variant.value,
        "specialist": specialist,
        "route_contract_sha256": route["route_contract_sha256"],
        "pack": pack_name,
        "project_scope": "private-evaluation-workspace",
        "source_layer": foundation_plugin.layer,
        "source_ref": _canonical_ref(foundation_plugin.ref),
        "source_release_tree": foundation_plugin.release_tree,
    }
    activation_sha256 = canonical_sha256(activation_document)
    pack = _codex_source_from_provenance(
        layer=foundation_layer,
        repository=foundation_plugin.repository,
        plugin_name=pack_name,
        relative_path=f"packs/{pack_name}",
        source_kind="activated-pack",
        adapter_version="codex-pack-v1",
        activation_sha256=activation_sha256,
    )
    files = {item.path: item for item in pack.snapshot.files}
    manifest_file = files.get("pack.json")
    skill = files.get(f"skills/{specialist}/SKILL.md")
    if manifest_file is None or skill is None:
        raise CanonicalContentUnavailable("signed-codex-pack-activation-invalid")
    manifest = _unique_json_object(
        manifest_file.content,
        reason="signed-codex-pack-activation-invalid",
    )
    activation = manifest.get("activation")
    if (
        manifest.get("name") != pack_name
        or specialist not in (manifest.get("specialists") or ())
        or not isinstance(activation, Mapping)
        or activation.get("script") != "scripts/activate-pack.py"
        or activation.get("skillDirectory") != f"packs/{pack_name}/skills"
    ):
        raise CanonicalContentUnavailable("signed-codex-pack-activation-invalid")
    return pack


def _codex_global_lock_identity(
    *,
    layers: Sequence[Mapping[str, Any]],
    inventories: Mapping[str, Mapping[str, str]],
    lock: Mapping[str, Any],
) -> str:
    """Bind the physical lock's exact global nearest-wins plugin result."""

    winner_by_plugin: dict[str, tuple[int, str, str]] = {}
    for layer in layers:
        layer_id = str(layer["id"])
        rank = layer.get("rank")
        if not isinstance(rank, int):
            raise CanonicalContentUnavailable("canonical-layer-set-invalid")
        for plugin, digest in inventories[layer_id].items():
            candidate = (rank, layer_id, digest)
            current = winner_by_plugin.get(plugin)
            if current is None or candidate < current:
                winner_by_plugin[plugin] = candidate
    expected_by_layer: dict[str, dict[str, str]] = {
        str(layer["id"]): {} for layer in layers
    }
    for plugin, (_rank, layer_id, digest) in winner_by_plugin.items():
        expected_by_layer[layer_id][plugin] = digest

    rows = []
    for layer in layers:
        layer_id = str(layer["id"])
        tier = str(layer["role"])
        row = lock.get(layer_id)
        meta = row.get("_meta") if isinstance(row, Mapping) else None
        expected_plugins = expected_by_layer[layer_id]
        if not isinstance(meta, Mapping) or dict(meta) != {
            "product": "codex",
            "role": tier,
            "tier": tier,
        }:
            raise CanonicalContentUnavailable("materialized-lock-missing")
        if expected_plugins:
            if (
                set(row) != {"_meta", "plugins"}
                or not isinstance(row.get("plugins"), Mapping)
                or dict(row["plugins"]) != dict(sorted(expected_plugins.items()))
            ):
                raise CanonicalContentUnavailable("materialized-lock-mismatch")
        elif set(row) != {"_meta"}:
            raise CanonicalContentUnavailable("materialized-lock-mismatch")
        rows.append({"layer": layer_id, "row": dict(row)})
    return canonical_sha256(
        {
            "schema_version": "evaluation-codex-global-lock-v1",
            "winners": [
                {
                    "plugin": plugin,
                    "rank": value[0],
                    "layer": value[1],
                    "content_sha256": value[2],
                }
                for plugin, value in sorted(winner_by_plugin.items())
            ],
            "rows": rows,
        }
    )


def issue_canonical_claude_content(
    *,
    variant: LayerVariant,
    specialist: str,
    case_id: str | None = None,
    personal_snapshot_receipt: object | None = None,
    manifest_path: Path | None = None,
    lock_path: Path | None = None,
) -> CanonicalContentProjection:
    """Issue exact shared Claude content or fail before a runtime call."""

    from cc.core import config
    from cc.core.ecosystem import entitlement
    from cc.core.ecosystem.knowledge_skill_source import resolve_knowledge_skill_sources
    from cc.core.ecosystem.lockfile import default_lockfile_path
    from cc.core.evaluation.journey_runtime import resolve_specialist_knowledge
    from cc.core.evaluation.live_runtime import resolve_claude_agent_projection

    personal = variant is LayerVariant.PERSONAL
    uses_personal_snapshot = False
    personal_source = None
    personal_receipt_document = None
    if personal:
        from cc.core.evaluation.matrix import route_contract_document
        from cc.evaluation_fixtures.personal_snapshot import (
            PersonalSnapshotReceipt,
            personal_snapshot_contribution,
            personal_snapshot_receipt_document,
            verify_personal_snapshot_receipt,
        )

        try:
            expected_specialist = route_contract_document(str(case_id))["specialists"][
                0
            ]
        except (KeyError, TypeError, ValueError):
            raise CanonicalContentUnavailable("personal-snapshot-unavailable")
        if specialist != expected_specialist:
            raise CanonicalContentUnavailable("personal-snapshot-unavailable")
        uses_personal_snapshot = case_id == "eval-07" and specialist == "doc"
        if uses_personal_snapshot:
            if not isinstance(
                personal_snapshot_receipt, PersonalSnapshotReceipt
            ) or not verify_personal_snapshot_receipt(personal_snapshot_receipt):
                raise CanonicalContentUnavailable("personal-snapshot-unavailable")
            _personal_content, personal_source = personal_snapshot_contribution(
                runtime=RuntimeName.CLAUDE.value
            )
            personal_receipt_document = personal_snapshot_receipt_document(
                personal_snapshot_receipt
            )
        elif personal_snapshot_receipt is not None:
            raise CanonicalContentUnavailable("personal-snapshot-unexpected")
    elif personal_snapshot_receipt is not None:
        raise CanonicalContentUnavailable("personal-snapshot-unexpected")
    tiers = _variant_tiers(variant)
    signed_tiers = tiers[:-1] if personal else tiers
    selected_manifest = manifest_path or Path(
        str(config.resolve_key("layers.manifest"))
    )
    selected_lock = lock_path or default_lockfile_path()
    retained_manifest = _RetainedFile(selected_manifest, maximum_bytes=1_000_000)
    try:
        retained_lock = _RetainedFile(selected_lock, maximum_bytes=4_000_000)
    except Exception:
        retained_manifest.close()
        raise
    transferred = False
    try:
        layers = _manifest_layers(retained_manifest.content)
        lock = _lock_document(retained_lock.content)
        required = [
            layer
            for layer in layers
            if layer.get("product") in {"knowledge", "claude"}
            and layer.get("role") in signed_tiers
        ]
        by_key = {
            (str(layer["product"]), str(layer["role"])): layer for layer in required
        }
        expected_keys = {
            (product, tier)
            for product in ("knowledge", "claude")
            for tier in signed_tiers
        }
        if set(by_key) != expected_keys or len(required) != len(expected_keys):
            raise CanonicalContentUnavailable("canonical-layer-set-invalid")
        protected_layers = [
            layer for layer in required if entitlement.is_protected_layer(layer)
        ]
        protected = bool(protected_layers)
        state_path = entitlement.entitlement_state_path()
        login = entitlement.current_login() if protected else None
        eligible, decisions = entitlement.filter_eligible_layers(
            required,
            state_path=state_path,
            login=login,
        )
        decision_by_layer = {item.layer: item for item in decisions}
        if (
            len(eligible) != len(required)
            or any(not item.eligible for item in decisions)
            or len(decision_by_layer) != len(required)
            or set(decision_by_layer) != {str(layer["id"]) for layer in required}
        ):
            raise CanonicalContentUnavailable("entitlement-unavailable")
        bindings = entitlement.bind_layer_decisions(
            required,
            decisions,
            state_path=state_path,
            login=login,
        )
        binding_by_layer = {item.layer: item for item in bindings}
        expected_protected = {str(layer["id"]): layer for layer in protected_layers}
        if len(binding_by_layer) != len(bindings) or set(binding_by_layer) != set(
            expected_protected
        ):
            raise CanonicalContentUnavailable("entitlement-binding-invalid")
        for layer_id, layer in expected_protected.items():
            decision = decision_by_layer[layer_id]
            binding = binding_by_layer[layer_id]
            source = layer.get("source")
            expected_repo = (
                entitlement.github_repo_slug(source.get("repo"))
                if isinstance(source, Mapping)
                else None
            )
            if (
                expected_repo is None
                or not binding.eligible
                or binding.repo != expected_repo
                or binding.login != login
                or binding.revision != (decision.revision or 0)
                or binding.state != decision.state
                or binding.eligible != decision.eligible
            ):
                raise CanonicalContentUnavailable("entitlement-binding-invalid")
        payload, sources = resolve_specialist_knowledge(
            specialist, variant.value, RuntimeName.CLAUDE.value
        )
        runtime_projection = resolve_claude_agent_projection(
            LayerVariant.DEPARTMENT if personal else variant,
            specialist,
        )
        resolved_knowledge = tuple(
            source
            for _root, source in resolve_knowledge_skill_sources()
            if source is not None and source.role in signed_tiers
        )

        def resolve_bound():
            runtime_rows = []
            runtime_facts = []
            for tier in signed_tiers:
                layer = by_key[("claude", tier)]
                repo, provenance, contribution, content = _release_for_agent(
                    layer, specialist
                )
                runtime_facts.append(
                    (tier, layer, repo, provenance, contribution, content)
                )
            contributing = [item for item in runtime_facts if item[5] is not None]
            if not contributing:
                raise CanonicalContentUnavailable("claude-specialist-unavailable")
            winner = contributing[-1]
            for tier, layer, repo, provenance, contribution, content in runtime_facts:
                _lock_layer(
                    lock,
                    layer,
                    specialist,
                    content,
                    selected=tier == winner[0],
                )
                if content is None:
                    action = "authenticated-absence"
                    contributions = ()
                    digests = ()
                    destinations = ()
                else:
                    action = "selected" if tier == winner[0] else "shadowed"
                    contributions = (contribution,)
                    digests = (hashlib.sha256(content).hexdigest(),)
                    destinations = (f"agents/{specialist}",)
                runtime_rows.append(
                    LayerContentReceipt(
                        product="claude-copilot",
                        tier=tier,
                        source_layer_identifier=str(layer["id"]),
                        source_runtime=RuntimeName.CLAUDE.value,
                        source_adapter_version="claude-agent-v1",
                        repository_identifier=repo,
                        immutable_ref=_canonical_ref(provenance.ref),
                        tree_sha256=canonical_sha256(
                            {
                                "tag": provenance.release.tag,
                                "commit": provenance.release.commit,
                                "tree": provenance.tree,
                            }
                        ),
                        signer_identity=provenance.signer,
                        policy_sha256=canonical_sha256(layer.get("policy") or {}),
                        manifest_sha256=hashlib.sha256(
                            retained_manifest.content
                        ).hexdigest(),
                        lock_sha256=hashlib.sha256(retained_lock.content).hexdigest(),
                        contribution_ids=contributions,
                        content_digests=digests,
                        resolution_action=action,
                        materialized_destinations=destinations,
                        source_tree=provenance.tree,
                    )
                )
            if personal:
                from cc.evaluation_fixtures import (
                    PACKAGED_BUNDLE_SHA256,
                    PACKAGED_MATRIX_SHA256,
                    PACKAGED_PERSONAL_LAYER_SHA256,
                )
                from cc.evaluation_fixtures.personal_snapshot import (
                    PACKAGE_IDENTITY_SHA256,
                    PERSONAL_SNAPSHOT_SHA256,
                    RELEASE_IDENTITY_SHA256,
                )

                personal_policy = {
                    "schema_version": "task285-personal-content-authority-v1",
                    "case_id": case_id,
                    "specialist": specialist,
                    "route_contract_sha256": route_contract_document(str(case_id))[
                        "route_contract_sha256"
                    ],
                    "matrix_sha256": PACKAGED_MATRIX_SHA256,
                    "snapshot_sha256": (
                        PERSONAL_SNAPSHOT_SHA256 if uses_personal_snapshot else None
                    ),
                    "release_identity_sha256": (
                        RELEASE_IDENTITY_SHA256 if uses_personal_snapshot else None
                    ),
                    "package_identity_sha256": (
                        PACKAGE_IDENTITY_SHA256 if uses_personal_snapshot else None
                    ),
                    "resolution": (
                        "synthetic-snapshot"
                        if uses_personal_snapshot
                        else "authenticated-absence"
                    ),
                }
                personal_identity = (
                    PERSONAL_SNAPSHOT_SHA256
                    if uses_personal_snapshot
                    else PACKAGED_MATRIX_SHA256
                )
                personal_manifest = (
                    PACKAGED_PERSONAL_LAYER_SHA256
                    if uses_personal_snapshot
                    else PACKAGED_BUNDLE_SHA256
                )
                personal_lock = (
                    str(personal_receipt_document["materialization_sha256"])
                    if personal_receipt_document is not None
                    else canonical_sha256(
                        {
                            "policy": personal_policy,
                            "resolution": "authenticated-absence",
                        }
                    )
                )
                runtime_rows.append(
                    LayerContentReceipt(
                        product="claude-copilot",
                        tier="personal",
                        source_layer_identifier="synthetic-personal-runtime-absence",
                        source_runtime=RuntimeName.CLAUDE.value,
                        source_adapter_version="synthetic-personal-snapshot-v1",
                        repository_identifier="cc/evaluation-fixtures",
                        immutable_ref=f"sha256:{personal_identity}",
                        tree_sha256=personal_identity,
                        signer_identity=(
                            "SHA256:FIfppOkzwXZUAamELQzYoSUQXiEAmTYiVewHe1ACMZo"
                        ),
                        policy_sha256=canonical_sha256(personal_policy),
                        manifest_sha256=personal_manifest,
                        lock_sha256=personal_lock,
                        contribution_ids=(),
                        content_digests=(),
                        resolution_action="authenticated-absence",
                        materialized_destinations=(),
                        source_tree=personal_identity,
                    )
                )
            winner_receipt = runtime_rows[signed_tiers.index(winner[0])]
            projected = runtime_projection.source_receipt
            if not (
                projected["layer"] == winner_receipt.source_layer_identifier
                and projected["tier"] == winner_receipt.tier
                and projected["repository"] == winner_receipt.repository_identifier
                and projected["ref"] == winner_receipt.immutable_ref
                and projected["tree"] == winner_receipt.source_tree
                and projected["signer"] == winner_receipt.signer_identity
                and projected["contribution"] == winner_receipt.contribution_ids[0]
                and projected["content_sha256"] == winner_receipt.content_digests[0]
            ):
                raise CanonicalContentUnavailable("claude-specialist-mismatch")
            manifest_sha256 = hashlib.sha256(retained_manifest.content).hexdigest()
            lock_sha256 = hashlib.sha256(retained_lock.content).hexdigest()
            shared_layer_ids = {
                str(by_key[("knowledge", tier)]["id"]) for tier in signed_tiers
            }
            shared_sources = tuple(
                item for item in sources if item.get("layer") in shared_layer_ids
            )
            knowledge_rows = _knowledge_rows(
                tiers=signed_tiers,
                specialist=specialist,
                runtime=RuntimeName.CLAUDE,
                layers_by_key=by_key,
                sources=shared_sources,
                manifest_sha256=manifest_sha256,
                lock_sha256=lock_sha256,
                lock=lock,
                resolved_sources=resolved_knowledge,
            )
            if personal:
                if uses_personal_snapshot:
                    assert personal_source is not None
                    assert personal_receipt_document is not None
                    personal_matches = [
                        item
                        for item in sources
                        if item.get("layer") == "synthetic-personal-knowledge"
                    ]
                    if len(personal_matches) != 1 or dict(personal_matches[0]) != dict(
                        personal_source
                    ):
                        raise CanonicalContentUnavailable("personal-snapshot-mismatch")
                    contribution_ids = (str(personal_source["contribution"]),)
                    content_digests = (str(personal_source["content_sha256"]),)
                    resolution_action = "accumulated"
                    materialized_destinations = ("personal-layer/doc.md",)
                    source_layer_identifier = "synthetic-personal-knowledge"
                    immutable_ref = str(personal_source["ref"])
                    source_tree = str(personal_source["tree"])
                else:
                    if any(item.get("tier") == "personal" for item in sources):
                        raise CanonicalContentUnavailable("personal-snapshot-mismatch")
                    contribution_ids = ()
                    content_digests = ()
                    resolution_action = "authenticated-absence"
                    materialized_destinations = ()
                    source_layer_identifier = "synthetic-personal-knowledge-absence"
                    immutable_ref = f"sha256:{personal_identity}"
                    source_tree = personal_identity
                knowledge_rows.append(
                    LayerContentReceipt(
                        product="knowledge",
                        tier="personal",
                        source_layer_identifier=source_layer_identifier,
                        source_runtime=RuntimeName.CLAUDE.value,
                        source_adapter_version="synthetic-personal-snapshot-v1",
                        repository_identifier="cc/evaluation-fixtures",
                        immutable_ref=immutable_ref,
                        tree_sha256=source_tree,
                        signer_identity=(
                            "SHA256:FIfppOkzwXZUAamELQzYoSUQXiEAmTYiVewHe1ACMZo"
                        ),
                        policy_sha256=canonical_sha256(personal_policy),
                        manifest_sha256=personal_manifest,
                        lock_sha256=personal_lock,
                        contribution_ids=contribution_ids,
                        content_digests=content_digests,
                        resolution_action=resolution_action,
                        materialized_destinations=materialized_destinations,
                        source_tree=source_tree,
                    )
                )
            entitlement_document = []
            for decision in decisions:
                binding = binding_by_layer.get(decision.layer)
                entitlement_document.append(
                    {
                        "layer": decision.layer,
                        "state": decision.state,
                        "eligible": decision.eligible,
                        "responsible_actor": decision.responsible_actor,
                        "recovery": decision.recovery,
                        "checked_at": decision.checked_at,
                        "expires_at": decision.expires_at,
                        "revision": decision.revision,
                        "superseded": decision.superseded,
                        "binding": (
                            None
                            if binding is None
                            else {
                                "repo": binding.repo,
                                "revision": binding.revision,
                                "state": binding.state,
                                "eligible": binding.eligible,
                                "login_bound": binding.login is not None,
                                "ledger": "private-entitlement-ledger",
                            }
                        ),
                    }
                )
            all_rows = tuple(
                sorted(
                    runtime_rows + knowledge_rows,
                    key=lambda item: (
                        tiers.index(item.tier),
                        item.product,
                        item.repository_identifier,
                    ),
                )
            )
            receipt = ContentReceipt(
                variant=variant,
                entitlement_receipt_sha256=canonical_sha256(entitlement_document),
                layers=all_rows,
                composed_content_sha256=hashlib.sha256(payload.encode()).hexdigest(),
                materialization_sha256=canonical_sha256(
                    {
                        "manifest_sha256": manifest_sha256,
                        "lock_sha256": lock_sha256,
                        "layers": [
                            {
                                "layer": item.source_layer_identifier,
                                "action": item.resolution_action,
                                "destinations": list(item.materialized_destinations),
                            }
                            for item in all_rows
                        ],
                    }
                ),
            )
            return receipt, payload, sources, runtime_projection

        valid, resolved = entitlement.run_under_binding_leases(bindings, resolve_bound)
        if not valid or resolved is None:
            raise CanonicalContentUnavailable("entitlement-changed")
        retained_manifest.validate()
        retained_lock.validate()
        receipt, payload, sources, runtime_projection = resolved
        evidence_document = {
            "schema_version": "evaluation-content-authority-v1",
            "content_receipt_sha256": content_receipt_identity(receipt),
            "knowledge_payload_sha256": hashlib.sha256(payload.encode()).hexdigest(),
            "knowledge_sources_sha256": canonical_sha256(
                [dict(item) for item in sources]
            ),
            "runtime_projection_sha256": canonical_sha256(
                dict(runtime_projection.source_receipt)
            ),
            "personal_materialization_sha256": (
                None
                if not uses_personal_snapshot
                else personal_snapshot_receipt.materialization_sha256
            ),
        }
        seal = object()
        result = CanonicalContentProjection(
            content_receipt=receipt,
            knowledge_payload=payload,
            knowledge_sources=sources,
            runtime_projection=runtime_projection,
            evidence_sha256=canonical_sha256(evidence_document),
            _manifest_capability=retained_manifest,
            _lock_capability=retained_lock,
            _entitlement_bindings=tuple(bindings),
            _personal_snapshot_receipt=(
                personal_snapshot_receipt if uses_personal_snapshot else None
            ),
            _seal=seal,
            _authority=_AUTHORITY,
        )
        _ISSUED[seal] = result
        if not verify_canonical_content_projection(result):
            raise CanonicalContentUnavailable("canonical-config-changed")
        transferred = True
        return result
    finally:
        if not transferred:
            retained_lock.close()
            retained_manifest.close()


def issue_canonical_codex_content(
    *,
    variant: LayerVariant,
    specialist: str,
    case_id: str | None = None,
    personal_snapshot_receipt: object | None = None,
    manifest_path: Path | None = None,
    lock_path: Path | None = None,
) -> CanonicalContentProjection:
    """Issue exact additive Codex specialist plus Knowledge content.

    This is source authority only. It does not authorize a Codex subprocess;
    the independently sealed isolation/dispatch boundary remains mandatory.
    """

    from cc.core import config
    from cc.core.ecosystem import entitlement
    from cc.core.ecosystem.knowledge_skill_source import resolve_knowledge_skill_sources
    from cc.core.ecosystem.lockfile import default_lockfile_path
    from cc.core.evaluation.journey_runtime import (
        _codex_specialist_projection,
        _compose_codex_specialist_knowledge,
        resolve_specialist_knowledge,
    )

    matrix_sha256, cell_plan_sha256 = _canonical_codex_cell_plan(
        case_id=case_id,
        variant=variant,
        specialist=specialist,
    )
    personal = variant is LayerVariant.PERSONAL
    uses_personal_snapshot = personal and case_id == "eval-07" and specialist == "doc"
    personal_source = None
    personal_receipt_document = None
    if personal:
        from cc.core.evaluation.matrix import route_contract_document
        from cc.evaluation_fixtures.personal_snapshot import (
            PersonalSnapshotReceipt,
            personal_snapshot_contribution,
            personal_snapshot_receipt_document,
            verify_personal_snapshot_receipt,
        )

        try:
            expected_specialist = route_contract_document(str(case_id))["specialists"][
                0
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise CanonicalContentUnavailable("personal-snapshot-unavailable") from exc
        if specialist != expected_specialist:
            raise CanonicalContentUnavailable("personal-snapshot-unavailable")
        if uses_personal_snapshot:
            if not isinstance(
                personal_snapshot_receipt, PersonalSnapshotReceipt
            ) or not verify_personal_snapshot_receipt(personal_snapshot_receipt):
                raise CanonicalContentUnavailable("personal-snapshot-unavailable")
            _personal_content, claude_personal_source = personal_snapshot_contribution(
                runtime=RuntimeName.CLAUDE.value
            )
            personal_source = {
                **claude_personal_source,
                "runtime": RuntimeName.CODEX.value,
            }
            personal_receipt_document = personal_snapshot_receipt_document(
                personal_snapshot_receipt
            )
        elif personal_snapshot_receipt is not None:
            raise CanonicalContentUnavailable("personal-snapshot-unexpected")
    elif personal_snapshot_receipt is not None:
        raise CanonicalContentUnavailable("personal-snapshot-unexpected")

    tiers = _variant_tiers(variant)
    signed_tiers = tiers[:-1] if personal else tiers
    selected_manifest = manifest_path or Path(
        str(config.resolve_key("layers.manifest"))
    )
    selected_lock = lock_path or default_lockfile_path()
    retained_manifest = _RetainedFile(selected_manifest, maximum_bytes=1_000_000)
    try:
        retained_lock = _RetainedFile(selected_lock, maximum_bytes=4_000_000)
    except Exception:
        retained_manifest.close()
        raise
    transferred = False
    try:
        layers = _manifest_layers(retained_manifest.content)
        lock = _lock_document(retained_lock.content)
        shared_codex = [
            layer
            for layer in layers
            if layer.get("product") == "codex"
            and layer.get("role") in _CODEX_SHARED_PLUGIN_BY_TIER
        ]
        codex_by_tier = {str(layer["role"]): layer for layer in shared_codex}
        knowledge_layers = [
            layer
            for layer in layers
            if layer.get("product") == "knowledge" and layer.get("role") in signed_tiers
        ]
        knowledge_by_tier = {str(layer["role"]): layer for layer in knowledge_layers}
        if (
            len(shared_codex) != 3
            or set(codex_by_tier) != set(_CODEX_SHARED_PLUGIN_BY_TIER)
            or len(knowledge_layers) != len(signed_tiers)
            or set(knowledge_by_tier) != set(signed_tiers)
        ):
            raise CanonicalContentUnavailable("canonical-layer-set-invalid")

        required = tuple(shared_codex) + tuple(knowledge_layers)
        protected_layers = [
            layer for layer in required if entitlement.is_protected_layer(layer)
        ]
        state_path = entitlement.entitlement_state_path()
        login = entitlement.current_login() if protected_layers else None
        eligible, decisions = entitlement.filter_eligible_layers(
            list(required),
            state_path=state_path,
            login=login,
        )
        decision_by_layer = {item.layer: item for item in decisions}
        required_ids = {str(layer["id"]) for layer in required}
        if (
            len(eligible) != len(required)
            or any(not item.eligible for item in decisions)
            or len(decision_by_layer) != len(required)
            or set(decision_by_layer) != required_ids
        ):
            raise CanonicalContentUnavailable("entitlement-unavailable")
        bindings = entitlement.bind_layer_decisions(
            list(required),
            decisions,
            state_path=state_path,
            login=login,
        )
        binding_by_layer = {item.layer: item for item in bindings}
        expected_protected = {str(layer["id"]): layer for layer in protected_layers}
        if len(binding_by_layer) != len(bindings) or set(binding_by_layer) != set(
            expected_protected
        ):
            raise CanonicalContentUnavailable("entitlement-binding-invalid")
        for layer_id, layer in expected_protected.items():
            decision = decision_by_layer[layer_id]
            binding = binding_by_layer[layer_id]
            source = layer.get("source")
            expected_repo = (
                entitlement.github_repo_slug(source.get("repo"))
                if isinstance(source, Mapping)
                else None
            )
            if (
                expected_repo is None
                or not binding.eligible
                or binding.repo != expected_repo
                or binding.login != login
                or binding.revision != (decision.revision or 0)
                or binding.state != decision.state
                or binding.eligible != decision.eligible
            ):
                raise CanonicalContentUnavailable("entitlement-binding-invalid")

        resolved_knowledge = tuple(
            source
            for _root, source in resolve_knowledge_skill_sources()
            if source is not None and source.role in signed_tiers
        )
        knowledge_content, raw_knowledge_sources = resolve_specialist_knowledge(
            specialist,
            variant.value,
            RuntimeName.CLAUDE.value,
        )
        shared_knowledge_ids = {
            str(knowledge_by_tier[tier]["id"]) for tier in signed_tiers
        }
        seen_knowledge_contributions: set[tuple[str, str]] = set()
        for item in raw_knowledge_sources:
            layer_id = item.get("layer")
            contribution = item.get("contribution")
            adapter_version = item.get("adapter_version")
            is_shared = (
                adapter_version == "knowledge-contribution-v1"
                and layer_id in shared_knowledge_ids
            )
            is_personal = (
                uses_personal_snapshot
                and adapter_version == "synthetic-personal-snapshot-v1"
                and layer_id == "synthetic-personal-knowledge"
            )
            identity = (str(layer_id), str(contribution))
            if (
                item.get("runtime") != RuntimeName.CLAUDE.value
                or not isinstance(contribution, str)
                or not (is_shared or is_personal)
                or identity in seen_knowledge_contributions
            ):
                raise CanonicalContentUnavailable("signed-knowledge-mismatch")
            seen_knowledge_contributions.add(identity)
        codex_knowledge_projection = (
            knowledge_content,
            tuple(
                {**dict(item), "runtime": RuntimeName.CODEX.value}
                for item in raw_knowledge_sources
            ),
        )

        def resolve_bound():
            primary_sources = {}
            inventories = {}
            for tier in _CODEX_SHARED_PLUGIN_BY_TIER:
                primary, inventory = _codex_plugin_inventory(codex_by_tier[tier])
                primary_sources[tier] = primary
                inventories[primary.layer] = inventory
            global_lock_sha256 = _codex_global_lock_identity(
                layers=shared_codex,
                inventories=inventories,
                lock=lock,
            )

            runtime_sources = []
            for tier in signed_tiers:
                source = primary_sources[tier]
                try:
                    _codex_specialist_projection(source, specialist)
                except ValueError as exc:
                    if str(exc) != "Required Codex specialist is unavailable.":
                        raise CanonicalContentUnavailable(
                            "signed-codex-source-invalid"
                        ) from exc
                    if tier == "foundation":
                        pack = _codex_pack_source(
                            foundation_layer=codex_by_tier[tier],
                            foundation_plugin=source,
                            specialist=specialist,
                            variant=variant,
                            case_id=case_id,
                        )
                        if pack is not None:
                            source = pack
                runtime_sources.append(source)
            try:
                payload, sources, winner_tier, facts = (
                    _compose_codex_specialist_knowledge(
                        specialist,
                        variant.value,
                        RuntimeName.CODEX.value,
                        tuple(runtime_sources),
                        knowledge_projection=codex_knowledge_projection,
                    )
                )
            except ValueError as exc:
                if str(exc) == "Required Codex specialist is unavailable.":
                    raise CanonicalContentUnavailable(
                        "codex-specialist-unavailable"
                    ) from exc
                raise CanonicalContentUnavailable(
                    "signed-codex-source-mismatch"
                ) from exc

            fact_by_tier = {
                tier: (content, receipt) for tier, content, receipt in facts
            }
            manifest_sha256 = hashlib.sha256(retained_manifest.content).hexdigest()
            lock_sha256 = hashlib.sha256(retained_lock.content).hexdigest()
            runtime_rows = []
            for source in runtime_sources:
                content, source_receipt = fact_by_tier[source.role]
                if content is None or source_receipt is None:
                    action = "authenticated-absence"
                    contribution_ids = ()
                    content_digests = ()
                    destinations = ()
                else:
                    action = "selected" if source.role == winner_tier else "shadowed"
                    contribution_ids = (str(source_receipt["contribution"]),)
                    content_digests = (str(source_receipt["content_sha256"]),)
                    destinations = (
                        (
                            (
                                f"project-packs/{source.plugin_name}/skills/{specialist}"
                                if source.source_kind == "activated-pack"
                                else f"plugins/{source.plugin_name}/skills/{specialist}"
                            ),
                        )
                        if action == "selected"
                        else ()
                    )
                runtime_rows.append(
                    LayerContentReceipt(
                        product="codex-copilot",
                        tier=source.role,
                        source_layer_identifier=source.layer,
                        source_runtime=RuntimeName.CODEX.value,
                        source_adapter_version=source.adapter_version,
                        repository_identifier=source.repository,
                        immutable_ref=_canonical_ref(source.ref),
                        tree_sha256=canonical_sha256(
                            {
                                "tag": source.release_tag,
                                "commit": source.release_commit,
                                "tree": source.release_tree,
                                "item_tree": source.tree,
                                "activation_sha256": source.activation_sha256,
                            }
                        ),
                        signer_identity=source.signer,
                        policy_sha256=canonical_sha256(
                            codex_by_tier[source.role].get("policy") or {}
                        ),
                        manifest_sha256=manifest_sha256,
                        lock_sha256=canonical_sha256(
                            {
                                "lockfile_sha256": lock_sha256,
                                "global_codex_lock_sha256": global_lock_sha256,
                                "activation_sha256": source.activation_sha256,
                            }
                        ),
                        contribution_ids=contribution_ids,
                        content_digests=content_digests,
                        resolution_action=action,
                        materialized_destinations=destinations,
                        source_tree=source.tree,
                    )
                )

            layers_by_key = {
                ("knowledge", tier): knowledge_by_tier[tier] for tier in signed_tiers
            }
            shared_layer_ids = {
                str(knowledge_by_tier[tier]["id"]) for tier in signed_tiers
            }
            shared_sources = tuple(
                item
                for item in sources
                if item.get("adapter_version") == "knowledge-contribution-v1"
                and item.get("layer") in shared_layer_ids
            )
            knowledge_rows = _knowledge_rows(
                tiers=signed_tiers,
                specialist=specialist,
                runtime=RuntimeName.CODEX,
                layers_by_key=layers_by_key,
                sources=shared_sources,
                manifest_sha256=manifest_sha256,
                lock_sha256=lock_sha256,
                lock=lock,
                resolved_sources=resolved_knowledge,
            )

            if personal:
                from cc.evaluation_fixtures import (
                    PACKAGED_BUNDLE_SHA256,
                    PACKAGED_MATRIX_SHA256,
                    PACKAGED_PERSONAL_LAYER_SHA256,
                )
                from cc.evaluation_fixtures.personal_snapshot import (
                    PACKAGE_IDENTITY_SHA256,
                    PERSONAL_SNAPSHOT_SHA256,
                    RELEASE_IDENTITY_SHA256,
                )

                personal_policy = {
                    "schema_version": "task285-personal-content-authority-v1",
                    "case_id": case_id,
                    "specialist": specialist,
                    "matrix_sha256": PACKAGED_MATRIX_SHA256,
                    "snapshot_sha256": (
                        PERSONAL_SNAPSHOT_SHA256 if uses_personal_snapshot else None
                    ),
                    "release_identity_sha256": (
                        RELEASE_IDENTITY_SHA256 if uses_personal_snapshot else None
                    ),
                    "package_identity_sha256": (
                        PACKAGE_IDENTITY_SHA256 if uses_personal_snapshot else None
                    ),
                    "resolution": (
                        "synthetic-snapshot"
                        if uses_personal_snapshot
                        else "authenticated-absence"
                    ),
                }
                personal_identity = (
                    PERSONAL_SNAPSHOT_SHA256
                    if uses_personal_snapshot
                    else PACKAGED_MATRIX_SHA256
                )
                personal_manifest = (
                    PACKAGED_PERSONAL_LAYER_SHA256
                    if uses_personal_snapshot
                    else PACKAGED_BUNDLE_SHA256
                )
                personal_lock = (
                    str(personal_receipt_document["materialization_sha256"])
                    if personal_receipt_document is not None
                    else canonical_sha256(personal_policy)
                )
                runtime_rows.append(
                    LayerContentReceipt(
                        product="codex-copilot",
                        tier="personal",
                        source_layer_identifier="synthetic-personal-runtime-absence",
                        source_runtime=RuntimeName.CODEX.value,
                        source_adapter_version="synthetic-personal-snapshot-v1",
                        repository_identifier="cc/evaluation-fixtures",
                        immutable_ref=f"sha256:{personal_identity}",
                        tree_sha256=personal_identity,
                        signer_identity=(
                            "SHA256:FIfppOkzwXZUAamELQzYoSUQXiEAmTYiVewHe1ACMZo"
                        ),
                        policy_sha256=canonical_sha256(personal_policy),
                        manifest_sha256=personal_manifest,
                        lock_sha256=personal_lock,
                        contribution_ids=(),
                        content_digests=(),
                        resolution_action="authenticated-absence",
                        materialized_destinations=(),
                        source_tree=personal_identity,
                    )
                )
                if uses_personal_snapshot:
                    assert personal_source is not None
                    personal_matches = [
                        item
                        for item in sources
                        if item.get("layer") == "synthetic-personal-knowledge"
                    ]
                    if len(personal_matches) != 1 or dict(personal_matches[0]) != dict(
                        personal_source
                    ):
                        raise CanonicalContentUnavailable("personal-snapshot-mismatch")
                    contribution_ids = (str(personal_source["contribution"]),)
                    content_digests = (str(personal_source["content_sha256"]),)
                    knowledge_action = "accumulated"
                    knowledge_destinations = ("personal-layer/doc.md",)
                    knowledge_layer = "synthetic-personal-knowledge"
                    knowledge_ref = str(personal_source["ref"])
                    knowledge_tree = str(personal_source["tree"])
                else:
                    contribution_ids = ()
                    content_digests = ()
                    knowledge_action = "authenticated-absence"
                    knowledge_destinations = ()
                    knowledge_layer = "synthetic-personal-knowledge-absence"
                    knowledge_ref = f"sha256:{personal_identity}"
                    knowledge_tree = personal_identity
                knowledge_rows.append(
                    LayerContentReceipt(
                        product="knowledge",
                        tier="personal",
                        source_layer_identifier=knowledge_layer,
                        source_runtime=RuntimeName.CODEX.value,
                        source_adapter_version="synthetic-personal-snapshot-v1",
                        repository_identifier="cc/evaluation-fixtures",
                        immutable_ref=knowledge_ref,
                        tree_sha256=knowledge_tree,
                        signer_identity=(
                            "SHA256:FIfppOkzwXZUAamELQzYoSUQXiEAmTYiVewHe1ACMZo"
                        ),
                        policy_sha256=canonical_sha256(personal_policy),
                        manifest_sha256=personal_manifest,
                        lock_sha256=personal_lock,
                        contribution_ids=contribution_ids,
                        content_digests=content_digests,
                        resolution_action=knowledge_action,
                        materialized_destinations=knowledge_destinations,
                        source_tree=knowledge_tree,
                    )
                )

            entitlement_document = []
            for decision in decisions:
                binding = binding_by_layer.get(decision.layer)
                entitlement_document.append(
                    {
                        "layer": decision.layer,
                        "state": decision.state,
                        "eligible": decision.eligible,
                        "revision": decision.revision,
                        "binding": (
                            None
                            if binding is None
                            else {
                                "repo": binding.repo,
                                "revision": binding.revision,
                                "state": binding.state,
                                "eligible": binding.eligible,
                                "login_bound": binding.login is not None,
                            }
                        ),
                    }
                )
            all_rows = tuple(
                sorted(
                    runtime_rows + knowledge_rows,
                    key=lambda item: (
                        tiers.index(item.tier),
                        item.product,
                        item.repository_identifier,
                    ),
                )
            )
            receipt = ContentReceipt(
                variant=variant,
                entitlement_receipt_sha256=canonical_sha256(entitlement_document),
                layers=all_rows,
                composed_content_sha256=hashlib.sha256(payload.encode()).hexdigest(),
                materialization_sha256=canonical_sha256(
                    {
                        "manifest_sha256": manifest_sha256,
                        "lock_sha256": lock_sha256,
                        "global_codex_lock_sha256": global_lock_sha256,
                        "layers": [
                            {
                                "layer": item.source_layer_identifier,
                                "action": item.resolution_action,
                                "destinations": list(item.materialized_destinations),
                            }
                            for item in all_rows
                        ],
                    }
                ),
            )
            selected_source = next(
                item for item in runtime_sources if item.role == winner_tier
            )
            selected_content, selected_receipts = _codex_specialist_projection(
                selected_source, specialist
            )
            selected_receipt = dict(selected_receipts[0])
            projection_document = {
                "schema_version": "evaluation-codex-runtime-projection-v1",
                "matrix_sha256": matrix_sha256,
                "cell_plan_sha256": cell_plan_sha256,
                "plugins": [
                    {
                        "layer": item.layer,
                        "tier": item.role,
                        "repository": item.repository,
                        "relative_path": item.relative_path,
                        "plugin_name": item.plugin_name,
                        "source_kind": item.source_kind,
                        "adapter_version": item.adapter_version,
                        "activation_sha256": item.activation_sha256,
                        "ref": _canonical_ref(item.ref),
                        "tree": item.tree,
                        "signer": item.signer,
                        "release_tag": item.release_tag,
                        "release_commit": item.release_commit,
                        "release_tree": item.release_tree,
                    }
                    for item in runtime_sources
                ],
                "selected_source": selected_receipt,
                "selected_content_sha256": hashlib.sha256(
                    selected_content.encode("utf-8")
                ).hexdigest(),
            }
            runtime_projection = CanonicalCodexRuntimeProjection(
                matrix_sha256=matrix_sha256,
                cell_plan_sha256=cell_plan_sha256,
                plugin_sources=tuple(runtime_sources),
                content=selected_content,
                source_receipt=selected_receipt,
                projection_sha256=canonical_sha256(projection_document),
            )
            return receipt, payload, tuple(sources), runtime_projection

        valid, resolved = entitlement.run_under_binding_leases(bindings, resolve_bound)
        if not valid or resolved is None:
            raise CanonicalContentUnavailable("entitlement-changed")
        retained_manifest.validate()
        retained_lock.validate()
        receipt, payload, sources, runtime_projection = resolved
        evidence_document = {
            "schema_version": "evaluation-content-authority-v1",
            "content_receipt_sha256": content_receipt_identity(receipt),
            "knowledge_payload_sha256": hashlib.sha256(payload.encode()).hexdigest(),
            "knowledge_sources_sha256": canonical_sha256(
                [dict(item) for item in sources]
            ),
            "runtime_projection_sha256": runtime_projection.projection_sha256,
            "personal_materialization_sha256": (
                None
                if not uses_personal_snapshot
                else personal_snapshot_receipt.materialization_sha256
            ),
        }
        seal = object()
        result = CanonicalContentProjection(
            content_receipt=receipt,
            knowledge_payload=payload,
            knowledge_sources=sources,
            runtime_projection=runtime_projection,
            evidence_sha256=canonical_sha256(evidence_document),
            _manifest_capability=retained_manifest,
            _lock_capability=retained_lock,
            _entitlement_bindings=tuple(bindings),
            _personal_snapshot_receipt=(
                personal_snapshot_receipt if uses_personal_snapshot else None
            ),
            _seal=seal,
            _authority=_AUTHORITY,
        )
        _ISSUED[seal] = result
        if not verify_canonical_content_projection(result):
            raise CanonicalContentUnavailable("canonical-config-changed")
        transferred = True
        return result
    finally:
        if not transferred:
            retained_lock.close()
            retained_manifest.close()


__all__ = [
    "CanonicalContentProjection",
    "CanonicalCodexPluginSource",
    "CanonicalCodexRuntimeProjection",
    "CanonicalContentUnavailable",
    "issue_canonical_claude_content",
    "issue_canonical_codex_content",
    "verify_canonical_content_projection",
]
