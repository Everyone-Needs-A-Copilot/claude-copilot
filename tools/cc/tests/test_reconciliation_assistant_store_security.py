"""Adversarial tests for private assistant session/proposal capabilities."""

from __future__ import annotations

import os
import stat
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cc.core.ecosystem.assistant_job_store import (
    AssistantAlreadyUsed,
    AssistantBindingMismatch,
    AssistantExpired,
    claim_session,
    complete_session,
    create_session,
    fingerprint,
    issue_proposal,
    load_progress,
    load_proposal,
    load_session,
    record_progress,
    session_directory,
)
from cc.core.ecosystem.project_locking import ProjectLockContention

NOW = datetime(2026, 8, 4, 20, 0, tzinfo=timezone.utc)
SESSION_ID = "session_" + "a" * 32


def _create(root: Path, *, ttl_seconds: int = 1800) -> dict:
    return create_session(
        base_request={
            "schema_version": "1.0",
            "roots": ["/projects"],
            "projects": [
                {"path": "/projects/one", "components": ["claude", "codex"]}
            ],
        },
        packet={
            "schema_version": "1.0",
            "projects": [
                {
                    "project_ref": "project_" + "1" * 32,
                    "candidate_ids": ["candidate_" + "2" * 64],
                }
            ],
        },
        candidates=[
            {
                "candidate_id": "candidate_" + "2" * 64,
                "project": "/projects/one",
                "component": "claude",
            }
        ],
        selected_projects=["/projects/one"],
        policy_fingerprint=fingerprint({"policy": "bounded-selection-v1"}),
        ttl_seconds=ttl_seconds,
        root=root,
        now=NOW,
        session_id=SESSION_ID,
    )


def _complete(root: Path) -> dict:
    _create(root)
    claim_session(SESSION_ID, root=root, now=NOW)
    return complete_session(
        SESSION_ID,
        [
            {
                "candidate_id": "candidate_" + "2" * 64,
                "project_ref": "project_" + "1" * 32,
            }
        ],
        root=root,
        now=NOW,
    )


def _issue(root: Path, *, ttl_seconds: int = 900) -> dict:
    _complete(root)
    return issue_proposal(
        SESSION_ID,
        resolved_request={
            "schema_version": "1.0",
            "roots": ["/projects"],
            "projects": [
                {
                    "path": "/projects/one",
                    "components": ["claude", "codex"],
                    "recipe_ids": {
                        "claude": "claude.assistant-preserve-entry.v1",
                        "codex": "codex.project-setup.v1",
                    },
                }
            ],
        },
        owned_components={"/projects/one": ["claude"]},
        plans_fingerprint=fingerprint({"plans": ["candidate"]}),
        ttl_seconds=ttl_seconds,
        root=root,
        now=NOW,
    )


def test_session_artifacts_are_private_regular_single_link_files(
    tmp_path: Path,
) -> None:
    root = tmp_path / "assistant-state"
    _create(root)
    directory = session_directory(SESSION_ID, root)
    record = directory / "session.json"

    assert stat.S_IMODE(root.lstat().st_mode) == 0o700
    assert stat.S_IMODE(directory.lstat().st_mode) == 0o700
    metadata = record.lstat()
    assert stat.S_ISREG(metadata.st_mode)
    assert stat.S_IMODE(metadata.st_mode) == 0o600
    assert metadata.st_uid == os.geteuid()
    assert metadata.st_nlink == 1


@pytest.mark.parametrize("attack", ["bytes", "mode", "symlink", "hardlink"])
def test_session_tampering_is_rejected(tmp_path: Path, attack: str) -> None:
    root = tmp_path / "assistant-state"
    _create(root)
    record = session_directory(SESSION_ID, root) / "session.json"

    if attack == "bytes":
        before = record.read_bytes()
        after = before.replace(b"/projects/one", b"/projects/two")
        assert after != before
        record.write_bytes(after)
    elif attack == "mode":
        record.chmod(0o644)
    elif attack == "symlink":
        outside = tmp_path / "outside.json"
        outside.write_bytes(record.read_bytes())
        record.unlink()
        record.symlink_to(outside)
    else:
        os.link(record, tmp_path / "hardlink.json")

    with pytest.raises(AssistantBindingMismatch):
        load_session(SESSION_ID, root=root, now=NOW)


def test_session_expiry_and_single_claim_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "assistant-state"
    _create(root, ttl_seconds=10)

    claimed = claim_session(SESSION_ID, root=root, now=NOW + timedelta(seconds=1))

    assert claimed["state"] == "running"
    with pytest.raises(AssistantAlreadyUsed):
        claim_session(SESSION_ID, root=root, now=NOW + timedelta(seconds=2))
    with pytest.raises(AssistantExpired):
        load_session(SESSION_ID, root=root, now=NOW + timedelta(seconds=10))


def test_progress_milestones_are_private_monotonic_and_heartbeat_backed(
    tmp_path: Path,
) -> None:
    root = tmp_path / "assistant-state"
    _create(root)
    prepared = load_progress(SESSION_ID, root=root, now=NOW)

    assert prepared["stage"] == "session-prepared"
    assert prepared["selected_project_count"] == 1
    assert prepared["candidate_group_count"] == 1
    claim_session(SESSION_ID, root=root, now=NOW)
    running = record_progress(
        SESSION_ID,
        "claude-code-running",
        root=root,
        now=NOW + timedelta(seconds=1),
    )
    heartbeat = record_progress(
        SESSION_ID,
        "claude-code-running",
        root=root,
        now=NOW + timedelta(seconds=5),
    )

    assert heartbeat["updated_at"] > running["updated_at"]
    with pytest.raises(AssistantBindingMismatch):
        record_progress(
            SESSION_ID,
            "session-prepared",
            root=root,
            now=NOW + timedelta(seconds=6),
        )


def test_running_status_reports_stale_when_python_heartbeat_stops(
    tmp_path: Path,
) -> None:
    from cc.core.ecosystem.reconciliation_assistant import (
        build_assistant_status_report,
    )

    root = tmp_path / "assistant-state"
    _create(root)
    claim_session(SESSION_ID, root=root, now=NOW)
    record_progress(SESSION_ID, "claude-code-running", root=root, now=NOW)

    report = build_assistant_status_report(
        SESSION_ID,
        state_root=root,
        now=NOW + timedelta(seconds=11),
    )

    assert report["result"] == "running"
    assert report["progress"]["stage"] == "claude-code-running"
    assert report["progress"]["liveness"] == "stale"
    assert report["progress"]["elapsed_seconds"] == 11


def test_session_record_cannot_be_swapped_under_another_session_id(
    tmp_path: Path,
) -> None:
    root = tmp_path / "assistant-state"
    _create(root)
    other_id = "session_" + "b" * 32
    create_session(
        base_request={
            "schema_version": "1.0",
            "roots": ["/projects"],
            "projects": [
                {"path": "/projects/two", "components": ["claude", "codex"]}
            ],
        },
        packet={"schema_version": "1.0", "projects": []},
        candidates=[],
        selected_projects=["/projects/two"],
        policy_fingerprint=fingerprint({"policy": "bounded-selection-v1"}),
        root=root,
        now=NOW,
        session_id=other_id,
    )
    first = session_directory(SESSION_ID, root) / "session.json"
    second = session_directory(other_id, root) / "session.json"
    first.write_bytes(second.read_bytes())
    first.chmod(0o600)

    with pytest.raises(AssistantBindingMismatch):
        load_session(SESSION_ID, root=root, now=NOW)


def test_expired_running_session_cannot_accept_late_output(tmp_path: Path) -> None:
    root = tmp_path / "assistant-state"
    ancient = datetime(2000, 1, 1, tzinfo=timezone.utc)
    create_session(
        base_request={
            "schema_version": "1.0",
            "roots": ["/projects"],
            "projects": [
                {"path": "/projects/one", "components": ["claude", "codex"]}
            ],
        },
        packet={"schema_version": "1.0", "projects": []},
        candidates=[],
        selected_projects=["/projects/one"],
        policy_fingerprint=fingerprint({"policy": "bounded-selection-v1"}),
        ttl_seconds=1,
        root=root,
        now=ancient,
        session_id=SESSION_ID,
    )
    claim_session(SESSION_ID, root=root, now=ancient)

    with pytest.raises(AssistantExpired):
        complete_session(SESSION_ID, [], root=root)


def test_two_concurrent_claims_have_exactly_one_winner(tmp_path: Path) -> None:
    root = tmp_path / "assistant-state"
    _create(root)

    def attempt() -> str:
        try:
            claim_session(SESSION_ID, root=root, now=NOW)
        except (AssistantAlreadyUsed, ProjectLockContention):
            return "refused"
        return "claimed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _index: attempt(), range(2)))

    assert sorted(outcomes) == ["claimed", "refused"]


def test_proposal_issue_is_idempotent_private_and_expiring(tmp_path: Path) -> None:
    root = tmp_path / "assistant-state"
    proposal = _issue(root, ttl_seconds=10)
    repeated = issue_proposal(
        SESSION_ID,
        resolved_request=proposal["resolved_request"],
        owned_components=proposal["owned_components"],
        plans_fingerprint=proposal["plans_fingerprint"],
        root=root,
        now=NOW + timedelta(seconds=1),
    )

    assert repeated == proposal
    record = root / "proposals" / f"{proposal['proposal_id']}.json"
    metadata = record.lstat()
    assert stat.S_ISREG(metadata.st_mode)
    assert stat.S_IMODE(metadata.st_mode) == 0o600
    assert metadata.st_nlink == 1
    assert load_proposal(
        proposal["proposal_id"], root=root, now=NOW + timedelta(seconds=9)
    ) == proposal
    with pytest.raises(AssistantExpired):
        load_proposal(
            proposal["proposal_id"], root=root, now=NOW + timedelta(seconds=10)
        )


@pytest.mark.parametrize("attack", ["bytes", "mode", "symlink", "hardlink"])
def test_proposal_tampering_is_rejected(tmp_path: Path, attack: str) -> None:
    root = tmp_path / "assistant-state"
    proposal = _issue(root)
    record = root / "proposals" / f"{proposal['proposal_id']}.json"

    if attack == "bytes":
        record.write_bytes(record.read_bytes().replace(b"/projects/one", b"/projects/two"))
    elif attack == "mode":
        record.chmod(0o644)
    elif attack == "symlink":
        outside = tmp_path / "outside-proposal.json"
        outside.write_bytes(record.read_bytes())
        record.unlink()
        record.symlink_to(outside)
    else:
        os.link(record, tmp_path / "proposal-hardlink.json")

    with pytest.raises(AssistantBindingMismatch):
        load_proposal(proposal["proposal_id"], root=root, now=NOW)
