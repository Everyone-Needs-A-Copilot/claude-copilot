from __future__ import annotations

import json
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cc.core.ecosystem.migration_diagnostics import (
    write_workspace_migration_diagnostic,
)


def _report() -> dict:
    return {
        "schema_version": "1.1",
        "mode": "apply",
        "result": "partial",
        "plan_id": "sha256:" + ("a" * 64),
        "summary": {
            "eligible": 1,
            "held": 0,
            "residual-guidance": 0,
            "total_guided": 1,
        },
        "candidates": [],
        "ledger": [],
    }


def test_diagnostic_is_atomic_private_and_content_free(tmp_path: Path) -> None:
    root = tmp_path / "diagnostics"
    action = {
        "project": "/projects/example",
        "preflight": {
            "inspection_id": "sha256:" + ("b" * 64),
            "classification": "guided-integration",
        },
        "targets_before": [
            {
                "path": "CLAUDE.md",
                "kind": "file",
                "checksum": "sha256:" + ("c" * 64),
                "mode": 420,
            }
        ],
        "completed_operations": [
            {
                "path": "CLAUDE.md",
                "operation": "write-bounded-claude-entry",
                "status": "applied",
            }
        ],
        "exception": {
            "type": "OSError",
            "message": "authorization=Bearer ghp_abcdefghijklmnopqrstuvwxyz123456",
        },
    }

    reference = write_workspace_migration_diagnostic(
        _report(),
        [action],
        root=root,
        now=datetime(2026, 8, 4, 12, 30, tzinfo=timezone.utc),
        run_id="run-one",
    )

    assert reference["state"] == "available"
    record = Path(reference["path"])
    assert record.parent == root / "workspace-migrations"
    assert stat.S_IMODE(record.stat().st_mode) == 0o600
    assert stat.S_IMODE(record.parent.stat().st_mode) == 0o700
    payload = json.loads(record.read_text(encoding="utf-8"))
    assert payload["run_id"] == "run-one"
    assert payload["actions"][0]["targets_before"][0]["checksum"].startswith("sha256:")
    serialized = record.read_text(encoding="utf-8")
    assert "file contents" not in serialized
    assert "USPTO_CLI_API_KEY=" not in serialized
    assert "ghp_abcdefghijklmnopqrstuvwxyz123456" not in serialized
    assert "Bearer <redacted>" not in serialized
    assert "authorization=<redacted>" in serialized
    assert not list(record.parent.glob(".*.json.*"))


def test_diagnostic_retention_keeps_only_newest_owned_records(tmp_path: Path) -> None:
    root = tmp_path / "diagnostics"
    start = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
    for index in range(5):
        reference = write_workspace_migration_diagnostic(
            _report(),
            [],
            root=root,
            now=start + timedelta(seconds=index),
            run_id=f"run-{index}",
            retention=3,
        )
        assert reference["state"] == "available"

    records = sorted((root / "workspace-migrations").glob("*.json"))
    assert len(records) == 3
    assert {path.stem.rsplit("-", 1)[-1] for path in records} == {"2", "3", "4"}


def test_symlinked_diagnostic_boundary_fails_closed_without_following(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    linked_root = tmp_path / "linked"
    linked_root.symlink_to(outside, target_is_directory=True)

    reference = write_workspace_migration_diagnostic(
        _report(), [], root=linked_root, run_id="blocked"
    )

    assert reference["state"] == "unavailable"
    assert reference["path"] is None
    assert list(outside.iterdir()) == []
