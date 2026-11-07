"""Real exported packets for synthetic signed release-script fixtures.

The lifecycle observations below are deterministic test inputs, never evidence
of actual native agents. The real service and offline verifier remain intact.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from tc import api
from tc.db.connection import init_db
from tc.services import cycle_stages, cycles, execution


def exported_packet(repo: Path, commit: str, evidence_parent: Path) -> dict[str, str]:
    """Export through the real authority against an exact, retained Git snapshot."""
    evidence = Path(tempfile.mkdtemp(prefix="stage-packet-", dir=evidence_parent))
    snapshot = evidence / "source"
    subprocess.run(["git", "clone", "--quiet", "--no-checkout", str(repo), str(snapshot)],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(snapshot), "checkout", "--quiet", "--detach", commit],
                   check=True, capture_output=True)
    paths = subprocess.check_output(
        ["git", "-C", str(snapshot), "ls-files"], text=True
    ).splitlines()
    db = evidence / "authority" / ".copilot" / "tasks.db"
    init_db(db)
    root = api.create_task(title="Synthetic release fixture", db_path=db)["id"]
    child = api.create_task(title="Synthetic exact-source check", parent=root, db_path=db)["id"]
    for task in (root, child):
        api.update_task(task_id=task, metadata={"acceptanceContract": {
            "schemaVersion": 2,
            "criteria": [{"id": "SOURCE", "expected": "Exact synthetic source is bound."}],
            "sources": paths,
        }}, db_path=db)
        execution.register_limits(task_id=task, root=snapshot, timeout_seconds=30, db_path=db)
    execution.bind_scope(root_task_id=root, task_id=child,
                         criterion_map={"SOURCE": "SOURCE"}, db_path=db)
    artifact = evidence / "synthetic-observation.json"
    artifact.write_text(json.dumps({"assurance": "deterministic fixture, not native proof",
                                    "commit": commit, "paths": paths}) + "\n")
    plan = {
        "schemaVersion": 2, "policyVersion": 1, "generation": 1,
        "id": "release-fixture", "task": root, "runtime": "codex", "root": str(snapshot),
        "capacity": 1, "resourceLimits": {"light": 1},
        "runtimeCapability": {"workers": 1, "evidence": str(artifact)},
        "stages": [{"id": "qa", "kind": "sweep", "owner": "reviewer",
                    "dependsOn": [], "phase": "source-ready"}],
        "streams": [{"id": "source", "task": child, "role": "qa", "kind": "qa",
                     "paths": [], "readOnly": True, "resource": "light",
                     "dependsOn": [], "stage": "qa"}],
        "checks": [{"id": "source", "stage": "qa", "stream": "source",
                    "criterion": "SOURCE", "consumer": "synthetic release script",
                    "paths": paths, "inputs": {"fixture": "exact signed source"},
                    "dependsOn": [], "required": True}],
    }
    cycles.create_cycle(plan=plan, db_path=db)

    def advance(event: str, **values):
        return cycle_stages.advance_cycle(cycle=plan["id"], event=event, db_path=db,
            receipt={"operationId": event, "generation": 1,
                     "artifact": str(artifact), **values})

    advance("inventory-frozen", actor="fixture-planner", reviewer="fixture-reviewer")
    claim = cycles.claim_stream(cycle=plan["id"], stream="source", agent="fixture-worker",
                                cwd=snapshot, db_path=db)
    cycles.verify_dispatch(cycle=plan["id"], stream="source", role="qa", cwd=snapshot, db_path=db)
    advance("native-started", stream="source", leaseToken=claim["token"],
            nativeId="synthetic-fixture-worker")
    advance("result-recorded", stream="source", leaseToken=claim["token"],
            check="source", outcome="passed")
    cycles.record_event(cycle=plan["id"], stream="source", event="stopped", db_path=db,
        receipt={"leaseToken": claim["token"], "stopped": True, "artifact": str(artifact)})
    advance("sweep-collected", stage="qa")
    advance("stage-accepted", stage="qa", actor="fixture-converger", reviewer="fixture-reviewer")
    packet = evidence / "packet.json"
    exported = cycle_stages.export_packet(cycle=plan["id"], phase="source-ready",
                                         output=packet, db_path=db)
    cycle_stages.verify_packet(file=packet, sha256=exported["sha256"], root=snapshot,
                               phase="source-ready", source_commit=commit)
    return {"TC_STAGE_PACKET": str(packet), "TC_STAGE_PACKET_SHA256": exported["sha256"]}
