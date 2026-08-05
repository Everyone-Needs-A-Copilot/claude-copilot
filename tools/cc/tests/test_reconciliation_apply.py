from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from cc.core.ecosystem.project_plan_store import PlanExpired
from cc.core.ecosystem.reconciliation import (
    ReconciliationError,
    build_apply_report,
)
from cc.core.ecosystem.reconciliation_types import parse_reconciliation_request
from jsonschema import Draft202012Validator


def _request():
    return parse_reconciliation_request(
        {
            "schema_version": "1.0",
            "roots": ["/projects"],
            "projects": [{"path": "/projects/example", "components": ["claude"]}],
        }
    )


def _machine() -> dict:
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
                "detail": f"The {component.title()} framework is ready.",
            }
            for component in ("claude", "codex")
        ],
        "configuration": {
            "state": "ready",
            "path": "/config.json",
            "approved_roots": ["/projects"],
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


def _project() -> dict:
    fingerprint = "sha256:" + ("a" * 64)
    return {
        "path": "/projects/example",
        "root": "/projects",
        "name": "example",
        "inspection_id": fingerprint,
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


def _plans(*, with_operation: bool = True):
    operation = {
        "id": "op_" + ("b" * 64),
        "kind": "append-managed-block",
        "component": "claude",
        "target": "CLAUDE.md",
        "description": "Add the bounded Claude entry.",
        "expected_before_fingerprint": "sha256:" + ("c" * 64),
        "source_fingerprint": None,
    }
    operations = [operation] if with_operation else []
    public = {
        "path": "/projects/example",
        "inspection_id": "sha256:" + ("a" * 64),
        "recipes": [{"component": "claude", "recipe_id": "claude-project-setup-v1"}],
        "sources": [],
        "operations": operations,
        "preservation": [],
        "prohibited_actions": ["overwrite-project-owned-content"],
        "verification": ["claude-project-integration"],
    }
    execution = SimpleNamespace(
        path="/projects/example",
        operations=tuple(SimpleNamespace(**item) for item in operations),
    )
    return [public], [execution]


def _diagnostic(run_id: str) -> dict:
    return {
        "schema_version": "1.0",
        "id": run_id,
        "state": "available",
        "path": "/private/reconciliation.json",
        "created_at": "2026-08-04T18:00:00Z",
        "detail": "A private redacted reconciliation record was saved.",
    }


def _claim_value(
    plan_id: str,
    request_fingerprint: str,
    fresh_plan_fingerprint: str,
    run_id: str,
    plans: list[dict],
) -> SimpleNamespace:
    payload = json.dumps(
        {
            "request_fingerprint": request_fingerprint,
            "fresh_plan_fingerprint": fresh_plan_fingerprint,
            "helper_version": "2.6.0",
            "schema_version": "1.0",
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return SimpleNamespace(
        plan_id=plan_id,
        claim_token="1" * 64,
        request_fingerprint=request_fingerprint,
        fresh_plan_fingerprint=fresh_plan_fingerprint,
        binding_fingerprint="sha256:" + hashlib.sha256(payload).hexdigest(),
        plans=tuple(plans),
        run_id=run_id,
    )


def _validate(report: dict) -> None:
    schema = json.loads(
        (Path(__file__).parent / "fixtures/schemas/reconcile.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(report)


def test_apply_claims_executes_consumes_refreshes_and_receipts() -> None:
    public, execution = _plans()
    captured: dict = {}

    def claim(plan_id, request_fingerprint, fresh_plan_fingerprint, *, run_id):
        captured.update(
            claimed=(plan_id, request_fingerprint, fresh_plan_fingerprint, run_id)
        )
        return _claim_value(
            plan_id,
            request_fingerprint,
            fresh_plan_fingerprint,
            run_id,
            public,
        )

    def finish(plan_id, claim_token, outcome, *, ledger):
        captured["finished"] = (plan_id, claim_token, outcome)
        captured["finished_ledger"] = ledger

    def execute(plans, *, run_id):
        captured["executed"] = (plans, run_id)
        return [
            {
                "path": "/projects/example",
                "status": "applied",
                "detail": "Every targeted operation completed and fresh verification passed.",
                "completed_operation_ids": ["op_" + ("b" * 64)],
                "verification": "ready",
                "rollback": [],
            }
        ]

    report = build_apply_report(
        _request(),
        "plan_" + ("1" * 32),
        machine_builder=_machine,
        census_builder=lambda **_kwargs: [_project()],
        plan_builder=lambda **_kwargs: (public, execution),
        plan_claimer=claim,
        plan_finisher=finish,
        transaction_adapter=lambda plan: ("adapted", plan.path),
        transaction_executor=execute,
        diagnostic_finalizer=lambda run_id, *_args, **_kwargs: _diagnostic(run_id),
        run_id="run_" + ("2" * 32),
    )

    _validate(report)
    assert report["result"] == "applied"
    assert report["ledger"][0]["status"] == "applied"
    assert captured["finished"] == (
        "plan_" + ("1" * 32),
        "1" * 64,
        "applied",
    )
    assert captured["executed"][1] == "run_" + ("2" * 32)


def test_stale_or_expired_plan_returns_blocked_receipt_without_mutation() -> None:
    public, execution = _plans()
    called = {"executor": False, "finisher": False}

    def expired(*_args, **_kwargs):
        raise PlanExpired("sensitive internal detail that must not be returned")

    def finalize(run_id, *_args, **kwargs):
        called["project_evidence"] = kwargs["project_evidence"]
        return _diagnostic(run_id)

    report = build_apply_report(
        _request(),
        "plan_" + ("3" * 32),
        machine_builder=_machine,
        census_builder=lambda **_kwargs: [_project()],
        plan_builder=lambda **_kwargs: (public, execution),
        plan_claimer=expired,
        plan_finisher=lambda *_args, **_kwargs: called.update(finisher=True),
        transaction_executor=lambda *_args, **_kwargs: called.update(executor=True),
        diagnostic_finalizer=finalize,
        run_id="run_" + ("4" * 32),
    )

    _validate(report)
    assert report["result"] == "blocked"
    assert report["ledger"][0]["status"] == "blocked"
    assert called["executor"] is False
    assert called["finisher"] is False
    assert called["project_evidence"][0]["post_apply_verification"] == [
        {"component": "claude", "state": "not-run", "evidence_ids": []}
    ]
    assert called["project_evidence"][0]["exception"] == {
        "type": "TransactionError",
        "code": "stale-plan",
    }
    assert "sensitive internal detail" not in json.dumps(report)
    assert report["next_actions"] == ["The reviewed plan expired. Create a fresh plan."]


def test_zero_operation_repeat_is_unchanged_and_does_not_enter_executor() -> None:
    public, execution = _plans(with_operation=False)
    captured: dict = {}

    report = build_apply_report(
        _request(),
        "plan_" + ("5" * 32),
        machine_builder=_machine,
        census_builder=lambda **_kwargs: [_project()],
        plan_builder=lambda **_kwargs: (public, execution),
        plan_claimer=lambda plan_id, request_fp, fresh_fp, *, run_id: _claim_value(
            plan_id,
            request_fp,
            fresh_fp,
            run_id,
            public,
        ),
        plan_finisher=lambda *_args, **_kwargs: None,
        transaction_executor=lambda plans, **_kwargs: (
            captured.setdefault("plans", plans) or []
        ),
        diagnostic_finalizer=lambda run_id, *_args, **_kwargs: _diagnostic(run_id),
        run_id="run_" + ("6" * 32),
    )

    _validate(report)
    assert captured["plans"] == []
    assert report["result"] == "applied"
    assert report["ledger"][0] == {
        "path": "/projects/example",
        "status": "unchanged",
        "detail": "The reviewed plan required no project mutation.",
        "completed_operation_ids": [],
        "verification": "ready",
        "rollback": [],
    }


def test_claimed_plan_is_consumed_when_adapter_refuses() -> None:
    public, execution = _plans()
    captured: dict = {}

    report = build_apply_report(
        _request(),
        "plan_" + ("7" * 32),
        machine_builder=_machine,
        census_builder=lambda **_kwargs: [_project()],
        plan_builder=lambda **_kwargs: (public, execution),
        plan_claimer=lambda plan_id, request_fp, fresh_fp, *, run_id: _claim_value(
            plan_id,
            request_fp,
            fresh_fp,
            run_id,
            public,
        ),
        plan_finisher=lambda *args, **_kwargs: captured.setdefault("finish", args),
        transaction_adapter=lambda _plan: (_ for _ in ()).throw(
            RuntimeError("credential sentinel")
        ),
        diagnostic_finalizer=lambda run_id, *_args, **_kwargs: _diagnostic(run_id),
        run_id="run_" + ("8" * 32),
    )

    _validate(report)
    assert report["result"] == "blocked"
    assert captured["finish"][2] == "blocked"
    assert "credential sentinel" not in json.dumps(report)


def test_apply_rejects_non_opaque_plan_id_before_inspection() -> None:
    called = False

    def machine():
        nonlocal called
        called = True
        return _machine()

    with pytest.raises(ReconciliationError, match="opaque plan identifier"):
        build_apply_report(_request(), "not-a-plan", machine_builder=machine)

    assert called is False


def test_apply_rejects_malformed_claim_before_executor() -> None:
    public, execution = _plans()
    called = {"executor": False}

    def malformed_claim(plan_id, request_fp, fresh_fp, *, run_id):
        claim = _claim_value(plan_id, request_fp, fresh_fp, run_id, public)
        claim.claim_token = "x"
        return claim

    report = build_apply_report(
        _request(),
        "plan_" + ("9" * 32),
        machine_builder=_machine,
        census_builder=lambda **_kwargs: [_project()],
        plan_builder=lambda **_kwargs: (public, execution),
        plan_claimer=malformed_claim,
        plan_finisher=lambda *_args, **_kwargs: None,
        transaction_executor=lambda *_args, **_kwargs: called.update(executor=True),
        diagnostic_finalizer=lambda run_id, *_args, **_kwargs: _diagnostic(run_id),
        run_id="run_" + ("a" * 32),
    )

    _validate(report)
    assert report["result"] == "blocked"
    assert called["executor"] is False
    assert report["ledger"][0]["status"] == "blocked"
    assert report["next_actions"] == [
        "This run still requires durable recovery finalization. Run cc reconcile recover --json before another apply."
    ]


def test_invalid_executor_receipt_is_uncertain_and_cannot_leak() -> None:
    public, execution = _plans()

    def claim(plan_id, request_fp, fresh_fp, *, run_id):
        return _claim_value(plan_id, request_fp, fresh_fp, run_id, public)

    report = build_apply_report(
        _request(),
        "plan_" + ("b" * 32),
        machine_builder=_machine,
        census_builder=lambda **_kwargs: [_project()],
        plan_builder=lambda **_kwargs: (public, execution),
        plan_claimer=claim,
        plan_finisher=lambda *_args, **_kwargs: None,
        transaction_adapter=lambda plan: plan,
        transaction_executor=lambda *_args, **_kwargs: [
            {
                "path": "/projects/example",
                "status": "applied",
                "detail": "credential sentinel",
                "completed_operation_ids": ["op_" + ("f" * 64)],
                "verification": "ready",
                "rollback": [],
            }
        ],
        diagnostic_finalizer=lambda run_id, *_args, **_kwargs: _diagnostic(run_id),
        run_id="run_" + ("c" * 32),
    )

    _validate(report)
    assert report["result"] == "partial"
    assert report["ledger"][0]["status"] == "incomplete-rollback"
    assert "credential sentinel" not in json.dumps(report)


@pytest.mark.parametrize(
    "receipt",
    [
        {
            "path": "/projects/example",
            "status": "rolled-back",
            "detail": "ignored",
            "completed_operation_ids": [],
            "verification": "not-run",
            "rollback": [],
        },
        {
            "path": "/projects/example",
            "status": "rolled-back",
            "detail": "ignored",
            "completed_operation_ids": ["op_" + ("b" * 64)],
            "verification": "failed",
            "rollback": [
                {"target": "CLAUDE.md", "status": "conflict", "detail": "ignored"}
            ],
        },
        {
            "path": "/projects/example",
            "status": "incomplete-rollback",
            "detail": "ignored",
            "completed_operation_ids": ["op_" + ("b" * 64)],
            "verification": "failed",
            "rollback": [
                {"target": "CLAUDE.md", "status": "restored", "detail": "ignored"}
            ],
        },
        {
            "path": "/projects/example",
            "status": "rolled-back",
            "detail": "ignored",
            "completed_operation_ids": ["op_" + ("b" * 64)],
            "verification": "failed",
            "rollback": [
                {"target": "CLAUDE.md", "status": "restored", "detail": "ignored"},
                {"target": "CLAUDE.md", "status": "restored", "detail": "ignored"},
            ],
        },
        {
            "path": "/projects/example",
            "status": "incomplete-rollback",
            "detail": "ignored",
            "completed_operation_ids": ["op_" + ("b" * 64)],
            "verification": "failed",
            "rollback": [
                {"target": "CLAUDE.md", "status": "restored", "detail": "ignored"},
                {"target": "CLAUDE.md", "status": "conflict", "detail": "ignored"},
            ],
        },
    ],
)
def test_impossible_rollback_receipts_fail_closed(receipt: dict) -> None:
    public, execution = _plans()

    def claim(plan_id, request_fp, fresh_fp, *, run_id):
        return _claim_value(plan_id, request_fp, fresh_fp, run_id, public)

    report = build_apply_report(
        _request(),
        "plan_" + ("6" * 32),
        machine_builder=_machine,
        census_builder=lambda **_kwargs: [_project()],
        plan_builder=lambda **_kwargs: (public, execution),
        plan_claimer=claim,
        plan_finisher=lambda *_args, **_kwargs: None,
        transaction_adapter=lambda plan: plan,
        transaction_executor=lambda *_args, **_kwargs: [receipt],
        diagnostic_finalizer=lambda run_id, *_args, **_kwargs: _diagnostic(run_id),
        run_id="run_" + ("7" * 32),
    )

    _validate(report)
    assert report["result"] == "partial"
    assert report["ledger"][0]["status"] == "incomplete-rollback"
    assert report["ledger"][0]["rollback"] == []


@pytest.mark.parametrize(
    ("status", "rollback_status", "expected_result"),
    [
        ("rolled-back", "restored", "blocked"),
        ("incomplete-rollback", "conflict", "partial"),
    ],
)
def test_evidence_bound_rollback_receipts_are_preserved(
    status: str, rollback_status: str, expected_result: str
) -> None:
    public, execution = _plans()

    def claim(plan_id, request_fp, fresh_fp, *, run_id):
        return _claim_value(plan_id, request_fp, fresh_fp, run_id, public)

    report = build_apply_report(
        _request(),
        "plan_" + ("8" * 32),
        machine_builder=_machine,
        census_builder=lambda **_kwargs: [_project()],
        plan_builder=lambda **_kwargs: (public, execution),
        plan_claimer=claim,
        plan_finisher=lambda *_args, **_kwargs: None,
        transaction_adapter=lambda plan: plan,
        transaction_executor=lambda *_args, **_kwargs: [
            {
                "path": "/projects/example",
                "status": status,
                "detail": "ignored",
                "completed_operation_ids": ["op_" + ("b" * 64)],
                "verification": "failed",
                "rollback": [
                    {
                        "target": "CLAUDE.md",
                        "status": rollback_status,
                        "detail": "ignored",
                    }
                ],
            }
        ],
        diagnostic_finalizer=lambda run_id, *_args, **_kwargs: _diagnostic(run_id),
        run_id="run_" + ("9" * 32),
    )

    _validate(report)
    assert report["result"] == expected_result
    assert report["ledger"][0]["status"] == status
    assert report["ledger"][0]["rollback"][0]["status"] == rollback_status


@pytest.mark.parametrize(
    "completed_and_rollback",
    [
        (
            ["op_" + ("c" * 64)],
            [{"target": ".mcp.json", "status": "restored", "detail": "ignored"}],
        ),
        (
            ["op_" + ("b" * 64), "op_" + ("c" * 64)],
            [
                {"target": "CLAUDE.md", "status": "restored", "detail": "ignored"},
                {"target": ".mcp.json", "status": "restored", "detail": "ignored"},
            ],
        ),
    ],
)
def test_rollback_receipts_require_completed_prefix_and_reverse_target_order(
    completed_and_rollback: tuple[list[str], list[dict]],
) -> None:
    public, execution = _plans()
    second = {
        "id": "op_" + ("c" * 64),
        "kind": "merge-json-keys",
        "component": "claude",
        "target": ".mcp.json",
        "description": "Merge the bounded MCP marker.",
        "expected_before_fingerprint": "sha256:" + ("d" * 64),
        "source_fingerprint": None,
    }
    public[0]["operations"].append(second)
    execution[0].operations = (*execution[0].operations, SimpleNamespace(**second))

    def claim(plan_id, request_fp, fresh_fp, *, run_id):
        return _claim_value(plan_id, request_fp, fresh_fp, run_id, public)

    completed, rollback = completed_and_rollback
    report = build_apply_report(
        _request(),
        "plan_" + ("a" * 32),
        machine_builder=_machine,
        census_builder=lambda **_kwargs: [_project()],
        plan_builder=lambda **_kwargs: (public, execution),
        plan_claimer=claim,
        plan_finisher=lambda *_args, **_kwargs: None,
        transaction_adapter=lambda plan: plan,
        transaction_executor=lambda *_args, **_kwargs: [
            {
                "path": "/projects/example",
                "status": "rolled-back",
                "detail": "ignored",
                "completed_operation_ids": completed,
                "verification": "failed",
                "rollback": rollback,
            }
        ],
        diagnostic_finalizer=lambda run_id, *_args, **_kwargs: _diagnostic(run_id),
        run_id="run_" + ("b" * 32),
    )

    _validate(report)
    assert report["result"] == "partial"
    assert report["ledger"][0]["status"] == "incomplete-rollback"


def test_extra_executor_receipt_downgrades_batch_but_preserves_valid_peer_truth() -> (
    None
):
    public, execution = _plans()

    def claim(plan_id, request_fp, fresh_fp, *, run_id):
        return _claim_value(plan_id, request_fp, fresh_fp, run_id, public)

    applied = {
        "path": "/projects/example",
        "status": "applied",
        "detail": "ignored",
        "completed_operation_ids": ["op_" + ("b" * 64)],
        "verification": "ready",
        "rollback": [],
    }
    report = build_apply_report(
        _request(),
        "plan_" + ("4" * 32),
        machine_builder=_machine,
        census_builder=lambda **_kwargs: [_project()],
        plan_builder=lambda **_kwargs: (public, execution),
        plan_claimer=claim,
        plan_finisher=lambda *_args, **_kwargs: None,
        transaction_adapter=lambda plan: plan,
        transaction_executor=lambda *_args, **_kwargs: [
            applied,
            {**applied, "path": "/projects/unselected"},
        ],
        diagnostic_finalizer=lambda run_id, *_args, **_kwargs: _diagnostic(run_id),
        run_id="run_" + ("5" * 32),
    )

    _validate(report)
    assert report["result"] == "partial"
    assert report["ledger"] == [
        {
            "path": "/projects/example",
            "status": "applied",
            "detail": "Every targeted operation completed and fresh verification passed.",
            "completed_operation_ids": ["op_" + ("b" * 64)],
            "verification": "ready",
            "rollback": [],
        }
    ]


def test_apply_diagnostics_ignore_unselected_census_projects() -> None:
    public, execution = _plans()
    unrelated = copy.deepcopy(_project())
    unrelated.update(
        {
            "path": "/projects/unrelated",
            "name": "unrelated",
            "selected_components": [],
        }
    )
    for component in unrelated["components"]:
        component["selected"] = False

    def claim(plan_id, request_fp, fresh_fp, *, run_id):
        return _claim_value(plan_id, request_fp, fresh_fp, run_id, public)

    report = build_apply_report(
        _request(),
        "plan_" + ("6" * 32),
        machine_builder=_machine,
        census_builder=lambda **_kwargs: [_project(), unrelated],
        plan_builder=lambda **_kwargs: (public, execution),
        plan_claimer=claim,
        plan_finisher=lambda *_args, **_kwargs: None,
        transaction_adapter=lambda plan: plan,
        transaction_executor=lambda *_args, **_kwargs: [
            {
                "path": "/projects/example",
                "status": "applied",
                "detail": "ignored",
                "completed_operation_ids": ["op_" + ("b" * 64)],
                "verification": "ready",
                "rollback": [],
            }
        ],
        diagnostic_finalizer=lambda run_id, *_args, **_kwargs: _diagnostic(run_id),
        run_id="run_" + ("7" * 32),
    )

    _validate(report)
    assert report["result"] == "applied"
    assert report["ledger"][0]["status"] == "applied"


def test_final_census_contradiction_downgrades_applied_batch() -> None:
    public, execution = _plans()
    assessments = 0

    def census(**_kwargs):
        nonlocal assessments
        assessments += 1
        project = copy.deepcopy(_project())
        if assessments == 2:
            project["route"] = "held"
            project["components"][0]["state"] = "held"
        return [project]

    def claim(plan_id, request_fp, fresh_fp, *, run_id):
        return _claim_value(plan_id, request_fp, fresh_fp, run_id, public)

    report = build_apply_report(
        _request(),
        "plan_" + ("d" * 32),
        machine_builder=_machine,
        census_builder=census,
        plan_builder=lambda **_kwargs: (public, execution),
        plan_claimer=claim,
        plan_finisher=lambda *_args, **_kwargs: None,
        transaction_adapter=lambda plan: plan,
        transaction_executor=lambda *_args, **_kwargs: [
            {
                "path": "/projects/example",
                "status": "applied",
                "detail": "ignored",
                "completed_operation_ids": ["op_" + ("b" * 64)],
                "verification": "ready",
                "rollback": [],
            }
        ],
        diagnostic_finalizer=lambda run_id, *_args, **_kwargs: _diagnostic(run_id),
        run_id="run_" + ("e" * 32),
    )

    _validate(report)
    assert report["result"] == "partial"
    assert report["ledger"][0]["status"] == "applied"
    assert report["projects"][0]["route"] == "held"
    assert report["next_actions"] == [
        "Fresh verification contradicted the transaction receipt. Inspect the selected projects and private diagnostic before continuing."
    ]


def test_zero_operation_and_preexecutor_paths_receive_private_evidence() -> None:
    public, execution = _plans(with_operation=False)
    captured: dict = {}

    def claim(plan_id, request_fp, fresh_fp, *, run_id):
        return _claim_value(plan_id, request_fp, fresh_fp, run_id, public)

    def finalize(run_id, *_args, **kwargs):
        captured.update(kwargs)
        return _diagnostic(run_id)

    report = build_apply_report(
        _request(),
        "plan_" + ("f" * 32),
        machine_builder=_machine,
        census_builder=lambda **_kwargs: [_project()],
        plan_builder=lambda **_kwargs: (public, execution),
        plan_claimer=claim,
        plan_finisher=lambda *_args, **_kwargs: None,
        transaction_executor=lambda *_args, **_kwargs: [],
        diagnostic_finalizer=finalize,
        run_id="run_" + ("1" * 32),
    )

    _validate(report)
    assert captured["project_evidence"][0]["path"] == "/projects/example"
    assert captured["project_evidence"][0]["preflight"]["inspection_id"] == (
        "sha256:" + ("a" * 64)
    )
    assert captured["project_evidence"][0]["post_apply_verification"] == [
        {"component": "claude", "state": "ready", "evidence_ids": []}
    ]


def test_public_diagnostic_reference_is_rebuilt_from_closed_fields() -> None:
    public, execution = _plans(with_operation=False)

    def claim(plan_id, request_fp, fresh_fp, *, run_id):
        return _claim_value(plan_id, request_fp, fresh_fp, run_id, public)

    def diagnostic(run_id, *_args, **_kwargs):
        return {
            **_diagnostic(run_id),
            "detail": "credential sentinel",
            "unexpected": {"token": "credential sentinel"},
        }

    report = build_apply_report(
        _request(),
        "plan_" + ("2" * 32),
        machine_builder=_machine,
        census_builder=lambda **_kwargs: [_project()],
        plan_builder=lambda **_kwargs: (public, execution),
        plan_claimer=claim,
        plan_finisher=lambda *_args, **_kwargs: None,
        transaction_executor=lambda *_args, **_kwargs: [],
        diagnostic_finalizer=diagnostic,
        run_id="run_" + ("3" * 32),
    )

    _validate(report)
    assert report["diagnostics"]["detail"] == (
        "A private redacted reconciliation record was saved."
    )
    assert "credential sentinel" not in json.dumps(report)
