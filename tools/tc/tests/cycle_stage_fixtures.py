"""Public-contract fixtures for stage policy; no production internals or providers."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
import subprocess
import uuid

from tc import api
from tc.db.connection import init_db
from tc.services import cycles, cycle_stages


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


@dataclass
class StageWorld:
    root: Path
    db: Path
    plan: dict
    sequence: int = 0
    claims: dict = field(default_factory=dict)

    @property
    def cycle(self):
        return self.plan["id"]

    def artifact(self, text="observed fixture result"):
        self.sequence += 1
        path = self.root / "evidence" / f"receipt-{self.sequence}.txt"
        path.parent.mkdir(exist_ok=True)
        path.write_text(text + "\n")
        return str(path)

    def status(self):
        return cycles.cycle_status(cycle=self.cycle, db_path=self.db)

    def advance(self, event, **receipt):
        payload = {"operationId": str(uuid.uuid4()),
                   "generation": self.status()["generation"],
                   "artifact": self.artifact(), **receipt}
        return cycle_stages.advance_cycle(cycle=self.cycle, event=event,
                                           receipt=payload, db_path=self.db)

    def freeze(self):
        return self.advance("inventory-frozen", actor="planner", reviewer="inventory-reviewer")

    def start(self, stream, *, native=True):
        spec = next(s for s in self.plan["streams"] if s["id"] == stream)
        cwd = Path(spec.get("worktree", self.root))
        claim = cycles.claim_stream(cycle=self.cycle, stream=stream,
                                    agent=f"worker-{stream}", cwd=cwd,
                                    branch=spec.get("branch"), db_path=self.db)
        self.claims[stream] = claim
        cycles.verify_dispatch(cycle=self.cycle, stream=stream, role=spec["role"],
                               cwd=cwd, db_path=self.db)
        if native:
            self.advance("native-started", stream=stream, leaseToken=claim["token"],
                         nativeId=f"synthetic-adapter-{stream}-{claim['token']}")
        return claim

    def result(self, stream, check, outcome="passed", **extra):
        return self.advance("result-recorded", stream=stream,
                            leaseToken=self.claims[stream]["token"], check=check,
                            outcome=outcome, **extra)

    def stop(self, stream):
        return cycles.record_event(cycle=self.cycle, stream=stream, event="stopped",
                                   receipt={"leaseToken": self.claims[stream]["token"],
                                            "stopped": True, "artifact": self.artifact()},
                                   db_path=self.db)

    def collect(self, stage="qa"):
        return self.advance("sweep-collected", stage=stage)

    def accept(self, stage="qa"):
        return self.advance("stage-accepted", stage=stage, actor="converger",
                            reviewer="independent-reviewer")

    def run_all(self):
        for spec in self.plan["streams"]:
            self.start(spec["id"])
            for case in self.plan["checks"]:
                if case["stream"] == spec["id"] and case["required"]:
                    self.result(spec["id"], case["id"])
            self.stop(spec["id"])
        self.collect()
        self.accept()


def make_world(tmp_path, *, count=5, configure=None, cycle="stage-example", register_policy=True):
    root = tmp_path / "project"
    root.mkdir()
    (root / "src").mkdir()
    (root / "tests").mkdir()
    for i in range(1, count + 1):
        (root / "src" / f"item{i}.py").write_text(f"VALUE = {i}\n")
        (root / "tests" / f"item{i}.txt").write_text(f"expect {i}\n")
    (root / "src" / "shared.py").write_text("SHARED = 1\n")
    (root / ".gitignore").write_text("evidence/\n")
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Synthetic Stage Fixture")
    git(root, "config", "user.email", "stage@example.invalid")
    git(root, "config", "commit.gpgsign", "false")
    git(root, "add", ".")
    git(root, "commit", "-m", "synthetic fixture")
    db = tmp_path / "authority" / ".copilot" / "tasks.db"
    init_db(db)
    parent = api.create_task(title="Stage root", db_path=db)["id"]
    children = [api.create_task(title=f"Stage child {i}", parent=parent,
                                db_path=db)["id"] for i in range(count)]
    evidence = root / "evidence"
    evidence.mkdir()
    capability = evidence / "capability.json"
    capability.write_text(json.dumps({"workers": 3, "assurance": "deterministic test adapter, not native model proof"}))
    plan = {"schemaVersion": 2, "policyVersion": 1, "generation": 1,
            "id": cycle, "task": parent, "runtime": "codex", "root": str(root),
            "capacity": 3, "resourceLimits": {"light": 3},
            "runtimeCapability": {"workers": 3, "evidence": str(capability)},
            "stages": [{"id": "qa", "kind": "sweep", "owner": "reviewer",
                        "dependsOn": [], "phase": "source-ready"}],
            "streams": [{"id": f"q{i}", "task": task, "role": "qa", "kind": "research",
                         "paths": [], "readOnly": True, "resource": "light",
                         "dependsOn": [], "stage": "qa"}
                        for i, task in enumerate(children, 1)],
            "checks": [{"id": f"C{i}", "stage": "qa", "stream": f"q{i}",
                        "criterion": "BEHAVIOR", "consumer": f"consumer-{i}",
                        "paths": [f"src/item{i}.py", f"tests/item{i}.txt"],
                        "inputs": {"runtime": "synthetic-fixed-runtime"},
                        "dependsOn": [], "required": True}
                       for i in range(1, count + 1)]}
    if configure:
        configure(plan, root, db)
    if register_policy:
        register_fixture_limits(plan, root, db)
    cycles.create_cycle(plan=plan, db_path=db)
    return StageWorld(root, db, plan)


def register_fixture_limits(plan, root, db):
    """Real default execution authority for every managed stream, including non-QA tasks."""
    from tc.db.connection import get_db
    from tc.services import execution
    for identity in [plan["task"], *(spec["task"] for spec in plan["streams"])]:
        task = api.get_task(task_id=identity, db_path=db)
        metadata = task.get("metadata") or {}
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        if not metadata.get("acceptanceContract") and not metadata.get("requiresQa"):
            api.update_task(task_id=identity, metadata={"acceptanceContract": {
                "schemaVersion": 2, "criteria": [{"id": "BEHAVIOR", "expected": "Declared item is correct."}],
                "sources": ["src/shared.py"]}}, db_path=db)
        with get_db(db) as conn:
            exists = execution.has_limits(task_id=identity, conn=conn)
        if not exists:
            execution.register_limits(task_id=identity, root=root, timeout_seconds=30, db_path=db)
    for spec in plan["streams"]:
        execution.bind_scope(root_task_id=plan["task"], task_id=spec["task"],
                             criterion_map={"BEHAVIOR": "BEHAVIOR"}, db_path=db)
