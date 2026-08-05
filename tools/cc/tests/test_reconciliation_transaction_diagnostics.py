from __future__ import annotations

import hashlib
import json

from cc.core.ecosystem.reconciliation_diagnostics import (
    append_project_receipt,
    finalize_run_diagnostic,
)


def _fingerprint(character: str) -> str:
    return "sha256:" + character * 64


def _canonical_request() -> dict:
    return {
        "schema_version": "1.0",
        "roots": ["/projects"],
        "projects": [{"path": "/projects/example", "components": ["claude"]}],
    }


def _request_fingerprint() -> str:
    encoded = json.dumps(
        _canonical_request(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _reviewed_plans() -> list[dict]:
    return [
        {
            "path": "/projects/example",
            "inspection_id": _fingerprint("c"),
            "recipes": [
                {
                    "component": "claude",
                    "recipe_id": "claude-project-update-v1",
                }
            ],
            "sources": [],
            "operations": [
                {
                    "id": "op_" + "a" * 64,
                    "kind": "append-managed-block",
                    "component": "claude",
                    "target": "CLAUDE.md",
                    "description": "Update the bounded Claude entry.",
                    "expected_before_fingerprint": _fingerprint("e"),
                    "source_fingerprint": None,
                }
            ],
            "preservation": [],
            "prohibited_actions": ["overwrite-project-owned-content"],
            "verification": ["claude-project-integration"],
        }
    ]


def _receipt() -> dict:
    return {
        "path": "/projects/example",
        "status": "incomplete-rollback",
        "detail": "authorization=Bearer sentinel-secret-value",
        "completed_operation_ids": ["op_" + "a" * 64],
        "verification": "failed",
        "rollback": [
            {
                "target": "CLAUDE.md",
                "status": "conflict",
                "detail": "stdin sentinel-secret-value",
            }
        ],
        "environment": {"OPENAI_API_KEY": "sentinel-secret-value"},
        "stdin": "sentinel-secret-value",
        "content": "sentinel-secret-value",
        "diagnostic_evidence": {
            "preflight": {
                "identity_fingerprint": _fingerprint("b"),
                "inspection_id": _fingerprint("c"),
                "classification": "safe-update-available",
                "components": [
                    {
                        "component": "claude",
                        "classification": "safe-update-available",
                        "requirement_ids": ["claude:component-setup"],
                    }
                ],
            },
            "sources": [
                {
                    "component": "claude",
                    "version": "2.6.0",
                    "fingerprint": _fingerprint("d"),
                }
            ],
            "targets": [
                {
                    "target": "CLAUDE.md",
                    "kind": "file",
                    "before_fingerprint": _fingerprint("e"),
                }
            ],
            "planned_operation_ids": ["op_" + "a" * 64],
            "post_apply_verification": [
                {
                    "component": "claude",
                    "state": "failed",
                    "evidence_ids": ["canonical-entry"],
                }
            ],
            "exception": {
                "type": "SyntheticSecretError",
                "code": "verification-failed",
                "detail": "sentinel-secret-value",
            },
        },
    }


def test_closed_diagnostic_is_complete_and_never_serializes_raw_values(
    tmp_path,
) -> None:
    run_id = "run_" + "1" * 32
    plan_id = "plan_" + "2" * 32
    receipt = _receipt()
    reference = append_project_receipt(run_id, receipt, root=tmp_path)
    assert reference.state == "available"
    final = finalize_run_diagnostic(
        run_id,
        plan_id,
        _request_fingerprint(),
        [receipt],
        canonical_request=_canonical_request(),
        reviewed_plans=_reviewed_plans(),
        fresh_plan_fingerprint=_fingerprint("0"),
        helper_version="2.6.0",
        schema_version="1.0",
        machine_evidence={
            "state": "ready",
            "helper": {"state": "ready", "version": "2.6.0", "path": "/secret/path"},
            "authentication": {
                "state": "signed-in",
                "credential_state": "present",
                "token": "sentinel-secret-value",
            },
            "connectivity": {"state": "online", "raw": "sentinel-secret-value"},
            "layers": {"state": "ready", "ready": 4, "total": 4},
            "frameworks": [
                {"component": "claude", "state": "ready", "version": "2.6.0"}
            ],
            "dependencies": [
                {"id": "git", "state": "ready", "detail": "sentinel-secret-value"}
            ],
        },
        final_census={"ready": 1, "total": 1},
        overlap_explanation="One updated component remains independently classified.",
        root=tmp_path,
    )
    assert final.state == "available"
    serialized = __import__("pathlib").Path(final.path).read_text(encoding="utf-8")
    assert "sentinel-secret-value" not in serialized
    payload = json.loads(serialized)
    assert payload["helper_version"] == "2.6.0"
    assert payload["requested_plan_id"] == plan_id
    assert payload["fresh_plan_fingerprint"] == _fingerprint("0")
    assert payload["machine"]["authentication"]["credential_state"] == "present"
    assert payload["projects"][0]["evidence"]["targets"][0]["kind"] == "file"
    assert payload["projects"][0]["evidence"]["preflight"]["components"][0][
        "requirement_ids"
    ] == ["claude:component-setup"]
    assert (
        payload["projects"][0]["evidence"]["exception"]["code"] == "verification-failed"
    )
    assert payload["projects"][0]["rollback"][0]["status"] == "conflict"
    assert payload["final_census"] == {"ready": 1, "total": 1}


def test_symlinked_diagnostic_boundary_returns_unavailable(tmp_path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(outside, target_is_directory=True)
    reference = append_project_receipt("run_" + "4" * 32, _receipt(), root=linked)
    assert reference.state == "unavailable"
    assert list(outside.iterdir()) == []


def test_finalize_preserves_rich_evidence_appended_before_plain_ledger(
    tmp_path,
) -> None:
    run_id = "run_" + "6" * 32
    rich = _receipt()
    assert append_project_receipt(run_id, rich, root=tmp_path).state == "available"
    plain = {key: value for key, value in rich.items() if key != "diagnostic_evidence"}

    reference = finalize_run_diagnostic(
        run_id,
        "plan_" + "7" * 32,
        _request_fingerprint(),
        [plain],
        canonical_request=_canonical_request(),
        reviewed_plans=_reviewed_plans(),
        fresh_plan_fingerprint=_fingerprint("9"),
        root=tmp_path,
    )

    payload = json.loads(
        __import__("pathlib").Path(reference.path).read_text(encoding="utf-8")
    )
    evidence = payload["projects"][0]["evidence"]
    assert evidence["preflight"]["inspection_id"] == _fingerprint("c")
    assert evidence["sources"][0]["fingerprint"] == _fingerprint("d")
    assert evidence["targets"][0]["target"] == "CLAUDE.md"
    assert evidence["exception"]["code"] == "verification-failed"


def test_every_allowlisted_diagnostic_string_field_rejects_raw_sentinel(
    tmp_path,
) -> None:
    sentinel = "sentinel-secret-value"
    receipt = _receipt()
    receipt["rollback"][0]["target"] = sentinel
    evidence = receipt["diagnostic_evidence"]
    evidence["preflight"].update(
        inspection_id=sentinel,
        classification=sentinel,
        components=[
            {
                "component": sentinel,
                "classification": sentinel,
                "requirement_ids": [sentinel],
            }
        ],
    )
    evidence["sources"] = [
        {
            "component": "claude",
            "version": sentinel,
            "fingerprint": _fingerprint("a"),
        },
        {
            "component": sentinel,
            "version": "2.6.0",
            "fingerprint": _fingerprint("b"),
        },
    ]
    evidence["targets"] = [
        {
            "target": sentinel,
            "kind": sentinel,
            "before_fingerprint": _fingerprint("c"),
        }
    ]
    evidence["post_apply_verification"] = [
        {"component": sentinel, "state": sentinel, "evidence_ids": [sentinel]}
    ]
    evidence["exception"] = {"type": sentinel, "code": sentinel}
    run_id = "run_" + "a" * 32
    reference = append_project_receipt(run_id, receipt, root=tmp_path)
    assert reference.state == "available"

    final = finalize_run_diagnostic(
        run_id,
        "plan_" + "b" * 32,
        _request_fingerprint(),
        [receipt],
        canonical_request=_canonical_request(),
        reviewed_plans=_reviewed_plans(),
        fresh_plan_fingerprint=_fingerprint("d"),
        machine_evidence={
            "state": sentinel,
            "helper": {"state": sentinel, "version": sentinel},
            "frameworks": [
                {"component": sentinel, "state": sentinel, "version": sentinel}
            ],
            "authentication": {
                "state": sentinel,
                "credential_state": sentinel,
            },
            "connectivity": {"state": sentinel},
            "layers": {"state": sentinel},
            "dependencies": [{"id": sentinel, "state": sentinel}],
        },
        final_census={sentinel: 1, "total": 1},
        overlap_explanation=sentinel,
        root=tmp_path,
    )
    serialized = __import__("pathlib").Path(final.path).read_text(encoding="utf-8")

    assert sentinel not in serialized
    payload = json.loads(serialized)
    assert payload["final_census"] == {"total": 1}
    assert payload["projects"][0]["evidence"]["exception"] == {
        "type": "TransactionError",
        "code": "unexpected",
        "detail": "The transaction stopped on a classified internal error.",
    }


def test_symlinked_default_diagnostics_base_returns_unavailable(
    tmp_path, monkeypatch
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "diagnostics"
    linked.symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(
        "cc.core.ecosystem.reconciliation_diagnostics.machine_diagnostics_root",
        lambda: linked,
    )

    reference = append_project_receipt("run_" + "5" * 32, _receipt())

    assert reference.state == "unavailable"
    assert list(outside.iterdir()) == []
