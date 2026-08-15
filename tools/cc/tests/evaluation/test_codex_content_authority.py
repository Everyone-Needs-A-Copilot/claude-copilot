from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from cc.core.evaluation.content_authority import (
    CanonicalCodexPluginSource,
    CanonicalContentUnavailable,
    _codex_global_lock_identity,
    _codex_pack_source,
    _codex_source_from_provenance,
    issue_canonical_codex_content,
    verify_canonical_content_projection,
)
from cc.core.evaluation.models import LayerVariant
from cc.core.evaluation.schema import canonical_sha256
from cc.evaluation_fixtures import PACKAGED_MATRIX_SHA256

_SIGNER = "SHA256:abcdefgh"
_TIERS = ("foundation", "organization", "department")
_PLUGIN_BY_TIER = {
    "foundation": "codex-copilot",
    "organization": "codex-copilot-internal",
    "department": "codex-copilot-accounting",
}


class _Release:
    def __init__(self, *, digit: int, blobs: dict[str, bytes]) -> None:
        self.tag = format(digit, "x") * 40
        self.commit = format(digit + 1, "x") * 40
        self.tree = format(digit + 2, "x") * 40
        self._blobs = blobs

    def read_blob(self, path: str) -> bytes:
        try:
            return self._blobs[path]
        except KeyError as exc:
            raise ValueError(path) from exc


def _snapshot(files: dict[str, bytes]) -> object:
    return SimpleNamespace(
        files=tuple(
            SimpleNamespace(path=path, content=content)
            for path, content in sorted(files.items())
        )
    )


def _plugin_source(
    tier: str,
    *,
    specialist: str | None,
    plugin_name: str | None = None,
    source_kind: str = "plugin",
    activation_sha256: str | None = None,
    catalog: list[dict[str, str]] | None = None,
) -> CanonicalCodexPluginSource:
    plugin_name = plugin_name or _PLUGIN_BY_TIER[tier]
    repository = f"Org/codex-{tier}"
    if source_kind == "plugin":
        manifest = {
            "name": plugin_name,
            "repository": f"https://github.com/{repository}.git",
            "skills": "./skills/",
        }
        files: dict[str, bytes] = {
            ".codex-plugin/plugin.json": json.dumps(manifest).encode(),
        }
        if catalog is not None:
            files["agent-catalog.json"] = json.dumps(
                {"optionalAgents": catalog}
            ).encode()
    else:
        manifest = {
            "name": plugin_name,
            "specialists": [] if specialist is None else [specialist],
            "activation": {
                "script": "scripts/activate-pack.py",
                "skillDirectory": f"packs/{plugin_name}/skills",
            },
        }
        files = {"pack.json": json.dumps(manifest).encode()}
    if specialist is not None:
        files[f"skills/{specialist}/SKILL.md"] = (
            f"Signed {tier} {specialist} guidance."
        ).encode()
    digit = _TIERS.index(tier) + 1
    return CanonicalCodexPluginSource(
        layer=f"codex-{tier}",
        role=tier,
        repository=repository,
        repository_root=Path(f"/signed/codex-{tier}"),
        relative_path=(
            f"plugins/{plugin_name}"
            if source_kind == "plugin"
            else f"packs/{plugin_name}"
        ),
        plugin_name=plugin_name,
        source_kind=source_kind,
        adapter_version=(
            "codex-plugin-v1" if source_kind == "plugin" else "codex-pack-v1"
        ),
        activation_sha256=activation_sha256,
        ref="refs/tags/v1.0.0",
        tree=str(digit) * 40,
        signer=_SIGNER,
        release_tag=str(digit + 3) * 40,
        release_commit=str(digit + 4) * 40,
        release_tree=str(digit + 5) * 40,
        snapshot=_snapshot(files),
    )


def _codex_layers(knowledge_tiers: tuple[str, ...]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for rank, tier in zip((40, 30, 20), _TIERS, strict=True):
        rows.append(
            {
                "id": f"codex-{tier}",
                "product": "codex",
                "role": tier,
                "rank": rank,
                "source": {
                    "repo": f"Org/codex-{tier}",
                    "path": f"/signed/codex-{tier}",
                    "ref": "v1.0.0",
                },
                "policy": {"allowed_signers": [_SIGNER]},
            }
        )
    for tier in knowledge_tiers:
        rows.append(
            {
                "id": f"knowledge-{tier}",
                "product": "knowledge",
                "role": tier,
                "rank": 40 - _TIERS.index(tier) * 10,
                "source": {
                    "repo": f"Org/knowledge-{tier}",
                    "path": f"/signed/knowledge-{tier}",
                    "ref": "v1.0.0",
                },
                "policy": {"allowed_signers": [_SIGNER]},
            }
        )
    return rows


def _global_lock() -> dict[str, object]:
    return {
        "codex-foundation": {
            "_meta": {
                "product": "codex",
                "role": "foundation",
                "tier": "foundation",
            }
        },
        "codex-organization": {
            "_meta": {
                "product": "codex",
                "role": "organization",
                "tier": "organization",
            },
            "plugins": {"codex-copilot-internal": "2" * 64},
        },
        "codex-department": {
            "_meta": {
                "product": "codex",
                "role": "department",
                "tier": "department",
            },
            "plugins": {
                "codex-copilot": "3" * 64,
                "codex-copilot-accounting": "4" * 64,
            },
        },
    }


def _configure_codex_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    variant: LayerVariant,
    specialist: str,
    runtime_specialists: dict[str, str | None],
    pack_enabled: bool = True,
    include_personal: bool = False,
) -> tuple[Path, Path]:
    from cc.core.ecosystem import entitlement, knowledge_skill_source
    from cc.core.evaluation import content_authority, journey_runtime

    signed_tiers = {
        LayerVariant.FOUNDATION: ("foundation",),
        LayerVariant.ORGANIZATION: ("foundation", "organization"),
        LayerVariant.DEPARTMENT: _TIERS,
        LayerVariant.PERSONAL: _TIERS,
    }[variant]
    layers = _codex_layers(signed_tiers)
    lock = _global_lock()
    knowledge_sources = []
    knowledge_receipts = []
    knowledge_content = []
    for index, tier in enumerate(signed_tiers, start=1):
        content = f"Signed {tier} Knowledge for {specialist}.".encode()
        contribution = f"skills/{specialist}-{tier}.md"
        manifest = {"extensions": [{"agent": specialist, "file": contribution}]}
        release = _Release(
            digit=index + 5,
            blobs={
                "knowledge-manifest.json": json.dumps(manifest).encode(),
                contribution: content,
            },
        )
        source = SimpleNamespace(
            role=tier,
            layer=f"knowledge-{tier}",
            repository=f"Org/knowledge-{tier}",
            repository_root=Path(f"/signed/knowledge-{tier}"),
            ref="v1.0.0",
            tree=release.tree,
            release=release,
            signer=_SIGNER,
        )
        knowledge_sources.append(source)
        knowledge_content.append(content.decode())
        knowledge_receipts.append(
            {
                "layer": source.layer,
                "role": tier,
                "tier": tier,
                "repository": source.repository,
                "ref": "refs/tags/v1.0.0",
                "tree": source.tree,
                "signer": _SIGNER,
                "contribution": contribution,
                "content_sha256": hashlib.sha256(content).hexdigest(),
                "runtime": "claude",
                "adapter_version": "knowledge-contribution-v1",
            }
        )
        lock[f"knowledge-{tier}"] = {
            "_meta": {"product": "knowledge", "role": tier, "tier": tier}
        }
    if include_personal:
        from cc.evaluation_fixtures.personal_snapshot import (
            personal_snapshot_contribution,
        )

        personal_content, personal_source = personal_snapshot_contribution(
            runtime="claude"
        )
        knowledge_content.append(personal_content)
        knowledge_receipts.append(personal_source)

    manifest_path = tmp_path / "codex-layers.yml"
    lock_path = tmp_path / "codex.lock.json"
    manifest_path.write_text("version: 1\nlayers: []\n", encoding="utf-8")
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    manifest_path.chmod(0o600)
    lock_path.chmod(0o600)
    monkeypatch.setattr(content_authority, "_manifest_layers", lambda _raw: layers)
    monkeypatch.setattr(content_authority, "_lock_document", lambda _raw: lock)
    monkeypatch.setattr(
        content_authority,
        "_origin",
        lambda root: f"Org/{root.name}",
    )

    primary = {
        tier: _plugin_source(
            tier,
            specialist=runtime_specialists.get(tier),
        )
        for tier in _TIERS
    }
    inventories = {
        "foundation": {"codex-copilot": "1" * 64},
        "organization": {"codex-copilot-internal": "2" * 64},
        "department": {
            "codex-copilot": "3" * 64,
            "codex-copilot-accounting": "4" * 64,
        },
    }
    monkeypatch.setattr(
        content_authority,
        "_codex_plugin_inventory",
        lambda layer: (
            primary[str(layer["role"])],
            inventories[str(layer["role"])],
        ),
    )

    def pack(**values):
        if not pack_enabled or values["specialist"] not in {"cco", "cpa"}:
            return None
        return _plugin_source(
            "foundation",
            specialist=values["specialist"],
            plugin_name="business-creative",
            source_kind="activated-pack",
            activation_sha256="a" * 64,
        )

    monkeypatch.setattr(content_authority, "_codex_pack_source", pack)
    monkeypatch.setattr(
        journey_runtime,
        "resolve_specialist_knowledge",
        lambda *_args: (
            "\n\n".join(knowledge_content),
            tuple(knowledge_receipts),
        ),
    )
    monkeypatch.setattr(
        knowledge_skill_source,
        "resolve_knowledge_skill_sources",
        lambda: tuple((item.repository_root, item) for item in knowledge_sources),
    )
    monkeypatch.setattr(
        knowledge_skill_source,
        "inspect_protected_knowledge_lock_projection",
        lambda _layer: None,
    )
    monkeypatch.setattr(entitlement, "is_protected_layer", lambda _layer: False)
    monkeypatch.setattr(entitlement, "entitlement_state_path", lambda: tmp_path)
    monkeypatch.setattr(entitlement, "current_login", lambda: None)

    def decisions(required, **_kwargs):
        return required, [
            SimpleNamespace(
                layer=str(layer["id"]),
                state="not-required",
                eligible=True,
                revision=None,
            )
            for layer in required
        ]

    monkeypatch.setattr(entitlement, "filter_eligible_layers", decisions)
    monkeypatch.setattr(
        entitlement,
        "bind_layer_decisions",
        lambda *_args, **_kwargs: (),
    )
    monkeypatch.setattr(
        entitlement,
        "run_under_binding_leases",
        lambda _bindings, action: (True, action()),
    )
    return manifest_path, lock_path


@pytest.mark.parametrize("specialist", ("cco", "cpa"))
def test_foundation_control_uses_exact_opt_in_business_creative_pack(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    specialist: str,
) -> None:
    manifest, lock = _configure_codex_authority(
        monkeypatch,
        tmp_path,
        variant=LayerVariant.FOUNDATION,
        specialist=specialist,
        runtime_specialists={tier: None for tier in _TIERS},
    )

    projection = issue_canonical_codex_content(
        variant=LayerVariant.FOUNDATION,
        specialist=specialist,
        case_id="eval-04" if specialist == "cco" else "eval-05",
        manifest_path=manifest,
        lock_path=lock,
    )
    try:
        assert verify_canonical_content_projection(projection)
        source = projection.runtime_projection.plugin_sources[0]
        runtime = next(
            row
            for row in projection.content_receipt.layers
            if row.product == "codex-copilot"
        )
        assert (source.plugin_name, source.source_kind) == (
            "business-creative",
            "activated-pack",
        )
        assert source.activation_sha256 == "a" * 64
        assert projection.runtime_projection.matrix_sha256 == PACKAGED_MATRIX_SHA256
        assert len(projection.runtime_projection.cell_plan_sha256) == 64
        assert runtime.resolution_action == "selected"
        assert runtime.materialized_destinations == (
            f"project-packs/business-creative/skills/{specialist}",
        )
    finally:
        projection.close()


@pytest.mark.parametrize(
    ("case_id", "variant", "specialist"),
    (
        ("eval-05", LayerVariant.FOUNDATION, "cco"),
        ("eval-04", LayerVariant.FOUNDATION, "cpa"),
        ("eval-07", LayerVariant.FOUNDATION, "doc"),
    ),
)
def test_codex_authority_rejects_wrong_case_route_or_variant_before_config_read(
    monkeypatch: pytest.MonkeyPatch,
    case_id: str,
    variant: LayerVariant,
    specialist: str,
) -> None:
    from cc.core import config

    monkeypatch.setattr(
        config,
        "resolve_key",
        lambda _key: pytest.fail("invalid cell plans must not read installed config"),
    )
    with pytest.raises(
        CanonicalContentUnavailable, match="canonical-cell-plan-invalid"
    ):
        issue_canonical_codex_content(
            variant=variant,
            specialist=specialist,
            case_id=case_id,
        )


def test_nearest_signed_plugin_shadows_activated_foundation_pack(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest, lock = _configure_codex_authority(
        monkeypatch,
        tmp_path,
        variant=LayerVariant.ORGANIZATION,
        specialist="cco",
        runtime_specialists={
            "foundation": None,
            "organization": "cco",
            "department": None,
        },
    )
    projection = issue_canonical_codex_content(
        variant=LayerVariant.ORGANIZATION,
        specialist="cco",
        case_id="eval-04",
        manifest_path=manifest,
        lock_path=lock,
    )
    try:
        assert verify_canonical_content_projection(projection)
        rows = [
            row
            for row in projection.content_receipt.layers
            if row.product == "codex-copilot"
        ]
        assert [row.resolution_action for row in rows] == ["shadowed", "selected"]
        assert rows[0].materialized_destinations == ()
        assert projection.runtime_projection.source_receipt["layer"] == (
            "codex-organization"
        )
        assert "Signed organization cco guidance." in (
            projection.runtime_projection.content
        )
    finally:
        projection.close()


def test_codex_runtime_source_receipt_is_immutable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest, lock = _configure_codex_authority(
        monkeypatch,
        tmp_path,
        variant=LayerVariant.ORGANIZATION,
        specialist="cco",
        runtime_specialists={
            "foundation": None,
            "organization": "cco",
            "department": None,
        },
    )
    projection = issue_canonical_codex_content(
        variant=LayerVariant.ORGANIZATION,
        specialist="cco",
        case_id="eval-04",
        manifest_path=manifest,
        lock_path=lock,
    )
    try:
        with pytest.raises(TypeError):
            projection.runtime_projection.source_receipt["layer"] = "substituted"
        assert verify_canonical_content_projection(projection)
    finally:
        projection.close()


@pytest.mark.parametrize("mutation", ("source-receipt", "content", "plugin"))
def test_parent_recomputes_complete_codex_runtime_projection_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: str,
) -> None:
    manifest, lock = _configure_codex_authority(
        monkeypatch,
        tmp_path,
        variant=LayerVariant.ORGANIZATION,
        specialist="cco",
        runtime_specialists={
            "foundation": None,
            "organization": "cco",
            "department": None,
        },
    )
    projection = issue_canonical_codex_content(
        variant=LayerVariant.ORGANIZATION,
        specialist="cco",
        case_id="eval-04",
        manifest_path=manifest,
        lock_path=lock,
    )
    runtime = projection.runtime_projection
    assert verify_canonical_content_projection(projection)
    if mutation == "source-receipt":
        object.__setattr__(
            runtime,
            "source_receipt",
            {**dict(runtime.source_receipt), "layer": "substituted-layer"},
        )
    elif mutation == "content":
        object.__setattr__(runtime, "content", "substituted content")
    else:
        first = replace(runtime.plugin_sources[0], layer="substituted-layer")
        object.__setattr__(
            runtime,
            "plugin_sources",
            (first, *runtime.plugin_sources[1:]),
        )

    assert not verify_canonical_content_projection(projection)
    projection.close()


def test_altered_codex_runtime_projection_copy_rejects_cached_identity() -> None:
    source = _plugin_source("foundation", specialist="sd")
    receipt = {
        "layer": source.layer,
        "tier": source.role,
        "repository": source.repository,
        "ref": source.ref,
        "tree": source.tree,
        "signer": source.signer,
        "contribution": "skills/sd/SKILL.md",
        "content_sha256": "a" * 64,
        "runtime": "codex",
        "adapter_version": source.adapter_version,
    }
    from cc.core.evaluation.content_authority import CanonicalCodexRuntimeProjection

    document = {
        "schema_version": "evaluation-codex-runtime-projection-v1",
        "matrix_sha256": PACKAGED_MATRIX_SHA256,
        "cell_plan_sha256": "b" * 64,
        "plugins": [
            {
                "layer": source.layer,
                "tier": source.role,
                "repository": source.repository,
                "relative_path": source.relative_path,
                "plugin_name": source.plugin_name,
                "source_kind": source.source_kind,
                "adapter_version": source.adapter_version,
                "activation_sha256": source.activation_sha256,
                "ref": source.ref,
                "tree": source.tree,
                "signer": source.signer,
                "release_tag": source.release_tag,
                "release_commit": source.release_commit,
                "release_tree": source.release_tree,
            }
        ],
        "selected_source": receipt,
        "selected_content_sha256": hashlib.sha256(b"signed").hexdigest(),
    }
    runtime = CanonicalCodexRuntimeProjection(
        matrix_sha256=PACKAGED_MATRIX_SHA256,
        cell_plan_sha256="b" * 64,
        plugin_sources=(source,),
        content="signed",
        source_receipt=receipt,
        projection_sha256=canonical_sha256(document),
    )

    with pytest.raises(ValueError, match="runtime projection is invalid"):
        replace(runtime, content="substituted")


def test_department_specialist_proves_absence_then_nearest_winner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest, lock = _configure_codex_authority(
        monkeypatch,
        tmp_path,
        variant=LayerVariant.DEPARTMENT,
        specialist="cpa",
        runtime_specialists={
            "foundation": None,
            "organization": None,
            "department": "cpa",
        },
    )
    projection = issue_canonical_codex_content(
        variant=LayerVariant.DEPARTMENT,
        specialist="cpa",
        case_id="eval-05",
        manifest_path=manifest,
        lock_path=lock,
    )
    try:
        rows = [
            row
            for row in projection.content_receipt.layers
            if row.product == "codex-copilot"
        ]
        assert [row.resolution_action for row in rows] == [
            "shadowed",
            "authenticated-absence",
            "selected",
        ]
        assert projection.runtime_projection.source_receipt["layer"] == (
            "codex-department"
        )
    finally:
        projection.close()


def test_missing_required_pack_activation_is_truthfully_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest, lock = _configure_codex_authority(
        monkeypatch,
        tmp_path,
        variant=LayerVariant.FOUNDATION,
        specialist="cco",
        runtime_specialists={tier: None for tier in _TIERS},
        pack_enabled=False,
    )
    with pytest.raises(
        CanonicalContentUnavailable, match="codex-specialist-unavailable"
    ):
        issue_canonical_codex_content(
            variant=LayerVariant.FOUNDATION,
            specialist="cco",
            case_id="eval-04",
            manifest_path=manifest,
            lock_path=lock,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("runtime", "codex"),
        ("repository", "Org/substituted"),
        ("layer", "knowledge-organization"),
        ("adapter_version", "codex-plugin-v1"),
        ("ref", "refs/tags/v9.9.9"),
        ("tree", "f" * 40),
    ),
)
def test_codex_authority_rejects_wrong_knowledge_source_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    from cc.core.evaluation import journey_runtime

    manifest, lock = _configure_codex_authority(
        monkeypatch,
        tmp_path,
        variant=LayerVariant.FOUNDATION,
        specialist="sd",
        runtime_specialists={
            "foundation": "sd",
            "organization": None,
            "department": None,
        },
    )
    resolver = journey_runtime.resolve_specialist_knowledge

    def changed(*args):
        payload, sources = resolver(*args)
        first = {**dict(sources[0]), field: value}
        return payload, (first, *sources[1:])

    monkeypatch.setattr(journey_runtime, "resolve_specialist_knowledge", changed)
    with pytest.raises(CanonicalContentUnavailable, match="signed-knowledge-mismatch"):
        issue_canonical_codex_content(
            variant=LayerVariant.FOUNDATION,
            specialist="sd",
            case_id="eval-01",
            manifest_path=manifest,
            lock_path=lock,
        )


@pytest.mark.parametrize("mode", ("missing", "ineligible", "substituted", "extra"))
def test_codex_authority_requires_exact_protected_entitlement_bindings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str,
) -> None:
    from cc.core.ecosystem import entitlement

    manifest, lock = _configure_codex_authority(
        monkeypatch,
        tmp_path,
        variant=LayerVariant.ORGANIZATION,
        specialist="cco",
        runtime_specialists={
            "foundation": None,
            "organization": "cco",
            "department": None,
        },
    )
    monkeypatch.setattr(
        entitlement,
        "is_protected_layer",
        lambda layer: layer["role"] == "organization",
    )
    monkeypatch.setattr(entitlement, "current_login", lambda: "test-user")

    def decisions(required, **_kwargs):
        return required, [
            SimpleNamespace(
                layer=str(layer["id"]),
                state=(
                    "entitled" if layer["role"] == "organization" else "not-required"
                ),
                eligible=True,
                revision=7 if layer["role"] == "organization" else None,
            )
            for layer in required
        ]

    monkeypatch.setattr(entitlement, "filter_eligible_layers", decisions)
    organization = SimpleNamespace(
        layer="codex-organization",
        repo=("Org/substituted" if mode == "substituted" else "Org/codex-organization"),
        login="test-user",
        revision=7,
        state="entitled",
        eligible=mode != "ineligible",
    )
    knowledge = SimpleNamespace(
        layer="knowledge-organization",
        repo="Org/knowledge-organization",
        login="test-user",
        revision=7,
        state="entitled",
        eligible=True,
    )
    bindings = [knowledge] if mode == "missing" else [organization, knowledge]
    if mode == "extra":
        bindings.append(
            SimpleNamespace(
                layer="codex-foundation",
                repo="Org/codex-foundation",
                login="test-user",
                revision=0,
                state="not-required",
                eligible=True,
            )
        )
    monkeypatch.setattr(
        entitlement,
        "bind_layer_decisions",
        lambda *_args, **_kwargs: tuple(bindings),
    )
    with pytest.raises(
        CanonicalContentUnavailable,
        match="entitlement-binding-invalid",
    ):
        issue_canonical_codex_content(
            variant=LayerVariant.ORGANIZATION,
            specialist="cco",
            case_id="eval-04",
            manifest_path=manifest,
            lock_path=lock,
        )


def test_personal_codex_authority_uses_only_eval07_synthetic_knowledge(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from cc.evaluation_fixtures.personal_snapshot import (
        materialize_personal_snapshot,
        verify_personal_snapshot_receipt,
    )

    tmp_path.chmod(0o700)
    manifest, lock = _configure_codex_authority(
        monkeypatch,
        tmp_path,
        variant=LayerVariant.PERSONAL,
        specialist="doc",
        runtime_specialists={
            "foundation": "doc",
            "organization": None,
            "department": None,
        },
        include_personal=True,
    )
    receipt = materialize_personal_snapshot(tmp_path / "codex-personal")
    projection = issue_canonical_codex_content(
        variant=LayerVariant.PERSONAL,
        specialist="doc",
        case_id="eval-07",
        personal_snapshot_receipt=receipt,
        manifest_path=manifest,
        lock_path=lock,
    )
    assert verify_canonical_content_projection(projection)
    assert [
        (row.product, row.resolution_action, row.contribution_ids)
        for row in projection.content_receipt.layers
        if row.tier == "personal"
    ] == [
        ("codex-copilot", "authenticated-absence", ()),
        ("knowledge", "accumulated", ("personal_layer/doc.md",)),
    ]
    projection.close()
    assert not verify_personal_snapshot_receipt(receipt)


@pytest.mark.parametrize("mutation", ("missing", "extra", "substituted"))
def test_global_plugin_lock_rejects_nonexact_rows(mutation: str) -> None:
    layers = _codex_layers(())[:3]
    inventories = {
        "codex-foundation": {"codex-copilot": "1" * 64},
        "codex-organization": {"codex-copilot-internal": "2" * 64},
        "codex-department": {
            "codex-copilot": "3" * 64,
            "codex-copilot-accounting": "4" * 64,
        },
    }
    lock = _global_lock()
    if mutation == "missing":
        del lock["codex-department"]["plugins"]["codex-copilot"]
    elif mutation == "extra":
        lock["codex-department"]["plugins"]["unreviewed"] = "5" * 64
    else:
        lock["codex-department"]["plugins"]["codex-copilot"] = "5" * 64
    with pytest.raises(CanonicalContentUnavailable, match="materialized-lock-mismatch"):
        _codex_global_lock_identity(
            layers=layers,
            inventories=inventories,
            lock=lock,
        )


def test_pack_activation_binds_case_route_matrix_and_signed_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cc.core.evaluation import content_authority

    foundation = _plugin_source(
        "foundation",
        specialist="sd",
        catalog=[{"id": "cco", "pack": "business-creative"}],
    )
    captured: dict[str, object] = {}

    def source_from_provenance(**values):
        captured.update(values)
        return _plugin_source(
            "foundation",
            specialist="cco",
            plugin_name="business-creative",
            source_kind="activated-pack",
            activation_sha256=values["activation_sha256"],
        )

    monkeypatch.setattr(
        content_authority,
        "_codex_source_from_provenance",
        source_from_provenance,
    )
    layer = _codex_layers(())[0]
    result = _codex_pack_source(
        foundation_layer=layer,
        foundation_plugin=foundation,
        specialist="cco",
        variant=LayerVariant.FOUNDATION,
        case_id="eval-04",
    )

    assert result is not None
    assert captured["relative_path"] == "packs/business-creative"
    assert captured["source_kind"] == "activated-pack"
    assert captured["adapter_version"] == "codex-pack-v1"
    assert result.activation_sha256 == captured["activation_sha256"]
    assert result.activation_sha256 != "0" * 64


@pytest.mark.parametrize(
    ("case_id", "specialist"),
    (("eval-05", "cco"), ("eval-04", "cpa")),
)
def test_pack_activation_rejects_wrong_case_or_specialist(
    case_id: str,
    specialist: str,
) -> None:
    foundation = _plugin_source(
        "foundation",
        specialist="sd",
        catalog=[{"id": specialist, "pack": "business-creative"}],
    )
    with pytest.raises(
        CanonicalContentUnavailable,
        match="signed-codex-pack-activation-invalid",
    ):
        _codex_pack_source(
            foundation_layer=_codex_layers(())[0],
            foundation_plugin=foundation,
            specialist=specialist,
            variant=LayerVariant.FOUNDATION,
            case_id=case_id,
        )


def test_pack_activation_rejects_missing_or_changed_signed_pack_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cc.core.evaluation import content_authority

    foundation = _plugin_source(
        "foundation",
        specialist="sd",
        catalog=[{"id": "cco", "pack": "business-creative"}],
    )
    changed = _plugin_source(
        "foundation",
        specialist="cco",
        plugin_name="business-creative",
        source_kind="activated-pack",
        activation_sha256="a" * 64,
    )
    files = {item.path: item.content for item in changed.snapshot.files}
    manifest = json.loads(files["pack.json"])
    manifest["activation"]["script"] = "scripts/unreviewed.py"
    files["pack.json"] = json.dumps(manifest).encode()
    changed = replace(changed, snapshot=_snapshot(files))
    monkeypatch.setattr(
        content_authority,
        "_codex_source_from_provenance",
        lambda **_values: changed,
    )
    with pytest.raises(
        CanonicalContentUnavailable,
        match="signed-codex-pack-activation-invalid",
    ):
        _codex_pack_source(
            foundation_layer=_codex_layers(())[0],
            foundation_plugin=foundation,
            specialist="cco",
            variant=LayerVariant.FOUNDATION,
            case_id="eval-04",
        )


@pytest.mark.parametrize(
    "mutation",
    ("repository-root", "relative-path", "ref", "release-root", "snapshot-tree"),
)
def test_codex_source_rejects_provenance_or_tree_substitution(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    from cc.core.ecosystem import policy
    from cc.core.evaluation import content_authority

    root = "/signed/codex-foundation"
    relative_path = "packs/business-creative"
    item_tree = "1" * 40
    repository_root = root
    returned_path = relative_path
    returned_ref = "v1.0.0"
    release_root = root
    snapshot_tree = item_tree
    if mutation == "repository-root":
        repository_root = "/signed/substituted"
    elif mutation == "relative-path":
        returned_path = "packs/substituted"
    elif mutation == "ref":
        returned_ref = "v9.9.9"
    elif mutation == "release-root":
        release_root = "/signed/substituted"
    else:
        snapshot_tree = "2" * 40
    provenance = SimpleNamespace(
        ref=returned_ref,
        tree=item_tree,
        signer=_SIGNER,
        repository_root=repository_root,
        relative_path=returned_path,
        release=SimpleNamespace(
            ref=returned_ref,
            tag="3" * 40,
            commit="4" * 40,
            tree="5" * 40,
            signer=_SIGNER,
            repository_root=release_root,
        ),
    )
    monkeypatch.setattr(
        policy,
        "verify_git_item_provenance",
        lambda *_args, **_kwargs: provenance,
    )
    monkeypatch.setattr(
        policy,
        "read_git_tree_snapshot",
        lambda *_args, **_kwargs: SimpleNamespace(
            tree=snapshot_tree,
            files=(SimpleNamespace(path="pack.json", content=b"{}"),),
        ),
    )
    monkeypatch.setattr(
        content_authority,
        "_origin",
        lambda _root: "Org/codex-foundation",
    )
    with pytest.raises(
        CanonicalContentUnavailable,
        match="signed-codex-source-(mismatch|invalid)",
    ):
        _codex_source_from_provenance(
            layer=_codex_layers(())[0],
            repository="Org/codex-foundation",
            plugin_name="business-creative",
            relative_path=relative_path,
            source_kind="activated-pack",
            adapter_version="codex-pack-v1",
            activation_sha256="a" * 64,
        )
