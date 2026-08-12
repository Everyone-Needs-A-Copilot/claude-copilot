from __future__ import annotations

import json
import os

from cc.commands.support import build_support_latest_report


def _record(run_id: str) -> dict:
    return {
        "schema_version": "1.0",
        "kind": "setup-journey-support-report",
        "run_id": run_id,
    }


def test_support_latest_returns_newest_private_redacted_record(tmp_path):
    directory = tmp_path / "control-tower"
    directory.mkdir()
    older = directory / "setup-journey-older.json"
    newer = directory / "setup-journey-newer.json"
    older.write_text(json.dumps(_record("older")))
    newer.write_text(json.dumps(_record("newer")))
    older.chmod(0o600)
    newer.chmod(0o600)
    # Do not rely on filesystem timestamp granularity or scheduler ordering.
    os.utime(older, ns=(1_000_000_000, 1_000_000_000))
    os.utime(newer, ns=(2_000_000_000, 2_000_000_000))

    report = build_support_latest_report(root=tmp_path)

    assert report["result"] == "ready"
    assert report["report"]["run_id"] == "newer"
    assert report["path"] == str(newer)


def test_support_latest_refuses_world_readable_or_unfamiliar_files(tmp_path):
    directory = tmp_path / "control-tower"
    directory.mkdir()
    unsafe = directory / "setup-journey-unsafe.json"
    unsafe.write_text(json.dumps(_record("unsafe")))
    unsafe.chmod(0o644)
    unfamiliar = directory / "setup-journey-unfamiliar.json"
    unfamiliar.write_text(json.dumps({"token": "must-not-return"}))
    unfamiliar.chmod(0o600)

    report = build_support_latest_report(root=tmp_path)

    assert report["result"] == "unavailable"
    assert "must-not-return" not in json.dumps(report)
