"""Offline release and task-gate contracts; no upload, signing, or model calls."""
import hashlib
import json

import pytest
from tc import api
from tc.db.connection import get_db
from tc.db.exceptions import ConflictError, ValidationError
from tc.services import cycle_stages
from tests.cycle_stage_fixtures import make_world, git

REFUSAL = (ConflictError, ValidationError)


def accepted(tmp_path):
    w = make_world(tmp_path, count=1)
    w.freeze()
    w.run_all()
    return w


def test_incomplete_stage_blocks_api_completion_and_cannot_be_downgraded(tmp_path):
    w = make_world(tmp_path, count=1)
    root = w.plan["task"]
    with get_db(w.db) as conn:
        assert not cycle_stages.task_gate(task_id=root, conn=conn)["approved"]
    with pytest.raises(REFUSAL):
        api.update_task(task_id=root, status="completed", db_path=w.db)
    for metadata in ({"stageRequirement": None}, {"stageRequirement": {}},
                     {"stageRequirement": {"cycle": "other", "policyVersion": 1}}):
        with pytest.raises(REFUSAL):
            api.update_task(task_id=root, metadata=metadata, db_path=w.db)
    assert api.get_task(task_id=root, db_path=w.db)["status"] == "pending"


def test_ungoverned_legacy_task_remains_compatible(db_path):
    task = api.create_task(title="Unmanaged legacy task", db_path=db_path)
    with get_db(db_path) as conn:
        assert cycle_stages.task_gate(task_id=task["id"], conn=conn)["approved"]


def test_no_packet_before_complete_independent_source_stage(tmp_path):
    w = make_world(tmp_path, count=1)
    path = tmp_path / "unapproved.json"
    with pytest.raises(REFUSAL):
        cycle_stages.export_packet(cycle=w.cycle, phase="source-ready", output=path, db_path=w.db)
    assert not path.exists()
    w.freeze()
    w.start("q1")
    w.result("q1", "C1")
    w.stop("q1")
    w.collect()
    with pytest.raises(REFUSAL):
        w.advance("stage-accepted", stage="qa", actor="converger", reviewer="worker-q1")


def test_export_verify_exact_commit_and_digest_without_database(tmp_path):
    w = accepted(tmp_path)
    path = tmp_path / "packet.json"
    result = cycle_stages.export_packet(cycle=w.cycle, phase="source-ready", output=path, db_path=w.db)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert result["sha256"] == digest
    verified = cycle_stages.verify_packet(file=path, sha256=digest, root=w.root,
                                           phase="source-ready", source_commit=git(w.root, "rev-parse", "HEAD"))
    assert verified["approved"]
    body = json.loads(path.read_text())
    assert body["kind"] == "tc-stage-release"
    assert body["schemaVersion"] == 2
    assert "assurance" in body
    assert str(w.db) not in path.read_text()
    assert "synthetic-fixed-runtime" not in path.read_text()
    expected_inputs = hashlib.sha256(json.dumps({"runtime": "synthetic-fixed-runtime"}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert body["checks"][0]["inputsSha256"] == expected_inputs


def test_export_never_overwrites_existing_file(tmp_path):
    w = accepted(tmp_path)
    path = tmp_path / "existing.json"
    path.write_text("private original retained\n")
    with pytest.raises((*REFUSAL, FileExistsError)):
        cycle_stages.export_packet(cycle=w.cycle, phase="source-ready", output=path, db_path=w.db)
    assert path.read_text() == "private original retained\n"


@pytest.mark.parametrize("change", ["digest", "source", "commit", "phase", "missing-check", "failed-check"])
def test_portable_packet_rejects_stale_misbound_or_incomplete_claim(tmp_path, change):
    w = accepted(tmp_path)
    path = tmp_path / "packet.json"
    exported = cycle_stages.export_packet(cycle=w.cycle, phase="source-ready", output=path, db_path=w.db)
    digest = exported["sha256"]
    phase = "source-ready"
    commit = git(w.root, "rev-parse", "HEAD")
    if change == "digest":
        digest = "0" * 64
    elif change == "source":
        (w.root / "src/item1.py").write_text("VALUE = 999\n")
    elif change == "commit":
        commit = "f" * 40
    elif change == "phase":
        phase = "activate-ready"
    else:
        body = json.loads(path.read_text())
        if change == "missing-check":
            body["checks"] = []
        else:
            if isinstance(body["checks"], dict):
                next(iter(body["checks"].values()))["outcome"] = "failed"
            else:
                body["checks"][0]["outcome"] = "failed"
        path = tmp_path / f"candidate-{change}.json"
        path.write_text(json.dumps(body))
        # Caller-provided digest proves bytes only, not that an incomplete packet is valid.
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(REFUSAL):
        cycle_stages.verify_packet(file=path, sha256=digest, root=w.root, phase=phase, source_commit=commit)


def test_new_candidate_needs_matching_fingerprint(tmp_path):
    w = accepted(tmp_path)
    assert not cycle_stages.check_cycle(cycle=w.cycle, phase="source-ready", candidate="not-current", db_path=w.db)["approved"]


def test_snapshot_verification_needs_independent_commit_authority(tmp_path):
    import shutil
    w = accepted(tmp_path)
    packet = tmp_path / "packet.json"
    exported = cycle_stages.export_packet(cycle=w.cycle, phase="source-ready", output=packet, db_path=w.db)
    snapshot = tmp_path / "immutable-snapshot"
    snapshot.mkdir()
    shutil.copytree(w.root / "src", snapshot / "src")
    shutil.copytree(w.root / "tests", snapshot / "tests")
    with pytest.raises(REFUSAL):
        cycle_stages.verify_packet(file=packet, sha256=exported["sha256"], root=snapshot, phase="source-ready")
    result = cycle_stages.verify_packet(file=packet, sha256=exported["sha256"], root=snapshot,
                                         phase="source-ready", source_commit=exported["sourceCommit"])
    assert result["approved"]


@pytest.mark.parametrize("document", [[], None, {"schemaVersion": 2, "kind": "tc-stage-release", "policyVersion": 1,
                                                "phase": "source-ready", "checks": "not-a-case-list",
                                                "stages": ["not-a-stage"], "sourcePaths": ["src/item1.py"]}])
def test_malformed_packet_is_structured_refusal_not_unhandled_python_error(tmp_path, document):
    path = tmp_path / "malformed.json"
    path.write_text(json.dumps(document))
    with pytest.raises(ValidationError):
        cycle_stages.verify_packet(file=path, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                    root=tmp_path, phase="source-ready")


@pytest.mark.parametrize("contract", [None,
    {"schemaVersion": 2, "criteria": [], "sources": ["src/item1.py"]},
    {"schemaVersion": 2, "criteria": [{"id": "BEHAVIOR", "expected": "Item is correct."}], "sources": []}])
def test_managed_qa_claim_requires_real_criterion_and_source_scope(tmp_path, contract):
    def configure(plan, root, db):
        metadata = {"requiresQa": True}
        if contract is not None:
            metadata["acceptanceContract"] = contract
        api.update_task(task_id=plan["streams"][0]["task"], metadata=metadata, db_path=db)
    w = None
    # Earlier validation is also valid: no invalid scope may reach a permit.
    with pytest.raises(REFUSAL):
        w = make_world(tmp_path, count=1, configure=configure)
        w.freeze()
        w.start("q1")
    if w is not None:
        assert not w.status()["running"]


def test_managed_qa_claim_accepts_declared_existing_source_scope(tmp_path):
    from tc.services import execution
    def configure(plan, root, db):
        task = plan["streams"][0]["task"]
        metadata = {"requiresQa": True, "acceptanceContract": {"schemaVersion": 2,
            "criteria": [{"id": "BEHAVIOR", "expected": "Item is correct."}], "sources": ["src/item1.py"]}}
        for identity in (plan["task"], task):
            api.update_task(task_id=identity, metadata=metadata, db_path=db)
            execution.register_limits(task_id=identity, root=root, timeout_seconds=30, db_path=db)
        execution.bind_scope(root_task_id=plan["task"], task_id=task,
                             criterion_map={"BEHAVIOR": "BEHAVIOR"}, db_path=db)
    w = make_world(tmp_path, count=1, configure=configure)
    w.freeze()
    assert w.start("q1")["token"]


@pytest.mark.parametrize("missing", ["root-policy", "child-policy", "binding"])
def test_managed_qa_cannot_omit_governing_execution_authority(tmp_path, missing):
    from tc.services import execution
    def configure(plan, root, db):
        child = plan["streams"][0]["task"]
        metadata = {"requiresQa": True, "acceptanceContract": {"schemaVersion": 2,
            "criteria": [{"id": "BEHAVIOR", "expected": "Item is correct."}], "sources": ["src/item1.py"]}}
        for identity in (plan["task"], child):
            api.update_task(task_id=identity, metadata=metadata, db_path=db)
        if missing != "root-policy":
            execution.register_limits(task_id=plan["task"], root=root, timeout_seconds=30, db_path=db)
        if missing != "child-policy":
            execution.register_limits(task_id=child, root=root, timeout_seconds=30, db_path=db)
        # No bind call: it is invalid without both policies, and mandatory otherwise.
    w = make_world(tmp_path, count=1, configure=configure)
    w.freeze()
    with pytest.raises(REFUSAL):
        w.start("q1")
    assert not w.status()["running"]
