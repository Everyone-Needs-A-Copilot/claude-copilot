"""Reviewed candidate relocation using real Git/SQLite; synthetic native IDs only."""
import copy
import json
import sqlite3
import uuid

import pytest
from tc.db.exceptions import ConflictError, ValidationError
from tc.services import cycle_stages, cycles

from tests.cycle_stage_fixtures import git, make_world

REFUSAL = (ConflictError, ValidationError)


def persisted(world):
    with sqlite3.connect(world.db) as conn:
        data = json.loads(conn.execute("SELECT data FROM protocol_cycles WHERE id=?", (world.cycle,)).fetchone()[0])
        events = conn.execute("SELECT * FROM protocol_cycle_events WHERE cycle_id=? ORDER BY id", (world.cycle,)).fetchall()
        authority = {}
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'execution_%' ORDER BY name"):
            authority[name] = conn.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall()
    return data, events, authority


def setup_transition(tmp_path, *, completed=True, frozen=True):
    world = make_world(tmp_path, count=2)
    if frozen:
        world.freeze()
    if completed:
        world.start("q1")
        world.result("q1", "C1")
        world.stop("q1")
        world.start("q2")
        world.result("q2", "C2", "failed", defect="D2")
        world.stop("q2")
        world.collect()
    successor = tmp_path / "successor"
    git(world.root, "worktree", "add", "-b", "corrected-source", str(successor))
    (successor / "src/item2.py").write_text("VALUE = 20\n")
    git(successor, "add", "src/item2.py")
    git(successor, "commit", "-m", "correct synthetic item2")
    data = persisted(world)[0]
    receipt = {"operationId": str(uuid.uuid4()), "generation": data["generation"],
               "artifact": world.artifact("independently reviewed source transition"),
               "actor": "integrator", "reviewer": "independent-reviewer",
               "sourceTransition": {"fromRoot": str(world.root.resolve()),
                                    "fromCommit": git(world.root, "rev-parse", "HEAD"),
                                    "toRoot": str(successor.resolve()),
                                    "toCommit": git(successor, "rev-parse", "HEAD"),
                                    "inventoryDigest": data.get("inventoryDigest", "not-frozen")}}
    return world, successor, receipt


def transition(world, receipt, *, revision=True):
    kwargs = {"expect_revision": world.status()["revision"]} if revision else {}
    return cycle_stages.advance_cycle(cycle=world.cycle, event="candidate-integrated",
                                     receipt=receipt, db_path=world.db, **kwargs)


def refuse_unchanged(world, receipt, **kwargs):
    before = persisted(world)
    with pytest.raises(REFUSAL):
        transition(world, receipt, **kwargs)
    assert persisted(world) == before


def objects(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


def test_reviewed_successor_preserves_authority_history_and_unchanged_pass(tmp_path):
    world, successor, receipt = setup_transition(tmp_path)
    before, old_events, authority = persisted(world)
    transition(world, receipt)
    after, events, current_authority = persisted(world)
    expected_plan = copy.deepcopy(before["plan"])
    expected_plan["root"] = str(successor.resolve())
    assert after["plan"] == expected_plan
    assert after["generation"] == before["generation"] + 1
    assert current_authority == authority
    assert events[:len(old_events)] == old_events
    assert after["checkResults"] == {"C1": before["checkResults"]["C1"]}
    assert after["stageState"]["qa"]["state"] == "planned"
    archived = list(objects(json.loads(events[-1][4])))
    assert before["plan"] in archived
    assert before["checkResults"] in archived
    assert before["bindings"] in archived
    assert before["streams"] in archived
    assert before["stageState"] in archived
    assert world.status()["ready"] == ["q2"]
    world.root = successor
    world.plan["root"] = str(successor.resolve())
    world.start("q2")
    world.result("q2", "C2")
    world.stop("q2")
    world.collect()
    world.accept()
    assert cycle_stages.check_cycle(cycle=world.cycle, phase="source-ready", db_path=world.db)["approved"]
    # Original failed result and attempt remain; the new observation is additive.
    latest, latest_events, latest_authority = persisted(world)
    assert latest_events[:len(old_events)] == old_events
    assert len(latest_authority["execution_attempts"]) == len(authority["execution_attempts"]) + 1
    assert any(row[5] == "failed" for row in authority["execution_attempts"])
    assert latest["checkResults"]["C2"]["outcome"] == "passed"


@pytest.mark.parametrize("field,value", [("fromRoot", "/missing/old"), ("fromCommit", "0" * 40),
    ("toRoot", "/missing/new"), ("toCommit", "0" * 40), ("inventoryDigest", "0" * 64)])
def test_transition_rejects_inexact_source_identity_atomically(tmp_path, field, value):
    world, _, receipt = setup_transition(tmp_path)
    receipt["sourceTransition"][field] = value
    refuse_unchanged(world, receipt)


@pytest.mark.parametrize("malformation", ["missing", "extra", "not-object", "blank"])
def test_transition_shape_is_exact_and_nonempty(tmp_path, malformation):
    world, _, receipt = setup_transition(tmp_path)
    if malformation == "missing":
        receipt["sourceTransition"].pop("fromCommit")
    elif malformation == "extra":
        receipt["sourceTransition"]["task"] = 999
    elif malformation == "not-object":
        receipt["sourceTransition"] = []
    else:
        receipt["sourceTransition"]["toCommit"] = " "
    refuse_unchanged(world, receipt)


@pytest.mark.parametrize("review", ["same-actor", "missing-reviewer", "no-revision", "stale-generation", "stale-inventory"])
def test_transition_requires_current_independent_review(tmp_path, review):
    world, _, receipt = setup_transition(tmp_path)
    if review == "same-actor":
        receipt["reviewer"] = receipt["actor"]
    elif review == "missing-reviewer":
        receipt.pop("reviewer")
    elif review == "stale-generation":
        receipt["generation"] = 0
    elif review == "stale-inventory":
        data = persisted(world)[0]
        from pathlib import Path
        Path(data["inventoryApproval"]["artifact"]).write_text("changed review")
    refuse_unchanged(world, receipt, revision=review != "no-revision")


def test_transition_requires_frozen_inventory(tmp_path):
    world, _, receipt = setup_transition(tmp_path, completed=False, frozen=False)
    refuse_unchanged(world, receipt)


@pytest.mark.parametrize("state", ["claim", "dispatched", "result-without-stop"])
def test_transition_holds_live_or_unacknowledged_native_scope(tmp_path, state):
    world, _, receipt = setup_transition(tmp_path, completed=False)
    if state == "claim":
        cycles.claim_stream(cycle=world.cycle, stream="q1", agent="worker", cwd=world.root, db_path=world.db)
    else:
        world.start("q1", native=state == "result-without-stop")
        if state == "result-without-stop":
            world.result("q1", "C1")
    refuse_unchanged(world, receipt)


@pytest.mark.parametrize("which,kind", [("old", "tracked"), ("new", "tracked"), ("old", "untracked"), ("new", "untracked")])
def test_both_source_roots_must_be_clean(tmp_path, which, kind):
    world, successor, receipt = setup_transition(tmp_path)
    root = world.root if which == "old" else successor
    (root / ("src/item1.py" if kind == "tracked" else "unknown.txt")).write_text("uncommitted")
    refuse_unchanged(world, receipt)


def test_same_commit_in_foreign_clone_does_not_establish_common_repo(tmp_path):
    world, successor, receipt = setup_transition(tmp_path)
    clone = tmp_path / "foreign-clone"
    git(world.root, "clone", str(successor), str(clone))
    receipt["sourceTransition"]["toRoot"] = str(clone.resolve())
    assert git(clone, "rev-parse", "HEAD") == receipt["sourceTransition"]["toCommit"]
    refuse_unchanged(world, receipt)


def test_same_resolved_root_is_not_a_successor(tmp_path):
    world, _, receipt = setup_transition(tmp_path)
    receipt["sourceTransition"]["toRoot"] = str(world.root.resolve())
    receipt["sourceTransition"]["toCommit"] = receipt["sourceTransition"]["fromCommit"]
    refuse_unchanged(world, receipt)


def test_unrelated_history_in_same_common_repo_is_refused(tmp_path):
    world, successor, receipt = setup_transition(tmp_path)
    tree = git(successor, "rev-parse", "HEAD^{tree}")
    unrelated = git(successor, "commit-tree", tree, "-m", "unrelated synthetic root")
    git(successor, "checkout", "--detach", unrelated)
    receipt["sourceTransition"]["toCommit"] = unrelated
    refuse_unchanged(world, receipt)


def test_mutated_pass_artifact_is_not_reused_on_successor(tmp_path):
    world, successor, receipt = setup_transition(tmp_path)
    from pathlib import Path
    Path(persisted(world)[0]["checkResults"]["C1"]["artifact"]).write_text("drifted result")
    transition(world, receipt)
    assert world.status()["generation"] == 2
    assert world.status()["checkResults"] == {}
    assert persisted(world)[0]["plan"]["root"] == str(successor.resolve())
