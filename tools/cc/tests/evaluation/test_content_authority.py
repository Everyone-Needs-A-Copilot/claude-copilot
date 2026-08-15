from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from cc.core.evaluation.artifact import (
    load_durable_unsupported_run,
    verify_artifact_receipt,
    write_run_record,
)
from cc.core.evaluation.content_authority import (
    CanonicalContentUnavailable,
    _release_for_agent,
    issue_canonical_claude_content,
    verify_canonical_content_projection,
)
from cc.core.evaluation.fixtures import load_fixture
from cc.core.evaluation.identity import build_consumption_receipt
from cc.core.evaluation.matrix import prompt_evidence_identity
from cc.core.evaluation.models import (
    GateState,
    LayerVariant,
    PreflightGate,
    RunState,
    RuntimeName,
)
from cc.core.evaluation.preflight import evaluate_preflight
from cc.core.evaluation.runner import EvaluationRunner
from test_runner_core import _cell as core_cell
from test_runner_core import _observations

_SIGNER = "SHA256:abcdefgh"


def _git(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", *arguments),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _signed_agent_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "signed-agent"
    repo.mkdir()
    key = tmp_path / "release-key"
    subprocess.run(
        ("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)),
        check=True,
    )
    fingerprint = subprocess.run(
        ("ssh-keygen", "-lf", f"{key}.pub", "-E", "sha256"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()[1]
    public_key = " ".join(
        key.with_suffix(".pub").read_text(encoding="utf-8").split()[:2]
    )
    _git(repo, "init", "-q")
    for key_name, value in (
        ("user.name", "Evaluation Release Test"),
        ("user.email", "evaluation@example.invalid"),
        ("gpg.format", "ssh"),
        ("user.signingkey", str(key)),
    ):
        _git(repo, "config", key_name, value)
    _git(
        repo,
        "remote",
        "add",
        "origin",
        "git@github.com:Example/signed-agent.git",
    )
    agents = repo / "agents"
    agents.mkdir()
    (agents / "sd.md").write_text("Signed service designer.\n", encoding="utf-8")
    _git(repo, "add", "agents/sd.md")
    _git(repo, "commit", "-q", "--no-gpg-sign", "-m", "agent")
    _git(repo, "tag", "-s", "v1.0.0", "-m", "release")
    return repo, fingerprint, public_key


class _Release:
    def __init__(self, *, tree: str, blobs: dict[str, bytes]) -> None:
        self.tag = tree[:40]
        self.commit = tree[::-1][:40]
        self.tree = tree
        self._blobs = blobs

    def read_blob(self, path: str) -> bytes:
        try:
            return self._blobs[path]
        except KeyError as exc:
            raise ValueError(path) from exc


def _layers(
    tiers: tuple[str, ...] = ("foundation", "organization"),
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for product in ("knowledge", "claude"):
        for tier in tiers:
            repository = f"Org/{product}-{tier}"
            rows.append(
                {
                    "id": f"{product}-{tier}",
                    "product": product,
                    "role": tier,
                    "source": {
                        "repo": repository,
                        "path": f"/signed/{product}-{tier}",
                        "ref": "v1.0.0",
                    },
                    "policy": {"allowed_signers": [_SIGNER]},
                }
            )
    return rows


def _configure_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    projected_tier: str = "foundation",
    winner_lock_sha256: str | None = None,
    knowledge_runtime: str = "claude",
    binding_mode: str = "public",
    tiers: tuple[str, ...] = ("foundation", "organization"),
    specialist: str = "sd",
    include_personal_source: bool = False,
    knowledge_projection_by_tier: dict[str, object] | None = None,
    protected_tiers: tuple[str, ...] = ("organization",),
    knowledge_plugin_mode: str | None = None,
) -> tuple[Path, Path]:
    from cc.core.ecosystem import entitlement, knowledge_skill_source
    from cc.core.evaluation import content_authority, journey_runtime, live_runtime

    manifest_path = tmp_path / "layers.yml"
    lock_path = tmp_path / "copilot.lock.json"
    manifest_path.write_text("version: 1\nlayers: []\n", encoding="utf-8")
    layers = _layers(tiers)
    foundation_agent = f"Signed foundation {specialist} specialist.".encode()
    selected_sha256 = hashlib.sha256(foundation_agent).hexdigest()
    lock = {}
    for tier in tiers:
        lock[f"knowledge-{tier}"] = {
            "_meta": {
                "product": "knowledge",
                "role": tier,
                "tier": tier,
            }
        }
        lock[f"claude-{tier}"] = {
            "_meta": {
                "product": "claude",
                "role": tier,
                "tier": tier,
            },
            "agents": (
                {specialist: winner_lock_sha256 or selected_sha256}
                if tier == "foundation"
                else {}
            ),
        }
    monkeypatch.setattr(content_authority, "_manifest_layers", lambda _raw: layers)
    monkeypatch.setattr(
        content_authority,
        "_origin",
        lambda root: f"Org/{root.name}",
    )

    knowledge_sources = []
    for index, tier in enumerate(tiers, start=1):
        tree = str(index) * 40
        manifest = {
            "extensions": (
                [{"agent": specialist, "file": f"skills/{specialist}.md"}]
                if tier == "foundation"
                else []
            )
        }
        blobs = {"knowledge-manifest.json": json.dumps(manifest).encode()}
        if tier == "foundation":
            blobs[f"skills/{specialist}.md"] = b"Signed foundation Knowledge."
        release = _Release(tree=tree, blobs=blobs)
        knowledge_sources.append(
            SimpleNamespace(
                role=tier,
                layer=f"knowledge-{tier}",
                repository=f"Org/knowledge-{tier}",
                repository_root=Path(f"/signed/knowledge-{tier}"),
                ref="v1.0.0",
                tree=tree,
                release=release,
                signer=_SIGNER,
            )
        )
    foundation_source = {
        "layer": "knowledge-foundation",
        "role": "foundation",
        "repository": "Org/knowledge-foundation",
        "ref": "refs/tags/v1.0.0",
        "tree": "1" * 40,
        "signer": _SIGNER,
        "contribution": f"skills/{specialist}.md",
        "content_sha256": hashlib.sha256(b"Signed foundation Knowledge.").hexdigest(),
        "runtime": knowledge_runtime,
        "adapter_version": "knowledge-contribution-v1",
    }
    knowledge_payload = "Signed foundation Knowledge."
    knowledge_receipts = (foundation_source,)
    if include_personal_source:
        from cc.evaluation_fixtures.personal_snapshot import (
            personal_snapshot_contribution,
        )

        personal_content, personal_source = personal_snapshot_contribution(
            runtime="claude"
        )
        knowledge_payload = f"{knowledge_payload}\n\n{personal_content}"
        knowledge_receipts = (*knowledge_receipts, personal_source)
    monkeypatch.setattr(
        journey_runtime,
        "resolve_specialist_knowledge",
        lambda _specialist, _variant, _runtime: (
            knowledge_payload,
            knowledge_receipts,
        ),
    )
    monkeypatch.setattr(
        knowledge_skill_source,
        "resolve_knowledge_skill_sources",
        lambda: tuple((source.repository_root, source) for source in knowledge_sources),
    )
    projection_by_tier = dict(knowledge_projection_by_tier or {})
    if knowledge_plugin_mode is not None:
        from cc.core.ecosystem.knowledge_skill_source import (
            ProtectedKnowledgeLockProjection,
        )

        source = next(item for item in knowledge_sources if item.role == "department")
        projection_by_tier["department"] = ProtectedKnowledgeLockProjection(
            layer=source.layer,
            repository=source.repository,
            ref=source.ref,
            tree=source.tree,
            signer=source.signer,
            binding="b" * 64,
            item_tree="9" * 40,
            release_tree=source.release.tree,
            content_sha256="e" * 64,
        )
        if knowledge_plugin_mode != "missing":
            lock["knowledge-department"]["plugins"] = {
                "codex-copilot": (
                    "f" * 64 if knowledge_plugin_mode == "substituted" else "e" * 64
                )
            }
        if knowledge_plugin_mode == "extra":
            lock["knowledge-department"]["plugins"]["unreviewed"] = "d" * 64
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    manifest_path.chmod(0o600)
    lock_path.chmod(0o600)
    monkeypatch.setattr(content_authority, "_lock_document", lambda _raw: lock)
    monkeypatch.setattr(
        knowledge_skill_source,
        "inspect_protected_knowledge_lock_projection",
        lambda layer: projection_by_tier.get(str(layer["role"])),
    )

    foundation_provenance = SimpleNamespace(
        ref="v1.0.0",
        tree="3" * 40,
        signer=_SIGNER,
        release=SimpleNamespace(
            tag="4" * 40,
            commit="5" * 40,
            tree="3" * 40,
        ),
    )

    def release_for_agent(layer, _specialist):
        if layer["role"] == "foundation":
            return (
                "Org/claude-foundation",
                foundation_provenance,
                f"agents/{specialist}.md",
                foundation_agent,
            )
        return (
            f"Org/claude-{layer['role']}",
            SimpleNamespace(
                ref="v1.0.0",
                tree="6" * 40,
                signer=_SIGNER,
                release=SimpleNamespace(
                    tag="7" * 40,
                    commit="8" * 40,
                    tree="6" * 40,
                ),
            ),
            f"agents/{specialist}.md",
            None,
        )

    monkeypatch.setattr(content_authority, "_release_for_agent", release_for_agent)
    projected = {
        "layer": f"claude-{projected_tier}",
        "tier": projected_tier,
        "repository": f"Org/claude-{projected_tier}",
        "ref": "refs/tags/v1.0.0",
        "tree": "3" * 40 if projected_tier == "foundation" else "6" * 40,
        "signer": _SIGNER,
        "contribution": f"agents/{specialist}.md",
        "content_sha256": selected_sha256,
    }
    monkeypatch.setattr(
        live_runtime,
        "resolve_claude_agent_projection",
        lambda _variant, _specialist: SimpleNamespace(source_receipt=projected),
    )
    decisions = [
        SimpleNamespace(
            layer=str(layer["id"]),
            state=(
                "entitled"
                if binding_mode != "public" and layer["role"] in protected_tiers
                else "not-required"
            ),
            eligible=True,
            responsible_actor="publisher",
            recovery="none",
            checked_at=None,
            expires_at=None,
            revision=(
                7
                if binding_mode != "public" and layer["role"] in protected_tiers
                else None
            ),
            superseded=False,
        )
        for layer in layers
    ]
    monkeypatch.setattr(
        entitlement,
        "filter_eligible_layers",
        lambda required, **_kwargs: (required, decisions[: len(required)]),
    )
    monkeypatch.setattr(
        entitlement,
        "is_protected_layer",
        lambda layer: binding_mode != "public" and layer["role"] in protected_tiers,
    )
    monkeypatch.setattr(entitlement, "current_login", lambda: "test-user")
    protected_bindings = [
        SimpleNamespace(
            layer=str(layer["id"]),
            repo=str(layer["source"]["repo"]),
            login="test-user",
            revision=7,
            state="entitled",
            eligible=binding_mode != "ineligible",
        )
        for layer in layers
        if binding_mode != "public" and layer["role"] in protected_tiers
    ]
    if binding_mode == "missing":
        protected_bindings = protected_bindings[:1]
    elif binding_mode == "substituted":
        protected_bindings[0].repo = "Org/substituted"
    monkeypatch.setattr(
        entitlement,
        "bind_layer_decisions",
        lambda *_args, **_kwargs: tuple(protected_bindings),
    )
    monkeypatch.setattr(
        entitlement,
        "run_under_binding_leases",
        lambda _bindings, action: (True, action()),
    )
    return manifest_path, lock_path


def test_canonical_authority_issues_inherited_signed_projection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest, lock = _configure_authority(monkeypatch, tmp_path)

    projection = issue_canonical_claude_content(
        variant=LayerVariant.ORGANIZATION,
        specialist="sd",
        manifest_path=manifest,
        lock_path=lock,
    )

    assert verify_canonical_content_projection(projection)
    assert [
        (row.product, row.tier, row.resolution_action)
        for row in projection.content_receipt.layers
    ] == [
        ("claude-copilot", "foundation", "selected"),
        ("knowledge", "foundation", "accumulated"),
        ("claude-copilot", "organization", "authenticated-absence"),
        ("knowledge", "organization", "authenticated-absence"),
    ]
    assert not verify_canonical_content_projection(
        replace(projection, knowledge_payload="Changed signed payload.")
    )


@pytest.mark.parametrize("target_name", ("manifest", "lock"))
def test_canonical_projection_retains_manifest_and_lock_until_use(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    target_name: str,
) -> None:
    manifest, lock = _configure_authority(monkeypatch, tmp_path)
    projection = issue_canonical_claude_content(
        variant=LayerVariant.ORGANIZATION,
        specialist="sd",
        manifest_path=manifest,
        lock_path=lock,
    )
    assert verify_canonical_content_projection(projection)
    target = manifest if target_name == "manifest" else lock
    replacement = target.with_suffix(".replacement")
    replacement.write_bytes(target.read_bytes())
    replacement.chmod(0o600)
    replacement.replace(target)
    assert not verify_canonical_content_projection(projection)


def test_repeated_projection_use_is_explicitly_revoked_without_fd_growth(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest, lock = _configure_authority(monkeypatch, tmp_path)
    baseline = len(os.listdir("/dev/fd"))
    for _index in range(36):
        projection = issue_canonical_claude_content(
            variant=LayerVariant.ORGANIZATION,
            specialist="sd",
            manifest_path=manifest,
            lock_path=lock,
        )
        assert verify_canonical_content_projection(projection)
        projection.close()
        assert not verify_canonical_content_projection(projection)
    assert len(os.listdir("/dev/fd")) <= baseline + 2


@pytest.mark.parametrize("target_name", ("manifest", "lock"))
def test_terminal_exception_cannot_bypass_post_use_config_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    target_name: str,
) -> None:
    from cc.core.evaluation.live_runtime import RuntimeTerminalFailure

    manifest, lock = _configure_authority(monkeypatch, tmp_path)
    projection = issue_canonical_claude_content(
        variant=LayerVariant.ORGANIZATION,
        specialist="sd",
        manifest_path=manifest,
        lock_path=lock,
    )
    target = manifest if target_name == "manifest" else lock

    def timed_out_after_swap():
        replacement = target.with_suffix(".terminal-swap")
        replacement.write_bytes(target.read_bytes())
        replacement.chmod(0o600)
        replacement.replace(target)
        raise RuntimeTerminalFailure("runtime-timeout")

    with pytest.raises(CanonicalContentUnavailable, match="canonical-config-changed"):
        projection.run_authorized(timed_out_after_swap)


def test_runtime_timeout_after_config_swap_is_invalid_and_not_retriable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from cc.core.evaluation._authority import (
        _cell_subject,
        _issue_evaluation_authority,
    )
    from cc.core.evaluation.live_runtime import RuntimeTerminalFailure

    manifest, lock = _configure_authority(monkeypatch, tmp_path)
    projection = issue_canonical_claude_content(
        variant=LayerVariant.ORGANIZATION,
        specialist="sd",
        manifest_path=manifest,
        lock_path=lock,
    )
    loaded = load_fixture(Path(__file__).parent / "fixtures" / "cases" / "eval-01")
    cell = _production_cell(projection, loaded)
    subject = _cell_subject(cell)
    authority = _issue_evaluation_authority(
        subject,
        evaluate_preflight(_observations(), subject_sha256=subject),
        content_projection=projection,
    )

    class Runtime:
        calls = 0

        def execute(self, _cell):
            self.calls += 1
            replacement = lock.with_suffix(".timeout-swap")
            replacement.write_bytes(lock.read_bytes())
            replacement.chmod(0o600)
            replacement.replace(lock)
            raise RuntimeTerminalFailure("runtime-timeout")

    runtime = Runtime()
    with patch(
        "cc.core.evaluation.runner._production_authority",
        return_value=authority,
    ):
        record = EvaluationRunner(runtime).run(cell)
    assert runtime.calls == 1
    assert record.state is RunState.INVALID
    assert record.technical_error_reason is None
    assert record.technical_error_evidence_sha256 is None
    entitlement = next(
        item
        for item in record.preflight.observations
        if item.gate is PreflightGate.ENTITLEMENT_AND_PINS
    )
    assert entitlement.state is GateState.FAIL
    assert entitlement.reason == "canonical-config-changed"


def test_runner_finally_revokes_content_authority_after_terminal_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from cc.core.evaluation._authority import (
        _cell_subject,
        _issue_evaluation_authority,
    )

    manifest, lock = _configure_authority(monkeypatch, tmp_path)
    projection = issue_canonical_claude_content(
        variant=LayerVariant.ORGANIZATION,
        specialist="sd",
        manifest_path=manifest,
        lock_path=lock,
    )
    loaded = load_fixture(Path(__file__).parent / "fixtures" / "cases" / "eval-01")
    cell = _production_cell(projection, loaded)
    subject = _cell_subject(cell)
    authority = _issue_evaluation_authority(
        subject,
        evaluate_preflight(_observations(), subject_sha256=subject),
        content_projection=projection,
    )

    class Runtime:
        def execute(self, _cell):
            return object()

    with patch(
        "cc.core.evaluation.runner._production_authority",
        return_value=authority,
    ):
        record = EvaluationRunner(Runtime()).run(cell)
    assert record.state is RunState.INVALID
    assert not authority.applies_to(cell)
    assert not verify_canonical_content_projection(projection)


def test_protected_content_requires_exact_current_entitlement_bindings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest, lock = _configure_authority(
        monkeypatch,
        tmp_path,
        binding_mode="exact",
    )
    projection = issue_canonical_claude_content(
        variant=LayerVariant.ORGANIZATION,
        specialist="sd",
        manifest_path=manifest,
        lock_path=lock,
    )
    assert verify_canonical_content_projection(projection)


@pytest.mark.parametrize("binding_mode", ("missing", "ineligible", "substituted"))
def test_protected_content_rejects_binding_coverage_or_identity_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    binding_mode: str,
) -> None:
    manifest, lock = _configure_authority(
        monkeypatch,
        tmp_path,
        binding_mode=binding_mode,
    )
    with pytest.raises(
        CanonicalContentUnavailable, match="entitlement-binding-invalid"
    ):
        issue_canonical_claude_content(
            variant=LayerVariant.ORGANIZATION,
            specialist="sd",
            manifest_path=manifest,
            lock_path=lock,
        )


def test_protected_content_rejects_changed_lease_before_issuance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from cc.core.ecosystem import entitlement

    manifest, lock = _configure_authority(
        monkeypatch,
        tmp_path,
        binding_mode="exact",
    )
    monkeypatch.setattr(
        entitlement,
        "run_under_binding_leases",
        lambda _bindings, _action: (False, None),
    )
    with pytest.raises(CanonicalContentUnavailable, match="entitlement-changed"):
        issue_canonical_claude_content(
            variant=LayerVariant.ORGANIZATION,
            specialist="sd",
            manifest_path=manifest,
            lock_path=lock,
        )


def test_protected_content_rechecks_lease_while_runtime_uses_projection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from cc.core.ecosystem import entitlement

    manifest, lock = _configure_authority(
        monkeypatch,
        tmp_path,
        binding_mode="exact",
    )
    projection = issue_canonical_claude_content(
        variant=LayerVariant.ORGANIZATION,
        specialist="sd",
        manifest_path=manifest,
        lock_path=lock,
    )
    monkeypatch.setattr(
        entitlement,
        "run_under_binding_leases",
        lambda _bindings, _action: (False, None),
    )
    called = False

    def runtime_action():
        nonlocal called
        called = True

    with pytest.raises(CanonicalContentUnavailable, match="entitlement-changed"):
        projection.run_authorized(runtime_action)
    assert not called


def test_terminal_exception_cannot_bypass_post_use_lease_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from cc.core.ecosystem import entitlement
    from cc.core.evaluation.live_runtime import RuntimeTerminalFailure

    manifest, lock = _configure_authority(
        monkeypatch,
        tmp_path,
        binding_mode="exact",
    )
    projection = issue_canonical_claude_content(
        variant=LayerVariant.ORGANIZATION,
        specialist="sd",
        manifest_path=manifest,
        lock_path=lock,
    )
    lease_calls = 0

    def lease(_bindings, action):
        nonlocal lease_calls
        lease_calls += 1
        if lease_calls == 1:
            return True, action()
        return False, None

    monkeypatch.setattr(entitlement, "run_under_binding_leases", lease)

    def timeout():
        raise RuntimeTerminalFailure("runtime-timeout")

    with pytest.raises(CanonicalContentUnavailable, match="entitlement-changed"):
        projection.run_authorized(timeout)
    assert lease_calls == 2


def test_agent_source_is_read_from_real_signed_tag_object(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from cc.core.ecosystem import policy

    repo, fingerprint, public_key = _signed_agent_repo(tmp_path)
    monkeypatch.setattr(
        policy,
        "FOUNDATION_SSH_SIGNING_KEYS",
        {fingerprint: public_key},
    )
    layer = {
        "source": {
            "repo": "Example/signed-agent",
            "path": str(repo),
            "ref": "v1.0.0",
        },
        "policy": {"allowed_signers": [fingerprint]},
    }

    repository, provenance, contribution, content = _release_for_agent(layer, "sd")

    assert repository == "Example/signed-agent"
    assert provenance.signer == fingerprint
    assert contribution == "agents/sd.md"
    assert content == b"Signed service designer.\n"
    layer["policy"] = {"allowed_signers": [_SIGNER]}
    with pytest.raises(CanonicalContentUnavailable, match="signed-source-unverified"):
        _release_for_agent(layer, "sd")


def test_canonical_authority_rejects_materialized_winner_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest, lock = _configure_authority(
        monkeypatch,
        tmp_path,
        winner_lock_sha256="f" * 64,
    )
    with pytest.raises(CanonicalContentUnavailable, match="materialized-lock-mismatch"):
        issue_canonical_claude_content(
            variant=LayerVariant.ORGANIZATION,
            specialist="sd",
            manifest_path=manifest,
            lock_path=lock,
        )


def test_canonical_authority_rejects_false_higher_tier_winner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest, lock = _configure_authority(
        monkeypatch,
        tmp_path,
        projected_tier="organization",
    )
    with pytest.raises(CanonicalContentUnavailable, match="claude-specialist-mismatch"):
        issue_canonical_claude_content(
            variant=LayerVariant.ORGANIZATION,
            specialist="sd",
            manifest_path=manifest,
            lock_path=lock,
        )


def test_canonical_authority_rejects_wrong_knowledge_runtime_label(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest, lock = _configure_authority(
        monkeypatch,
        tmp_path,
        knowledge_runtime="codex",
    )
    with pytest.raises(CanonicalContentUnavailable, match="signed-knowledge-mismatch"):
        issue_canonical_claude_content(
            variant=LayerVariant.ORGANIZATION,
            specialist="sd",
            manifest_path=manifest,
            lock_path=lock,
        )


def test_department_knowledge_lock_binds_exact_signed_plugin_projection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest, lock = _configure_authority(
        monkeypatch,
        tmp_path,
        tiers=("foundation", "organization", "department"),
        specialist="cpa",
        binding_mode="exact",
        protected_tiers=("department",),
        knowledge_plugin_mode="exact",
    )

    projection = issue_canonical_claude_content(
        variant=LayerVariant.DEPARTMENT,
        specialist="cpa",
        manifest_path=manifest,
        lock_path=lock,
    )

    department = next(
        row
        for row in projection.content_receipt.layers
        if row.product == "knowledge" and row.tier == "department"
    )
    assert verify_canonical_content_projection(projection)
    assert department.resolution_action == "authenticated-absence"
    assert department.lock_sha256 != hashlib.sha256(lock.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    ("mode", "reason"),
    (
        ("missing", "materialized-lock-mismatch"),
        ("substituted", "materialized-lock-mismatch"),
        ("extra", "materialized-lock-mismatch"),
    ),
)
def test_department_knowledge_lock_rejects_missing_extra_or_substituted_plugin_pin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str,
    reason: str,
) -> None:
    manifest, lock = _configure_authority(
        monkeypatch,
        tmp_path,
        tiers=("foundation", "organization", "department"),
        specialist="cpa",
        binding_mode="exact",
        protected_tiers=("department",),
        knowledge_plugin_mode=mode,
    )
    with pytest.raises(CanonicalContentUnavailable, match=reason):
        issue_canonical_claude_content(
            variant=LayerVariant.DEPARTMENT,
            specialist="cpa",
            manifest_path=manifest,
            lock_path=lock,
        )


def test_personal_authority_blocks_without_reading_real_personal_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cc.core import config

    monkeypatch.setattr(
        config,
        "resolve_key",
        lambda _key: pytest.fail("real personal configuration must not be read"),
    )
    with pytest.raises(
        CanonicalContentUnavailable, match="personal-snapshot-unavailable"
    ):
        issue_canonical_claude_content(
            variant=LayerVariant.PERSONAL,
            specialist="doc",
        )


def test_personal_authority_uses_only_exact_eval07_snapshot_and_inherited_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from cc.evaluation_fixtures.personal_snapshot import (
        materialize_personal_snapshot,
        verify_personal_snapshot_receipt,
    )

    tmp_path.chmod(0o700)
    manifest, lock = _configure_authority(
        monkeypatch,
        tmp_path,
        tiers=("foundation", "organization", "department"),
        specialist="doc",
        include_personal_source=True,
    )
    personal_receipt = materialize_personal_snapshot(tmp_path / "personal-content")

    projection = issue_canonical_claude_content(
        variant=LayerVariant.PERSONAL,
        specialist="doc",
        case_id="eval-07",
        personal_snapshot_receipt=personal_receipt,
        manifest_path=manifest,
        lock_path=lock,
    )

    assert verify_canonical_content_projection(projection)
    assert [
        (row.product, row.tier, row.resolution_action)
        for row in projection.content_receipt.layers
    ] == [
        ("claude-copilot", "foundation", "selected"),
        ("knowledge", "foundation", "accumulated"),
        ("claude-copilot", "organization", "authenticated-absence"),
        ("knowledge", "organization", "authenticated-absence"),
        ("claude-copilot", "department", "authenticated-absence"),
        ("knowledge", "department", "authenticated-absence"),
        ("claude-copilot", "personal", "authenticated-absence"),
        ("knowledge", "personal", "accumulated"),
    ]
    personal_rows = [
        row for row in projection.content_receipt.layers if row.tier == "personal"
    ]
    assert all(
        row.repository_identifier == "cc/evaluation-fixtures" for row in personal_rows
    )
    assert personal_rows[0].contribution_ids == ()
    assert personal_rows[1].contribution_ids == ("personal_layer/doc.md",)
    projection.close()
    assert not verify_canonical_content_projection(projection)
    assert not verify_personal_snapshot_receipt(personal_receipt)


def test_non_eval07_personal_authority_attests_absence_and_does_not_consume_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from cc.evaluation_fixtures.personal_snapshot import (
        materialize_personal_snapshot,
        verify_personal_snapshot_receipt,
    )

    tmp_path.chmod(0o700)
    manifest, lock = _configure_authority(
        monkeypatch,
        tmp_path,
        tiers=("foundation", "organization", "department"),
        specialist="sd",
    )
    receipt = materialize_personal_snapshot(tmp_path / "personal-content")

    with pytest.raises(
        CanonicalContentUnavailable,
        match="personal-snapshot-unexpected",
    ):
        issue_canonical_claude_content(
            variant=LayerVariant.PERSONAL,
            specialist="sd",
            case_id="eval-01",
            personal_snapshot_receipt=receipt,
            manifest_path=manifest,
            lock_path=lock,
        )
    projection = issue_canonical_claude_content(
        variant=LayerVariant.PERSONAL,
        specialist="sd",
        case_id="eval-01",
        manifest_path=manifest,
        lock_path=lock,
    )

    assert verify_canonical_content_projection(projection)
    assert [
        (row.product, row.resolution_action)
        for row in projection.content_receipt.layers
        if row.tier == "personal"
    ] == [
        ("claude-copilot", "authenticated-absence"),
        ("knowledge", "authenticated-absence"),
    ]
    projection.close()
    assert verify_personal_snapshot_receipt(receipt)


def test_projection_double_close_never_closes_reused_snapshot_descriptors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from cc.evaluation_fixtures.personal_snapshot import materialize_personal_snapshot

    tmp_path.chmod(0o700)
    manifest, lock = _configure_authority(
        monkeypatch,
        tmp_path,
        tiers=("foundation", "organization", "department"),
        specialist="doc",
        include_personal_source=True,
    )
    receipt = materialize_personal_snapshot(tmp_path / "personal-content")
    projection = issue_canonical_claude_content(
        variant=LayerVariant.PERSONAL,
        specialist="doc",
        case_id="eval-07",
        personal_snapshot_receipt=receipt,
        manifest_path=manifest,
        lock_path=lock,
    )
    capability = receipt._capability
    retained = {
        capability.parent_descriptor,
        capability.root_descriptor,
        *(descriptor for _name, descriptor in capability.file_descriptors),
    }

    projection.close()
    unrelated: list[int] = []
    try:
        while not retained.issubset(unrelated):
            unrelated.append(os.open("/dev/null", os.O_RDONLY))
            assert len(unrelated) <= max(retained) + len(retained) + 8

        projection.close()

        for descriptor in retained:
            os.fstat(descriptor)
    finally:
        for descriptor in unrelated:
            os.close(descriptor)


def test_copied_projection_close_cannot_revoke_authentic_projection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest, lock = _configure_authority(monkeypatch, tmp_path)
    projection = issue_canonical_claude_content(
        variant=LayerVariant.ORGANIZATION,
        specialist="sd",
        manifest_path=manifest,
        lock_path=lock,
    )

    copied = copy.copy(projection)
    assert not verify_canonical_content_projection(copied)
    copied.close()
    assert verify_canonical_content_projection(projection)

    projection.close()
    projection.close()
    assert not verify_canonical_content_projection(projection)


def test_runner_routes_one_shot_snapshot_only_to_exact_eval07_personal_cell(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from cc.evaluation_fixtures.personal_snapshot import (
        materialize_personal_snapshot,
        verify_personal_snapshot_receipt,
    )

    receipt = materialize_personal_snapshot(tmp_path / "personal-content")
    observed: list[object | None] = []

    class Authority:
        def close(self) -> None:
            return None

    def issue(_cell, **kwargs):
        observed.append(kwargs["personal_snapshot_receipt"])
        return Authority()

    def finish(_runner, cell, _authority):
        return cell

    monkeypatch.setattr("cc.core.evaluation.runner._production_authority", issue)
    monkeypatch.setattr(EvaluationRunner, "_run_authorized", finish)
    runner = EvaluationRunner(
        SimpleNamespace(execute=lambda _cell: None),
        personal_snapshot_receipt=receipt,
    )

    runner.run(core_cell(LayerVariant.ORGANIZATION, case_id="eval-01"))
    assert observed == [None]
    assert verify_personal_snapshot_receipt(receipt)

    runner.run(core_cell(LayerVariant.PERSONAL, case_id="eval-07"))
    assert observed == [None, receipt]
    assert verify_personal_snapshot_receipt(receipt)


@pytest.mark.parametrize(
    ("case_id", "specialist"),
    (("eval-06", "doc"), ("eval-07", "sd")),
)
def test_personal_authority_rejects_case_or_specialist_substitution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    case_id: str,
    specialist: str,
) -> None:
    from cc.evaluation_fixtures.personal_snapshot import materialize_personal_snapshot

    tmp_path.chmod(0o700)
    receipt = materialize_personal_snapshot(tmp_path / "personal-content")
    with pytest.raises(
        CanonicalContentUnavailable,
        match="personal-snapshot-unavailable",
    ):
        issue_canonical_claude_content(
            variant=LayerVariant.PERSONAL,
            specialist=specialist,
            case_id=case_id,
            personal_snapshot_receipt=receipt,
        )


def _production_cell(projection, loaded):
    original = core_cell(LayerVariant.ORGANIZATION, case_id="eval-01")
    prompt_sha256 = prompt_evidence_identity(loaded)
    consumption = build_consumption_receipt(
        task_id=original.consumption_receipt.task_id,
        runtime_receipt=original.runtime_receipt,
        content_receipt=projection.content_receipt,
        prompt_evidence_sha256=prompt_sha256,
        journey_evidence_sha256=original.consumption_receipt.journey_evidence_sha256,
        route_evidence_sha256=original.consumption_receipt.route_evidence_sha256,
        continuity_evidence_sha256=(
            original.consumption_receipt.continuity_evidence_sha256
        ),
    )
    return replace(
        original,
        fixture_sha256=loaded.fixture_sha256,
        prompt_evidence_sha256=prompt_sha256,
        content_receipt=projection.content_receipt,
        consumption_receipt=consumption,
    )


def _codex_production_cell(loaded):
    original = core_cell(LayerVariant.ORGANIZATION, case_id="eval-01")
    runtime = replace(
        original.runtime_receipt,
        runtime=RuntimeName.CODEX,
        adapter_name="codex-exec",
        adapter_version="v1-test",
    )
    layers = tuple(
        replace(
            row,
            product=(
                "codex-copilot" if row.product == "claude-copilot" else row.product
            ),
            source_runtime=RuntimeName.CODEX.value,
            source_adapter_version=(
                "codex-plugin-v1"
                if row.product == "claude-copilot"
                else row.source_adapter_version
            ),
            repository_identifier=row.repository_identifier.replace(
                "claude-copilot",
                "codex-copilot",
            ),
        )
        for row in original.content_receipt.layers
    )
    content = replace(original.content_receipt, layers=layers)
    prompt_sha256 = prompt_evidence_identity(loaded)
    consumption = build_consumption_receipt(
        task_id=original.consumption_receipt.task_id,
        runtime_receipt=runtime,
        content_receipt=content,
        prompt_evidence_sha256=prompt_sha256,
        journey_evidence_sha256=original.consumption_receipt.journey_evidence_sha256,
        route_evidence_sha256=original.consumption_receipt.route_evidence_sha256,
        continuity_evidence_sha256=(
            original.consumption_receipt.continuity_evidence_sha256
        ),
    )
    return replace(
        original,
        fixture_sha256=loaded.fixture_sha256,
        prompt_evidence_sha256=prompt_sha256,
        runtime_receipt=runtime,
        content_receipt=content,
        consumption_receipt=consumption,
    )


def _journey_state(cell, projection) -> dict[str, object]:
    return {
        "task_id": cell.consumption_receipt.task_id,
        "run_id": "task-285-evaluation-run",
        "prompt_sha256": cell.prompt_evidence_sha256,
        "journey_evidence_sha256": (cell.consumption_receipt.journey_evidence_sha256),
        "route_evidence_sha256": cell.consumption_receipt.route_evidence_sha256,
        "continuity_evidence_sha256": (
            cell.consumption_receipt.continuity_evidence_sha256
        ),
        "runtime": "claude",
        "variant": "F+O",
        "specialist": "sd",
        "stage_index": 0,
        "composed_content_sha256": (projection.content_receipt.composed_content_sha256),
        "sources": [dict(item) for item in projection.knowledge_sources],
    }


class _JourneyRows:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.items: dict[int, dict[str, object]] = {}

    def store_wp(self, **values):
        with self._lock:
            row_id = len(self.items) + 1
            row = {
                "id": row_id,
                "guard": "title=clean;content=clean",
                **values,
            }
            self.items[row_id] = row
            return row

    def get_wp(self, *, wp_id):
        return self.items[wp_id]

    def list_wps(self, *, task=None, type_=None):
        return [
            row
            for row in reversed(tuple(self.items.values()))
            if (task is None or row["task_id"] == task)
            and (type_ is None or row["type_"] == type_)
        ]


def test_prepared_claude_cell_reaches_all_eleven_gates_without_model_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from cc.core.evaluation import _authority as authority_module
    from cc.core.evaluation import content_authority, journey_runtime, live_runtime
    from cc.core.evaluation.execution import (
        EvaluationExecutionUnavailable,
        _execute_prepared_claude_cell,
        _prepare_claude_cell,
    )
    from cc.core.evaluation.journey_runtime import TcJourneyLedger
    from cc.core.evaluation.matrix import build_matrix
    from cc.core.evaluation.runner import _preflight_for
    from cc.evaluation_fixtures import packaged_cases_root

    manifest, lock = _configure_authority(
        monkeypatch,
        tmp_path,
        tiers=("foundation",),
    )
    original_issue = content_authority.issue_canonical_claude_content
    resolver = journey_runtime.resolve_specialist_knowledge

    def exact_resolver(*args):
        payload, sources = resolver(*args)
        return payload, tuple(
            {
                **{key: value for key, value in source.items() if key != "role"},
                "tier": source.get("tier", source.get("role")),
            }
            for source in sources
        )

    monkeypatch.setattr(
        journey_runtime,
        "resolve_specialist_knowledge",
        exact_resolver,
    )

    def issue(**values):
        return original_issue(
            **values,
            manifest_path=manifest,
            lock_path=lock,
        )

    monkeypatch.setattr(
        content_authority,
        "issue_canonical_claude_content",
        issue,
    )
    agent_content = "Signed foundation sd specialist."
    agent_projection = live_runtime.ClaudeAgentProjection(
        content=agent_content,
        layer="claude-foundation",
        ref="refs/tags/v1.0.0",
        tree="3" * 40,
        signer=_SIGNER,
        content_sha256=hashlib.sha256(agent_content.encode()).hexdigest(),
        tier="foundation",
        repository_identifier="Org/claude-foundation",
        contribution="agents/sd.md",
    )
    monkeypatch.setattr(
        live_runtime,
        "resolve_claude_agent_projection",
        lambda _variant, _specialist: agent_projection,
    )
    terminal = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "session_id": "synthetic-session",
        "result": "Synthetic evidence-bound result.",
        "permission_denials": [],
        "num_turns": 1,
        "stop_reason": "end_turn",
        "terminal_reason": "completed",
        "modelUsage": {
            "claude-fable-5": {
                "canonicalModel": "claude-fable-5",
                "webSearchRequests": 0,
            }
        },
        "usage": {"server_tool_use": {"web_search_requests": 0}},
    }
    fake_claude = tmp_path / "fake-claude"
    fake_claude.write_text(
        "#!/bin/sh\nprintf '%s' '" + json.dumps(terminal) + "'\n",
        encoding="utf-8",
    )
    fake_claude.chmod(0o700)
    monkeypatch.setattr(
        "cc.core.executables.resolve_executable",
        lambda _name: str(fake_claude),
    )
    matrix, fixtures = build_matrix(packaged_cases_root())
    plan = next(
        item
        for item in matrix.cells
        if item.case_id == "eval-01"
        and item.variant is LayerVariant.FOUNDATION
        and item.runtime is RuntimeName.CLAUDE
    )
    loaded = next(item for item in fixtures if item.fixture.case_id == "eval-01")
    rows = _JourneyRows()
    ledger = TcJourneyLedger(
        285,
        store_wp=rows.store_wp,
        get_wp=rows.get_wp,
        list_wps=rows.list_wps,
    )
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir(mode=0o700)

    prepared = _prepare_claude_cell(plan, loaded, artifact_root, ledger)
    authority = authority_module._production_authority(
        prepared.cell,
        loaded_fixture=loaded,
        journey_run_id=prepared.journey_run_id,
        journey_ledger=ledger,
        runtime_adapter=prepared.adapter,
        content_projection=prepared.content_projection,
    )
    try:
        preflight = _preflight_for(
            prepared.cell,
            authority,
            artifact_root,
            loaded_fixture=loaded,
            journey_run_id=prepared.journey_run_id,
            journey_ledger=ledger,
        )
        assert len(preflight.observations) == 11
        assert {item.gate for item in preflight.observations} == set(PreflightGate)
        assert all(item.state is GateState.PASS for item in preflight.observations)
        assert not tuple((artifact_root / "runtime-quarantine").glob("*.json"))
        root_substitution = tmp_path / "other-artifacts"
        root_substitution.mkdir(mode=0o700)
        fixture_substitution = load_fixture(packaged_cases_root() / "eval-01")
        copied_prepared = copy.copy(prepared)
        copied_prepared.close()
        prepared._root_capability.validate()
        assert verify_canonical_content_projection(prepared.content_projection)
        for candidate, candidate_fixture, candidate_root in (
            (copy.copy(prepared), loaded, artifact_root),
            (prepared, fixture_substitution, artifact_root),
            (prepared, loaded, root_substitution),
        ):
            with pytest.raises(
                EvaluationExecutionUnavailable,
                match="claude-prepared-attempt-invalid",
            ):
                _execute_prepared_claude_cell(
                    candidate,
                    candidate_fixture,
                    candidate_root,
                )
        assert not tuple(artifact_root.iterdir())
        assert not tuple(root_substitution.iterdir())
        displaced_root = tmp_path / "displaced-artifacts"
        replacement_root = tmp_path / "replacement-artifacts"
        artifact_root.rename(displaced_root)
        artifact_root.mkdir(mode=0o700)
        with pytest.raises(
            EvaluationExecutionUnavailable,
            match="claude-prepared-attempt-invalid",
        ):
            _execute_prepared_claude_cell(prepared, loaded, artifact_root)
        artifact_root.rename(replacement_root)
        displaced_root.rename(artifact_root)
        assert not tuple(replacement_root.iterdir())
        report = _execute_prepared_claude_cell(prepared, loaded, artifact_root)
        assert report["state"] == "completed"
        assert report["live_calls_started"] == 1
        assert len(tuple((artifact_root / "run-record").glob("*.json"))) == 1
        with pytest.raises(
            EvaluationExecutionUnavailable,
            match="claude-prepared-attempt-invalid",
        ):
            _execute_prepared_claude_cell(prepared, loaded, artifact_root)
        assert len(tuple((artifact_root / "run-record").glob("*.json"))) == 1
    finally:
        authority.close()
        prepared.close()


def test_production_authority_passes_only_exact_canonical_content(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from cc.core.evaluation import _authority as authority_module
    from cc.core.evaluation import content_authority, journey_runtime

    manifest, lock = _configure_authority(monkeypatch, tmp_path)
    projection = issue_canonical_claude_content(
        variant=LayerVariant.ORGANIZATION,
        specialist="sd",
        manifest_path=manifest,
        lock_path=lock,
    )
    loaded = load_fixture(Path(__file__).parent / "fixtures" / "cases" / "eval-01")
    cell = _production_cell(projection, loaded)
    state = _journey_state(cell, projection)

    class Ledger:
        pass

    monkeypatch.setattr(journey_runtime, "TcJourneyLedger", Ledger)
    monkeypatch.setattr(
        authority_module,
        "_verified_journey_identities",
        lambda _run_id, _ledger: state,
    )
    monkeypatch.setattr(
        content_authority,
        "issue_canonical_claude_content",
        lambda **_kwargs: projection,
    )
    authority = authority_module._production_authority(
        cell,
        loaded_fixture=loaded,
        journey_run_id=str(state["run_id"]),
        journey_ledger=Ledger(),
    )
    entitlement = next(
        item
        for item in authority.preflight.observations
        if item.gate is PreflightGate.ENTITLEMENT_AND_PINS
    )
    assert entitlement.state is GateState.PASS
    assert entitlement.reason == "signed-content-verified"
    copied_authority = copy.copy(authority)
    assert not copied_authority.applies_to(cell)
    copied_authority.close()
    assert authority.applies_to(cell)

    changed_content = replace(
        projection.content_receipt,
        composed_content_sha256="f" * 64,
    )
    changed_consumption = build_consumption_receipt(
        task_id=cell.consumption_receipt.task_id,
        runtime_receipt=cell.runtime_receipt,
        content_receipt=changed_content,
        prompt_evidence_sha256=cell.prompt_evidence_sha256,
        journey_evidence_sha256=cell.consumption_receipt.journey_evidence_sha256,
        route_evidence_sha256=cell.consumption_receipt.route_evidence_sha256,
        continuity_evidence_sha256=cell.consumption_receipt.continuity_evidence_sha256,
    )
    changed = replace(
        cell,
        content_receipt=changed_content,
        consumption_receipt=changed_consumption,
    )
    changed_authority = authority_module._production_authority(
        changed,
        loaded_fixture=loaded,
        journey_run_id=str(state["run_id"]),
        journey_ledger=Ledger(),
    )
    changed_entitlement = next(
        item
        for item in changed_authority.preflight.observations
        if item.gate is PreflightGate.ENTITLEMENT_AND_PINS
    )
    assert changed_entitlement.state is GateState.FAIL
    assert changed_entitlement.reason == "signed-content-mismatch"

    with patch.dict(state, {"specialist": "ta"}):
        route_authority = authority_module._production_authority(
            cell,
            loaded_fixture=loaded,
            journey_run_id=str(state["run_id"]),
            journey_ledger=Ledger(),
        )
    route_entitlement = next(
        item
        for item in route_authority.preflight.observations
        if item.gate is PreflightGate.ENTITLEMENT_AND_PINS
    )
    assert route_entitlement.state is GateState.FAIL
    assert route_entitlement.reason == "journey-content-route-mismatch"

    def unavailable(**_kwargs):
        raise CanonicalContentUnavailable("materialized-lock-mismatch")

    monkeypatch.setattr(
        content_authority,
        "issue_canonical_claude_content",
        unavailable,
    )
    unavailable_authority = authority_module._production_authority(
        cell,
        loaded_fixture=loaded,
        journey_run_id=str(state["run_id"]),
        journey_ledger=Ledger(),
    )
    unavailable_entitlement = next(
        item
        for item in unavailable_authority.preflight.observations
        if item.gate is PreflightGate.ENTITLEMENT_AND_PINS
    )
    assert unavailable_entitlement.state is GateState.FAIL
    assert unavailable_entitlement.reason == "materialized-lock-mismatch"
    authority.close()
    authority.close()


def test_production_codex_is_zero_call_durable_unsupported(
    tmp_path: Path,
) -> None:
    from cc.core.evaluation.execution import _issue_codex_zero_call_cell
    from cc.core.evaluation.matrix import build_matrix
    from cc.evaluation_fixtures import packaged_cases_root

    loaded = load_fixture(Path(__file__).parent / "fixtures" / "cases" / "eval-01")
    matrix, _fixtures = build_matrix(packaged_cases_root())
    plan = next(
        item
        for item in matrix.cells
        if item.case_id == "eval-01"
        and item.runtime is RuntimeName.CODEX
        and item.variant is LayerVariant.FOUNDATION
    )
    cell = _issue_codex_zero_call_cell(plan, loaded)

    class Runtime:
        calls = 0

        def execute(self, _cell):
            self.calls += 1
            raise AssertionError(
                "Codex must not be called while isolation is unavailable"
            )

    runtime = Runtime()
    runner = EvaluationRunner(
        runtime,
        loaded_fixture=loaded,
    )
    record = runner.run(cell)

    assert runtime.calls == 0
    assert record.state is RunState.UNSUPPORTED
    assert record.preflight.state.value == "UNSUPPORTED"
    unsupported = [
        item
        for item in record.preflight.observations
        if item.state is GateState.UNSUPPORTED
    ]
    assert [(item.gate, item.reason) for item in unsupported] == [
        (
            PreflightGate.RUNTIME_CAPABILITY,
            "codex-no-tool-isolation-unavailable",
        )
    ]
    assert all(
        item.state is GateState.PASS
        for item in record.preflight.observations
        if item.gate is not PreflightGate.RUNTIME_CAPABILITY
    )

    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir(mode=0o700)
    write_run_record(
        artifact_root,
        record,
        cell=cell,
        loaded_fixture=loaded,
    )
    reloaded = load_durable_unsupported_run(
        artifact_root,
        record.run_sha256,
        cell=cell,
        loaded_fixture=loaded,
    )
    assert reloaded is not None
    assert reloaded.record.run_sha256 == record.run_sha256
    assert reloaded.validate()


def test_production_codex_zero_call_rejects_self_consistent_cell_substitution(
    tmp_path: Path,
) -> None:
    from cc.core.evaluation.execution import _issue_codex_zero_call_cell
    from cc.core.evaluation.matrix import build_matrix
    from cc.evaluation_fixtures import packaged_cases_root

    loaded = load_fixture(Path(__file__).parent / "fixtures" / "cases" / "eval-01")
    matrix, _fixtures = build_matrix(packaged_cases_root())
    plan = next(
        item
        for item in matrix.cells
        if item.case_id == "eval-01"
        and item.runtime is RuntimeName.CODEX
        and item.variant is LayerVariant.FOUNDATION
    )
    canonical = _issue_codex_zero_call_cell(plan, loaded)
    changed = replace(canonical, command_policy_sha256="f" * 64)

    class Runtime:
        calls = 0

        def execute(self, _cell):
            self.calls += 1
            raise AssertionError("An invalid zero-call cell must never dispatch")

    runtime = Runtime()
    record = EvaluationRunner(runtime, loaded_fixture=loaded).run(changed)

    assert runtime.calls == 0
    assert record.state is RunState.INVALID
    assert record.preflight.state.value == "INVALID"
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir(mode=0o700)
    receipt = write_run_record(
        artifact_root,
        record,
        cell=changed,
        loaded_fixture=loaded,
    )
    assert verify_artifact_receipt(receipt)
