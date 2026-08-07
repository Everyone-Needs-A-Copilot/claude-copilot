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


def test_journey_claims_operational_only_after_every_phase_is_ready(monkeypatch) -> None:
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
        assess_builder=_ready_assessment,
    )

    assert report["result"] == "ready"
    assert report["operational"] is True
    assert report["confidence"] == 0.95


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
        "default_selection": [
            {"path": "/projects/one", "components": ["claude"]}
        ],
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
        assess_builder=lambda: next(assessments),
        plan_builder=lambda request: {"phase": "plan", "result": "ready", "plan_id": "plan_" + "1" * 32},
        apply_builder=lambda request, plan_id: {
            "phase": "apply",
            "result": "applied",
            "ledger": [{"path": "/projects/one", "status": "applied"}],
        },
    )

    assert len(preparations) == 3
    assert report["operational"] is True


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
        assess_builder=_ready_assessment,
    )

    assert report["result"] == "action-required"
    assert report["operational"] is False
    assert report["confidence"] == 0.0
