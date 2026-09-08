"""Task acceptance binding and bounded, content-based QA identities.

Receipts establish identity and coverage, never the truth of an observation.
No command supplied in evidence is executed. Filesystem ownership remains with
the reviewer through capture, verification and completion; no OS-wide lock is
claimed by the SQLite completion transaction.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath

from tc.db.exceptions import ValidationError

CONTRACT_VERSION = 2
_IGNORED = {".git", ".copilot", "__pycache__", ".pytest_cache", ".venv", "node_modules"}
_MAX_FILES = 10000
_MAX_BYTES = 256 * 1024 * 1024


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def validate_contract(contract: dict) -> dict:
    if not isinstance(contract, dict) or contract.get("schemaVersion") != CONTRACT_VERSION:
        raise ValidationError("Register a schemaVersion 2 acceptanceContract with tc task contract")
    criteria, sources = contract.get("criteria"), contract.get("sources")
    if not isinstance(criteria, list) or not 1 <= len(criteria) <= 100:
        raise ValidationError("Acceptance contract requires 1–100 criteria")
    ids = set()
    for criterion in criteria:
        if not isinstance(criterion, dict):
            raise ValidationError("Acceptance criterion must be an object")
        cid, expected = criterion.get("id"), criterion.get("expected")
        if not isinstance(cid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", cid) or cid in ids:
            raise ValidationError("Acceptance criteria require unique simple IDs")
        if not isinstance(expected, str) or not expected.strip() or len(expected) > 12000 or any(c in expected for c in "\n\r"):
            raise ValidationError("Each criterion needs a nonempty, single-line expected behavior")
        if expected != expected.strip():
            raise ValidationError("Expected behavior must not contain surrounding whitespace")
        ids.add(cid)
    if not isinstance(sources, list) or not 1 <= len(sources) <= 100:
        raise ValidationError("Acceptance contract requires 1–100 source files/directories")
    for name in sources:
        if not isinstance(name, str) or not name or len(name) > 1024 or any(c in name for c in "\0\n\r\\"):
            raise ValidationError("Invalid source path")
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or any(p in _IGNORED for p in path.parts) or str(path) != name:
            raise ValidationError("Source paths must be canonical project-relative paths outside runtime state")
    if len(set(sources)) != len(sources):
        raise ValidationError("Duplicate source paths")
    return contract


def database_path(conn) -> Path:
    for row in conn.execute("PRAGMA database_list"):
        if row[1] == "main" and row[2]:
            path = Path(row[2]).resolve()
            if path.parent.name != ".copilot":
                raise ValidationError("QA identity requires a project .copilot database")
            return path
    raise ValidationError("QA identity requires a persistent project database")


def _safe_path(root: Path, name: str) -> Path:
    path = root
    for part in PurePosixPath(name).parts:
        path = path / part
        if path.is_symlink():
            raise ValidationError(f"QA source cannot traverse a symlink: {name}")
    if not path.resolve().is_relative_to(root):
        raise ValidationError("QA source escaped project root")
    return path


def source_manifest(root: Path, scopes: list[str]) -> list[dict]:
    """Capture explicit scopes, including tracked deletions and new files.

    Git supplies ignored-file semantics when the project is its own repository.
    Plain directories remain supported for disposable projects. Missing explicit
    paths are recorded, never silently omitted. No file contents leave this API.
    """
    names = set(scopes)
    try:
        probe = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=root, capture_output=True, timeout=5)
        is_repo = probe.returncode == 0 and Path(os.fsdecode(probe.stdout.strip())).resolve() == root
        if is_repo:
            result = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root, capture_output=True, timeout=10, check=True)
            if len(result.stdout) > 4 * 1024 * 1024:
                raise ValidationError("QA source inventory exceeds limit")
            for raw in result.stdout.split(b"\0"):
                if not raw:
                    continue
                name = os.fsdecode(raw)
                if not any(p in _IGNORED for p in PurePosixPath(name).parts) and any(s == "." or name == s or name.startswith(s + "/") for s in scopes):
                    names.add(name)
        else:
            for scope in scopes:
                path = _safe_path(root, scope)
                if path.is_dir():
                    for directory, dirs, files in os.walk(path, followlinks=False):
                        dirs[:] = sorted(d for d in dirs if d not in _IGNORED)
                        for name in dirs + files:
                            names.add((Path(directory) / name).relative_to(root).as_posix())
                        if len(names) > _MAX_FILES:
                            raise ValidationError("QA source inventory exceeds limit")
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValidationError("Unable to inventory QA sources") from exc
    if len(names) > _MAX_FILES:
        raise ValidationError("QA source inventory exceeds limit")
    records, total = [], 0
    for name in sorted(names):
        path = _safe_path(root, name)
        if not path.exists():
            records.append({"path": name, "kind": "missing"})
            continue
        before = path.stat()
        if stat.S_ISDIR(before.st_mode):
            records.append({"path": name, "kind": "directory"})
            continue
        if not stat.S_ISREG(before.st_mode) or before.st_size > 20 * 1024 * 1024:
            raise ValidationError(f"Unsupported or oversized QA source: {name}")
        total += before.st_size
        if total > _MAX_BYTES:
            raise ValidationError("QA source bytes exceed limit")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(path, flags), "rb") as handle:
            opened = os.fstat(handle.fileno())
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise ValidationError("QA source changed while opening")
            payload = handle.read(20 * 1024 * 1024 + 1)
            after = os.fstat(handle.fileno())
        current = path.stat()
        if len(payload) != before.st_size or (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValidationError("QA source changed during capture")
        records.append({"path": name, "kind": "file", "sha256": hashlib.sha256(payload).hexdigest(), "executable": bool(before.st_mode & 0o111)})
    if not any(r["kind"] == "file" for r in records):
        raise ValidationError("QA source scope contains no materialized files")
    return records


def bound_contract(task: dict, conn) -> dict:
    from tc.services.qa import task_metadata
    contract = validate_contract(task_metadata(task["metadata"]).get("acceptanceContract"))
    return {"database": str(database_path(conn)), "task_id": task["id"], "title": task["title"], "description": task["description"], "contract": contract}


def capture_for_task(task: dict, conn) -> dict:
    bound = bound_contract(task, conn)
    root = database_path(conn).parent.parent
    sources = source_manifest(root, bound["contract"]["sources"])
    package = Path(__file__).resolve().parents[1]
    runtime = {p.relative_to(package).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(package.rglob("*.py"))}
    identity = {"schemaVersion": CONTRACT_VERSION, "database": bound["database"], "task_id": task["id"],
                "contract_sha256": digest(bound), "source_sha256": digest(sources), "source_count": len(sources),
                "runtime": {"python": sys.version, "executable": str(Path(sys.executable).absolute()), "tc_sha256": digest(runtime)}}
    return {"identity": identity, "sources": sources, "identity_line": "IDENTITY: " + json.dumps(identity, sort_keys=True, separators=(",", ":"))}


def capture_qa_identity(*, task_id: int, conn=None, db_path=None) -> dict:
    from tc.services.tasks import get_task, _open_conn, _require_db_path
    owns = conn is None
    if owns:
        conn = _open_conn(_require_db_path(db_path))
    try:
        return capture_for_task(get_task(task_id=task_id, conn=conn), conn)
    finally:
        if owns:
            conn.close()


def binding_errors(task: dict, conn, packet: dict) -> list[str]:
    try:
        bound = bound_contract(task, conn)
        expected = {c["id"]: c["expected"] for c in bound["contract"]["criteria"]}
        records = packet["records"]
        if len(records) != len(expected) or {r["criterion"] for r in records} != set(expected):
            return ["Evidence must cover exactly this task's acceptance criterion IDs"]
        if any(r["expected"] != expected[r["criterion"]] for r in records):
            return ["Evidence expected behavior differs from the task acceptance contract"]
        recorded = json.loads(packet.get("identity") or "null")
        if recorded != capture_for_task(task, conn)["identity"]:
            return ["QA identity is stale or belongs to a different task, contract, source or runtime"]
        return []
    except (ValidationError, OSError, ValueError, TypeError) as exc:
        return [str(exc)]
