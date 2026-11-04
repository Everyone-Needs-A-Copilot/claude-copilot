"""Behavioral coordination probes: no model providers, real SQLite/processes/Git."""
import copy
import json
from pathlib import Path
import subprocess
import time

import pytest
from tc.db.connection import init_db, get_db
from tc.db.exceptions import ConflictError, ValidationError
from tc.services.tasks import create_task
from tc.services import cycles


def make_plan(root, count=3, readonly=True):
    return {"schemaVersion": 1, "id": "example", "task": 1, "runtime": "codex", "root": str(root), "capacity": 3,
            "resourceLimits": {"light": 2}, "streams": [{"id": f"s{i}", "task": i + 1, "role": role, "kind": "research", "paths": [], "readOnly": True, "resource": "light", "dependsOn": []} for i, role in enumerate(["sd", "uxd", "qa"][:count])]}


def setup_cycle(tmp_path, count=3):
    db = tmp_path / ".copilot/tasks.db"
    init_db(db)
    for i in range(count):
        create_task(title=f"Scope {i}", db_path=db)
    plan = make_plan(tmp_path, count)
    cycles.create_cycle(plan=plan, db_path=db)
    return db, plan


def artifact(root, name="evidence.txt"):
    path = root / name
    path.write_text("observed successful focused check\n")
    return str(path)


def test_plan_idempotence_and_conflicting_reuse(tmp_path):
    db, plan = setup_cycle(tmp_path)
    assert cycles.create_cycle(plan=plan, db_path=db)["revision"] == 1
    plan["capacity"] = 5
    with pytest.raises(ConflictError):
        cycles.create_cycle(plan=plan, db_path=db)
    assert cycles.cycle_status(cycle="example", db_path=db)["revision"] == 1


@pytest.mark.parametrize("path", ["../secret", "/absolute", "src/*/file.py", "src/?.py", "src/[ab].py", "", "src\\file"])
def test_ownership_refuses_escapes_and_ambiguous_globs(tmp_path, path):
    with pytest.raises(ValidationError):
        cycles.validate_claims([{"id": "writer", "paths": [path]}], tmp_path)


def test_ownership_covers_directories_new_files_and_symlink_escape(tmp_path):
    with pytest.raises(ValidationError, match="overlap"):
        cycles.validate_claims([{"id": "a", "paths": ["src/**"]}, {"id": "b", "paths": ["src/new/file.py"]}], tmp_path)
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    (tmp_path / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValidationError, match="escapes"):
        cycles.validate_claims([{"id": "writer", "paths": ["escape/new.py"]}], tmp_path)
    assert len(cycles.validate_claims([{"id": "a", "paths": ["src/a.py"]}, {"id": "b", "paths": ["src/b.py"]}], tmp_path)) == 2


def test_readers_overlap_but_missing_ownership_and_shared_writer_roots_refuse(tmp_path):
    plan = make_plan(tmp_path)
    cycles.validate_plan(plan)
    plan["streams"][0].pop("paths")
    with pytest.raises(ValidationError):
        cycles.validate_plan(plan)
    plan = make_plan(tmp_path, 2)
    for i, stream in enumerate(plan["streams"]):
        stream.update(readOnly=False, paths=[f"output{i}.md"], worktree=str(tmp_path))
    with pytest.raises(ValidationError, match="share"):
        cycles.validate_plan(plan)


def test_capacity_claims_are_exclusive_and_dispatch_permit_is_single_use(tmp_path):
    db, plan = setup_cycle(tmp_path)
    first = cycles.claim_stream(cycle="example", stream="s0", agent="worker-a", cwd=tmp_path, db_path=db)
    second = cycles.claim_stream(cycle="example", stream="s1", agent="worker-b", cwd=tmp_path, db_path=db)
    state = cycles.cycle_status(cycle="example", db_path=db)
    assert state["running"] == ["s0", "s1"]
    assert state["queued"] == [{"id": "s2", "reason": "resource-capacity", "resource": "light"}]
    with pytest.raises(ConflictError):
        cycles.claim_stream(cycle="example", stream="s0", agent="other", cwd=tmp_path, db_path=db)
    assert cycles.claim_stream(cycle="example", stream="s0", agent="worker-a", cwd=tmp_path, db_path=db)["token"] == first["token"]
    with pytest.raises(ValidationError):
        cycles.verify_dispatch(cycle="example", stream="s0", role="me", cwd=tmp_path, db_path=db)
    assert cycles.verify_dispatch(cycle="example", stream="s0", role="sd", cwd=tmp_path, db_path=db)["allowed"]
    with pytest.raises(ConflictError):
        cycles.verify_dispatch(cycle="example", stream="s0", role="sd", cwd=tmp_path, db_path=db)


def test_contract_unlocks_consumer_before_provider_completion(tmp_path):
    db, plan = setup_cycle(tmp_path)
    # A separate cycle allows us to assert a genuine typed dependency.
    plan["id"] = "contracts"
    plan["resourceLimits"] = {}
    plan["streams"][1]["dependsOn"] = [{"stream": "s0", "event": "contract", "reason": "Agreed response shape"}]
    cycles.create_cycle(plan=plan, db_path=db)
    assert "s1" not in cycles.cycle_status(cycle="contracts", db_path=db)["ready"]
    claim = cycles.claim_stream(cycle="contracts", stream="s0", agent="provider", cwd=tmp_path, db_path=db)
    cycles.record_event(cycle="contracts", stream="s0", event="contract", receipt={"leaseToken": claim["token"], "artifact": artifact(tmp_path)}, db_path=db)
    status = cycles.cycle_status(cycle="contracts", db_path=db)
    assert "s1" in status["ready"]
    assert status["streams"]["s0"]["state"] == "running"


def test_wrong_cwd_and_dependency_cycles_refuse_before_mutation(tmp_path):
    db, plan = setup_cycle(tmp_path)
    with pytest.raises(ValidationError, match="directory"):
        cycles.claim_stream(cycle="example", stream="s0", agent="a", cwd=tmp_path.parent, db_path=db)
    assert not cycles.cycle_status(cycle="example", db_path=db)["running"]
    plan["streams"][0]["dependsOn"] = [{"stream": "s1", "event": "built", "reason": "input"}]
    plan["streams"][1]["dependsOn"] = [{"stream": "s0", "event": "built", "reason": "input"}]
    with pytest.raises(ValidationError, match="cycle"):
        cycles.validate_plan(plan)


def test_expired_claim_is_held_not_reallocated(tmp_path):
    db, plan = setup_cycle(tmp_path)
    cycles.claim_stream(cycle="example", stream="s0", agent="first", cwd=tmp_path, db_path=db)
    conn = get_db(db)
    data = json.loads(conn.execute("SELECT data FROM protocol_cycles").fetchone()[0])
    data["streams"]["s0"]["claim"]["leaseUntil"] = 1
    conn.execute("UPDATE protocol_cycles SET data=?", (json.dumps(data),))
    conn.commit(); conn.close()
    assert cycles.cycle_status(cycle="example", db_path=db)["stalled"] == ["s0"]
    with pytest.raises(ConflictError):
        cycles.claim_stream(cycle="example", stream="s0", agent="second", cwd=tmp_path, db_path=db)


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()


def code_cycle(tmp_path):
    root = tmp_path / "integration"; root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "Synthetic Fixture")
    git(root, "config", "commit.gpgsign", "false")
    (root / "base.txt").write_text("base\n")
    git(root, "add", "base.txt"); git(root, "commit", "-m", "synthetic base")
    db = tmp_path / ".copilot/tasks.db"; init_db(db); create_task(title="synthetic scope", db_path=db)
    worktree = tmp_path / "writer"
    plan = make_plan(root, 1)
    plan["streams"][0].update(kind="code", role="me", readOnly=False, paths=["result.txt"], worktree=str(worktree), branch="cycle/result")
    cycles.create_cycle(plan=plan, db_path=db)
    cycles.prepare_worktree(cycle="example", stream="s0", db_path=db)
    claim = cycles.claim_stream(cycle="example", stream="s0", agent="builder", cwd=worktree, branch="cycle/result", db_path=db)
    return root, worktree, db, claim


def complete_contribution(root, worktree, db, claim):
    (worktree / "result.txt").write_text("correct result\n")
    git(worktree, "add", "result.txt"); git(worktree, "commit", "-m", "synthetic contribution")
    evidence = artifact(root.parent)
    cycles.record_event(cycle="example", stream="s0", event="built", receipt={"leaseToken": claim["token"], "artifact": evidence}, db_path=db)
    cycles.record_event(cycle="example", stream="s0", event="stopped", receipt={"leaseToken": claim["token"], "stopped": True, "artifact": evidence}, db_path=db)
    git(root, "merge", "--ff-only", "cycle/result")
    cycles.record_event(cycle="example", stream="s0", event="integrated", receipt={"commit": git(root, "rev-parse", "HEAD")}, db_path=db)
    fp = cycles.fingerprint(root, ["result.txt"])
    cycles.record_event(cycle="example", stream="s0", event="accepted", receipt={"agent": "independent-qa", "verdict": "approved", "sourceFingerprint": fp, "artifact": evidence}, db_path=db)
    cycles.record_event(cycle="example", stream="s0", event="teardown", receipt={"passed": True, "command": ["synthetic-no-resource-teardown"], "artifact": evidence}, db_path=db)


def test_real_worktree_convergence_and_authorized_cleanup_preserves_branch(tmp_path):
    root, worktree, db, claim = code_cycle(tmp_path)
    complete_contribution(root, worktree, db, claim)
    assert cycles.cycle_status(cycle="example", db_path=db)["deliveryAccepted"]
    packet = cycles.cleanup_plan(cycle="example", db_path=db)
    assert not packet["held"], packet
    assert len(packet["eligible"]) == 1
    result = cycles.cleanup_cycle(cycle="example", db_path=db)
    assert len(result["removed"]) == 1, result
    assert not worktree.exists()
    assert git(root, "rev-parse", "cycle/result") == git(root, "rev-parse", "HEAD")
    assert cycles.cleanup_cycle(cycle="example", db_path=db)["removed"] == []
    assert cycles.cycle_status(cycle="example", db_path=db)["cleanupComplete"]


def test_cleanup_preserves_unique_dirty_active_or_unverified_resources(tmp_path, monkeypatch):
    root, worktree, db, claim = code_cycle(tmp_path)
    packet = cycles.cleanup_cycle(cycle="example", db_path=db)
    assert not packet["removed"] and worktree.exists()
    assert any("active" in reason for reason in packet["held"][0]["reasons"])
    complete_contribution(root, worktree, db, claim)
    (worktree / "unique.txt").write_text("preserve this\n")
    assert not cycles.cleanup_cycle(cycle="example", db_path=db)["removed"]
    assert (worktree / "unique.txt").read_text() == "preserve this\n"
    # Preserve the file through a commit; unique commits remain held too.
    git(worktree, "add", "unique.txt"); git(worktree, "commit", "-m", "unmerged preserved work")
    assert not cycles.cleanup_cycle(cycle="example", db_path=db)["removed"]
    monkeypatch.setattr(cycles, "_active_consumers", lambda path: ["synthetic-consumer"])
    assert any("consumer" in r for r in cycles.cleanup_plan(cycle="example", db_path=db)["held"][0]["reasons"])
    assert worktree.exists()


def test_stale_acceptance_is_refused_and_shared_changes_invalidate_status(tmp_path):
    root, worktree, db, claim = code_cycle(tmp_path)
    complete_contribution(root, worktree, db, claim)
    (root / "result.txt").write_text("changed after review\n")
    status = cycles.cycle_status(cycle="example", db_path=db)
    assert status["stale"] == ["s0"]
    assert not status["deliveryAccepted"]
    assert not cycles.cleanup_cycle(cycle="example", db_path=db)["removed"]


def test_worker_cannot_build_an_out_of_scope_change(tmp_path):
    root, worktree, db, claim = code_cycle(tmp_path)
    (worktree / "base.txt").write_text("outside owner\n")
    with pytest.raises(ValidationError, match="outside"):
        cycles.record_event(cycle="example", stream="s0", event="built", receipt={"leaseToken": claim["token"], "artifact": artifact(tmp_path)}, db_path=db)
    assert cycles.cycle_status(cycle="example", db_path=db)["streams"]["s0"]["state"] == "running"


def test_smoke_real_processes_overlap_and_all_stop_without_provider_calls():
    result = cycles.smoke_roles()
    assert result["overlap"] == len(cycles.DEFAULT_ROLES)
    assert result["stopped"] == len(cycles.DEFAULT_ROLES)
    assert result["residualProcesses"] == result["tokens"] == result["paidCalls"] == 0
    assert result["nativeAgentDispatch"] is False


def test_non_git_document_attestation_is_scoped_and_rejects_stale_text(tmp_path):
    from tc.services.tiers import set_tier, attest, attestation_status
    db = tmp_path / ".copilot/tasks.db"; init_db(db)
    task = create_task(title="Research conclusion", db_path=db)
    set_tier(task_id=task["id"], tier="T1", reason="Document only", db_path=db)
    (tmp_path / "finding.md").write_text("# Finding\nThe evidence is consistent.\n")
    (tmp_path / "capture.png").write_bytes(b"synthetic screenshot artifact")
    receipt = attest(task_id=task["id"], tier="T1", inputs={"in": "finding.md", "present": ["evidence is consistent"], "absent": ["TODO"], "load": "capture.png"}, db_path=db)
    assert receipt["files"] == ["finding.md"]
    from tc.services.tasks import get_task
    conn = get_db(db)
    assert attestation_status(get_task(task_id=task["id"], conn=conn), conn)["approved"]
    (tmp_path / "finding.md").write_text("Changed after attestation")
    assert not attestation_status(get_task(task_id=task["id"], conn=conn), conn)["approved"]
    conn.close()
    with pytest.raises(ValidationError, match="document"):
        attest(task_id=task["id"], tier="T1", inputs={"in": "code.py", "present": ["x"], "absent": ["y"], "load": "capture.png"}, db_path=db)


def test_prd_close_refuses_open_descendants_and_active_claims(tmp_path):
    from tc.services.prds import create_prd, update_prd, body_status
    from tc.services.tasks import update_task
    db = tmp_path / ".copilot/tasks.db"; init_db(db)
    prd = create_prd(title="Whole body", db_path=db)
    parent = create_task(title="parent", prd=prd["id"], db_path=db)
    child = create_task(title="child without direct prd", parent=parent["id"], db_path=db)
    with pytest.raises(ValidationError, match="unresolved"):
        update_prd(prd_id=prd["id"], status="completed", db_path=db)
    update_task(task_id=parent["id"], status="completed", db_path=db)
    assert body_status(prd_id=prd["id"], db_path=db)["openTasks"][0]["id"] == child["id"]
    for status in ["in_progress", "blocked"]:
        update_task(task_id=child["id"], status=status, db_path=db)
        with pytest.raises(ValidationError):
            update_prd(prd_id=prd["id"], status="completed", db_path=db)
    update_task(task_id=child["id"], status="cancelled", metadata={"handoff": "Synthetic requirement explicitly dispositioned; retained history"}, db_path=db)
    conn = get_db(db); conn.execute("UPDATE tasks SET claimed_by='active-worker' WHERE id=?", (child["id"],)); conn.commit(); conn.close()
    with pytest.raises(ValidationError):
        update_prd(prd_id=prd["id"], status="archived", db_path=db)
    update_task(task_id=child["id"], clear_claim=True, db_path=db)
    assert update_prd(prd_id=prd["id"], status="completed", db_path=db)["status"] == "completed"
    assert body_status(prd_id=prd["id"], db_path=db)["counts"]["cancelled"] == 1
    conn = get_db(db); assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 2; conn.close()


def test_modified_contract_artifact_blocks_dependent_dispatch(tmp_path):
    db, plan = setup_cycle(tmp_path)
    plan["id"] = "fresh-contract"
    plan["resourceLimits"] = {}
    plan["streams"][1]["dependsOn"] = [{"stream": "s0", "event": "contract", "reason": "schema"}]
    cycles.create_cycle(plan=plan, db_path=db)
    claim = cycles.claim_stream(cycle="fresh-contract", stream="s0", agent="provider", cwd=tmp_path, db_path=db)
    evidence = artifact(tmp_path)
    cycles.record_event(cycle="fresh-contract", stream="s0", event="contract", receipt={"leaseToken": claim["token"], "artifact": evidence}, db_path=db)
    assert "s1" in cycles.cycle_status(cycle="fresh-contract", db_path=db)["ready"]
    Path(evidence).write_text("changed schema after receipt")
    assert "s1" not in cycles.cycle_status(cycle="fresh-contract", db_path=db)["ready"]


def test_built_worker_keeps_capacity_until_observed_shutdown(tmp_path):
    db, plan = setup_cycle(tmp_path)
    plan["id"] = "one-slot"; plan["capacity"] = 1; plan["resourceLimits"] = {}
    cycles.create_cycle(plan=plan, db_path=db)
    claim = cycles.claim_stream(cycle="one-slot", stream="s0", agent="builder", cwd=tmp_path, db_path=db)
    evidence = artifact(tmp_path)
    cycles.record_event(cycle="one-slot", stream="s0", event="built", receipt={"leaseToken": claim["token"], "artifact": evidence}, db_path=db)
    status = cycles.cycle_status(cycle="one-slot", db_path=db)
    assert status["running"] == ["s0"]
    assert status["ready"] == []
    with pytest.raises(ConflictError):
        cycles.claim_stream(cycle="one-slot", stream="s1", agent="next", cwd=tmp_path, db_path=db)
    cycles.record_event(cycle="one-slot", stream="s0", event="stopped", receipt={"leaseToken": claim["token"], "stopped": True, "artifact": evidence}, db_path=db)
    assert cycles.cycle_status(cycle="one-slot", db_path=db)["ready"] == ["s1"]


def test_upstream_receipt_change_invalidates_consumer_acceptance(tmp_path):
    db, plan = setup_cycle(tmp_path, 2)
    plan["id"] = "upstream"; plan["resourceLimits"] = {}
    plan["streams"][1]["dependsOn"] = [{"stream": "s0", "event": "contract", "reason": "schema"}]
    cycles.create_cycle(plan=plan, db_path=db)
    evidence = artifact(tmp_path)
    provider = cycles.claim_stream(cycle="upstream", stream="s0", agent="provider", cwd=tmp_path, db_path=db)
    cycles.record_event(cycle="upstream", stream="s0", event="contract", receipt={"leaseToken": provider["token"], "artifact": evidence, "version": "initial"}, db_path=db)
    consumer = cycles.claim_stream(cycle="upstream", stream="s1", agent="consumer", cwd=tmp_path, db_path=db)
    cycles.record_event(cycle="upstream", stream="s1", event="built", receipt={"leaseToken": consumer["token"], "artifact": evidence}, db_path=db)
    cycles.record_event(cycle="upstream", stream="s1", event="integrated", receipt={}, db_path=db)
    cycles.record_event(cycle="upstream", stream="s1", event="accepted", receipt={"agent": "reviewer", "verdict": "approved", "sourceFingerprint": cycles.fingerprint(tmp_path, []), "artifact": evidence}, db_path=db)
    assert "s1" not in cycles.cycle_status(cycle="upstream", db_path=db)["stale"]
    cycles.record_event(cycle="upstream", stream="s0", event="contract", receipt={"leaseToken": provider["token"], "artifact": evidence, "version": "changed"}, db_path=db)
    assert "s1" in cycles.cycle_status(cycle="upstream", db_path=db)["stale"]


def test_built_refuses_contract_changed_while_consumer_was_running(tmp_path):
    db, plan = setup_cycle(tmp_path, 2)
    plan["id"] = "consumed-input"; plan["resourceLimits"] = {}
    plan["streams"][1]["dependsOn"] = [{"stream": "s0", "event": "contract", "reason": "schema"}]
    cycles.create_cycle(plan=plan, db_path=db)
    evidence = artifact(tmp_path)
    provider = cycles.claim_stream(cycle="consumed-input", stream="s0", agent="provider", cwd=tmp_path, db_path=db)
    cycles.record_event(cycle="consumed-input", stream="s0", event="contract", receipt={"leaseToken": provider["token"], "artifact": evidence, "version": "initial"}, db_path=db)
    consumer = cycles.claim_stream(cycle="consumed-input", stream="s1", agent="consumer", cwd=tmp_path, db_path=db)
    cycles.record_event(cycle="consumed-input", stream="s0", event="contract", receipt={"leaseToken": provider["token"], "artifact": evidence, "version": "changed"}, db_path=db)
    with pytest.raises(ValidationError, match="since claim"):
        cycles.record_event(cycle="consumed-input", stream="s1", event="built", receipt={"leaseToken": consumer["token"], "artifact": evidence}, db_path=db)
    assert cycles.cycle_status(cycle="consumed-input", db_path=db)["streams"]["s1"]["state"] == "running"


def test_cleanup_holds_receipt_evidence_inside_the_worktree(tmp_path):
    root, worktree, db, claim = code_cycle(tmp_path)
    complete_contribution(root, worktree, db, claim)
    # Existing tracked source is also made the evidence file, so a clean Git
    # status cannot accidentally hide this dependency.
    internal = str(worktree / "result.txt")
    cycles.record_event(cycle="example", stream="s0", event="stopped", receipt={"leaseToken": claim["token"], "stopped": True, "artifact": internal}, db_path=db)
    packet = cycles.cleanup_plan(cycle="example", db_path=db)
    assert packet["eligible"] == []
    assert any("evidence" in reason for reason in packet["held"][0]["reasons"])
    assert worktree.exists()


def test_two_concurrent_claims_cannot_own_one_scope(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    db, plan = setup_cycle(tmp_path)
    def claim(agent):
        try:
            cycles.claim_stream(cycle="example", stream="s0", agent=agent, cwd=tmp_path, db_path=db)
            return True
        except ConflictError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ["worker-a", "worker-b"]))
    assert sorted(results) == [False, True]
    assert cycles.cycle_status(cycle="example", db_path=db)["running"] == ["s0"]


def test_pending_qa_task_refusal_does_not_consume_dispatch_permit(tmp_path):
    db, plan = setup_cycle(tmp_path)
    cycles.claim_stream(cycle="example", stream="s0", agent="worker", cwd=tmp_path, db_path=db)
    with pytest.raises(ValidationError, match="Pending-QA"):
        cycles.verify_dispatch(cycle="example", stream="s0", role="sd", cwd=tmp_path, blocked_task=1, db_path=db)
    assert not cycles.cycle_status(cycle="example", db_path=db)["streams"]["s0"]["claim"].get("dispatchAuthorized")
    assert cycles.verify_dispatch(cycle="example", stream="s0", role="sd", cwd=tmp_path, blocked_task=2, db_path=db)["allowed"]


def test_prd_gate_agrees_with_cycle_when_shutdown_evidence_changes(tmp_path):
    from tc.services.prds import create_prd, update_prd, body_status
    from tc.services.tasks import update_task
    db = tmp_path / ".copilot/tasks.db"; init_db(db)
    prd = create_prd(title="Current shutdown", db_path=db)
    task = create_task(title="scope", prd=prd["id"], db_path=db)
    plan = make_plan(tmp_path, 1)
    cycles.create_cycle(plan=plan, db_path=db)
    claim = cycles.claim_stream(cycle="example", stream="s0", agent="worker", cwd=tmp_path, db_path=db)
    evidence = artifact(tmp_path)
    cycles.record_event(cycle="example", stream="s0", event="stopped", receipt={"leaseToken": claim["token"], "stopped": True, "artifact": evidence}, db_path=db)
    update_task(task_id=task["id"], status="completed", db_path=db)
    assert body_status(prd_id=prd["id"], db_path=db)["canComplete"]
    Path(evidence).write_text("Changed shutdown evidence")
    assert cycles.cycle_status(cycle="example", db_path=db)["running"] == ["s0"]
    assert not body_status(prd_id=prd["id"], db_path=db)["canComplete"]
    with pytest.raises(ValidationError, match="active"):
        update_prd(prd_id=prd["id"], status="completed", db_path=db)


def test_in_root_symlink_alias_cannot_bypass_exclusive_ownership(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/a.py").write_text("source")
    (tmp_path / "alias").symlink_to(tmp_path / "src", target_is_directory=True)
    with pytest.raises(ValidationError, match="symlink"):
        cycles.validate_claims([{"id": "a", "paths": ["src/a.py"]}, {"id": "b", "paths": ["alias/a.py"]}], tmp_path)


def test_event_retry_is_idempotent_without_rewriting_history(tmp_path):
    db, plan = setup_cycle(tmp_path)
    claim = cycles.claim_stream(cycle="example", stream="s0", agent="worker", cwd=tmp_path, db_path=db)
    receipt = {"leaseToken": claim["token"], "artifact": artifact(tmp_path)}
    first = cycles.record_event(cycle="example", stream="s0", event="built", receipt=receipt, db_path=db)
    revision = cycles.cycle_status(cycle="example", db_path=db)["revision"]
    second = cycles.record_event(cycle="example", stream="s0", event="built", receipt=receipt, db_path=db)
    assert second["idempotent"]
    assert first["receipt"] == second["receipt"]
    assert cycles.cycle_status(cycle="example", db_path=db)["revision"] == revision


def test_adapter_discovery_is_read_only_and_honest_about_isolation(tmp_path):
    fallback = cycles.inspect_adapter(project=tmp_path)
    assert fallback["source"] == "filesystem-default"
    assert fallback["isolation"]["stateful"] is False
    assert fallback["executed"] == []
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"worktree:setup": "false", "worktree:teardown": "false"}}))
    detected = cycles.inspect_adapter(project=tmp_path)
    assert detected["commands"]["setup"] == ["npm", "run", "worktree:setup"]
    assert detected["isolation"]["stateful"] is False
    assert detected["executed"] == []
    (tmp_path / ".copilot").mkdir()
    descriptor = tmp_path / ".copilot/worktree-adapter.json"
    descriptor.write_text(json.dumps({"schemaVersion": 1, "commands": {"setup": "npm run setup"}, "isolation": {"stateful": False, "details": "file only"}}))
    with pytest.raises(ValidationError, match="argv"):
        cycles.inspect_adapter(project=tmp_path)
    descriptor.write_text(json.dumps({"schemaVersion": 1, "commands": {"setup": ["false"]}, "isolation": {"stateful": True, "details": "managed synthetic receipt per worker"}}))
    declared = cycles.inspect_adapter(project=tmp_path)
    assert declared["requiresSetupEvidence"] and not declared["executed"]


def test_stateful_claim_refuses_unproven_shared_state(tmp_path):
    db, plan = setup_cycle(tmp_path, 1)
    plan["id"] = "stateful"; plan["streams"][0]["stateful"] = True
    cycles.create_cycle(plan=plan, db_path=db)
    with pytest.raises(ValidationError, match="isolation adapter"):
        cycles.claim_stream(cycle="stateful", stream="s0", agent="worker", cwd=tmp_path, db_path=db)
    descriptor = tmp_path / ".copilot/worktree-adapter.json"
    descriptor.write_text(json.dumps({"schemaVersion": 1, "commands": {}, "isolation": {"stateful": True, "details": "managed synthetic resources"}}))
    with pytest.raises(ValidationError, match="artifact"):
        cycles.claim_stream(cycle="stateful", stream="s0", agent="worker", cwd=tmp_path, db_path=db)
    assert not cycles.cycle_status(cycle="stateful", db_path=db)["running"]
