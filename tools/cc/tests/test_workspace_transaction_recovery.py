from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cc.core.ecosystem.project_plan_store import issue_plan
from cc.core.ecosystem.reconciliation_transaction import (
    recover_incomplete_transactions,
)


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


_CHILD = r"""
import os
import sys
from pathlib import Path
from cc.core.ecosystem.project_locking import inspect_project_identity, project_lock
from cc.core.ecosystem.reconciliation_transaction import ProjectTransactionPlan, TransactionOperation, execute_reconciliation

project = Path(sys.argv[1])
state = Path(sys.argv[2])
boundary = sys.argv[3]
from cc.core.ecosystem.project_plan_store import claim_plan
claim_plan(
    sys.argv[4],
    sys.argv[5],
    sys.argv[6],
    run_id='run_' + '4' * 32,
    root=state,
)
with project_lock(project, lock_root=state / 'fingerprint-locks') as anchored:
    before = anchored.fingerprint('CLAUDE.md')
operation = TransactionOperation(
    id='op_' + 'a' * 64,
    kind='append-managed-block',
    component='claude',
    target='CLAUDE.md',
    expected_before_fingerprint=before,
    source_fingerprint=None,
    payload={'block': '<!-- managed -->\nManaged.\n'},
)
plan = ProjectTransactionPlan(
    path=str(project),
    expected_identity=inspect_project_identity(project),
    operations=(operation,),
    verification=lambda _project: True,
)
def observer(event, _context):
    if event == boundary:
        os._exit(73)
execute_reconciliation([plan], run_id='run_' + '4' * 32, observer=observer, root=state)
"""


@pytest.mark.parametrize(
    ("boundary", "expected_status", "expected_completed"),
    [
        ("transaction-prepared", "blocked", []),
        ("after-output-write", "rolled-back", ["op_" + "a" * 64]),
        ("after-mutation", "rolled-back", ["op_" + "a" * 64]),
    ],
)
def test_killed_process_leaves_recoverable_durable_journal(
    tmp_path,
    boundary: str,
    expected_status: str,
    expected_completed: list[str],
) -> None:
    project = _repo(tmp_path / "project")
    state = tmp_path / "state"
    request = {
        "schema_version": "1.0",
        "roots": [str(tmp_path)],
        "projects": [{"path": str(project), "components": ["claude"]}],
    }
    request_fingerprint = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                request,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
    )
    fresh_fingerprint = "sha256:" + "b" * 64
    record = issue_plan(
        request_fingerprint,
        fresh_fingerprint,
        [{"path": str(project), "operations": [{"id": "op_" + "a" * 64}]}],
        canonical_request=request,
        helper_version="2.6.0",
        schema_version="1.0",
        root=state,
    )
    before = (project / "CLAUDE.md").read_bytes()
    env = dict(os.environ)
    source_root = Path(__file__).resolve().parents[1] / "src"
    env["PYTHONPATH"] = str(source_root) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        (
            sys.executable,
            "-c",
            _CHILD,
            str(project),
            str(state),
            boundary,
            record.plan_id,
            request_fingerprint,
            fresh_fingerprint,
        ),
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 73, result.stderr

    receipts = recover_incomplete_transactions(root=state)
    assert len(receipts) == 1
    assert receipts[0]["status"] == expected_status
    assert receipts[0]["completed_operation_ids"] == expected_completed
    assert [item["status"] for item in receipts[0]["rollback"]] == (
        ["restored"] if expected_completed else []
    )
    assert (project / "CLAUDE.md").read_bytes() == before
    assert recover_incomplete_transactions(root=state) == []
