"""cc priorities against temp tasks.db files built with the real tc schema."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest
from cc.main import app

TC_SRC = Path(__file__).resolve().parents[2] / "tc" / "src"


def _schema() -> str:
    sys.path.insert(0, str(TC_SRC))
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("tc_schema_under_test", TC_SRC / "tc" / "db" / "schema.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.SCHEMA_SQL
    finally:
        sys.path.remove(str(TC_SRC))


def make_project(root: Path, name: str, prds=(), tasks=(), deps=()):
    """tasks: (id, prd_id, title, status, priority, updated, metadata, description)."""
    proj = root / name
    (proj / ".copilot").mkdir(parents=True)
    conn = sqlite3.connect(proj / ".copilot" / "tasks.db")
    conn.executescript(_schema())
    for pid, title, updated in prds:
        conn.execute("INSERT INTO prds (id, title, updated_at, created_at) VALUES (?,?,?,?)", (pid, title, updated, updated))
    for tid, prd, title, status, prio, updated, meta, desc in tasks:
        conn.execute(
            "INSERT INTO tasks (id, prd_id, title, description, status, priority, metadata, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (tid, prd, title, desc, status, prio, meta, updated, updated),
        )
    for a, b in deps:
        conn.execute("INSERT INTO task_dependencies VALUES (?,?)", (a, b))
    conn.commit()
    conn.close()
    return proj


def T(tid, prd, title, status="pending", prio=1, updated="2026-10-27 10:00:00", meta=None, desc=None):
    return (tid, prd, title, status, prio, updated, meta, desc)


@pytest.fixture
def fleet(tmp_path, monkeypatch):
    a = make_project(
        tmp_path, "alpha",
        prds=[(1, "Alpha launch", "2026-10-27 10:00:00")],
        tasks=[
            T(1, 1, "Design done", status="completed", prio=0),
            T(2, 1, "Needs sign-off", prio=0, desc="DECISION NEEDED: pick the campaign line"),
            T(3, 1, "Build after design", prio=1),
            T(4, 1, "Waits on open task", prio=0),
        ],
        deps=[(3, 1), (4, 2)],
    )
    b = make_project(
        tmp_path, "beta",
        prds=[(1, "Beta old", "2026-09-01 10:00:00")],
        tasks=[T(1, 1, "Old work", prio=2, updated="2026-09-01 10:00:00")],
    )
    c = make_project(
        tmp_path, "gamma",
        tasks=[
            T(1, None, "Ship it", prio=0, updated="2026-10-26 10:00:00", meta=json.dumps({"deadline": "soon"})),
            T(2, None, "Awaiting", prio=2, meta=json.dumps({"awaiting": "owner"})),
        ],
    )
    monkeypatch.setenv("CC_PROJECT_ROOTS", ":".join(str(p) for p in (a, b, c)))
    return tmp_path


def _run(runner, *args):
    r = runner.invoke(app, ["priorities", "--week", "2026-10-29", *args])
    assert r.exit_code == 0, r.output
    return r.output


def test_json_shape_and_ordering(runner, fleet):
    out = json.loads(_run(runner, "--json"))
    assert set(out) == {"week", "outcomes", "canProceedWithoutYou", "shouldWait", "missingInformation"}
    assert [o["project"] for o in out["outcomes"]] == ["alpha", "gamma"]
    assert set(out["outcomes"][0]) >= {"project", "task", "nextAction", "prd", "blockedOn", "dependencyDepth", "lastActivity", "stale"}


def test_blocked_on_owner_and_dependency_readiness(runner, fleet):
    out = json.loads(_run(runner, "--json"))
    alpha = out["outcomes"][0]
    # TASK-4 (P0) is not ready (depends on open TASK-2); TASK-2 is ready, P0, and asks for a decision.
    assert alpha["task"] == "TASK-2" and alpha["blockedOn"] == "owner decision"
    assert alpha["prd"] == "Alpha launch"
    assert out["outcomes"][1]["blockedOn"] == "nothing"


def test_dependency_depth(runner, fleet, monkeypatch, tmp_path):
    p = make_project(tmp_path / "d", "deep", tasks=[
        T(1, None, "a", status="completed"), T(2, None, "b", status="completed", prio=3), T(3, None, "c", prio=0)],
        deps=[(2, 1), (3, 2)])
    monkeypatch.setenv("CC_PROJECT_ROOTS", str(p))
    out = json.loads(_run(runner, "--json"))
    assert out["outcomes"][0]["dependencyDepth"] == 2


def test_stale_prd_goes_to_should_wait(runner, fleet):
    out = json.loads(_run(runner, "--json"))
    assert [w["project"] for w in out["shouldWait"]] == ["beta"]
    assert out["shouldWait"][0]["tasks"][0]["prd"] == "Beta old"
    assert [p["project"] for p in out["canProceedWithoutYou"]] == ["beta"]


def test_missing_information(runner, fleet):
    out = json.loads(_run(runner, "--json"))
    items = {m["project"]: m["items"] for m in out["missingInformation"]}
    kinds = {i["kind"] for i in items["gamma"]}
    assert kinds == {"no-prd", "deadline-without-date"}
    assert "alpha" not in items


def test_text_output_sections_in_order_without_estimates(runner, fleet):
    text = _run(runner)
    heads = ["This week's three outcomes", "Can proceed without you", "Should wait", "Missing information"]
    assert [text.index(h) for h in heads] == sorted(text.index(h) for h in heads)
    assert "TASK-2" in text and "Blocked on: owner decision" in text


def test_read_only_and_worktree_skipping(runner, fleet, tmp_path, monkeypatch):
    wt = make_project(tmp_path / ".worktrees", "x", tasks=[T(1, None, "w", prio=0)])
    monkeypatch.setenv("CC_PROJECT_ROOTS", str(wt))
    out = json.loads(_run(runner, "--json"))
    assert out["outcomes"] == []
    db = tmp_path / "alpha" / ".copilot" / "tasks.db"
    before = db.read_bytes()
    monkeypatch.setenv("CC_PROJECT_ROOTS", str(tmp_path / "alpha"))
    _run(runner, "--json")
    assert db.read_bytes() == before
