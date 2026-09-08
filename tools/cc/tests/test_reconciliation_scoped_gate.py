"""New coverage for Fix (a): scoping the machine-wide preflight gate to the
components a request actually selects (`docs/30-operations/12-cse-gap-closure
-and-release-handoff.md`, layer-fix design section 5.2/5.3).

Companion to `test_reconciliation_apply.py`, `test_reconciliation_coordinator.py`
and `test_reconciliation_assistant_product.py`, which stay untouched (existing
tests are read-only). This file reuses their established fixtures by direct
sibling import rather than duplicating the whole harness.

Core property under test: an unrequested framework's `could-not-verify` state
can never block a request that never selected it, but the gate stays
FAIL-CLOSED for anything requested or unattributed.
"""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).parent))

from test_reconciliation_apply import (  # noqa: E402
    _claim_value,
    _diagnostic,
    _plans,
)

from cc.core.ecosystem import reconciliation as coordinator  # noqa: E402
from cc.core.ecosystem.machine_assessment import MachineVerification  # noqa: E402
from cc.core.ecosystem.reconciliation import (  # noqa: E402
    assess_reconciliation,
    build_apply_report,
    build_plan_report,
    build_verify_report,
)
from cc.core.ecosystem.reconciliation_types import (  # noqa: E402
    parse_reconciliation_request,
)


def _request(components: list[str], *, path: str = "/projects/example"):
    return parse_reconciliation_request(
        {
            "schema_version": "1.0",
            "roots": ["/projects"],
            "projects": [{"path": path, "components": components}],
        }
    )


def _two_project_request():
    return parse_reconciliation_request(
        {
            "schema_version": "1.0",
            "roots": ["/projects"],
            "projects": [
                {"path": "/projects/claude-only", "components": ["claude"]},
                {"path": "/projects/codex-too", "components": ["claude", "codex"]},
            ],
        }
    )


def _machine(*, codex_unverifiable: bool) -> dict[str, Any]:
    return {
        "state": "could-not-verify" if codex_unverifiable else "ready",
        "helper": {
            "state": "ready",
            # Must match the hardcoded "helper_version" the imported
            # `_claim_value()` (test_reconciliation_apply.py) bakes into its
            # claim binding payload, or `build_apply_report`'s own binding
            # check rejects the claim as stale before the machine gate is
            # ever reached.
            "version": "2.6.0",
            "path": "/usr/local/bin/cc",
            "detail": "The helper is available.",
        },
        "frameworks": [
            {
                "component": "claude",
                "state": "ready",
                "path": "/claude-framework",
                "version": "5.13.3",
                "detail": "The Claude framework is ready.",
            },
            {
                "component": "codex",
                "state": "could-not-verify" if codex_unverifiable else "ready",
                "path": "/codex-framework",
                "version": None if codex_unverifiable else "0.7.0",
                "detail": (
                    "The configured Codex framework source cannot supply a "
                    "verified reconciliation recipe."
                    if codex_unverifiable
                    else "The Codex framework is ready."
                ),
            },
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
        "blockers": (
            [
                {
                    "code": "codex-framework-recipe-source-unverified",
                    "responsible_actor": "ecosystem-owner",
                    "evidence": [],
                    "next_action": "Restore the authoritative Codex recipe source.",
                }
            ]
            if codex_unverifiable
            else []
        ),
        "next_action": "Nothing needs to be changed.",
    }


def _codex_only_unverifiable_verification() -> MachineVerification:
    return MachineVerification(frozenset({"codex"}), False)


def _patch_machine_builders(
    monkeypatch: pytest.MonkeyPatch,
    machine: dict[str, Any],
    verification: MachineVerification,
) -> None:
    """Patch BOTH the verified builder `prepare_reconciliation` uses and the
    plain builder `build_apply_report`'s own post-apply census refresh calls
    directly -- otherwise the refresh step falls through to the real,
    unmocked production machine assessment."""
    monkeypatch.setattr(
        coordinator, "_default_verified_machine_builder", lambda: (machine, verification)
    )
    monkeypatch.setattr(coordinator, "_default_machine_builder", lambda: machine)


def _beyond_frameworks_verification() -> MachineVerification:
    return MachineVerification(frozenset(), True)


def _project(
    *, path: str = "/projects/example", root: str = "/projects", components: list[str]
) -> dict[str, Any]:
    fingerprint = "sha256:" + ("a" * 64)
    all_components = ["claude", "codex"]
    return {
        "path": path,
        "root": root,
        "name": path.rsplit("/", 1)[-1],
        "inspection_id": fingerprint,
        "presence": (
            "both"
            if set(components) == {"claude", "codex"}
            else "claude-only"
            if components == ["claude"]
            else "codex-only"
            if components == ["codex"]
            else "none"
        ),
        "route": "ready",
        "selected_components": list(components),
        "components": [
            {
                "component": component,
                "state": "ready" if component in components else "not-selected",
                "selected": component in components,
                "recommended": component in components,
                "recommendation_reason": f"{component.title()} is ready.",
                "responsible_actor": "none",
                "evidence": [],
                "missing_requirements": [],
                "next_action": "Nothing needs to be changed.",
                "recipe_options": [],
            }
            for component in all_components
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


def _apply_kwargs(
    request,
    project: dict[str, Any],
    *,
    with_operation: bool = True,
) -> dict[str, Any]:
    public, execution = _plans(with_operation=with_operation)
    public = deepcopy(public)
    execution = deepcopy(execution)
    for plan in public:
        plan["path"] = project["path"]
    for plan in execution:
        plan.path = project["path"]
    return {
        "census_builder": lambda **_kwargs: [project],
        "plan_builder": lambda **_kwargs: (public, execution),
        "plan_claimer": lambda plan_id, request_fp, fresh_fp, *, run_id: _claim_value(
            plan_id, request_fp, fresh_fp, run_id, public
        ),
        "plan_finisher": lambda *_args, **_kwargs: None,
        "transaction_adapter": lambda plan: ("adapted", plan.path),
        "transaction_executor": lambda plans, **_kwargs: [
            {
                "path": project["path"],
                "status": "applied",
                "detail": "Every targeted operation completed and fresh verification passed.",
                "completed_operation_ids": [
                    op["id"] for op in public[0]["operations"]
                ],
                "verification": "ready",
                "rollback": [],
            }
        ],
        "diagnostic_finalizer": lambda run_id, *_args, **_kwargs: _diagnostic(run_id),
    }


def test_apply_proceeds_when_only_unrequested_framework_is_unverifiable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    machine = _machine(codex_unverifiable=True)
    verification = _codex_only_unverifiable_verification()
    _patch_machine_builders(monkeypatch, machine, verification)
    project = _project(components=["claude"])
    request = _request(["claude"])

    report = build_apply_report(
        request,
        "plan_" + ("1" * 32),
        **_apply_kwargs(request, project),
        run_id="run_" + ("1" * 32),
    )

    _validate(report)
    # The scoped PREFLIGHT gate (`build_apply_report`'s own
    # `unsafe-machine-preflight` check, the one Fix (a) changes) does not
    # fire: the claim/execute transaction runs and the ledger shows the
    # project actually applied. `_post_apply_contradictions` (a SEPARATE,
    # deliberately-unscoped post-hoc verification the design does not name
    # for scoping) still reads the raw, unscoped `machine.state` and can
    # downgrade the top-level `result` to "partial" purely because Codex
    # remains genuinely unverifiable machine-wide -- that is expected,
    # unmodified, conservative behavior, not a regression of this fix.
    assert report["result"] in {"applied", "partial"}
    assert report["ledger"][0]["status"] == "applied"


def test_apply_still_blocks_when_the_requested_framework_is_unverifiable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`build_apply_report` catches its own internal `unsafe-machine-preflight`
    and returns a blocked report rather than raising -- assert on the report,
    not on a propagated exception (matches the existing
    `test_stale_or_expired_plan_returns_blocked_receipt_without_mutation`
    pattern in test_reconciliation_apply.py)."""
    machine = _machine(codex_unverifiable=True)
    verification = _codex_only_unverifiable_verification()
    _patch_machine_builders(monkeypatch, machine, verification)
    project = _project(components=["codex"])
    request = _request(["codex"])
    kwargs = _apply_kwargs(request, project)
    kwargs["plan_claimer"] = lambda *_a, **_k: (_ for _ in ()).throw(
        AssertionError("apply must never claim a plan behind a blocked gate")
    )

    report = build_apply_report(
        request,
        "plan_" + ("2" * 32),
        **kwargs,
        run_id="run_" + ("2" * 32),
    )

    _validate(report)
    assert report["result"] == "blocked"


def test_apply_still_blocks_on_non_framework_machine_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    machine = _machine(codex_unverifiable=True)
    verification = _beyond_frameworks_verification()
    _patch_machine_builders(monkeypatch, machine, verification)
    project = _project(components=["claude"])
    request = _request(["claude"])
    kwargs = _apply_kwargs(request, project)
    kwargs["plan_claimer"] = lambda *_a, **_k: (_ for _ in ()).throw(
        AssertionError("apply must never claim a plan behind a blocked gate")
    )

    report = build_apply_report(
        request,
        "plan_" + ("3" * 32),
        **kwargs,
        run_id="run_" + ("3" * 32),
    )

    _validate(report)
    assert report["result"] == "blocked"


def test_apply_fails_closed_for_an_injected_bare_dict_machine_builder() -> None:
    """Guards `_conservative_verification`: a legacy injected `machine_builder`
    supplies no attribution at all, so a could-not-verify machine must still
    block even for a claude-only request."""
    machine = _machine(codex_unverifiable=True)
    project = _project(components=["claude"])
    request = _request(["claude"])
    kwargs = _apply_kwargs(request, project)
    kwargs["plan_claimer"] = lambda *_a, **_k: (_ for _ in ()).throw(
        AssertionError("apply must never claim a plan behind a blocked gate")
    )

    report = build_apply_report(
        request,
        "plan_" + ("4" * 32),
        machine_builder=lambda: machine,
        **kwargs,
        run_id="run_" + ("4" * 32),
    )

    _validate(report)
    assert report["result"] == "blocked"


def test_apply_blocks_when_request_spans_both_and_one_is_unverifiable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    machine = _machine(codex_unverifiable=True)
    verification = _codex_only_unverifiable_verification()
    _patch_machine_builders(monkeypatch, machine, verification)
    request = _two_project_request()
    claude_only_project = _project(
        path="/projects/claude-only", components=["claude"]
    )
    both_project = _project(
        path="/projects/codex-too", components=["claude", "codex"]
    )
    public1, execution1 = _plans(with_operation=True)
    public1[0]["path"] = "/projects/claude-only"
    execution1[0].path = "/projects/claude-only"
    public2, execution2 = _plans(with_operation=True)
    public2[0]["path"] = "/projects/codex-too"
    execution2[0].path = "/projects/codex-too"
    public = public1 + public2
    execution = execution1 + execution2

    report = build_apply_report(
        request,
        "plan_" + ("5" * 32),
        census_builder=lambda **_kwargs: [claude_only_project, both_project],
        plan_builder=lambda **_kwargs: (public, execution),
        plan_claimer=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("apply must never claim a plan behind a blocked gate")
        ),
        run_id="run_" + ("5" * 32),
    )

    _validate(report)
    assert report["result"] == "blocked"


def test_plan_result_is_scoped_to_requested_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    machine = _machine(codex_unverifiable=True)
    verification = _codex_only_unverifiable_verification()
    _patch_machine_builders(monkeypatch, machine, verification)
    project = _project(components=["claude"])
    request = _request(["claude"])
    public, execution = _plans(with_operation=True)
    public[0]["path"] = project["path"]
    execution[0].path = project["path"]

    report = build_plan_report(
        request,
        census_builder=lambda **_kwargs: [project],
        plan_builder=lambda **_kwargs: (public, execution),
        plan_issuer=lambda **kwargs: {
            "plan_id": "plan_" + ("6" * 32),
            "expires_at": "2026-09-08T12:00:00Z",
        },
        run_id="run_" + ("6" * 32),
    )

    _validate(report)
    assert report["result"] == "action-required"


def test_verify_result_is_scoped_to_requested_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    machine = _machine(codex_unverifiable=True)
    verification = _codex_only_unverifiable_verification()
    _patch_machine_builders(monkeypatch, machine, verification)
    project = _project(components=["claude"])
    request = _request(["claude"])

    report = build_verify_report(
        request,
        census_builder=lambda **_kwargs: [project],
        run_id="run_" + ("7" * 32),
    )

    _validate(report)
    assert report["result"] != "blocked"


def test_verify_still_blocks_when_requested_framework_is_unverifiable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    machine = _machine(codex_unverifiable=True)
    verification = _codex_only_unverifiable_verification()
    _patch_machine_builders(monkeypatch, machine, verification)
    project = _project(components=["codex"])
    request = _request(["codex"])

    report = build_verify_report(
        request,
        census_builder=lambda **_kwargs: [project],
        run_id="run_" + ("8" * 32),
    )

    _validate(report)
    assert report["result"] == "blocked"


def test_assess_remains_globally_honest(monkeypatch: pytest.MonkeyPatch) -> None:
    """`assess_reconciliation` carries no request and must remain globally
    honest -- it is never scoped, unlike plan/apply/verify."""
    machine = _machine(codex_unverifiable=True)

    project = _project(components=["claude"])

    report = assess_reconciliation(
        machine_builder=lambda: machine,
        census_builder=lambda **_kwargs: [project],
    )

    assert report["result"] == "blocked"
    assert "codex-framework-recipe-source-unverified" in {
        item["code"] for item in report["machine"]["blockers"]
    }
