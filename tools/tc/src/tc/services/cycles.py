"""Durable, harness-neutral ready-work coordination; no model calls, retirement preserves integrated history.

Native coordinators dispatch workers after claiming a ready scope. SQLite owns the
claims; evidence remains authoritative in tc's existing QA completion service.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from tc.db.exceptions import ConflictError, ValidationError

SLUG = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
EVENTS = {"contract", "built", "integrated", "accepted", "rejected", "held", "released", "teardown", "stopped"}
KINDS = {"code", "research", "design", "qa", "operations"}
DEFAULT_ROLES = ("ta", "me", "qa", "sec", "doc", "do", "sd", "uxd", "uids", "uid", "ind")


def _slug(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SLUG.fullmatch(value):
        raise ValidationError(f"{label} must be a short identifier")
    return value


def _positive(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValidationError(f"{label} must be a positive integer")
    return value


def normalize_path(value: Any, root: Path | None = None, *, literal_file: bool = False) -> str:
    """Restricted, conservatively comparable ownership syntax: literal or prefix/**.

    ``literal_file`` is for file names Git reports as changed. They are never
    patterns, so square brackets (Next.js ``[id]`` routes) are ordinary
    characters there; ``*`` and ``?`` stay refused.
    """
    if not isinstance(value, str) or not value or "\\" in value or "\0" in value:
        raise ValidationError("Ownership paths must be nonempty repository-relative strings")
    directory = value.endswith("/**") or value.endswith("/")
    prefix = value[:-3] if value.endswith("/**") else value.rstrip("/")
    parts = PurePosixPath(prefix).parts
    refused = "*?" if literal_file else "*?[]"
    if not parts or prefix.startswith("/") or any(p in {"..", "."} for p in parts) or any(c in prefix for c in refused):
        raise ValidationError(f"Unsafe or unsupported ownership path: {value}; use literal paths or terminal /**")
    normalized = "/".join(parts)
    if root is not None:
        resolved = (root / normalized).resolve()
        if resolved == root or root not in resolved.parents:
            raise ValidationError(f"Ownership path escapes project root: {value}")
        for index in range(1, len(parts) + 1):
            if root.joinpath(*parts[:index]).is_symlink():
                raise ValidationError(f"Ownership path uses a symlink alias: {value}")
    return normalized + ("/**" if directory else "")


def paths_overlap(a: str, b: str) -> bool:
    # A literal may denote a not-yet-created directory: treating its descendants
    # as conflicting is conservative, and covers new files without filesystem globbing.
    x, y = a.removesuffix("/**"), b.removesuffix("/**")
    return x == y or x.startswith(y + "/") or y.startswith(x + "/")


def validate_claims(streams: list[dict], root: Path | str | None = None) -> list[dict]:
    if not isinstance(streams, list) or not streams:
        raise ValidationError("streams must be a nonempty list")
    base = Path(root).resolve() if root is not None else None
    result, owners = [], []
    for raw in streams:
        if not isinstance(raw, dict):
            raise ValidationError("Each stream must be an object")
        stream = dict(raw)
        sid = _slug(stream.get("id"), "stream id")
        readonly = stream.get("readOnly", False)
        if not isinstance(readonly, bool):
            raise ValidationError(f"{sid}: readOnly must be boolean")
        paths = stream.get("paths")
        if not isinstance(paths, list) or (not paths and not readonly):
            raise ValidationError(f"{sid}: writers need explicit nonempty paths; readers declare paths=[] and readOnly=true")
        if readonly and paths:
            raise ValidationError(f"{sid}: read-only streams cannot claim write paths")
        stream["paths"] = sorted(set(normalize_path(p, base) for p in paths))
        for path in stream["paths"]:
            for owner, prior in owners:
                if owner != sid and paths_overlap(path, prior):
                    raise ValidationError(f"Ownership overlap: {owner} {prior} <-> {sid} {path}")
            owners.append((sid, path))
        result.append(stream)
    if len({s["id"] for s in result}) != len(result):
        raise ValidationError("Duplicate stream id")
    return result


def validate_plan(plan: dict) -> dict:
    if isinstance(plan, dict) and plan.get("schemaVersion") == 2:
        from tc.services.cycle_stages import validate_plan as validate_stages
        return validate_stages(plan)
    if not isinstance(plan, dict) or plan.get("schemaVersion") != 1:
        raise ValidationError("Cycle plan requires schemaVersion 1")
    data = json.loads(json.dumps(plan))
    _slug(data.get("id"), "cycle id")
    _positive(data.get("task"), "cycle task")
    if data.get("runtime") not in {"claude", "codex", "local"}:
        raise ValidationError("runtime must be claude, codex or local")
    if not isinstance(data.get("root"), str):
        raise ValidationError("root must be an absolute directory string")
    root = Path(data["root"])
    if not root.is_absolute() or not root.is_dir():
        raise ValidationError("root must be an existing absolute directory")
    data["root"] = str(root.resolve())
    _positive(data.get("capacity"), "capacity (available worker slots, excluding coordinator)")
    limits = data.get("resourceLimits", {})
    if not isinstance(limits, dict):
        raise ValidationError("resourceLimits must be an object")
    for key, limit in limits.items():
        _slug(key, "resource class")
        _positive(limit, f"resourceLimits.{key}")
    data["resourceLimits"] = limits
    data["streams"] = validate_claims(data.get("streams"), root.resolve())
    by_id = {s["id"]: s for s in data["streams"]}
    worktrees = set()
    for stream in data["streams"]:
        sid = stream["id"]
        _positive(stream.get("task"), f"{sid}.task")
        _slug(stream.get("role"), f"{sid}.role")
        if stream.get("kind") not in KINDS:
            raise ValidationError(f"{sid}: kind must be one of {sorted(KINDS)}")
        if not isinstance(stream.setdefault("stateful", False), bool):
            raise ValidationError(f"{sid}: stateful must be boolean")
        resource = stream.setdefault("resource", "light")
        _slug(resource, f"{sid}.resource")
        if not isinstance(stream.setdefault("dependsOn", []), list):
            raise ValidationError(f"{sid}: dependsOn must be a list")
        for dep in stream["dependsOn"]:
            if not isinstance(dep, dict) or dep.get("stream") not in by_id or dep.get("event") not in {"contract", "built", "integrated", "accepted"}:
                raise ValidationError(f"{sid}: invalid dependency")
            if not isinstance(dep.get("reason"), str) or not dep["reason"].strip():
                raise ValidationError(f"{sid}: every dependency needs its concrete input or decision reason")
        if not stream.get("readOnly"):
            path = stream.get("worktree")
            if not isinstance(path, str) or not Path(path).is_absolute():
                raise ValidationError(f"{sid}: writer needs an explicit absolute worktree")
            canonical = str(Path(path).resolve())
            if canonical in worktrees:
                raise ValidationError("Two writers cannot share a working directory")
            worktrees.add(canonical)
            stream["worktree"] = canonical
            if stream["kind"] == "code" and not stream.get("branch"):
                raise ValidationError(f"{sid}: code writer needs an explicit branch")
    visiting, visited = set(), set()
    def visit(sid):
        if sid in visiting:
            raise ValidationError("Dependency cycle: " + sid)
        if sid in visited:
            return
        visiting.add(sid)
        for dep in by_id[sid]["dependsOn"]:
            visit(dep["stream"])
        visiting.remove(sid)
        visited.add(sid)
    for sid in by_id:
        visit(sid)
    return data


def _ensure(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS protocol_cycles (id TEXT PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id), revision INTEGER NOT NULL, data TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS protocol_cycle_events (id INTEGER PRIMARY KEY, cycle_id TEXT NOT NULL REFERENCES protocol_cycles(id), stream_id TEXT, event TEXT NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL)")


def _connection(db_path):
    from tc.db.connection import get_db
    conn = get_db(db_path)
    _ensure(conn)
    conn.commit()
    return conn


def _load(conn, cycle):
    row = conn.execute("SELECT * FROM protocol_cycles WHERE id=?", (cycle,)).fetchone()
    if row is None:
        raise ValidationError(f"Unknown cycle: {cycle}")
    return json.loads(row["data"])


def _save(conn, data, stream, event, payload):
    from tc.services.cycle_stages import record_queue
    record_queue(conn, data)
    data["revision"] += 1
    conn.execute("UPDATE protocol_cycles SET revision=?, data=? WHERE id=?", (data["revision"], json.dumps(data, sort_keys=True), data["id"]))
    conn.execute("INSERT INTO protocol_cycle_events(cycle_id,stream_id,event,payload,created) VALUES(?,?,?,?,?)", (data["id"], stream, event, json.dumps(payload, sort_keys=True), time.time()))


def create_cycle(*, plan, db_path):
    normalized = validate_plan(plan)
    conn = _connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for task in {normalized["task"], *(s["task"] for s in normalized["streams"])}:
            if conn.execute("SELECT 1 FROM tasks WHERE id=?", (task,)).fetchone() is None:
                raise ValidationError(f"Unknown cycle task: {task}")
        prior = conn.execute("SELECT data FROM protocol_cycles WHERE id=?", (normalized["id"],)).fetchone()
        if prior:
            old = json.loads(prior["data"])
            if old["plan"] != normalized:
                raise ConflictError("Cycle id already belongs to a different plan")
            return old
        data = {"id": normalized["id"], "task": normalized["task"], "revision": 1, "plan": normalized,
                "streams": {s["id"]: {"state": "planned", "events": {}, "claim": None} for s in normalized["streams"]}, "resources": []}
        from tc.services.cycle_stages import initialize
        initialize(data, conn)
        conn.execute("INSERT INTO protocol_cycles VALUES(?,?,?,?)", (data["id"], data["task"], 1, json.dumps(data, sort_keys=True)))
        conn.execute("INSERT INTO protocol_cycle_events(cycle_id,event,payload,created) VALUES(?,?,?,?)", (data["id"], "planned", json.dumps(normalized, sort_keys=True), time.time()))
        conn.commit()
        return data
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _git(root, *args):
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise ValidationError("Git preflight failed: " + (result.stderr.strip()[:300] or " ".join(args)))
    return result.stdout.strip()


def fingerprint(root, paths):
    base = Path(root).resolve()
    files = []
    for claim in paths:
        rel = claim.removesuffix("/**")
        normalize_path(claim, base)
        path = base / rel
        candidates = sorted(path.rglob("*")) if path.is_dir() else [path]
        for candidate in candidates:
            if candidate.is_symlink() and base not in candidate.resolve().parents:
                raise ValidationError("Source symlink escapes root: " + str(candidate))
            if candidate.is_file():
                files.append((candidate.relative_to(base).as_posix(), hashlib.sha256(candidate.read_bytes()).hexdigest()))
        if not path.exists():
            files.append((rel, None))
    return hashlib.sha256(json.dumps(sorted(set(files)), sort_keys=True).encode()).hexdigest()


def _current(data, sid, event):
    state = data["streams"][sid]
    receipt = state["events"].get(event)
    if not receipt:
        return False
    artifact = receipt.get("artifactIdentity")
    if artifact:
        path = Path(artifact["path"])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
            return False
    if event in {"integrated", "accepted"}:
        stream = next(s for s in data["plan"]["streams"] if s["id"] == sid)
        if receipt.get("dependencyIdentity", {}) != _dependency_identity(data, stream):
            return False
        return receipt.get("sourceFingerprint") == fingerprint(data["plan"]["root"], stream["paths"])
    return True


def _dependency_identity(data, stream):
    result = {}
    for dep in stream["dependsOn"]:
        key = dep["stream"] + "." + dep["event"]
        if not _current(data, dep["stream"], dep["event"]):
            result[key] = None
        else:
            receipt = data["streams"][dep["stream"]]["events"][dep["event"]]
            result[key] = hashlib.sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest()
    return result


def worker_is_active(data, sid):
    """A live or unproven-stopped native claim occupies capacity in every caller."""
    return bool(data["streams"][sid].get("claim")) and not _current(data, sid, "stopped")


def ready_state(data, conn=None):
    plan = data["plan"]
    active = [sid for sid in data["streams"] if worker_is_active(data, sid)]
    by_id = {s["id"]: s for s in plan["streams"]}
    slots = max(0, plan["capacity"] - len(active))
    if conn is not None and plan.get("schemaVersion") == 2:
        slots = min(slots, _runtime_available(conn, data))
    available = slots
    counts = {}
    for sid in active:
        resource = by_id[sid]["resource"]
        counts[resource] = counts.get(resource, 0) + 1
    ready, queued = [], []
    for stream in plan["streams"]:
        sid = stream["id"]
        if data["streams"][sid]["state"] not in {"planned", "rejected", "released"}:
            continue
        from tc.services.cycle_stages import eligibility
        missing = eligibility(data, stream) + [f"{d['stream']}.{d['event']}: {d['reason']}" for d in stream["dependsOn"] if not _current(data, d["stream"], d["event"])]
        resource = stream["resource"]
        if missing:
            queued.append({"id": sid, "reason": "input", "details": missing})
        elif not available:
            queued.append({"id": sid, "reason": "worker-capacity"})
        elif counts.get(resource, 0) >= plan["resourceLimits"].get(resource, plan["capacity"]):
            queued.append({"id": sid, "reason": "resource-capacity", "resource": resource})
        else:
            ready.append(sid)
            available -= 1
            counts[resource] = counts.get(resource, 0) + 1
    return {"ready": ready, "queued": queued, "running": active,
            "stalled": [sid for sid in active if data["streams"][sid]["claim"]["leaseUntil"] < time.time()],
            "capacity": plan["capacity"], "available": slots}


def cycle_status(*, cycle, db_path):
    conn = _connection(db_path)
    try:
        data = _load(conn, cycle)
        result = {**data, **ready_state(data, conn)}
        result["stale"] = [sid for sid, state in data["streams"].items() if state["state"] in {"integrated", "accepted"} and not _current(data, sid, state["state"])]
        result["deliveryAccepted"] = all(s["state"] == "accepted" and sid not in result["stale"] for sid, s in data["streams"].items())
        if data["plan"].get("schemaVersion") == 2:
            from tc.services.cycle_stages import _check
            result["stages"] = data["stageState"]
            result["deliveryAccepted"] = _check(data)["approved"]
        result["cleanupComplete"] = not data["resources"] and not result["running"]
        task = conn.execute("SELECT prd_id FROM tasks WHERE id=?", (data["task"],)).fetchone()
        if task and task["prd_id"] is not None:
            from tc.services.prds import body_status
            result["body"] = body_status(prd_id=task["prd_id"], conn=conn)
            result["openBodyTasks"] = result["body"]["openTasks"]
        else:
            result["openBodyTasks"] = []
        return result
    finally:
        conn.close()


def _preflight(data, stream, cwd, branch):
    root = Path(data["plan"]["root"])
    actual = Path(cwd).resolve()
    expected = Path(stream.get("worktree", root)).resolve()
    if not actual.is_dir() or actual != expected:
        raise ValidationError(f"Wrong execution directory: expected {expected}, got {actual}")
    for path in stream["paths"]:
        normalize_path(path, actual)
    identity = {"cwd": str(actual), "device": actual.stat().st_dev, "inode": actual.stat().st_ino}
    if stream.get("stateful"):
        adapter = inspect_adapter(project=root)
        if not adapter["isolation"]["stateful"]:
            raise ValidationError("Stateful scope requires an explicit project isolation adapter")
        evidence = _artifact(stream.get("setupEvidence", ""), root)
        try:
            setup = json.loads(Path(evidence["path"]).read_text())
        except (OSError, ValueError) as exc:
            raise ValidationError("Stateful setup evidence must be JSON") from exc
        if setup.get("passed") is not True or setup.get("isolated") is not True or setup.get("cwd") != str(actual) or not setup.get("resources"):
            raise ValidationError("Stateful setup evidence must prove passed isolated setup, exact cwd and resource receipts")
        for resource in setup["resources"]:
            if not isinstance(resource, dict) or not resource.get("receipt"):
                raise ValidationError("Stateful setup needs explicit resource receipt paths")
            _artifact(resource["receipt"], root)
        identity["setupIdentity"] = evidence
        identity["adapterSha256"] = adapter["sourceSha256"]
    if stream["kind"] == "code" and not stream.get("readOnly"):
        expected_branch = stream["branch"]
        if branch is not None and branch != expected_branch:
            raise ValidationError("Dispatch branch disagrees with plan")
        actual_branch = _git(actual, "symbolic-ref", "--short", "HEAD")
        if actual_branch != expected_branch:
            raise ValidationError(f"Wrong branch: expected {expected_branch}, got {actual_branch}")
        common = _git(actual, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if common != _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir"):
            raise ValidationError("Worker worktree belongs to a different repository")
        identity.update(branch=actual_branch, base=_git(actual, "rev-parse", "HEAD"), commonDir=common)
    return identity


def _runtime_available(conn, data):
    """Conservative shared-runtime pool within this authoritative database."""
    active = 0
    ceiling = data['plan']['runtimeCapability']['workers']
    for row in conn.execute('SELECT data FROM protocol_cycles'):
        other = json.loads(row[0])
        if other['id'] == data['id']:
            other = data
        if other['plan']['runtime'] != data['plan']['runtime']:
            continue
        count = sum(worker_is_active(other, sid) for sid in other['streams'])
        active += count
        if count and other['plan'].get('schemaVersion') == 2:
            ceiling = min(ceiling, other['plan']['runtimeCapability']['workers'])
    return max(0, ceiling - active)


def _assert_runtime_capacity(conn, data):
    if not _runtime_available(conn, data):
        raise ConflictError('Shared runtime worker capacity is occupied; reconcile or refill after stop')


def claim_stream(*, cycle, stream, agent, cwd, branch=None, lease_seconds=900, db_path):
    _slug(agent, "agent")
    _positive(lease_seconds, "lease_seconds")
    conn = _connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        data = _load(conn, cycle)
        if stream not in data["streams"]:
            raise ValidationError("Unknown stream")
        state = data["streams"][stream]
        if state["state"] == "running":
            old = state["claim"]
            if old["agent"] == agent and old["identity"]["cwd"] == str(Path(cwd).resolve()):
                return old  # Retry never creates another lease or process.
            raise ConflictError("Stream already claimed; an expired lease is held until explicit release")
        if stream not in ready_state(data, conn)["ready"]:
            raise ConflictError("Stream is not ready or lacks capacity")
        spec = next(s for s in data["plan"]["streams"] if s["id"] == stream)
        if data["plan"].get("schemaVersion") == 2:
            from tc.services.cycle_stages import validate_task_scope
            validate_task_scope(conn, data["task"])
            validate_task_scope(conn, spec["task"], data["task"])
        if data["plan"].get("schemaVersion") == 2:
            _assert_runtime_capacity(conn, data)
        identity = _preflight(data, spec, cwd, branch)
        _assert_active_paths(conn, data, spec)
        from tc.services.execution import check_scope_authority
        check_scope_authority(conn, spec["task"])
        if not spec.get("readOnly") and any(s["state"] == "running" and s["claim"]["identity"]["cwd"] == identity["cwd"] for s in data["streams"].values()):
            raise ConflictError("Execution directory already has a writer")
        if not spec.get("readOnly"):
            for other in conn.execute("SELECT id,data FROM protocol_cycles WHERE id != ?", (cycle,)):
                other_data = json.loads(other["data"])
                specs = {s["id"]: s for s in other_data["plan"]["streams"]}
                for other_id, other_state in other_data["streams"].items():
                    other_claim = other_state.get("claim")
                    if other_claim and not specs[other_id].get("readOnly") and not _current(other_data, other_id, "stopped") and other_claim["identity"]["cwd"] == identity["cwd"]:
                        raise ConflictError("Execution directory has a live writer in another cycle")
        claim = {"agent": agent, "token": uuid.uuid4().hex, "leaseUntil": time.time() + lease_seconds, "identity": identity, "started": time.time(), "dependencyIdentity": _dependency_identity(data, spec)}
        state.update(state="running", claim=claim)
        state["events"].pop("stopped", None)
        state.pop("nativeStart", None)
        _save(conn, data, stream, "claimed", claim)
        conn.commit()
        return claim
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _artifact(path, root):
    target = Path(path)
    if not target.is_absolute():
        target = Path(root) / target
    target = target.resolve()
    if not target.is_file():
        raise ValidationError("Receipt requires an existing evidence artifact")
    return {"path": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}


def record_event(*, cycle, stream, event, receipt, db_path):
    if event not in EVENTS or not isinstance(receipt, dict):
        raise ValidationError("Unknown event or invalid receipt")
    conn = _connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        data = _load(conn, cycle)
        if stream not in data["streams"]:
            raise ValidationError("Unknown stream")
        state = data["streams"][stream]
        spec = next(s for s in data["plan"]["streams"] if s["id"] == stream)
        claim = state["claim"]
        prior = state["events"].get(event)
        if prior and all(prior.get(key) == value for key, value in receipt.items()):
            if not _current(data, stream, event):
                raise ValidationError("Existing event receipt is stale; reverify before recording")
            return {"cycle": cycle, "stream": stream, "state": state["state"], "receipt": prior, "idempotent": True}
        if event in {"contract", "built", "released", "held"}:
            if state["state"] != "running" or not claim or receipt.get("leaseToken") != claim["token"]:
                raise ConflictError("Worker event needs its current running leaseToken")
            current_identity = _preflight(data, spec, claim["identity"]["cwd"], spec.get("branch"))
            if current_identity.get("setupIdentity") != claim["identity"].get("setupIdentity") or current_identity.get("adapterSha256") != claim["identity"].get("adapterSha256"):
                raise ValidationError("Stateful setup or adapter changed during work")
        body = json.loads(json.dumps(receipt))
        body["recordedAt"] = time.time()
        if event in {"contract", "built", "accepted", "rejected"}:
            body["artifactIdentity"] = _artifact(receipt.get("artifact", ""), data["plan"]["root"])
        if event == "built":
            body["dependencyIdentity"] = _dependency_identity(data, spec)
            if body["dependencyIdentity"] != claim.get("dependencyIdentity", {}):
                raise ValidationError("Consumed input changed since claim; release and replan against fresh input")
            if any(value is None for value in body["dependencyIdentity"].values()):
                raise ValidationError("A consumed input changed or became unavailable during work")
            cwd = claim["identity"]["cwd"]
            if spec["kind"] == "code" and not spec.get("readOnly"):
                changed = set(_git(cwd, "diff", "--name-only", claim["identity"]["base"]).splitlines())
                changed.update(_git(cwd, "ls-files", "--others", "--exclude-standard").splitlines())
                for path in changed:
                    normalize_path(path, Path(cwd), literal_file=True)
                    if not any(path == p.removesuffix("/**") or path.startswith(p.removesuffix("/**") + "/") for p in spec["paths"]):
                        raise ValidationError("Worker wrote outside owned paths: " + path)
                body["tip"] = _git(cwd, "rev-parse", "HEAD")
            body["sourceFingerprint"] = fingerprint(cwd, spec["paths"])
        elif event == "integrated":
            if state["state"] != "built":
                raise ConflictError("Only built work can integrate")
            actual = fingerprint(data["plan"]["root"], spec["paths"])
            body["dependencyIdentity"] = _dependency_identity(data, spec)
            if body["dependencyIdentity"] != state["events"]["built"].get("dependencyIdentity", {}):
                raise ValidationError("Built contribution consumed stale upstream input")
            if actual != state["events"]["built"]["sourceFingerprint"]:
                raise ValidationError("Integrated sources differ from built contribution")
            if spec["kind"] == "code":
                tip = state["events"]["built"].get("tip")
                commit = receipt.get("commit")
                if not commit or _git(data["plan"]["root"], "rev-parse", commit) != _git(data["plan"]["root"], "rev-parse", "HEAD"):
                    raise ValidationError("Integration receipt must name current integration HEAD")
                if tip:
                    _git(data["plan"]["root"], "merge-base", "--is-ancestor", tip, commit)
                body["commit"] = commit
            body["sourceFingerprint"] = actual
        elif event == "accepted":
            if state["state"] != "integrated" or not _current(data, stream, "integrated"):
                raise ConflictError("Acceptance needs fresh integrated work")
            if not claim or receipt.get("agent") == claim["agent"] or not receipt.get("agent"):
                raise ValidationError("Acceptance needs an independent reviewer")
            actual = fingerprint(data["plan"]["root"], spec["paths"])
            if receipt.get("sourceFingerprint") != actual or receipt.get("verdict") != "approved":
                raise ValidationError("Acceptance receipt has stale sources or a failing verdict")
            from tc.services.qa import check_task_qa, task_metadata
            from tc.services.tasks import get_task
            task = get_task(task_id=spec["task"], conn=conn)
            if task_metadata(task["metadata"]).get("requiresQa"):
                qa = check_task_qa(task_id=spec["task"], conn=conn)
                if not qa["approved"]:
                    raise ValidationError("Existing task QA gate has not approved this scope: " + qa["reason"])
                body["qaWorkProduct"] = qa["work_product_id"]
            body["sourceFingerprint"] = actual
            body["dependencyIdentity"] = _dependency_identity(data, spec)
        elif event == "stopped":
            if not claim or receipt.get("leaseToken") != claim["token"] or receipt.get("stopped") is not True:
                raise ValidationError("Stopped receipt needs current leaseToken and stopped=true")
            body["artifactIdentity"] = _artifact(receipt.get("artifact", ""), data["plan"]["root"])
            if state["state"] == "running":
                state["state"] = "released"
        elif event == "released":
            if receipt.get("stopped") is not True:
                raise ValidationError("Release requires observed native shutdown; use stopped=true and an artifact")
            body["artifactIdentity"] = _artifact(receipt.get("artifact", ""), data["plan"]["root"])
            state["events"]["stopped"] = body
        elif event == "rejected":
            if state["state"] not in {"built", "integrated", "accepted"}:
                raise ConflictError("Only completed contributions can be rejected")
        elif event == "teardown":
            if receipt.get("passed") is not True or not receipt.get("command"):
                raise ValidationError("Teardown needs command and passed=true evidence")
            body["artifactIdentity"] = _artifact(receipt.get("artifact", ""), data["plan"]["root"])
        if data['plan'].get('schemaVersion') == 2 and event in {'stopped', 'released'} and claim and claim.get('executionToken'):
            from tc.services import cycle_stages as stages
            from tc.services import execution
            checks = [r for r in data['plan']['checks'] if r['stream'] == stream and r['required']]
            succeeded = bool(state.get('nativeStart') and checks and all(stages.result_current(data, r) and data['checkResults'][r['id']]['outcome'] == 'passed' for r in checks))
            body['executionSettlement'] = execution.settle_attempt(token=claim['executionToken'], succeeded=succeeded,
                artifact=body['artifactIdentity']['path'], reason='Observed native stop with current complete results' if succeeded else 'Stopped without complete passing result evidence', conn=conn)
        state["events"][event] = body
        if event not in {"contract", "teardown", "stopped"}:
            state["state"] = {"released": "released", "held": "held"}.get(event, event)
        if event == "rejected":
            # Keep original evidence in the event journal, but no stale contract
            # may unlock downstream work during a repair.
            stopped = state["events"].get("stopped")
            state["events"] = {"rejected": body, **({"stopped": stopped} if stopped else {})}
        _save(conn, data, stream, event, body)
        conn.commit()
        return {"cycle": cycle, "stream": stream, "state": state["state"], "receipt": body}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def prepare_worktree(*, cycle, stream, db_path):
    """Create only the planned new worktree/branch and record identity; never removes it."""
    conn = _connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        data = _load(conn, cycle)
        spec = next((s for s in data["plan"]["streams"] if s["id"] == stream), None)
        if not spec or spec.get("readOnly") or spec["kind"] != "code":
            raise ValidationError("prepare is only for planned code writer worktrees")
        path = Path(spec["worktree"])
        if path.exists():
            raise ConflictError("prepare refuses existing paths; never adopts another worktree")
        root = data["plan"]["root"]
        # New branch creation is atomic at Git, and refuses an existing branch.
        _git(root, "worktree", "add", "-b", spec["branch"], str(path), "HEAD")
        identity = _preflight(data, spec, path, spec["branch"])
        resource = {"kind": "worktree", "stream": stream, "path": str(path), "branch": spec["branch"], "createdBy": cycle,
                    "creationIdentity": identity, "receipt": uuid.uuid4().hex, "createdAt": time.time()}
        data["resources"].append(resource)
        _save(conn, data, stream, "resource-created", resource)
        conn.commit()
        return resource
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _evidence_consumers(path, db_path):
    """Current receipt artifacts, stored work products and bound task roots keep a tree live."""
    candidate = path.resolve()
    def inside(value):
        target = Path(value).resolve()
        return target == candidate or candidate in target.parents
    consumers = []
    conn = _connection(db_path)
    try:
        for row in conn.execute("SELECT id,data FROM protocol_cycles"):
            other = json.loads(row["data"])
            for sid, state in other["streams"].items():
                for event, receipt in state["events"].items():
                    artifact = receipt.get("artifactIdentity", {})
                    if artifact.get("path") and inside(artifact["path"]):
                        consumers.append(f"{row['id']}.{sid}.{event} evidence")
        for row in conn.execute("SELECT id,file_path FROM work_products WHERE file_path IS NOT NULL"):
            value = Path(row["file_path"])
            if not value.is_absolute():
                value = Path(db_path).resolve().parent.parent / value
            if inside(value):
                consumers.append(f"work product {row['id']}")
        from tc.services.qa_contract import execution_root
        for row in conn.execute("SELECT id FROM tasks"):
            try:
                root = execution_root(row["id"], conn)
            except (OSError, ValidationError):
                continue
            if root and inside(root):
                consumers.append(f"task {row['id']} bound execution root")
    finally:
        conn.close()
    return consumers


def cleanup_plan(*, cycle, db_path):
    """Read-only exact retirement packet. Eligibility never grants deletion authority."""
    data = cycle_status(cycle=cycle, db_path=db_path)
    eligible, held = [], []
    for resource in data["resources"]:
        reasons = []
        sid = resource["stream"]
        state = data["streams"][sid]
        path = Path(resource["path"])
        if worker_is_active(data, sid):
            reasons.append("worker still active (including expired lease)")
        if not path.is_dir():
            reasons.append("path missing or identity drifted")
        else:
            current = path.stat()
            old = resource["creationIdentity"]
            if (current.st_dev, current.st_ino) != (old["device"], old["inode"]):
                reasons.append("path identity drifted")
            try:
                if _git(path, "symbolic-ref", "--short", "HEAD") != resource["branch"]:
                    reasons.append("branch identity drifted")
                if _git(path, "status", "--porcelain", "--untracked-files=all") or _git(path, "ls-files", "--others", "--ignored", "--exclude-standard"):
                    reasons.append("tracked, untracked or ignored content remains")
                tip = _git(path, "rev-parse", "HEAD")
                built = state["events"].get("built", {})
                if tip != built.get("tip"):
                    reasons.append("branch tip changed after built receipt")
                _git(data["plan"]["root"], "merge-base", "--is-ancestor", tip, "HEAD")
            except ValidationError:
                reasons.append("unique/unmerged work or Git identity unavailable")
        if not _current(data, sid, "accepted"):
            reasons.append("current acceptance missing")
        if not _current(data, sid, "stopped"):
            reasons.append("native worker shutdown not verified")
        if not _current(data, sid, "teardown"):
            reasons.append("project teardown not verified")
        if path.resolve() == Path(data["plan"]["root"]).resolve() or path.resolve() == Path.cwd().resolve() or path.resolve() in Path.cwd().resolve().parents:
            reasons.append("coordinator or integration checkout")
        evidence_consumers = _evidence_consumers(path, db_path)
        if evidence_consumers:
            reasons.append("required evidence or bound task consumers: " + ",".join(evidence_consumers))
        consumers = _active_consumers(path) if path.is_dir() else ["path unavailable"]
        if consumers:
            reasons.append("active consumers or unavailable process inspection: " + ",".join(consumers))
        entry = {**resource, "recovery": "Git branch and integrated commit; recheck active external consumers before exact approval", "requiresExactApproval": False, "branchDisposition": "preserved"}
        (held if reasons else eligible).append({**entry, **({"reasons": reasons} if reasons else {})})
    return {"cycle": cycle, "eligible": eligible, "held": held, "deleted": [], "authority": "Owner-authorized automatic eligible merged-worktree retirement; branches preserved", "externalConsumerCheckRequired": True}


def smoke_roles(*, roles=None, out=None):
    """Provider-free actual process lifecycle probe; does not impersonate native model dispatch."""
    selected = list(dict.fromkeys(roles or DEFAULT_ROLES))
    if not selected:
        raise ValidationError("At least one role required")
    for role in selected:
        _slug(role, "role")
    # All workers handshake before coordinator releases them; observed overlap
    # is deterministic rather than inferred from timing or sleep estimates.
    code = "import json,os,sys,time; print(json.dumps({'role':sys.argv[1],'pid':os.getpid(),'ready':True}),flush=True); sys.stdin.readline(); print(json.dumps({'role':sys.argv[1],'stopped':True}),flush=True)"
    processes, receipts = [], []
    started = time.monotonic()
    try:
        for role in selected:
            processes.append((role, subprocess.Popen([sys.executable, "-u", "-c", code, role], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)))
        for role, process in processes:
            receipt = json.loads(process.stdout.readline())
            if receipt.get("role") != role or not receipt.get("ready") or process.poll() is not None:
                raise ValidationError("Lifecycle worker failed readiness handshake")
            receipts.append(receipt)
        overlap = sum(process.poll() is None for _, process in processes)
        for _, process in processes:
            process.stdin.write("release\n")
            process.stdin.flush()
        for role, process in processes:
            stdout, stderr = process.communicate(timeout=10)
            if process.returncode or not json.loads(stdout).get("stopped"):
                raise ValidationError("Lifecycle worker failed shutdown: " + role + stderr)
        result = {"status": "passed", "mode": "provider-free-process-lifecycle", "nativeAgentDispatch": False, "paidCalls": 0, "tokens": 0,
                  "roles": selected, "workers": receipts, "overlap": overlap, "stopped": len(processes), "residualProcesses": sum(p.poll() is None for _, p in processes),
                  "elapsedSeconds": round(time.monotonic() - started, 4), "persistentResourcesCreated": [], "deleted": []}
        if overlap != len(selected):
            raise ValidationError("Lifecycle workers did not overlap")
        if out:
            target = Path(out)
            if target.exists():
                raise ConflictError("Smoke output exists; choose a new evidence path")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(result, indent=2) + "\n")
        return result
    finally:
        for _, process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def verify_dispatch(*, cycle, stream, role, cwd, blocked_task=None, blocked_tasks=None, db_path):
    """Validate and consume a single-use dispatch permit (not a completion receipt)."""
    conn = _connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        data = _load(conn, cycle)
        state = data["streams"].get(stream)
        spec = next((s for s in data["plan"]["streams"] if s["id"] == stream), None)
        if not spec or spec["role"] != role or not state or state["state"] != "running":
            raise ValidationError("Dispatch has no matching running role/scope claim")
        if spec["task"] in set(blocked_tasks or []) | ({blocked_task} if blocked_task is not None else set()):
            raise ValidationError("Pending-QA builder cannot consume its own unrelated-work permit")
        claim = state["claim"]
        if claim["leaseUntil"] < time.time() or claim.get("dispatchAuthorized"):
            raise ConflictError("Dispatch lease expired or its permit was already consumed")
        identity = _preflight(data, spec, cwd, spec.get("branch"))
        if identity["cwd"] != claim["identity"]["cwd"] or identity["inode"] != claim["identity"]["inode"] or identity.get("setupIdentity") != claim["identity"].get("setupIdentity") or identity.get("adapterSha256") != claim["identity"].get("adapterSha256"):
            raise ValidationError("Dispatch execution-root identity drifted")
        if data['plan'].get('schemaVersion') == 2:
            from tc.services import cycle_stages as stages
            from tc.services import execution
            reasons = stages.eligibility(data, spec)
            if reasons:
                raise ConflictError('Dispatch stage no longer ready: ' + '; '.join(reasons))
            stages.validate_task_scope(conn, data['task'])
            stages.validate_task_scope(conn, spec['task'], data['task'])
            if _dependency_identity(data, spec) != claim['dependencyIdentity'] or identity.get('base') != claim['identity'].get('base'):
                raise ConflictError('Claimed input changed before dispatch')
            checks = [r for r in data['plan']['checks'] if r['stream'] == stream and r['required']]
            if any(stages.binding(data, r) != data['bindings'][r['id']] for r in checks):
                raise ConflictError('Frozen case source changed before dispatch')
            criteria = {r['criterion'] for r in checks}
            criterion = spec.get('criterion') or (next(iter(criteria)) if len(criteria) == 1 else None)
            if not criterion or (criteria and criterion not in criteria):
                raise ValidationError('Stream requires one explicit registered execution criterion')
            attempt = execution.begin_attempt(task_id=spec['task'], criterion=criterion,
                                              label=f"cycle {cycle}/{stream} generation {data['generation']}",
                                              work_identity=[stages._digest({"rootTask": stages.governing_task(conn, data["task"]), "check": r["id"]}) for r in checks], conn=conn)
            claim['executionToken'] = attempt['token']
            claim['executionCriterion'] = criterion
        claim["dispatchAuthorized"] = True
        result = {"allowed": True, "cycle": cycle, "stream": stream, "role": role, "task": spec["task"], "cwd": identity["cwd"], "leaseToken": claim["token"], "runtime": data["plan"]["runtime"]}
        _save(conn, data, stream, "dispatch-authorized", result)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _active_consumers(path):
    executable = shutil.which("lsof")
    if not executable:
        return ["lsof-unavailable"]
    try:
        result = subprocess.run([executable, "-t", "+D", str(path)], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return ["process-inspection-failed"]
    if result.stderr.strip() or result.returncode not in {0, 1}:
        return ["process-inspection-incomplete"]
    return sorted(set(result.stdout.split()))


def cleanup_cycle(*, cycle, db_path):
    """Execute the owner's narrow merged-worktree cleanup authority, never branch deletion."""
    packet = cleanup_plan(cycle=cycle, db_path=db_path)
    removed, held = [], list(packet["held"])
    for candidate in packet["eligible"]:
        conn = _connection(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            data = _load(conn, cycle)
            # Recheck every eligibility condition after acquiring the mutation
            # lock. Other sessions cannot claim or change this cycle mid-remove.
            fresh = cleanup_plan(cycle=cycle, db_path=db_path)
            eligible = next((r for r in fresh["eligible"] if r["receipt"] == candidate["receipt"]), None)
            if eligible is None:
                held.extend(r for r in fresh["held"] if r["receipt"] == candidate["receipt"])
                continue
            path = Path(eligible["path"])
            identity = eligible["creationIdentity"]
            if _git(path, "rev-parse", "--path-format=absolute", "--git-common-dir") != identity["commonDir"]:
                raise ValidationError("Worktree repository identity drifted")
            _git(data["plan"]["root"], "worktree", "remove", str(path))  # Never --force; branch remains recovery.
            if path.exists():
                raise ValidationError("Git did not remove the eligible worktree")
            data["resources"] = [r for r in data["resources"] if r["receipt"] != eligible["receipt"]]
            receipt = {"path": str(path), "branch": eligible["branch"], "branchPreserved": True, "creationReceipt": eligible["receipt"], "retiredAt": time.time()}
            data.setdefault("retiredResources", []).append(receipt)
            _save(conn, data, eligible["stream"], "resource-retired", receipt)
            conn.commit()
            removed.append(receipt)
        except (ValidationError, OSError) as exc:
            conn.rollback()
            held.append({**candidate, "reasons": [str(exc)]})
        finally:
            conn.close()
    return {"cycle": cycle, "removed": removed, "held": held, "branchesDeleted": [], "cleanupComplete": not held and cycle_status(cycle=cycle, db_path=db_path)["cleanupComplete"]}


def finish_cycle(*, cycle, db_path):
    from tc.services.cycle_stages import check_cycle
    initial = cycle_status(cycle=cycle, db_path=db_path)
    if initial["plan"].get("schemaVersion") == 2:
        checked = check_cycle(cycle=cycle, db_path=db_path)
        if not checked["approved"]:
            raise ValidationError("Stage gate: " + "; ".join(checked["reasons"]))
    """Close the PRD only after current acceptance, cleanup, and every body task resolves."""
    status = cycle_status(cycle=cycle, db_path=db_path)
    if not status["deliveryAccepted"] or not status["cleanupComplete"]:
        raise ConflictError("Cycle finish requires current acceptance and completed resource cleanup")
    if "body" not in status:
        raise ValidationError("Cycle task has no PRD body to finish")
    from tc.services.prds import update_prd
    result = update_prd(prd_id=status["body"]["prd"], status="completed", db_path=db_path)
    return {"cycle": cycle, "prd": result["id"], "status": result["status"], "openTasks": [], "historyPreserved": True}


def inspect_adapter(*, project):
    """Read a project-owned worktree contract once; discovery never executes commands."""
    root = Path(project).resolve()
    if not root.is_dir():
        raise ValidationError("Adapter project must be an existing directory")
    phases = {"setup", "readiness", "focused", "integration", "teardown"}
    descriptor = root / ".copilot/worktree-adapter.json"
    result = {"schemaVersion": 1, "project": str(root), "source": "filesystem-default", "commands": {phase: [] for phase in sorted(phases)},
              "isolation": {"filesystem": True, "stateful": False, "details": "Separate Git worktrees isolate files only; no database, browser, port or credential isolation is inferred."},
              "requiresSetupEvidence": False, "executed": []}
    if descriptor.exists():
        if descriptor.is_symlink() or root not in descriptor.resolve().parents:
            raise ValidationError("Adapter descriptor must be an in-project regular file")
        try:
            raw = json.loads(descriptor.read_text())
        except (OSError, ValueError) as exc:
            raise ValidationError("Malformed worktree adapter JSON") from exc
        if not isinstance(raw, dict) or raw.get("schemaVersion") != 1 or not isinstance(raw.get("commands"), dict):
            raise ValidationError("Worktree adapter needs schemaVersion 1 and commands object")
        for phase, command in raw["commands"].items():
            if phase not in phases or not isinstance(command, list) or any(not isinstance(arg, str) or not arg or "\0" in arg for arg in command):
                raise ValidationError("Adapter commands are phase -> argv arrays, never shell strings")
            result["commands"][phase] = command
        isolation = raw.get("isolation")
        if not isinstance(isolation, dict) or not isinstance(isolation.get("stateful"), bool) or not isinstance(isolation.get("details"), str) or not isolation["details"].strip():
            raise ValidationError("Adapter needs an explicit isolation.stateful boolean and details")
        result.update(source=str(descriptor), sourceSha256=hashlib.sha256(descriptor.read_bytes()).hexdigest(), isolation={"filesystem": True, **isolation}, requiresSetupEvidence=isolation["stateful"])
    else:
        package = root / "package.json"
        if package.is_file():
            try:
                raw = json.loads(package.read_text())
            except (OSError, ValueError) as exc:
                raise ValidationError("Malformed package.json while discovering adapter defaults") from exc
            scripts = raw.get("scripts", {}) if isinstance(raw, dict) else {}
            if isinstance(scripts, dict):
                detected = []
                for phase in ("setup", "teardown"):
                    name = "worktree:" + phase
                    if isinstance(scripts.get(name), str):
                        result["commands"][phase] = ["npm", "run", name]
                        detected.append(name)
                if detected:
                    result.update(source="package-scripts", sourceSha256=hashlib.sha256(package.read_bytes()).hexdigest(), detectedScripts=detected)
    return result


def _repository_identity(root):
    try:
        return _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    except ValidationError:
        return str(Path(root).resolve())


def _assert_active_paths(conn, data, spec):
    if spec.get("readOnly"):
        return
    identity = _repository_identity(data["plan"]["root"])
    for row in conn.execute("SELECT data FROM protocol_cycles"):
        other = json.loads(row[0])
        if _repository_identity(other["plan"]["root"]) != identity:
            continue
        for peer in other["plan"]["streams"]:
            if other["id"] == data["id"] and peer["id"] == spec["id"]:
                continue
            if not peer.get("readOnly") and worker_is_active(other, peer["id"]) and any(paths_overlap(a, b) for a in spec["paths"] for b in peer["paths"]):
                raise ConflictError("Active writer owns overlapping canonical repository paths")
