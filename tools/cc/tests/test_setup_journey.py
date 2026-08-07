from __future__ import annotations

from copy import deepcopy

from cc.core.ecosystem.setup_journey import build_setup_journey_report


def _ready_assessment() -> dict:
    return {
        "phase": "assess",
        "result": "ready",
        "projects": [],
        "default_selection": [],
    }


def _ready_store() -> dict:
    return {"result": "ready", "checks": {"read_only": True}}


def test_journey_claims_operational_only_after_every_phase_is_ready(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "cc.core.ecosystem.setup_journey.resolve_key",
        lambda key: "Example-Org" if key == "github_app.org" else "/repos",
    )
    report = build_setup_journey_report(
        recover_builder=lambda: {"phase": "recover", "result": "ready"},
        prepare_builder=lambda: {
            "phase": "prepare",
            "result": "ready",
            "completed_actions": [],
        },
        ecosystem_builder=lambda **kwargs: {
            "result": "ready",
            "completed_actions": [],
        },
        store_builder=_ready_store,
        assess_builder=_ready_assessment,
        diagnostics_writer=lambda report: {"state": "available", "path": "/report"},
    )

    assert report["result"] == "ready"
    assert report["operational"] is True
    assert report["confidence"] == 0.95
    assert report["diagnostics"]["path"] == "/report"


def test_journey_applies_safe_defaults_then_reassesses_and_checkpoints(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "cc.core.ecosystem.setup_journey.resolve_key",
        lambda key: "Example-Org" if key == "github_app.org" else "/repos",
    )
    actionable = {
        "phase": "assess",
        "result": "action-required",
        "projects": [
            {
                "path": "/projects/one",
                "root": "/projects",
                "scope": {"kind": "product-project"},
            }
        ],
        "default_selection": [{"path": "/projects/one", "components": ["claude"]}],
    }
    assessments = iter((deepcopy(actionable), _ready_assessment(), _ready_assessment()))
    preparations: list[int] = []

    def prepare():
        preparations.append(1)
        return {"phase": "prepare", "result": "ready", "completed_actions": []}

    report = build_setup_journey_report(
        recover_builder=lambda: {"phase": "recover", "result": "ready"},
        prepare_builder=prepare,
        ecosystem_builder=lambda **kwargs: {
            "result": "ready",
            "completed_actions": [],
        },
        store_builder=_ready_store,
        assess_builder=lambda: next(assessments),
        plan_builder=lambda request: {
            "phase": "plan",
            "result": "ready",
            "plan_id": "plan_" + "1" * 32,
        },
        apply_builder=lambda request, plan_id: {
            "phase": "apply",
            "result": "applied",
            "ledger": [{"path": "/projects/one", "status": "applied"}],
        },
        diagnostics_writer=lambda report: {"state": "available", "path": "/report"},
    )

    assert len(preparations) == 3
    assert report["operational"] is True


def test_journey_retries_when_final_verification_races_product_edits(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "cc.core.ecosystem.setup_journey.resolve_key",
        lambda key: "Example-Org" if key == "github_app.org" else "/repos",
    )
    dirty = {
        "phase": "assess",
        "result": "action-required",
        "machine": {"state": "ready", "blockers": []},
        "projects": [
            {
                "path": "/projects/one",
                "scope": {"kind": "product-project"},
                "route": "held",
                "blockers": [{"code": "dirty-working-tree"}],
            }
        ],
        "default_selection": [],
    }
    assessments = iter((deepcopy(dirty), deepcopy(dirty), _ready_assessment()))
    preparations: list[int] = []

    def prepare():
        preparations.append(1)
        return {"phase": "prepare", "result": "ready", "completed_actions": []}

    report = build_setup_journey_report(
        recover_builder=lambda: {"phase": "recover", "result": "ready"},
        prepare_builder=prepare,
        ecosystem_builder=lambda **kwargs: {
            "result": "ready",
            "completed_actions": [],
        },
        store_builder=_ready_store,
        assess_builder=lambda: next(assessments),
        diagnostics_writer=lambda report: {"state": "available", "path": "/report"},
    )

    assert len(preparations) == 3
    assert report["operational"] is True


def test_journey_caps_final_dirty_project_stabilization(monkeypatch) -> None:
    monkeypatch.setattr(
        "cc.core.ecosystem.setup_journey.resolve_key",
        lambda key: "Example-Org" if key == "github_app.org" else "/repos",
    )
    dirty = {
        "phase": "assess",
        "result": "action-required",
        "machine": {"state": "ready", "blockers": []},
        "projects": [
            {
                "path": "/projects/one",
                "scope": {"kind": "product-project"},
                "route": "held",
                "blockers": [{"code": "dirty-working-tree"}],
            }
        ],
        "default_selection": [],
    }
    preparations: list[int] = []

    def prepare():
        preparations.append(1)
        return {"phase": "prepare", "result": "ready", "completed_actions": []}

    report = build_setup_journey_report(
        recover_builder=lambda: {"phase": "recover", "result": "ready"},
        prepare_builder=prepare,
        ecosystem_builder=lambda **kwargs: {
            "result": "ready",
            "completed_actions": [],
        },
        store_builder=_ready_store,
        assess_builder=lambda: deepcopy(dirty),
        diagnostics_writer=lambda report: {"state": "available", "path": "/report"},
        max_final_stabilization_passes=2,
    )

    assert len(preparations) == 3
    assert report["operational"] is False
    assert report["confidence"] == 0.0


def test_journey_never_claims_operational_when_external_phase_is_held(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "cc.core.ecosystem.setup_journey.resolve_key",
        lambda key: "Example-Org" if key == "github_app.org" else "/repos",
    )
    report = build_setup_journey_report(
        recover_builder=lambda: {"phase": "recover", "result": "ready"},
        prepare_builder=lambda: {
            "phase": "prepare",
            "result": "partial",
            "completed_actions": [],
        },
        ecosystem_builder=lambda **kwargs: {
            "result": "ready",
            "completed_actions": [],
        },
        store_builder=_ready_store,
        assess_builder=_ready_assessment,
        diagnostics_writer=lambda report: {"state": "available", "path": "/report"},
    )

    assert report["result"] == "action-required"
    assert report["operational"] is False
    assert report["confidence"] == 0.0


def test_journey_does_not_treat_successful_prepare_with_machine_action_as_a_hold(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "cc.core.ecosystem.setup_journey.resolve_key",
        lambda key: "Example-Org" if key == "github_app.org" else "/repos",
    )
    action_required = {
        "phase": "assess",
        "result": "action-required",
        "projects": [],
        "default_selection": [],
        "machine_summary": {"title": "This Mac needs attention."},
        "next_actions": ["Restore the organization credential store."],
    }
    report = build_setup_journey_report(
        recover_builder=lambda: {"phase": "recover", "result": "ready"},
        prepare_builder=lambda: {
            "phase": "prepare",
            "result": "action-required",
            "completed_actions": [],
            "holds": [],
        },
        ecosystem_builder=lambda **kwargs: {
            "result": "ready",
            "completed_actions": [],
        },
        store_builder=_ready_store,
        assess_builder=lambda: action_required,
        diagnostics_writer=lambda report: {"state": "available", "path": "/report"},
    )

    assert [hold["phase"] for hold in report["holds"]] == ["verify-all"]


def test_journey_does_not_return_raw_exception_text(monkeypatch) -> None:
    monkeypatch.setattr(
        "cc.core.ecosystem.setup_journey.resolve_key",
        lambda key: "Example-Org" if key == "github_app.org" else "/repos",
    )
    report = build_setup_journey_report(
        recover_builder=lambda: (_ for _ in ()).throw(
            RuntimeError("password=do-not-return-this")
        ),
        diagnostics_writer=lambda report: {"state": "unavailable", "path": None},
    )

    assert "do-not-return-this" not in str(report)
    assert report["holds"][0]["error"]["code"] == "recover-unavailable"


def test_journey_result_survives_diagnostic_writer_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        "cc.core.ecosystem.setup_journey.resolve_key",
        lambda key: "Example-Org" if key == "github_app.org" else "/repos",
    )

    def fail_diagnostic(report):
        raise RuntimeError("token=do-not-return-this")

    report = build_setup_journey_report(
        recover_builder=lambda: {"phase": "recover", "result": "ready"},
        prepare_builder=lambda: {
            "phase": "prepare",
            "result": "ready",
            "completed_actions": [],
        },
        ecosystem_builder=lambda **kwargs: {
            "result": "ready",
            "completed_actions": [],
        },
        store_builder=_ready_store,
        assess_builder=_ready_assessment,
        diagnostics_writer=fail_diagnostic,
    )

    assert report["operational"] is True
    assert report["diagnostics"]["state"] == "unavailable"
    assert "do-not-return-this" not in str(report)


def test_journey_never_claims_operational_without_live_read_only_store_proof(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "cc.core.ecosystem.setup_journey.resolve_key",
        lambda key: "Example-Org" if key == "github_app.org" else "/repos",
    )
    report = build_setup_journey_report(
        recover_builder=lambda: {"phase": "recover", "result": "ready"},
        prepare_builder=lambda: {
            "phase": "prepare",
            "result": "ready",
            "completed_actions": [],
        },
        ecosystem_builder=lambda **kwargs: {
            "result": "ready",
            "completed_actions": [],
        },
        store_builder=lambda: {
            "result": "unsafe",
            "checks": {"positive_read": True, "negative_denied": False},
        },
        assess_builder=_ready_assessment,
        diagnostics_writer=lambda report: {"state": "available", "path": "/report"},
    )

    assert report["operational"] is False
    assert report["confidence"] == 0.0
    assert any(hold.get("phase") == "store" for hold in report["holds"])
