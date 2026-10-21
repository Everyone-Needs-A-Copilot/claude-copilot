"""Tests for tc archive / tc history (services/archive.py)."""

from __future__ import annotations

import json
import sqlite3

import pytest


def _task(cli, title, **kw):
    args = ["task", "create", "--title", title, "--json"]
    for k, v in kw.items():
        args += [f"--{k}", str(v)]
    r = cli(args)
    assert r.exit_code == 0, r.output
    return json.loads(r.output)["id"]


def _sql(db_path, sql, *params):
    c = sqlite3.connect(db_path)
    rows = c.execute(sql, params).fetchall()
    c.commit()
    c.close()
    return rows


def _age(db_path, task_id, days):
    _sql(db_path, "UPDATE tasks SET updated_at = datetime('now', ?) WHERE id = ?", f"-{days} days", task_id)
    _sql(db_path, "UPDATE agent_log SET created_at = datetime('now', ?) WHERE task_id = ?", f"-{days} days", task_id)


def _hist(db_path):
    return str(db_path) + "-history"


@pytest.fixture(autouse=True)
def _no_auto(monkeypatch):
    monkeypatch.setenv("TC_AUTO_ARCHIVE", "0")


def _done(cli, db_path, title, days, **kw):
    i = _task(cli, title, **kw)
    cli(["task", "update", str(i), "--status", "completed"])
    _age(db_path, i, days)
    return i


def test_archive_moves_old_finished_tasks_with_their_log_and_work(cli, db_path):
    old = _done(cli, db_path, "Old done", 30, agent="me")
    cli(["wp", "store", "--task", str(old), "--type", "implementation", "--title", "Zebra notes", "--content", "striped findings"])
    recent = _done(cli, db_path, "Recent done", 2)
    open_ = _task(cli, "Still open")

    r = cli(["archive", "--json"])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["task_ids"] == [old]

    live = {row[0] for row in _sql(db_path, "SELECT id FROM tasks")}
    assert live == {recent, open_}
    assert _sql(db_path, "SELECT COUNT(*) FROM agent_log WHERE task_id = ?", old) == [(0,)]
    assert _sql(_hist(db_path), "SELECT id, title FROM tasks") == [(old, "Old done")]
    assert _sql(_hist(db_path), "SELECT COUNT(*) FROM agent_log WHERE task_id = ?", old)[0][0] >= 1

    found = json.loads(cli(["history", "search", "striped", "--json"]).output)
    assert [t["id"] for t in found] == [old]
    got = json.loads(cli(["history", "get", str(old), "--json"]).output)
    assert got["work_products"][0]["title"] == "Zebra notes"


def test_dry_run_moves_nothing(cli, db_path):
    old = _done(cli, db_path, "Old", 30)
    assert json.loads(cli(["archive", "--dry-run", "--json"]).output)["task_ids"] == [old]
    assert _sql(db_path, "SELECT id FROM tasks") == [(old,)]


def test_finished_task_referenced_by_live_work_stays(cli, db_path):
    parent = _done(cli, db_path, "Done parent", 30)
    dep = _done(cli, db_path, "Done dependency", 30)
    lone = _done(cli, db_path, "Done alone", 30)
    child = _task(cli, "Open child")
    _sql(db_path, "UPDATE tasks SET parent_task_id = ? WHERE id = ?", parent, child)
    assert cli(["task", "deps", "add", str(child), "--depends-on", str(dep)]).exit_code == 0
    assert json.loads(cli(["archive", "--json"]).output)["task_ids"] == [lone]


def test_closure_keeps_whole_chain(cli, db_path):
    grand = _done(cli, db_path, "Grandparent", 30)
    mid = _done(cli, db_path, "Parent", 30)
    _sql(db_path, "UPDATE tasks SET parent_task_id = ? WHERE id = ?", grand, mid)
    leaf = _task(cli, "Open leaf")
    _sql(db_path, "UPDATE tasks SET parent_task_id = ? WHERE id = ?", mid, leaf)
    assert json.loads(cli(["archive", "--json"]).output)["task_ids"] == []


def test_restore_round_trip_and_ids_are_not_reused(cli, db_path):
    old = _done(cli, db_path, "Old", 30, agent="qa")
    cli(["archive"])
    newer = _task(cli, "New after archive")
    assert newer > old
    r = cli(["history", "restore", str(old), "--json"])
    assert r.exit_code == 0, r.output
    assert {row[0] for row in _sql(db_path, "SELECT id FROM tasks")} == {old, newer}
    assert _sql(_hist(db_path), "SELECT COUNT(*) FROM tasks") == [(0,)]
    assert json.loads(cli(["task", "get", str(old), "--json"]).output)["agent"] == "qa"


def test_restore_unknown_id_fails(cli, db_path):
    _done(cli, db_path, "Old", 30)
    cli(["archive"])
    assert cli(["history", "restore", "999"]).exit_code != 0


def test_history_file_has_no_wal_sidecars(cli, db_path):
    _done(cli, db_path, "Old", 30)
    cli(["archive"])
    assert _sql(_hist(db_path), "PRAGMA journal_mode") == [("delete",)]


def test_auto_archive_runs_once_a_day(cli, db_path, monkeypatch):
    old = _done(cli, db_path, "Old", 30)
    other = _task(cli, "Other")
    monkeypatch.setenv("TC_AUTO_ARCHIVE", "1")
    cli(["task", "update", str(other), "--priority", "1"])
    assert _sql(db_path, "SELECT id FROM tasks WHERE id = ?", old) == []
    # A second old task does not move again the same day.
    again = _task(cli, "Old two")
    _sql(db_path, "UPDATE tasks SET status = 'completed' WHERE id = ?", again)
    _age(db_path, again, 30)
    cli(["task", "update", str(other), "--priority", "2"])
    assert _sql(db_path, "SELECT id FROM tasks WHERE id = ?", again) == [(again,)]
