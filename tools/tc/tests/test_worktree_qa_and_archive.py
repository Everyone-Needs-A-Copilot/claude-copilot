"""Guarded tasks: QA reads the registered worktree, archiving keeps execution history live."""
import sqlite3
import subprocess

import pytest
from tc import api
from tc.db.exceptions import TaskNotFound
from tc.services import archive as ar
from tc.services import execution as ex


def _repo(db_path):
    root = db_path.parent.parent

    def git(*args):
        subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL)

    git("init", "-q")
    (root / "code.py").write_text("value = 1\n")
    git("add", "code.py")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "baseline")
    linked = root.parent / (root.name + "-linked")
    git("worktree", "add", "--detach", str(linked), "HEAD")
    contract = {"schemaVersion": 2, "criteria": [{"id": "C1", "expected": "Usable result"}], "sources": ["code.py"]}
    task = api.create_task(title="Linked evidence", metadata={"requiresQa": True, "acceptanceContract": contract}, db_path=db_path)
    return task, root, linked


def _approve(task_id, identity_line, db_path):
    body = ("CRITERION: C1\nEXPECTED: Usable result\nOBSERVED: local verification passed\n"
            + identity_line + "\nBASELINE: linked source\nARTIFACT: test-run|local\nVERDICT: APPROVED\n")
    api.store_wp(task_id=task_id, type_="test", title="Linked QA", content=body, db_path=db_path)


def test_qa_identity_reads_the_registered_worktree(db_path):
    task, root, linked = _repo(db_path)
    plain = api.capture_qa_identity(task_id=task["id"], db_path=db_path)
    assert "source_root" not in plain["identity"]
    (linked / "code.py").write_text("value = 2\n")
    ex.register_limits(task_id=task["id"], root=linked, db_path=db_path)
    receipt = api.capture_qa_identity(task_id=task["id"], db_path=db_path)
    assert receipt["identity"]["source_root"] == str(linked.resolve())
    assert receipt["identity"]["source_sha256"] != plain["identity"]["source_sha256"]
    _approve(task["id"], receipt["identity_line"], db_path)
    assert api.check_task_qa(task_id=task["id"], db_path=db_path)["approved"]
    # Editing the main checkout does not touch the evidence; editing the worktree does.
    (root / "code.py").write_text("value = 9\n")
    assert api.check_task_qa(task_id=task["id"], db_path=db_path)["approved"]
    (linked / "code.py").write_text("value = 3\n")
    assert not api.check_task_qa(task_id=task["id"], db_path=db_path)["approved"]


def test_qa_identity_unchanged_when_registered_at_the_main_checkout(db_path):
    task, root, linked = _repo(db_path)
    plain = api.capture_qa_identity(task_id=task["id"], db_path=db_path)
    ex.register_limits(task_id=task["id"], db_path=db_path)
    assert api.capture_qa_identity(task_id=task["id"], db_path=db_path)["identity"] == plain["identity"]


def _finish_and_age(db_path, task_id):
    c = sqlite3.connect(db_path)
    c.execute("UPDATE tasks SET status='completed', updated_at=datetime('now','-30 days') WHERE id=?", (task_id,))
    c.execute("UPDATE agent_log SET created_at=datetime('now','-30 days') WHERE task_id=?", (task_id,))
    c.commit()
    c.close()


@pytest.fixture
def two_finished(db_path, monkeypatch):
    monkeypatch.setenv("TC_AUTO_ARCHIVE", "0")
    (db_path.parent.parent / "code.py").write_text("value = 1\n")
    contract = {"schemaVersion": 2, "criteria": [{"id": "C1", "expected": "x"}], "sources": ["code.py"]}
    guarded = api.create_task(title="guarded", metadata={"requiresQa": True, "acceptanceContract": contract}, db_path=db_path)
    ex.register_limits(task_id=guarded["id"], db_path=db_path)
    plain = api.create_task(title="plain", db_path=db_path)
    for t in (guarded, plain):
        _finish_and_age(db_path, t["id"])
    return guarded["id"], plain["id"]


def test_archive_keeps_tasks_with_execution_history(db_path, two_finished):
    guarded, plain = two_finished
    result = ar.archive(days=14, db_path=db_path)
    assert result["task_ids"] == [plain]
    assert ex.execution_status(task_id=guarded, db_path=db_path)["limits"]
    c = sqlite3.connect(db_path)
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    c.close()


def test_archive_returns_tasks_stranded_by_earlier_versions(db_path, two_finished):
    guarded, plain = two_finished
    # Reproduce the old behaviour: the guarded task moved, its records stayed.
    conn = ar._open_pair(db_path, create=True)
    ar._move(conn, "main", "h", [guarded])
    conn.close()
    with pytest.raises(TaskNotFound):
        ex.execution_status(task_id=guarded, db_path=db_path)
    preview = ar.archive(days=14, dry_run=True, db_path=db_path)
    assert preview["returned"] == [guarded]
    with pytest.raises(TaskNotFound):
        ex.execution_status(task_id=guarded, db_path=db_path)
    result = ar.archive(days=14, db_path=db_path)
    assert result["returned"] == [guarded] and result["task_ids"] == [plain]
    assert ex.execution_status(task_id=guarded, db_path=db_path)["limits"]
    assert [r["id"] for r in ar.history_list(db_path=db_path)] == [plain]
