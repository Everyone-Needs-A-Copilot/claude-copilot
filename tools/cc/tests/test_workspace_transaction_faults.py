from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from cc.core.ecosystem.project_locking import inspect_project_identity, project_lock
from cc.core.ecosystem.project_reconciliation import assess_project
from cc.core.ecosystem.reconciliation_transaction import (
    DurableReceiptUnavailable,
    ProjectPreflightSpec,
    ProjectTransactionPlan,
    ReconciliationTransactionError,
    TransactionOperation,
    execute_reconciliation,
    fingerprint_recipe_source,
    transaction_plan_from_recipe,
)

from cc.core.ecosystem import project_reconciliation


def _repo(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(("git", "init", "-q"), cwd=path, check=True)
    (path / "CLAUDE.md").write_text("Project instructions.\n", encoding="utf-8")
    subprocess.run(("git", "add", "-A"), cwd=path, check=True)
    subprocess.run(
        (
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ),
        cwd=path,
        check=True,
    )
    return path


def _plan(
    project: Path, tmp_path: Path, *, verifies: bool = True
) -> ProjectTransactionPlan:
    with project_lock(project, lock_root=tmp_path / "fingerprint-locks") as anchored:
        before = anchored.fingerprint("CLAUDE.md")
    operation = TransactionOperation(
        id="op_" + "a" * 64,
        kind="append-managed-block",
        component="claude",
        target="CLAUDE.md",
        expected_before_fingerprint=before,
        source_fingerprint=None,
        payload={"block": "<!-- cc:managed -->\nManaged.\n"},
    )
    return ProjectTransactionPlan(
        path=str(project),
        expected_identity=inspect_project_identity(project),
        operations=(operation,),
        verification=lambda _project: verifies,
        inspection_id="sha256:" + "b" * 64,
    )


def test_success_requires_typed_output_and_fresh_verification(tmp_path) -> None:
    project = _repo(tmp_path / "project")
    ledger = execute_reconciliation(
        [_plan(project, tmp_path)],
        run_id="run_" + "1" * 32,
        root=tmp_path / "state",
    )
    assert ledger[0]["status"] == "applied"
    assert ledger[0]["verification"] == "ready"
    assert "cc:managed" in (project / "CLAUDE.md").read_text(encoding="utf-8")


def test_preflight_allows_safe_selected_component_with_owner_decision_sibling(
    tmp_path, monkeypatch
) -> None:
    project = _repo(tmp_path / "project")
    plan = _plan(project, tmp_path)
    inspection_id = "sha256:" + "c" * 64
    plan = ProjectTransactionPlan(
        **{
            **plan.__dict__,
            "preflight": ProjectPreflightSpec(
                inspection_id=inspection_id,
                selected_components=("claude",),
            ),
        }
    )
    monkeypatch.setattr(
        project_reconciliation,
        "assess_project",
        lambda *args, **kwargs: {
            "inspection_id": inspection_id,
            "route": "owner-decision",
            "selected_components": ["claude"],
            "components": [
                {
                    "component": "claude",
                    "state": "safe-update-available",
                    "selected": True,
                    "recommended": True,
                },
                {
                    "component": "codex",
                    "state": "owner-decision",
                    "selected": False,
                    "recommended": False,
                },
            ],
        },
    )

    ledger = execute_reconciliation(
        [plan],
        run_id="run_" + "9" * 32,
        root=tmp_path / "state",
    )

    assert ledger[0]["status"] == "applied"


@pytest.mark.parametrize(
    ("fault_boundary", "expected_status"),
    [
        ("before-mutation", "blocked"),
        ("after-mutation", "rolled-back"),
        ("before-verification", "rolled-back"),
    ],
)
def test_failure_at_each_mutation_boundary_restores_owned_output(
    tmp_path, fault_boundary: str, expected_status: str
) -> None:
    project = _repo(tmp_path / "project")
    before = (project / "CLAUDE.md").read_bytes()

    def observer(event, _context):
        if event == fault_boundary:
            raise RuntimeError("test boundary interruption")

    ledger = execute_reconciliation(
        [_plan(project, tmp_path)],
        run_id="run_" + "2" * 32,
        observer=observer,
        root=tmp_path / "state",
    )
    assert ledger[0]["status"] == expected_status
    assert (project / "CLAUDE.md").read_bytes() == before


def test_verifier_failure_rolls_back_and_batch_peer_still_succeeds(tmp_path) -> None:
    failing = _repo(tmp_path / "failing")
    passing = _repo(tmp_path / "passing")
    failing_before = (failing / "CLAUDE.md").read_bytes()
    ledger = execute_reconciliation(
        [
            _plan(failing, tmp_path / "one", verifies=False),
            _plan(passing, tmp_path / "two", verifies=True),
        ],
        run_id="run_" + "3" * 32,
        root=tmp_path / "state",
    )
    assert [item["status"] for item in ledger] == ["rolled-back", "applied"]
    assert (failing / "CLAUDE.md").read_bytes() == failing_before
    assert "cc:managed" in (passing / "CLAUDE.md").read_text(encoding="utf-8")
    diagnostic = (
        tmp_path / "state/diagnostics" / ("reconciliation-run_" + "3" * 32 + ".json")
    )
    assert diagnostic.is_file()
    assert len(__import__("json").loads(diagnostic.read_text())["projects"]) == 2


def test_unavailable_project_receipt_rolls_back_retains_state_and_stops_batch(
    tmp_path, monkeypatch
) -> None:
    first = _repo(tmp_path / "first")
    second = _repo(tmp_path / "second")
    first_before = (first / "CLAUDE.md").read_bytes()
    second_before = (second / "CLAUDE.md").read_bytes()
    monkeypatch.setattr(
        "cc.core.ecosystem.reconciliation_transaction.append_project_receipt",
        lambda *_args, **_kwargs: SimpleNamespace(state="unavailable"),
    )
    run_id = "run_" + "8" * 32

    with pytest.raises(DurableReceiptUnavailable):
        execute_reconciliation(
            [
                _plan(first, tmp_path / "first-plan"),
                _plan(second, tmp_path / "second-plan"),
            ],
            run_id=run_id,
            root=tmp_path / "state",
        )

    assert (first / "CLAUDE.md").read_bytes() == first_before
    assert (second / "CLAUDE.md").read_bytes() == second_before
    journal = next(
        (tmp_path / "state" / "transactions" / run_id).glob("project-*/journal.json")
    )
    payload = json.loads(journal.read_text(encoding="utf-8"))
    assert payload["phase"] == "recovery-required"
    assert (journal.parent / "snapshots" / "snapshots.json").is_file()
    assert (
        len(list((tmp_path / "state" / "transactions" / run_id).glob("project-*"))) == 1
    )


def test_unavailable_preflight_receipt_stops_before_next_batch_project(
    tmp_path, monkeypatch
) -> None:
    first = _repo(tmp_path / "first")
    second = _repo(tmp_path / "second")
    stale = _plan(first, tmp_path / "first-plan")
    stale_identity = stale.expected_identity.as_dict()
    stale_identity["inode"] += 1
    stale = ProjectTransactionPlan(
        path=stale.path,
        expected_identity=stale_identity,
        operations=stale.operations,
        verification=stale.verification,
        inspection_id=stale.inspection_id,
    )
    second_before = (second / "CLAUDE.md").read_bytes()
    monkeypatch.setattr(
        "cc.core.ecosystem.reconciliation_transaction.append_project_receipt",
        lambda *_args, **_kwargs: SimpleNamespace(state="unavailable"),
    )

    with pytest.raises(DurableReceiptUnavailable):
        execute_reconciliation(
            [stale, _plan(second, tmp_path / "second-plan")],
            run_id="run_" + "b" * 32,
            root=tmp_path / "state",
        )

    assert (second / "CLAUDE.md").read_bytes() == second_before
    assert not (tmp_path / "state/transactions" / ("run_" + "b" * 32)).exists()


def test_file_source_swap_after_capture_cannot_change_written_bytes(tmp_path) -> None:
    project = _repo(tmp_path / "project")
    source = tmp_path / "source.md"
    source.write_text("Reviewed source.\n", encoding="utf-8")
    with project_lock(project, lock_root=tmp_path / "fingerprint-locks") as anchored:
        before = anchored.fingerprint("SOUL.md")
    operation = TransactionOperation(
        id="op_" + "8" * 64,
        kind="copy-file-from-source",
        component="claude",
        target="SOUL.md",
        expected_before_fingerprint=before,
        source_fingerprint=fingerprint_recipe_source(source),
        payload={"source_path": str(source), "mode": 0o644},
    )
    plan = ProjectTransactionPlan(
        path=str(project),
        expected_identity=inspect_project_identity(project),
        operations=(operation,),
        verification=lambda _project: True,
    )

    def observer(event, _context):
        if event == "source-captured":
            source.write_text("Swapped source.\n", encoding="utf-8")

    ledger = execute_reconciliation(
        [plan],
        run_id="run_" + "9" * 32,
        observer=observer,
        root=tmp_path / "state",
    )

    assert ledger[0]["status"] == "applied"
    assert (project / "SOUL.md").read_text(encoding="utf-8") == "Reviewed source.\n"


def test_tree_source_swap_after_capture_installs_only_staged_tree(tmp_path) -> None:
    project = _repo(tmp_path / "project")
    source = tmp_path / "tree-source"
    source.mkdir()
    (source / "manifest.json").write_text("reviewed\n", encoding="utf-8")
    with project_lock(project, lock_root=tmp_path / "fingerprint-locks") as anchored:
        before = anchored.fingerprint("plugins/codex-copilot")
    operation = TransactionOperation(
        id="op_" + "9" * 64,
        kind="copy-tree-from-source",
        component="codex",
        target="plugins/codex-copilot",
        expected_before_fingerprint=before,
        source_fingerprint=fingerprint_recipe_source(source, tree=True, mode=0o755),
        payload={"source_path": str(source)},
    )
    plan = ProjectTransactionPlan(
        path=str(project),
        expected_identity=inspect_project_identity(project),
        operations=(operation,),
        verification=lambda _project: True,
    )

    def observer(event, _context):
        if event == "source-captured":
            (source / "manifest.json").write_text("swapped\n", encoding="utf-8")

    ledger = execute_reconciliation(
        [plan],
        run_id="run_" + "a" * 32,
        observer=observer,
        root=tmp_path / "state",
    )

    assert ledger[0]["status"] == "applied"
    assert (project / "plugins/codex-copilot/manifest.json").read_text(
        encoding="utf-8"
    ) == "reviewed\n"
    transaction = next(
        (tmp_path / "state/transactions" / ("run_" + "a" * 32)).glob("project-*")
    )
    assert not (transaction / "prepared-sources").exists()


def test_recipe_source_with_symlinked_ancestor_is_rejected(tmp_path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "source.md").write_text("reviewed\n", encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)

    with pytest.raises(
        ReconciliationTransactionError, match="symlinked or unavailable"
    ):
        fingerprint_recipe_source(linked / "source.md")


def test_coalesced_lock_update_verifies_every_selected_component(
    tmp_path, monkeypatch
) -> None:
    project = _repo(tmp_path / "project")
    with project_lock(project, lock_root=tmp_path / "fingerprint-locks") as anchored:
        before = anchored.fingerprint("copilot.lock.json")
    operation = {
        "id": "op_" + "c" * 64,
        "kind": "upsert-lock-component",
        "component": "claude",
        "target": "copilot.lock.json",
        "expected_before_fingerprint": before,
        "source_fingerprint": None,
        "payload": {
            "component_entry": [
                {"component": "claude", "version": "1.0.0"},
                {"component": "codex", "version": "1.0.0"},
            ]
        },
    }
    seen: dict[str, object] = {}

    def inspect(path, *, detail=False):
        seen.update(path=str(path), detail=detail)
        return {
            "components": [
                {"component": "claude", "classification": "ready"},
                {"component": "codex", "classification": "ready"},
            ]
        }

    monkeypatch.setattr(
        "cc.core.ecosystem.project_integration.inspect_project_integration",
        inspect,
    )
    monkeypatch.setattr(
        "cc.core.ecosystem.project_reconciliation.assess_project",
        lambda *_args, **_kwargs: {
            "inspection_id": "sha256:" + "d" * 64,
            "selected_components": ["claude", "codex"],
            "route": "safe-update-available",
        },
    )
    transaction = transaction_plan_from_recipe(
        {
            "path": str(project),
            "expected_identity": inspect_project_identity(project).as_dict(),
            "inspection_id": "sha256:" + "d" * 64,
            "selected_components": ["claude", "codex"],
            "operations": [operation],
            "allowed_targets": ["copilot.lock.json"],
        }
    )
    ledger = execute_reconciliation(
        [transaction],
        run_id="run_" + "4" * 32,
        root=tmp_path / "state",
    )

    assert ledger[0]["status"] == "applied"
    assert seen == {"path": str(project), "detail": True}
    lock = json.loads((project / "copilot.lock.json").read_text(encoding="utf-8"))
    assert [item["component"] for item in lock["components"]] == ["claude", "codex"]


def test_preflight_refusal_persists_classified_exception_evidence(tmp_path) -> None:
    project = _repo(tmp_path / "project")
    original = _plan(project, tmp_path)
    stale_identity = original.expected_identity.as_dict()
    stale_identity["inode"] += 1
    stale = ProjectTransactionPlan(
        path=original.path,
        expected_identity=stale_identity,
        operations=original.operations,
        verification=original.verification,
        inspection_id=original.inspection_id,
    )
    run_id = "run_" + "5" * 32

    ledger = execute_reconciliation(
        [stale],
        run_id=run_id,
        root=tmp_path / "state",
    )

    assert ledger[0]["status"] == "blocked"
    diagnostic = json.loads(
        (tmp_path / "state/diagnostics" / f"reconciliation-{run_id}.json").read_text(
            encoding="utf-8"
        )
    )
    exception = diagnostic["projects"][0]["evidence"]["exception"]
    assert exception["type"] == "ProjectIdentityMismatch"
    assert exception["code"] == "stale-plan"


def test_nested_missing_targets_prepare_without_writes_and_rollback_exact_tree(
    tmp_path,
) -> None:
    project = tmp_path / "empty-project"
    project.mkdir()
    subprocess.run(("git", "init", "-q"), cwd=project, check=True)
    subprocess.run(
        (
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "empty fixture",
        ),
        cwd=project,
        check=True,
    )
    with project_lock(project, lock_root=tmp_path / "fingerprint-locks") as anchored:
        missing = anchored.fingerprint(".claude/commands/protocol.md")
        assert missing == anchored.fingerprint(".claude/commands/continue.md")
    operations = tuple(
        TransactionOperation(
            id="op_" + character * 64,
            kind="append-managed-block",
            component="claude",
            target=target,
            expected_before_fingerprint=missing,
            source_fingerprint=None,
            payload={"block": f"<!-- {character}:managed -->\n"},
        )
        for character, target in (
            ("d", ".claude/commands/protocol.md"),
            ("e", ".claude/commands/continue.md"),
        )
    )
    plan = ProjectTransactionPlan(
        path=str(project),
        expected_identity=inspect_project_identity(project),
        operations=operations,
        verification=lambda _project: True,
    )
    snapshots: list[str] = []

    def observer(event, context):
        if event == "snapshot-persisted":
            snapshots.append(str(context["operation_id"]))
        if event == "before-mutation":
            assert snapshots == [operation.id for operation in operations]
        if event == "after-output-write":
            raise RuntimeError("rollback nested output")

    ledger = execute_reconciliation(
        [plan],
        run_id="run_" + "6" * 32,
        observer=observer,
        root=tmp_path / "state",
    )

    assert ledger[0]["status"] == "rolled-back"
    assert [
        path.relative_to(project).as_posix()
        for path in project.rglob("*")
        if ".git" not in path.relative_to(project).parts
    ] == []


def test_later_batch_project_is_freshly_reassessed_under_its_lock(
    tmp_path, monkeypatch
) -> None:
    first = _repo(tmp_path / "first")
    later = tmp_path / "later"
    later.mkdir()
    subprocess.run(("git", "init", "-q"), cwd=later, check=True)
    subprocess.run(
        (
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "empty fixture",
        ),
        cwd=later,
        check=True,
    )
    # This test isolates transaction freshness. Inspector and source behavior
    # are covered by the project-reconciliation suite and must not depend on
    # the runner's installed Copilot frameworks here.
    monkeypatch.setattr(
        "cc.core.ecosystem.project_reconciliation.inspect_project_integration",
        lambda _path, detail: {
            "inspection": {"id": "sha256:" + "1" * 64},
            "components": [
                {
                    "component": "claude",
                    "classification": "safe-finish",
                    "recognized_setup": None,
                    "missing_requirements": [
                        {
                            "id": "component-setup",
                            "detail": "The Claude integration is absent.",
                        }
                    ],
                },
                {
                    "component": "codex",
                    "classification": "ready",
                    "recognized_setup": {
                        "variant_id": "codex-tracked-lock-v1",
                        "evidence": [],
                    },
                    "missing_requirements": [],
                },
            ],
            "preservation": {"must_preserve": []},
        },
    )
    monkeypatch.setattr(
        "cc.core.ecosystem.project_reconciliation.is_project_excluded",
        lambda _path: False,
    )
    monkeypatch.setattr(
        "cc.core.ecosystem.project_reconciliation._source_available",
        lambda _component: True,
    )
    assessment = assess_project(
        later,
        approved_root=later,
        selected_components=("claude",),
        detail=True,
    )
    assert assessment["route"] == "safe-setup-available"
    with project_lock(
        later, lock_root=tmp_path / "later-fingerprint-locks"
    ) as anchored:
        before = anchored.fingerprint("CLAUDE.md")
    later_transaction = transaction_plan_from_recipe(
        {
            "path": str(later),
            "expected_identity": inspect_project_identity(later).as_dict(),
            "inspection_id": assessment["inspection_id"],
            "selected_components": ["claude"],
            "operations": [
                {
                    "id": "op_" + "f" * 64,
                    "kind": "append-managed-block",
                    "component": "claude",
                    "target": "CLAUDE.md",
                    "expected_before_fingerprint": before,
                    "source_fingerprint": None,
                    "payload": {"block": "<!-- cc:managed -->\nManaged.\n"},
                }
            ],
            "allowed_targets": ["CLAUDE.md"],
        },
        verifier=lambda _project: True,
    )

    def observer(event, context):
        if event == "receipt-persisted" and context.get("project") == str(first):
            (later / "human-note.txt").write_text("later drift\n", encoding="utf-8")

    run_id = "run_" + "7" * 32
    ledger = execute_reconciliation(
        [_plan(first, tmp_path / "first-state"), later_transaction],
        run_id=run_id,
        observer=observer,
        root=tmp_path / "state",
    )

    assert [entry["status"] for entry in ledger] == ["applied", "blocked"]
    assert not (later / "CLAUDE.md").exists()
    diagnostic = json.loads(
        (tmp_path / "state/diagnostics" / f"reconciliation-{run_id}.json").read_text(
            encoding="utf-8"
        )
    )
    exception = diagnostic["projects"][1]["evidence"]["exception"]
    assert exception["type"] == "ReconciliationTransactionError"
    assert exception["code"] == "stale-plan"
