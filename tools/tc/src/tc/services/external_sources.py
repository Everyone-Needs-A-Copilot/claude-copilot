"""Cross-repository acceptance sources for schemaVersion 3 contracts.

A per-database registry maps a repo id to a local git checkout and its origin
URL. Scoped paths are hashed from git objects at the commit a ref resolves to,
so uncommitted work in the other checkout is invisible by construction. Only
local, read-only git plumbing runs (rev-parse, ls-tree, cat-file, remote
get-url); nothing here fetches, pulls, clones or contacts a remote.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from tc.db.exceptions import ValidationError

_TABLE = "CREATE TABLE IF NOT EXISTS source_repos (id TEXT PRIMARY KEY, path TEXT NOT NULL, remote TEXT NOT NULL, registered_at TEXT NOT NULL)"
_REPO_ID = re.compile(r"[A-Za-z0-9._-]{1,100}")
_HEX = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_GIT = ("git", "-c", "core.fsmonitor=false", "--no-optional-locks", "--literal-pathspecs")
_MODES = {"100644": False, "100755": True}
MAX_FILES = 10000
MAX_BYTES = 256 * 1024 * 1024
MAX_FILE = 20 * 1024 * 1024
_MAX_LISTING = 4 * 1024 * 1024
_IGNORED = {".git", ".copilot", "__pycache__", ".pytest_cache", ".venv", "node_modules"}


class Budget:
    """File and byte caps shared by local and external scopes of one capture."""

    def __init__(self):
        self.files = 0
        self.bytes = 0

    def add(self, files: int, size: int) -> None:
        self.files += files
        self.bytes += size
        if self.files > MAX_FILES:
            raise ValidationError("QA source inventory exceeds limit")
        if self.bytes > MAX_BYTES:
            raise ValidationError("QA source bytes exceed limit")


def _git(cwd: Path, *args: str, input: bytes | None = None, timeout: int = 10) -> bytes:
    # Ambient GIT_* variables (GIT_DIR, GIT_INDEX_FILE, ...) must not redirect the read.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        done = subprocess.run([*_GIT, *args], cwd=cwd, input=input, capture_output=True, timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValidationError(f"git is unavailable or failed for an external source: {type(exc).__name__}") from exc
    if done.returncode != 0:
        raise ValidationError(f"git {args[0]} failed for an external source: {done.stderr.decode(errors='replace').strip()[:200]}")
    return done.stdout


def _checkout(path: Path) -> tuple[Path, str]:
    """Verify `path` is the top level of a git work tree with an origin; return (path, origin URL)."""
    if path.is_symlink() or not path.is_dir():
        raise ValidationError(f"Repository path is missing or a symlink: {path}")
    resolved = path.resolve()
    try:
        top = Path(os.fsdecode(_git(resolved, "rev-parse", "--show-toplevel").strip())).resolve()
    except ValidationError as exc:
        raise ValidationError(f"Not a git work tree: {path}") from exc
    if top != resolved:
        raise ValidationError(f"Path must be the top level of a git work tree: {path}")
    try:
        remote = os.fsdecode(_git(resolved, "remote", "get-url", "origin")).strip()
    except ValidationError as exc:
        raise ValidationError(f"Repository has no origin remote: {path}") from exc
    if not remote:
        raise ValidationError(f"Repository has no origin remote: {path}")
    return resolved, remote


def _ensure(conn) -> None:
    conn.execute(_TABLE)


def _has_table(conn) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_repos'").fetchone() is not None


def add_repo(*, repo_id: str, path, db_path=None) -> dict:
    from tc.services.tasks import _open_conn, _require_db_path

    if not isinstance(repo_id, str) or not _REPO_ID.fullmatch(repo_id):
        raise ValidationError("Repo ids use 1-100 letters, digits, dot, underscore or hyphen")
    resolved, remote = _checkout(Path(path))
    conn = _open_conn(_require_db_path(db_path))
    try:
        conn.execute("BEGIN IMMEDIATE")
        _ensure(conn)
        old = conn.execute("SELECT remote, registered_at FROM source_repos WHERE id=?", (repo_id,)).fetchone()
        if old and old[0] != remote:
            raise ValidationError(f"Repo '{repo_id}' is registered with a different origin; refusing to repoint it")
        registered = old[1] if old else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute("INSERT OR REPLACE INTO source_repos (id, path, remote, registered_at) VALUES (?,?,?,?)",
                     (repo_id, str(resolved), remote, registered))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"id": repo_id, "path": str(resolved), "remote": remote, "registered_at": registered}


def list_repos(*, db_path=None) -> list[dict]:
    from tc.services.tasks import _open_conn, _require_db_path

    conn = _open_conn(_require_db_path(db_path))
    try:
        if not _has_table(conn):
            return []
        rows = conn.execute("SELECT id, path, remote, registered_at FROM source_repos ORDER BY id").fetchall()
        return [{"id": r[0], "path": r[1], "remote": r[2], "registered_at": r[3]} for r in rows]
    finally:
        conn.close()


def _registered(conn, repo_id: str) -> tuple[str, str]:
    row = conn.execute("SELECT path, remote FROM source_repos WHERE id=?", (repo_id,)).fetchone() if _has_table(conn) else None
    if row is None:
        raise ValidationError(f"External repo '{repo_id}' is not registered; run tc repo add {repo_id} --path <checkout>")
    return row[0], row[1]


def _scoped(name: str, scopes: list[str]) -> bool:
    return any(s == "." or name == s or name.startswith(s + "/") for s in scopes)


def _listing(path: Path, commit: str, scopes: list[str]) -> list[tuple[str, str, str, int]]:
    args = ["ls-tree", "-r", "-z", "--long", commit]
    if "." not in scopes:
        args += ["--", *scopes]
    out = _git(path, *args, timeout=30)
    if len(out) > _MAX_LISTING:
        raise ValidationError("QA source inventory exceeds limit")
    entries = []
    for chunk in out.split(b"\0"):
        if not chunk:
            continue
        meta, _, raw = chunk.partition(b"\t")
        fields = meta.decode().split()
        name = os.fsdecode(raw)
        if len(fields) != 4 or any(p in _IGNORED for p in PurePosixPath(name).parts) or not _scoped(name, scopes):
            continue
        mode, kind, oid, size = fields
        if mode not in _MODES or kind != "blob":
            raise ValidationError(f"Unsupported external source entry (symlink or submodule): {name}")
        if int(size) > MAX_FILE:
            raise ValidationError(f"Unsupported or oversized QA source: {name}")
        entries.append((name, mode, oid, int(size)))
        if len(entries) > MAX_FILES:
            raise ValidationError("QA source inventory exceeds limit")
    return entries


def _blobs(path: Path, oids: list[str]) -> list[bytes]:
    if not oids:
        return []
    out = _git(path, "cat-file", "--batch", input=("\n".join(oids) + "\n").encode(), timeout=120)
    blobs, pos = [], 0
    for oid in oids:
        end = out.find(b"\n", pos)
        header = out[pos:end].split() if end >= 0 else []
        if len(header) != 3 or header[0].decode() != oid or header[1] != b"blob":
            raise ValidationError("Unexpected git object while reading an external source")
        size, pos = int(header[2]), end + 1
        blobs.append(out[pos:pos + size])
        if len(blobs[-1]) != size or out[pos + size:pos + size + 1] != b"\n":
            raise ValidationError("Truncated git object while reading an external source")
        pos += size + 1
    return blobs


def resolve(conn, entry: dict) -> dict:
    """Locate the registered checkout, verify its origin and resolve the ref to a commit."""
    raw_path, remote = _registered(conn, entry["repo"])
    path, current = _checkout(Path(raw_path))
    if current != remote:
        raise ValidationError(f"External repo '{entry['repo']}' origin changed since registration; re-run tc repo add")
    try:
        commit = _git(path, "rev-parse", "--verify", "--quiet", "--end-of-options", entry["ref"] + "^{commit}").decode().strip()
    except ValidationError as exc:
        raise ValidationError(f"External ref '{entry['ref']}' does not resolve in repo '{entry['repo']}'") from exc
    if not _HEX.fullmatch(commit):
        raise ValidationError("External ref did not resolve to a commit")
    return {"path": path, "remote": remote, "commit": commit}


def manifest(path: Path, commit: str, scopes: list[str], budget: Budget) -> list[dict]:
    """Records shaped like local ones: path, kind, sha256 and executable bit, plus directory/missing markers."""
    entries = _listing(path, commit, scopes)
    blobs = _blobs(path, [oid for _, _, oid, _ in entries])
    records = {}
    for (name, mode, _, size), payload in zip(entries, blobs):
        if len(payload) != size:
            raise ValidationError(f"QA source changed during capture: {name}")
        records[name] = {"path": name, "kind": "file", "sha256": hashlib.sha256(payload).hexdigest(), "executable": _MODES[mode]}
    files = sorted(records)
    for scope in scopes:
        if scope not in records:
            nested = scope == "." or any(n.startswith(scope + "/") for n in files)
            records[scope] = {"path": scope, "kind": "directory" if nested else "missing"}
    if not files:
        raise ValidationError("QA source scope contains no materialized files")
    budget.add(len(records), sum(size for *_, size in entries))
    return [records[k] for k in sorted(records)]
