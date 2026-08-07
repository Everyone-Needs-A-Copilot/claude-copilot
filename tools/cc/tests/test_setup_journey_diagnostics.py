from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from cc.core.ecosystem.setup_journey_diagnostics import (
    safe_setup_journey_record,
    write_setup_journey_diagnostic,
)


def _report() -> dict:
    return {
        "result": "action-required",
        "operational": False,
        "confidence": 0.0,
        "phases": [
            {
                "phase": "prepare",
                "result": "blocked",
                "error": {
                    "code": "prepare-unavailable",
                    "detail": "secret=must-not-survive",
                },
                "diagnostics": {
                    "state": "available",
                    "path": "/private/nested-report.json",
                },
            },
            {
                "phase": "store",
                "result": "unavailable",
                "detail": "The live read-only store proof did not pass.",
                "organization": "Example-Org",
                "scope": "shared",
                "checks": {
                    "policy_valid": True,
                    "positive_read": False,
                    "negative_denied": False,
                    "read_only": False,
                    "untrusted": "must-not-survive",
                },
                "evidence": {
                    "auth_mode": "github-broker",
                    "secret_count": 0,
                    "exit_code": 1,
                    "token": "must-not-survive",
                },
            },
        ],
        "completed_actions": [
            {
                "action": "checkpoint",
                "path": "/projects/example",
                "detail": "password=must-not-survive",
            }
        ],
        "assessment": {
            "machine": {
                "state": "action-required",
                "helper": {"version": "2.11.0"},
                "blockers": [
                    {
                        "code": "connection-identity-invalid",
                        "responsible_actor": "ecosystem-owner",
                        "next_action": "Restore the machine identity.",
                        "evidence": [
                            {
                                "id": "shared-store-auth",
                                "state": "blocked",
                                "detail": "token=must-not-survive",
                            }
                        ],
                    }
                ],
            },
            "summary": {
                "scope_counts": {
                    "total_repositories": 63,
                    "product_projects": 47,
                    "ecosystem_repositories": 16,
                },
                "project_counts": {"ready": 47, "total": 63},
            },
            "projects": [
                {
                    "path": "/projects/held",
                    "route": "held",
                    "next_action": "Stabilize the project.",
                    "components": [
                        {"component": "claude", "state": "held", "secret": "no"}
                    ],
                },
                {
                    "path": "/ecosystem/managed",
                    "route": "ecosystem-managed",
                    "next_action": "Keep this managed separately.",
                    "components": [],
                },
            ],
        },
    }


def test_safe_record_is_useful_and_strictly_allowlisted() -> None:
    record = safe_setup_journey_record(
        _report(), created_at="2026-08-07T12:00:00Z", run_id="run-1"
    )
    rendered = json.dumps(record)

    assert record["machine"]["blockers"][0]["code"] == "connection-identity-invalid"
    assert record["machine"]["blockers"][0]["evidence"] == [
        {"id": "shared-store-auth", "state": "blocked"}
    ]
    assert record["projects"]["scope_counts"]["product_projects"] == 47
    assert record["projects"]["holds"][0]["path"] == "/projects/held"
    assert len(record["projects"]["holds"]) == 1
    assert record["nested_diagnostics"][0]["path"] == "/private/nested-report.json"
    store = record["phases"][1]
    assert store["detail"] == "The live read-only store proof did not pass."
    assert store["checks"]["read_only"] is False
    assert store["evidence"] == {
        "auth_mode": "github-broker",
        "secret_count": 0,
        "exit_code": 1,
    }
    assert "must-not-survive" not in rendered
    assert '"secret"' not in rendered
    assert '"token"' not in rendered
    assert '"untrusted"' not in rendered


def test_writer_saves_private_report_and_prunes_owned_records(tmp_path: Path) -> None:
    root = tmp_path / "diagnostics"
    for index in range(3):
        reference = write_setup_journey_diagnostic(
            _report(),
            root=root,
            now=datetime(2026, 8, 7, 12, 0, index, tzinfo=timezone.utc),
            run_id=f"run-{index}",
            retention=2,
        )

    assert reference["state"] == "available"
    path = Path(reference["path"])
    assert path.is_file()
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert len(list(path.parent.glob("setup-journey-*.json"))) == 2
    assert "must-not-survive" not in path.read_text(encoding="utf-8")
