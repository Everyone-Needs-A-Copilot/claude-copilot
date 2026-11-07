"""Real local authority/packet tests; synthetic adapters are not native proof."""
import hashlib
import json
import sqlite3
from copy import deepcopy

import pytest
from tc import api
from tc.db.exceptions import ConflictError, ValidationError
from tc.services import cycle_stages, cycles, execution

from tests.cycle_stage_fixtures import StageWorld, git, make_world

REFUSAL = (ConflictError, ValidationError)


def attempt_rows(db):
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(
            "SELECT * FROM execution_attempts ORDER BY started, token"
        )]


def task(world, name, governing=None, root=None):
    identity = api.create_task(title=name, metadata={"acceptanceContract": {
        "schemaVersion": 2,
        "criteria": [{"id": "BEHAVIOR", "expected": "Declared item is correct."}],
        "sources": ["src/shared.py"],
    }}, db_path=world.db)["id"]
    execution.register_limits(task_id=identity, root=root or world.root,
                              timeout_seconds=30, db_path=world.db)
    if governing is not None:
        execution.bind_scope(root_task_id=governing, task_id=identity,
                             criterion_map={"BEHAVIOR": "BEHAVIOR"}, db_path=world.db)
    return identity


def child_cycle(world, name, *, governing=None, stream_governing="same",
                root=None, check="RELEASE-CHECK", digest=None):
    governing = world.plan["task"] if governing is None else governing
    root = root or world.root
    parent = task(world, name, governing, root)
    stream_root = governing if stream_governing == "same" else stream_governing
    child = task(world, name + " reviewer", stream_root, root)
    plan = deepcopy(world.plan)
    plan.update(id=name, task=parent, root=str(root))
    plan["streams"] = [{**plan["streams"][0], "task": child}]
    plan["checks"] = [{**plan["checks"][0], "id": check}]
    if digest is not None:
        plan["candidateInputsSha256"] = digest
        plan["stages"][0]["phase"] = "activate-ready"
    cycles.create_cycle(plan=plan, db_path=world.db)
    result = StageWorld(root, world.db, plan, sequence=parent * 100)
    result.freeze()
    return result


def finish(world, outcome="passed"):
    world.start("q1")
    extra = {"defect": "synthetic-release-failure"} if outcome in {"failed", "error"} else {}
    world.result("q1", world.plan["checks"][0]["id"], outcome, **extra)
    world.stop("q1")
    if outcome == "passed":
        world.collect()
        world.accept()


def test_nested_release_cycle_preserves_existing_root_attempt_history(tmp_path):
    world = make_world(tmp_path, count=1)
    world.freeze()
    finish(world)
    prior = attempt_rows(world.db)
    nested = child_cycle(world, "release-source")
    finish(nested)
    after = attempt_rows(world.db)
    assert after[:len(prior)] == prior
    assert len(after) == len(prior) + 1
    assert execution.scope_usage(task_id=nested.plan["task"], db_path=world.db)["root_task_id"] == world.plan["task"]
    assert execution.execution_status(task_id=world.plan["task"], db_path=world.db)["usage"]["attempts"] == 2
    assert execution.budget_status(db_path=world.db)["used_calls"] == 0


@pytest.mark.parametrize("association", ["unbound", "unrelated"])
def test_unbound_or_unrelated_release_stream_refuses_before_claim(tmp_path, association):
    world = make_world(tmp_path, count=1)
    other = task(world, "Unrelated budget root") if association == "unrelated" else None
    nested = child_cycle(world, "invalid-release", stream_governing=other)
    before = attempt_rows(world.db)
    with pytest.raises(REFUSAL):
        nested.start("q1")
    assert attempt_rows(world.db) == before
    assert nested.status()["streams"]["q1"]["claim"] is None


def test_direct_root_cycle_keeps_existing_dispatch_and_accounting(tmp_path):
    world = make_world(tmp_path, count=1)
    world.freeze()
    finish(world)
    assert execution.scope_usage(task_id=world.plan["task"], db_path=world.db)["usage"]["attempts"] == 1
    assert cycle_stages.check_cycle(cycle=world.cycle, phase="source-ready", db_path=world.db)["approved"]


def test_same_check_across_child_cycles_cannot_reset_failed_work(tmp_path):
    world = make_world(tmp_path, count=1)
    first = child_cycle(world, "source-attempt-one")
    finish(first, "failed")
    second = child_cycle(world, "source-attempt-two")
    finish(second, "failed")
    rows = attempt_rows(world.db)
    assert len(rows) == 2
    assert rows[0]["work_identity"] == rows[1]["work_identity"]
    assert rows[0]["state"] == rows[1]["state"] == "failed"
    third = child_cycle(world, "source-attempt-three")
    with pytest.raises(REFUSAL):
        third.start("q1")
    assert attempt_rows(world.db) == rows


def test_each_release_packet_remains_bound_to_its_exact_repo_commit(tmp_path):
    world = make_world(tmp_path, count=1)
    companion = tmp_path / "companion"
    companion.mkdir()
    (companion / "src").mkdir()
    (companion / "tests").mkdir()
    (companion / "src/shared.py").write_text("SHARED = 2\n")
    (companion / "src/item1.py").write_text("VALUE = 2\n")
    (companion / "tests/item1.txt").write_text("expect 2\n")
    (companion / ".gitignore").write_text("evidence/\n")
    git(companion, "init", "-b", "main")
    git(companion, "config", "user.name", "Synthetic Stage Fixture")
    git(companion, "config", "user.email", "stage@example.invalid")
    git(companion, "config", "commit.gpgsign", "false")
    git(companion, "add", ".")
    git(companion, "commit", "-m", "distinct companion source")
    for name, root in [("foundation-source", world.root), ("companion-source", companion)]:
        nested = child_cycle(world, name, root=root, check=name)
        finish(nested)
        packet = tmp_path / (name + ".json")
        exported = cycle_stages.export_packet(cycle=nested.cycle, phase="source-ready", output=packet, db_path=world.db)
        commit = git(root, "rev-parse", "HEAD")
        assert exported["sourceCommit"] == commit
        assert exported["sha256"] == hashlib.sha256(packet.read_bytes()).hexdigest()
        cycle_stages.verify_packet(file=packet, sha256=exported["sha256"], root=root,
                                  source_commit=commit, phase="source-ready")
        other = companion if root == world.root else world.root
        with pytest.raises(REFUSAL):
            cycle_stages.verify_packet(file=packet, sha256=exported["sha256"], root=other,
                                      source_commit=git(other, "rev-parse", "HEAD"), phase="source-ready")


def test_later_composition_cycle_shares_history_and_requires_actual_input_digest(tmp_path):
    world = make_world(tmp_path, count=1)
    source = child_cycle(world, "source-release")
    finish(source)
    prior = attempt_rows(world.db)
    digest = hashlib.sha256(b"actual synthetic selected component identities").hexdigest()
    composition = child_cycle(world, "composition-release", check="COMPOSITION", digest=digest)
    finish(composition)
    packet = tmp_path / "activate.json"
    exported = cycle_stages.export_packet(cycle=composition.cycle, phase="activate-ready", output=packet, db_path=world.db)
    assert attempt_rows(world.db)[:len(prior)] == prior
    assert json.loads(packet.read_text())["candidateInputsSha256"] == digest
    cycle_stages.verify_packet(file=packet, sha256=exported["sha256"], root=world.root,
                              phase="activate-ready", candidate_inputs_sha256=digest)
    with pytest.raises(REFUSAL):
        cycle_stages.verify_packet(file=packet, sha256=exported["sha256"], root=world.root,
                                  phase="activate-ready")
