from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from cc.core.ecosystem.project_locking import (
    atomic_json_write,
    inspect_project_identity,
)
from cc.core.ecosystem.project_plan_store import (
    PlanBindingMismatch,
    claim_plan,
    finalize_run_intent,
    finish_plan,
    incomplete_run_ids,
    issue_plan,
    load_recovery_context,
)
from cc.core.ecosystem.reconciliation import (
    ReconciliationError,
    build_apply_report,
    build_recover_report,
)
from cc.core.ecosystem.reconciliation_diagnostics import finalize_run_diagnostic
from cc.core.ecosystem.reconciliation_transaction import (
    ProjectTransactionPlan,
    TransactionOperation,
    execute_reconciliation,
)
from cc.core.ecosystem.reconciliation_types import parse_reconciliation_request
from jsonschema import Draft202012Validator


def _fingerprint(value: dict) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(("git", "init", "-q"), cwd=path, check=True)
    (path / "CLAUDE.md").write_text("Before.\n", encoding="utf-8")
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


def _machine(root: Path) -> dict:
    return {
        "state": "ready",
        "helper": {
            "state": "ready",
            "version": "2.6.0",
            "path": "/usr/local/bin/cc",
            "detail": "The helper is available.",
        },
        "frameworks": [
            {
                "component": component,
                "state": "ready",
                "path": f"/{component}-framework",
                "version": "1.0.0",
                "detail": "The framework is ready.",
            }
            for component in ("claude", "codex")
        ],
        "configuration": {
            "state": "ready",
            "path": "/config.json",
            "approved_roots": [str(root)],
            "detail": "The machine configuration is readable.",
        },
        "authentication": {
            "state": "signed-in",
            "credential_state": "present",
            "detail": "Sign-in is available.",
        },
        "connectivity": {"state": "online", "detail": "Network checks passed."},
        "layers": {
            "state": "ready",
            "ready": 2,
            "total": 2,
            "detail": "Layers are ready.",
        },
        "dependencies": [],
        "blockers": [],
        "next_action": "Nothing needs to be changed.",
    }


def _project(project: Path, root: Path, inspection_id: str) -> dict:
    return {
        "path": str(project),
        "root": str(root),
        "name": project.name,
        "inspection_id": inspection_id,
        "presence": "claude-only",
        "route": "ready",
        "selected_components": ["claude"],
        "components": [
            {
                "component": "claude",
                "state": "ready",
                "selected": True,
                "recommended": True,
                "recommendation_reason": "Claude is ready.",
                "responsible_actor": "none",
                "evidence": [],
                "missing_requirements": [],
                "next_action": "Nothing needs to be changed.",
                "recipe_options": [],
            },
            {
                "component": "codex",
                "state": "not-selected",
                "selected": False,
                "recommended": False,
                "recommendation_reason": "Codex was not selected.",
                "responsible_actor": "none",
                "evidence": [],
                "missing_requirements": [],
                "next_action": "Nothing needs to be changed.",
                "recipe_options": [],
            },
        ],
        "blockers": [],
        "next_action": "Nothing needs to be changed.",
    }


def _validate(report: dict) -> None:
    schema = json.loads(
        (Path(__file__).parent / "fixtures/schemas/reconcile.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(report)


def _reviewed_plan(path: str, inspection_id: str, *, executable: bool) -> dict:
    return {
        "path": path,
        "inspection_id": inspection_id,
        "recipes": [{"component": "claude", "recipe_id": "claude-project-update-v1"}],
        "sources": [
            {
                "component": "claude",
                "version": "2.6.0",
                "fingerprint": "sha256:" + "e" * 64,
            }
        ],
        "operations": (
            [
                {
                    "id": "op_" + "f" * 64,
                    "kind": "append-managed-block",
                    "component": "claude",
                    "target": "CLAUDE.md",
                    "description": "Append the bounded Claude entry.",
                    "expected_before_fingerprint": "sha256:" + "0" * 64,
                    "source_fingerprint": None,
                }
            ]
            if executable
            else []
        ),
        "preservation": [],
        "prohibited_actions": ["overwrite-project-owned-content"],
        "verification": ["claude-project-integration"],
    }


def test_mixed_recovery_synthesizes_zero_operation_receipt_and_full_evidence(
    tmp_path,
) -> None:
    root = tmp_path
    first = tmp_path / "first"
    second = tmp_path / "second"
    inspection_id = "sha256:" + "a" * 64
    canonical_request = {
        "schema_version": "1.0",
        "roots": [str(root)],
        "projects": [
            {"path": str(first), "components": ["claude"]},
            {"path": str(second), "components": ["claude"]},
        ],
    }
    plans = (
        _reviewed_plan(str(first), inspection_id, executable=True),
        _reviewed_plan(str(second), inspection_id, executable=False),
    )
    interrupted_run = "run_" + "5" * 32
    context = SimpleNamespace(
        owner_live=False,
        state="applying",
        plan_state="applying",
        plan_id="plan_" + "5" * 32,
        canonical_request=canonical_request,
        plans=plans,
        request_fingerprint=_fingerprint(canonical_request),
        fresh_plan_fingerprint="sha256:" + "5" * 64,
        helper_version="2.6.0",
        schema_version="1.0",
    )
    captured: dict = {}

    def diagnostic(run_id, *_args, **kwargs):
        captured["evidence"] = kwargs["project_evidence"]
        return {
            "schema_version": "1.0",
            "id": run_id,
            "state": "available",
            "path": "/private/recovery.json",
            "created_at": "2026-08-04T18:00:00Z",
            "detail": "A private redacted reconciliation record was saved.",
        }

    report = build_recover_report(
        machine_builder=lambda: _machine(root),
        census_builder=lambda **_kwargs: [
            _project(first, root, inspection_id),
            _project(second, root, inspection_id),
        ],
        recovery_lister=lambda **_kwargs: (interrupted_run,),
        context_loader=lambda *_args, **_kwargs: context,
        transaction_recoverer=lambda *_args, **_kwargs: [
            {
                "path": str(first),
                "status": "applied",
                "completed_operation_ids": ["op_" + "f" * 64],
                "verification": "ready",
                "rollback": [],
            }
        ],
        recovery_recorder=lambda *_args, **_kwargs: SimpleNamespace(
            state="outcome-recorded"
        ),
        diagnostic_finalizer=diagnostic,
        run_finalizer=lambda *_args, **_kwargs: captured.update(finalized=True),
        state_root=tmp_path / "state",
        run_id="run_" + "6" * 32,
    )

    _validate(report)
    assert report["recoveries"][0]["diagnostics"]["state"] == "available", report
    assert report["result"] == "ready", report
    assert [item["status"] for item in report["recoveries"][0]["ledger"]] == [
        "applied",
        "unchanged",
    ]
    assert captured["finalized"] is True
    assert [item["path"] for item in captured["evidence"]] == [str(first), str(second)]
    assert captured["evidence"][0]["sources"]
    assert captured["evidence"][0]["planned_operation_ids"] == ["op_" + "f" * 64]
    assert captured["evidence"][1]["preflight"]["components"]
    assert captured["evidence"][1]["post_apply_verification"]


def test_true_preclaim_is_abandoned_only_after_bound_diagnostic(tmp_path) -> None:
    root = tmp_path
    project = tmp_path / "project"
    inspection_id = "sha256:" + "a" * 64
    canonical_request = {
        "schema_version": "1.0",
        "roots": [str(root)],
        "projects": [{"path": str(project), "components": ["claude"]}],
    }
    interrupted_run = "run_" + "7" * 32
    context = SimpleNamespace(
        owner_live=False,
        state="claiming",
        plan_state="reviewed",
        plan_id="plan_" + "7" * 32,
        canonical_request=canonical_request,
        plans=(_reviewed_plan(str(project), inspection_id, executable=False),),
        request_fingerprint=_fingerprint(canonical_request),
        fresh_plan_fingerprint="sha256:" + "7" * 64,
        helper_version="2.6.0",
        schema_version="1.0",
    )
    events: list[str] = []

    def diagnostic(run_id, *_args, **_kwargs):
        events.append("diagnostic")
        return {
            "schema_version": "1.0",
            "id": run_id,
            "state": "available",
            "path": "/private/preclaim.json",
            "created_at": "2026-08-04T18:00:00Z",
            "detail": "A private redacted reconciliation record was saved.",
        }

    def abandon(run_id, *, ledger, diagnostic_id, diagnostic_state, root):
        events.append("abandon")
        assert run_id == diagnostic_id == interrupted_run
        assert diagnostic_state == "available"
        assert ledger[0]["status"] == "blocked"
        assert root == tmp_path / "state"

    report = build_recover_report(
        machine_builder=lambda: _machine(root),
        census_builder=lambda **_kwargs: [_project(project, root, inspection_id)],
        recovery_lister=lambda **_kwargs: (interrupted_run,),
        context_loader=lambda *_args, **_kwargs: context,
        transaction_recoverer=lambda *_args, **_kwargs: pytest.fail(
            "preclaim recovery must not enter transaction authority"
        ),
        preclaim_abandoner=abandon,
        diagnostic_finalizer=diagnostic,
        state_root=tmp_path / "state",
        run_id="run_" + "8" * 32,
    )

    _validate(report)
    assert report["result"] == "ready"
    assert report["recoveries"][0]["diagnostics"]["state"] == "available"
    assert events == ["diagnostic", "abandon"]


def test_killed_true_preclaim_builds_bound_record_then_abandons(tmp_path) -> None:
    state = tmp_path / "state"
    project = tmp_path / "project"
    inspection_id = "sha256:" + "a" * 64
    request = {
        "schema_version": "1.0",
        "roots": [str(tmp_path)],
        "projects": [{"path": str(project), "components": ["claude"]}],
    }
    public_plan = _reviewed_plan(str(project), inspection_id, executable=False)
    fresh = "sha256:" + "8" * 64
    record = issue_plan(
        _fingerprint(request),
        fresh,
        [public_plan],
        canonical_request=request,
        helper_version="2.6.0",
        schema_version="1.0",
        root=state,
    )
    interrupted_run = "run_" + "a" * 32
    child = """
import os
import sys
from pathlib import Path
from cc.core.ecosystem import project_plan_store as store

original = store.atomic_json_write
writes = 0
def kill_after_claiming_intent(path, payload):
    global writes
    original(path, payload)
    writes += 1
    if writes == 1:
        os._exit(73)

store.atomic_json_write = kill_after_claiming_intent
store.claim_plan(
    sys.argv[1], sys.argv[2], sys.argv[3], run_id=sys.argv[4], root=Path(sys.argv[5])
)
"""
    environment = dict(os.environ)
    source_root = Path(__file__).resolve().parents[1] / "src"
    environment["PYTHONPATH"] = (
        str(source_root) + os.pathsep + environment.get("PYTHONPATH", "")
    )
    killed = subprocess.run(
        (
            sys.executable,
            "-c",
            child,
            record.plan_id,
            _fingerprint(request),
            fresh,
            interrupted_run,
            str(state),
        ),
        env=environment,
        check=False,
    )
    assert killed.returncode == 73
    context = load_recovery_context(interrupted_run, root=state)
    assert (context.state, context.plan_state) == ("claiming", "reviewed")

    report = build_recover_report(
        machine_builder=lambda: _machine(tmp_path),
        census_builder=lambda **_kwargs: [_project(project, tmp_path, inspection_id)],
        state_root=state,
        run_id="run_" + "b" * 32,
    )

    _validate(report)
    assert report["recoveries"][0]["diagnostics"]["state"] == "available", report
    abandoned = load_recovery_context(interrupted_run, root=state)
    assert (abandoned.state, abandoned.outcome) == ("abandoned", "blocked"), report
    assert report["result"] == "ready", report
    assert incomplete_run_ids(root=state) == ()
    diagnostic = json.loads(
        (state / "diagnostics" / f"reconciliation-{interrupted_run}.json").read_text(
            encoding="utf-8"
        )
    )
    assert diagnostic["canonical_request"] == request
    assert diagnostic["reviewed_plans"] == [public_plan]


@pytest.mark.parametrize("tamper", ["ledger", "sources", "ancestor"])
def test_final_intent_refuses_tampered_or_symlinked_diagnostic(
    tmp_path, tamper: str
) -> None:
    state = tmp_path / "state"
    path = "/projects/example"
    inspection_id = "sha256:" + "a" * 64
    request = {
        "schema_version": "1.0",
        "roots": ["/projects"],
        "projects": [{"path": path, "components": ["claude"]}],
    }
    public_plan = _reviewed_plan(path, inspection_id, executable=False)
    fresh = "sha256:" + "9" * 64
    record = issue_plan(
        _fingerprint(request),
        fresh,
        [public_plan],
        canonical_request=request,
        helper_version="2.6.0",
        schema_version="1.0",
        root=state,
    )
    run_id = "run_" + "9" * 32
    claim = claim_plan(
        record.plan_id,
        _fingerprint(request),
        fresh,
        run_id=run_id,
        root=state,
    )
    ledger = [
        {
            "path": path,
            "status": "unchanged",
            "completed_operation_ids": [],
            "verification": "ready",
            "rollback": [],
        }
    ]
    finish_plan(
        record.plan_id,
        claim.claim_token,
        "applied",
        ledger=ledger,
        root=state,
    )
    diagnostic = finalize_run_diagnostic(
        run_id,
        record.plan_id,
        _fingerprint(request),
        ledger,
        canonical_request=request,
        reviewed_plans=[public_plan],
        fresh_plan_fingerprint=fresh,
        helper_version="2.6.0",
        schema_version="1.0",
        final_census={"ready": 1, "total": 1},
        root=state,
    )
    assert diagnostic.state == "available"
    diagnostic_path = Path(str(diagnostic.path))
    if tamper == "ancestor":
        outside = tmp_path / "outside-diagnostics"
        diagnostic_path.parent.rename(outside)
        diagnostic_path.parent.symlink_to(outside, target_is_directory=True)
    else:
        payload = json.loads(diagnostic_path.read_text(encoding="utf-8"))
        if tamper == "ledger":
            payload["projects"][0]["status"] = "blocked"
        else:
            payload["source_bindings"] = []
        diagnostic_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PlanBindingMismatch):
        finalize_run_intent(
            run_id,
            diagnostic_id=run_id,
            diagnostic_state="available",
            root=state,
        )
    assert incomplete_run_ids(root=state) == (run_id,)


def test_incomplete_rollback_blocks_apply_then_retries_retained_snapshot(
    tmp_path,
) -> None:
    root = tmp_path
    project = _repo(tmp_path / "project")
    state = tmp_path / "state"
    run_id = "run_" + "1" * 32
    inspection_id = "sha256:" + "a" * 64
    request_payload = {
        "schema_version": "1.0",
        "roots": [str(root)],
        "projects": [{"path": str(project), "components": ["claude"]}],
    }
    request = parse_reconciliation_request(request_payload)
    with __import__(
        "cc.core.ecosystem.project_locking", fromlist=["project_lock"]
    ).project_lock(project, lock_root=tmp_path / "fingerprint-locks") as anchored:
        before_fingerprint = anchored.fingerprint("CLAUDE.md")
    operation_id = "op_" + "b" * 64
    public_plan = {
        "path": str(project),
        "inspection_id": inspection_id,
        "recipes": [{"component": "claude", "recipe_id": "claude-project-update-v1"}],
        "sources": [],
        "operations": [
            {
                "id": operation_id,
                "kind": "append-managed-block",
                "component": "claude",
                "target": "CLAUDE.md",
                "description": "Append the bounded Claude entry.",
                "expected_before_fingerprint": before_fingerprint,
                "source_fingerprint": None,
            }
        ],
        "preservation": [],
        "prohibited_actions": ["overwrite-project-owned-content"],
        "verification": ["claude-project-integration"],
    }
    fresh_fingerprint = "sha256:" + "c" * 64
    record = issue_plan(
        _fingerprint(request_payload),
        fresh_fingerprint,
        [public_plan],
        canonical_request=request_payload,
        helper_version="2.6.0",
        schema_version="1.0",
        root=state,
    )
    claim = claim_plan(
        record.plan_id,
        _fingerprint(request_payload),
        fresh_fingerprint,
        run_id=run_id,
        root=state,
    )
    transaction = ProjectTransactionPlan(
        path=str(project),
        expected_identity=inspect_project_identity(project),
        operations=(
            TransactionOperation(
                id=operation_id,
                kind="append-managed-block",
                component="claude",
                target="CLAUDE.md",
                expected_before_fingerprint=before_fingerprint,
                source_fingerprint=None,
                payload={"block": "<!-- managed -->\nManaged.\n"},
            ),
        ),
        verification=lambda _project: False,
        inspection_id=inspection_id,
    )

    def conflict(event, _context):
        if event == "before-rollback":
            (project / "CLAUDE.md").write_text("Human edit.\n", encoding="utf-8")

    ledger = execute_reconciliation(
        [transaction], run_id=run_id, observer=conflict, root=state
    )
    assert ledger[0]["status"] == "incomplete-rollback"
    finish_plan(
        record.plan_id,
        claim.claim_token,
        "partial",
        ledger=ledger,
        root=state,
    )
    intent_path = state / "runs" / f"{run_id}.json"
    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    intent["owner_pid"] = 999_999_999
    atomic_json_write(intent_path, intent)
    assert load_recovery_context(run_id, root=state).state == "recovered-projects"

    inspected = False

    def must_not_inspect() -> dict:
        nonlocal inspected
        inspected = True
        return _machine(root)

    with pytest.raises(ReconciliationError, match="must be recovered"):
        build_apply_report(
            request,
            "plan_" + "d" * 32,
            machine_builder=must_not_inspect,
            state_root=state,
        )
    assert inspected is False

    first = build_recover_report(
        machine_builder=lambda: _machine(root),
        census_builder=lambda **_kwargs: [_project(project, root, inspection_id)],
        state_root=state,
        run_id="run_" + "2" * 32,
    )
    _validate(first)
    assert first["result"] == "blocked"
    assert first["recoveries"][0]["outcome"] == "incomplete-rollback"
    assert incomplete_run_ids(root=state) == (run_id,)

    (project / "CLAUDE.md").write_text(
        "Before.\n\n<!-- managed -->\nManaged.\n", encoding="utf-8"
    )
    second = build_recover_report(
        machine_builder=lambda: _machine(root),
        census_builder=lambda **_kwargs: [_project(project, root, inspection_id)],
        state_root=state,
        run_id="run_" + "3" * 32,
    )
    _validate(second)
    assert second["result"] == "ready"
    assert second["recoveries"][0]["outcome"] == "rolled-back"
    assert incomplete_run_ids(root=state) == ()
    assert (project / "CLAUDE.md").read_text(encoding="utf-8") == "Before.\n"
    diagnostic = json.loads(
        (state / "diagnostics" / f"reconciliation-{run_id}.json").read_text(
            encoding="utf-8"
        )
    )
    evidence = diagnostic["projects"][0]["evidence"]
    assert evidence["preflight"]["inspection_id"] == inspection_id
    assert evidence["planned_operation_ids"] == [operation_id]
    assert evidence["post_apply_verification"]

    third = build_recover_report(
        state_root=state,
        run_id="run_" + "4" * 32,
    )
    _validate(third)
    assert third["result"] == "ready"
    assert third["recoveries"] == []
