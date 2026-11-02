"""Verification tiers: T1 copy, T2 structural, T3 foundational.

A task records one tier (``metadata.verificationTier``). Untiered tasks are T3.
The tier can only rise: a diff classifier computes the minimum tier a change
needs and ``attest`` refuses to approve below it; lowering a recorded tier needs
the owner's verbatim words (``authority``), stored in an append-only history.

T1 and T2 are approved by ``attest``: tc reads the evidence the implementer
points at (text present/absent in a built file, render artifacts, a stored
``cc verify`` status) and writes a receipt row plus a generated work product.
``check_task_qa`` approves from that row only while the receipt, the task, the
tier and the content hashes of the changed files still match. T3 keeps the
strict per-criterion packet path in ``qa`` untouched. tc reads evidence files; it
never executes anything they name.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Optional

from tc.db.exceptions import TaskNotFound, ValidationError

TIERS = ("T1", "T2", "T3")
_RANK = {t: i for i, t in enumerate(TIERS)}
TIER_KEY = "verificationTier"

_TABLES = (
    "CREATE TABLE IF NOT EXISTS attestations (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL REFERENCES tasks(id), "
    "tier TEXT NOT NULL, identity_sha TEXT NOT NULL, receipt TEXT NOT NULL UNIQUE, payload TEXT NOT NULL, wp_id INTEGER, "
    "created_at TEXT NOT NULL DEFAULT (datetime('now')))",
    "CREATE TABLE IF NOT EXISTS qa_approvals (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL REFERENCES tasks(id), "
    "identity_sha TEXT NOT NULL, wp_id INTEGER, files TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')), "
    "UNIQUE(task_id, identity_sha))",
)
_MAX_TEXT = 256 * 1024
_MAX_STORED = 4 * 1024 * 1024


def ensure_tables(conn) -> None:
    for sql in _TABLES:
        conn.execute(sql)


def rank(tier: str) -> int:
    return _RANK[tier]


def highest(*tiers: str) -> str:
    return max(tiers, key=rank)


def _check_tier(value) -> str:
    if value not in _RANK:
        raise ValidationError("Tier must be one of: " + ", ".join(TIERS))
    return value


# --- recorded tier ----------------------------------------------------------

def recorded_tier(metadata: dict) -> dict | None:
    value = (metadata or {}).get(TIER_KEY)
    return value if isinstance(value, dict) and value.get("tier") in _RANK else None


def effective_tier(metadata: dict) -> str:
    """Untiered work is T3 (full QA)."""
    entry = recorded_tier(metadata)
    return entry["tier"] if entry else "T3"


def validate_tier_change(existing: dict, new: dict) -> None:
    """Guard every write path: tiers rise freely, fall only with stored authority.

    History is append-only so a downgrade cannot be erased afterwards.
    """
    if TIER_KEY not in new:
        return
    old_entry = recorded_tier(existing)
    entry = new[TIER_KEY]
    if not isinstance(entry, dict) or entry.get("tier") not in _RANK:
        raise ValidationError("verificationTier must be an object with tier T1, T2 or T3")
    history = entry.get("history")
    old_history = (old_entry or {}).get("history") or []
    if not isinstance(history, list) or history[:len(old_history)] != old_history:
        raise ValidationError("Tier history is append-only")
    if old_entry is None or entry == old_entry:
        return
    if rank(entry["tier"]) < rank(old_entry["tier"]):
        last = history[-1] if len(history) > len(old_history) else {}
        authority = last.get("authority")
        if not isinstance(authority, str) or len(authority.strip()) < 8 or last.get("to") != entry["tier"]:
            raise ValidationError(
                f"Lowering a tier ({old_entry['tier']} to {entry['tier']}) needs the owner's verbatim words: --authority \"<quote>\""
            )


def _head(root: Path) -> str | None:
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def set_tier(*, task_id: int, tier: str, reason: str, authority: Optional[str] = None, setter: str = "agent", conn=None, db_path=None) -> dict:
    """Record a tier. Raising is free; lowering needs ``authority``. Sets requiresQa."""
    from tc.services.tasks import get_task, update_task, _open_conn, _require_db_path

    _check_tier(tier)
    if not reason or not reason.strip():
        raise ValidationError("A tier needs a reason")
    owns = conn is None
    if owns:
        conn = _open_conn(_require_db_path(db_path))
    try:
        task = get_task(task_id=task_id, conn=conn)
        from tc.services.qa import task_metadata
        metadata = task_metadata(task["metadata"])
        old = recorded_tier(metadata)
        from tc.services.qa_contract import database_path
        root = database_path(conn).parent.parent
        now = conn.execute("SELECT datetime('now')").fetchone()[0]
        event = {"from": old["tier"] if old else None, "to": tier, "reason": reason.strip(), "setBy": setter, "at": now}
        if authority and authority.strip():
            event["authority"] = authority.strip()
        entry = {
            "tier": tier, "reason": reason.strip(), "setBy": setter, "setAt": now,
            "baseRev": (old or {}).get("baseRev") or _head(root),
            "history": [*((old or {}).get("history") or []), event],
        }
        update_task(task_id=task_id, metadata={"requiresQa": True, TIER_KEY: entry}, conn=conn)
        if owns:
            conn.commit()
        return entry
    finally:
        if owns:
            conn.close()


# --- classifier -------------------------------------------------------------

_DEP_NAMES = {
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb", "pyproject.toml", "uv.lock", "poetry.lock",
    "pipfile", "pipfile.lock", "cargo.toml", "cargo.lock", "go.mod", "go.sum", "gemfile", "gemfile.lock", "composer.json", "composer.lock",
}
_SECURITY_WORDS = {"auth", "oauth", "crypto", "permission", "permissions", "security", "secret", "secrets", "credential", "credentials", "password", "passwords", "acl", "rbac"}
_FRAMEWORK_PARTS = {".claude", ".codex", ".copilot", "hooks", "tools", "plugins"}
_FRAMEWORK_NAMES = {"claude.md", "agents.md", "settings.json", "settings.local.json"}
_TEST_RE = re.compile(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]*$|\.(test|spec)\.[a-z]+$|_test\.[a-z]+$")
_CODE_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}
_TEXT_EXT = {".md", ".markdown", ".txt"}
_HTML_EXT = {".html", ".htm"}
_CSS_EXT = {".css", ".scss"}
_STRING_RE = re.compile(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'|`(?:\\.|[^`\\])*`')
_NUMBER_RE = re.compile(r"\d{4}-\d{2}-\d{2}|[$€£]?\d[\d,]*(?:\.\d+)?%?")


def _path_tier(path: str, map_tiers: dict) -> tuple[str | None, str | None]:
    pure = PurePosixPath(path)
    name = pure.name.lower()
    parts = {p.lower() for p in pure.parts[:-1]}
    if name.startswith(".env"):
        return "T3", "security path (.env)"
    if name in _DEP_NAMES or name.startswith("requirements") and name.endswith(".txt"):
        return "T3", "dependency manifest or lockfile"
    words = set(re.split(r"[^a-z0-9]+", path.lower()))
    if words & _SECURITY_WORDS:
        return "T3", "security path"
    if name in _FRAMEWORK_NAMES or parts & _FRAMEWORK_PARTS:
        return "T3", "framework path"
    from tc.services.test_map import _best
    glob = _best(path, list(map_tiers))
    if glob:
        return map_tiers[glob], f"test-map tier for {glob}"
    return None, None


def _frontmatter(text: str) -> tuple[str, str]:
    match = re.match(r"---\n[\s\S]*?\n---\n?", text)
    return (match.group(0), text[match.end():]) if match else ("", text)


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _html_parts(text: str) -> tuple[list[str], list[str], str]:
    scripts = re.findall(r"<script\b[\s\S]*?</script\s*>", text, re.I)
    styles = re.findall(r"<style\b[\s\S]*?</style\s*>", text, re.I)
    rest = re.sub(r"<(script|style)\b[\s\S]*?</\1\s*>", "<\\1/>", text, flags=re.I)
    rest = re.sub(r"<!--[\s\S]*?-->", "", rest)
    skeleton = _squash(re.sub(r">[^<]*<", "><", rest))
    return [_squash(s) for s in scripts], [_squash(s) for s in styles], skeleton


def _text_view(path: str, text: str) -> str:
    """Prose a reader sees: no frontmatter, no tags, no list markers."""
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in _TEXT_EXT:
        text = _frontmatter(text)[1]
    elif suffix in _HTML_EXT:
        text = re.sub(r"<(script|style)\b[\s\S]*?</\1\s*>|<!--[\s\S]*?-->|<[^>]*>", " ", text, flags=re.I)
    return re.sub(r"(?m)^\s*\d+[.)]\s", "", text)


def classify_file(path: str, old: Optional[str], new: Optional[str], map_tiers: Optional[dict] = None) -> dict:
    """Minimum tier for one file change. Unknown impact goes up, never to nothing."""
    def out(tier, trigger):
        return {"path": path, "tier": tier, "trigger": trigger}

    forced, why = _path_tier(path, map_tiers or {})
    if forced == "T3":
        return out("T3", why)
    suffix = PurePosixPath(path).suffix.lower()
    floor = (forced, why) if forced else ("T1", None)

    def result(tier, trigger):
        return out(highest(tier, floor[0]), trigger if rank(tier) >= rank(floor[0]) else floor[1])

    if new is None:
        return out("T3", "file deleted")
    if old is None:
        return result("T1", "new Markdown file") if suffix in _TEXT_EXT else out("T3", "new file")
    if old == new:
        return result("T1", "no content change")
    if suffix in _TEXT_EXT:
        if _frontmatter(old)[0] != _frontmatter(new)[0]:
            return result("T2", "frontmatter fields changed")
        return result("T1", "text only")
    if suffix in _HTML_EXT:
        old_scripts, old_styles, old_skeleton = _html_parts(old)
        new_scripts, new_styles, new_skeleton = _html_parts(new)
        if old_scripts != new_scripts:
            return out("T3", "script changed")
        if old_styles != new_styles:
            return result("T2", "style changed")
        if old_skeleton != new_skeleton:
            return result("T2", "markup, attribute or class changed")
        return result("T1", "text only")
    if suffix in _CSS_EXT:
        return result("T2", "styling")
    if suffix in _CODE_EXT:
        if _squash(_STRING_RE.sub('""', old)) == _squash(_STRING_RE.sub('""', new)):
            return result("T2", "string literals only")
        if _TEST_RE.search(path):
            return result("T2", "test file updated")
        return out("T3", "code logic changed")
    return out("T3", "unknown file type")


def changed_numbers(path: str, old: Optional[str], new: Optional[str]) -> list[str]:
    """Numeric tokens present in the new prose and not the old: each needs a source."""
    suffix = PurePosixPath(path).suffix.lower()
    if new is None or suffix not in _TEXT_EXT | _HTML_EXT | _CODE_EXT | _CSS_EXT:
        return []
    if suffix in _CSS_EXT:
        return []
    before = Counter(_NUMBER_RE.findall(_text_view(path, old or "")))
    after = Counter(_NUMBER_RE.findall(_text_view(path, new)))
    return sorted((after - before).elements())


def classify(changes: list[dict], map_tiers: Optional[dict] = None) -> dict:
    files = [classify_file(c["path"], c["old"], c["new"], map_tiers) for c in changes]
    numbers = []
    for c in changes:
        for token in changed_numbers(c["path"], c["old"], c["new"]):
            if token not in numbers:
                numbers.append(token)
    return {"minimum": highest("T1", *[f["tier"] for f in files]), "files": files, "numbers": numbers,
            "triggers": sorted({f"{f['path']}: {f['trigger']}" for f in files if f["tier"] != "T1"})}


# --- change sources ---------------------------------------------------------

def _task_root(task: dict, conn) -> Path:
    from tc.services.qa_contract import database_path, execution_root
    return execution_root(task["id"], conn) or database_path(conn).parent.parent


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValidationError(f"git failed: {exc}") from exc


def _read(root: Path, rel: str) -> Optional[str]:
    path = (root / rel).resolve()
    if root.resolve() not in path.parents or not path.is_file():
        return None
    try:
        return path.read_text()
    except (OSError, UnicodeDecodeError):
        return "\0unreadable"  # binary or unreadable: never equal, so never below T3


def _sha(root: Path, rel: str) -> Optional[str]:
    path = (root / rel).resolve()
    if root.resolve() not in path.parents or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_changes(root: Path, base: Optional[str]) -> list[dict]:
    from tc.services.test_map import changed_paths

    paths = changed_paths(root, base)
    if base:
        paths += [p for p in _git(root, "ls-files", "--others", "--exclude-standard").stdout.splitlines() if p and not p.startswith(".copilot/")]
    changes = []
    for rel in dict.fromkeys(paths):
        shown = _git(root, "show", f"{base or 'HEAD'}:{rel}")
        changes.append({"path": rel, "old": shown.stdout if shown.returncode == 0 else None, "new": _read(root, rel), "sha": _sha(root, rel)})
    return changes


def _stored_files(root: Path, records: list[dict]) -> dict:
    files, total = {}, 0
    for record in records:
        if record.get("kind") != "file":
            continue
        text = _read(root, record["path"])
        keep = text is not None and text != "\0unreadable" and len(text.encode()) <= _MAX_TEXT and total + len(text.encode()) <= _MAX_STORED
        if keep:
            total += len(text.encode())
        files[record["path"]] = {"sha": record["sha256"], "text": text if keep else None}
    return files


def delta_changes(root: Path, approval_files: dict, sources: list[str]) -> list[dict]:
    """Files that differ from the last approved manifest (the carry-forward delta)."""
    from tc.services.qa_contract import source_manifest
    current = {r["path"]: r["sha256"] for r in source_manifest(root, sources) if r.get("kind") == "file"}
    changes = []
    for rel in sorted(set(current) | set(approval_files)):
        old = approval_files.get(rel)
        if old and current.get(rel) == old["sha"]:
            continue
        # Unstored (oversized) old text is None: new files and unknown history both classify upward.
        changes.append({"path": rel, "old": old["text"] if old else None, "new": _read(root, rel), "sha": current.get(rel)})
    return changes


def latest_approval(conn, task_id: int) -> dict | None:
    try:
        row = conn.execute("SELECT * FROM qa_approvals WHERE task_id=? ORDER BY id DESC LIMIT 1", (task_id,)).fetchone()
    except sqlite3.OperationalError:
        return None
    return dict(row) if row else None


def record_approval(*, task: dict, conn, wp_id: Optional[int]) -> None:
    """Remember the approved per-file manifest so later small changes can carry it forward."""
    try:
        from tc.services.qa_contract import capture_for_task, digest
        captured = capture_for_task(task, conn)
        local = [r for r in captured["sources"] if r.get("kind") == "file"]
        if not local:
            return
        files = _stored_files(_task_root(task, conn), local)
        ensure_tables(conn)
        conn.execute("INSERT OR IGNORE INTO qa_approvals (task_id, identity_sha, wp_id, files) VALUES (?,?,?,?)",
                     (task["id"], digest(captured["identity"]), wp_id, json.dumps(files, sort_keys=True)))
    except (ValidationError, OSError, sqlite3.Error):
        return  # best effort: without a manifest the next change needs one normal round


def current_changes(task: dict, conn, base: Optional[str] = None) -> tuple[dict, list[dict]]:
    """(basis, changes). Basis is the last approval when one exists, else git against base."""
    from tc.services.qa import task_metadata
    metadata = task_metadata(task["metadata"])
    root = _task_root(task, conn)
    contract = metadata.get("acceptanceContract")
    approval = None if base else latest_approval(conn, task["id"])
    if approval and isinstance(contract, dict) and contract.get("sources"):
        return ({"kind": "approval", "id": approval["id"]}, delta_changes(root, json.loads(approval["files"]), contract["sources"]))
    entry = recorded_tier(metadata) or {}
    ref = base or entry.get("baseRev")
    return ({"kind": "git", "base": ref}, git_changes(root, ref))


def _map_tiers(conn) -> dict:
    from tc.services.qa_contract import database_path
    from tc.services.test_map import load_map
    return {g: e["tier"] for g, e in load_map(database_path(conn)).items() if isinstance(e, dict) and e.get("tier")}


def _identity(task_id: int, basis: dict, changes: list[dict]) -> str:
    files = sorted((c["path"], c["sha"]) for c in changes)
    return hashlib.sha256(json.dumps({"task": task_id, "basis": basis, "files": files}, sort_keys=True).encode()).hexdigest()


def check_tier(*, task_id: int, base: Optional[str] = None, conn=None, db_path=None) -> dict:
    """Minimum tier the actual change needs, with the triggers that set it."""
    from tc.services.tasks import get_task, _open_conn, _require_db_path
    owns = conn is None
    if owns:
        conn = _open_conn(_require_db_path(db_path))
    try:
        task = get_task(task_id=task_id, conn=conn)
        from tc.services.qa import task_metadata
        metadata = task_metadata(task["metadata"])
        basis, changes = current_changes(task, conn, base)
        verdict = classify(changes, _map_tiers(conn))
        verdict.update(basis=basis, recorded=effective_tier(metadata))
        verdict["required"] = highest(verdict["minimum"], effective_tier(metadata))
        return verdict
    finally:
        if owns:
            conn.close()


# --- attestation ------------------------------------------------------------

_SOURCE_VALUE = re.compile(r"^(.+?)=(.+)$", re.S)


def _verify_sources(root: Path, conn, task_id: int, numbers: list[str], sources: list[str]) -> list[dict]:
    given = {}
    for item in sources or []:
        match = _SOURCE_VALUE.match(item)
        if not match:
            raise ValidationError("--source must look like VALUE=file:line | WP-id | pablo:<quote>")
        given[match.group(1).strip()] = match.group(2).strip()
    missing = [n for n in numbers if n not in given]
    if missing:
        raise ValidationError("Changed numbers need a source (--source \"VALUE=file:line | WP-id | pablo:<quote>\"): " + ", ".join(missing))
    checked = []
    for value, ref in given.items():
        if ref.lower().startswith("pablo:"):
            quote = ref[6:].strip()
            if value not in quote:
                raise ValidationError(f"Quote does not contain {value!r}")
            checked.append({"value": value, "source": ref, "kind": "quote"})
        elif re.fullmatch(r"WP-\d+", ref, re.I):
            row = conn.execute("SELECT content, file_path FROM work_products WHERE id=?", (int(ref[3:]),)).fetchone()
            if row is None:
                raise ValidationError(f"{ref} not found")
            content = row["content"] or ((root / row["file_path"]).read_text() if row["file_path"] and (root / row["file_path"]).is_file() else "")
            if value not in content:
                raise ValidationError(f"{value!r} does not appear in {ref}")
            checked.append({"value": value, "source": ref, "kind": "wp"})
        else:
            rel, _, line = ref.partition(":")
            text = _read(root, rel)
            if text is None:
                raise ValidationError(f"Source file not found inside the project: {rel}")
            lines = text.splitlines()
            scope = text
            if line:
                if not line.isdigit() or not 1 <= int(line) <= len(lines):
                    raise ValidationError(f"Bad line in source {ref}")
                scope = lines[int(line) - 1]
            if value not in scope:
                raise ValidationError(f"{value!r} does not appear in {ref}")
            checked.append({"value": value, "source": ref, "kind": "file"})
    return checked


def _artifact(root: Path, ref: str, newest: float, what: str) -> dict:
    path = Path(ref)
    path = path if path.is_absolute() else root / path
    if not path.is_file():
        raise ValidationError(f"{what} artifact not found: {ref}")
    if newest and path.stat().st_mtime < newest:
        raise ValidationError(f"{what} artifact predates the newest changed source: {ref}")
    return {"path": ref, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _verify_run(root: Path, run_id: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", run_id):
        raise ValidationError("Bad check run id")
    status_file = root / ".copilot" / "verification" / run_id / "status.json"
    try:
        status = json.loads(status_file.read_text())
    except (OSError, ValueError) as exc:
        raise ValidationError(f"No stored cc verify status for run {run_id}") from exc
    if status.get("status") != "passed":
        raise ValidationError(f"cc verify run {run_id} did not pass (status: {status.get('status')})")
    return {"run": run_id, "status": "passed", "sha256": hashlib.sha256(status_file.read_bytes()).hexdigest()}


def _receipt(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def attest(*, task_id: int, tier: str, inputs: dict, base: Optional[str] = None, agent: Optional[str] = None, conn=None, db_path=None) -> dict:
    """Check the tier's one check and record the result. Never lowers, never executes."""
    from tc.services.tasks import get_task, _open_conn, _require_db_path
    from tc.services.wp import store_wp
    from tc.services.qa import task_metadata

    _check_tier(tier)
    if tier == "T3":
        raise ValidationError("T3 work is approved by an independent QA packet, not an attestation")
    owns = conn is None
    if owns:
        conn = _open_conn(_require_db_path(db_path))
    try:
        task = get_task(task_id=task_id, conn=conn)
        metadata = task_metadata(task["metadata"])
        entry = recorded_tier(metadata)
        if entry is None:
            raise ValidationError("Task has no recorded tier (untiered work is T3); record one first: tc task tier <id> T1|T2 --reason ...")
        root = _task_root(task, conn)
        basis, changes = current_changes(task, conn, base)
        verdict = classify(changes, _map_tiers(conn))
        required = highest(verdict["minimum"], entry["tier"])
        if rank(tier) < rank(required):
            if verdict["minimum"] == "T3":
                raise ValidationError("Diff needs T3 (full QA): " + "; ".join(verdict["triggers"]))
            raise ValidationError(f"Diff needs at least {required}, attested {tier}: " + ("; ".join(verdict["triggers"]) or "recorded tier"))
        if tier != entry["tier"]:
            set_tier(task_id=task_id, tier=tier, reason=f"attest raised the tier to {tier}: " + ("; ".join(verdict["triggers"]) or "attested tier"), setter="tc", conn=conn)
        newest = max([(root / c["path"]).stat().st_mtime for c in changes if (root / c["path"]).is_file()] or [0])
        results: dict[str, Any] = {}
        if tier == "T1":
            file_ref = inputs.get("in")
            present, absent = inputs.get("present") or [], inputs.get("absent") or []
            if not file_ref or not present or not absent:
                raise ValidationError("T1 needs --in <built file>, at least one --present and at least one --absent")
            text = _read(root, file_ref)
            if text is None:
                raise ValidationError(f"--in file not found inside the project: {file_ref}")
            lost = [p for p in present if p not in text]
            if lost:
                raise ValidationError("New text missing from " + file_ref + ": " + "; ".join(lost))
            kept = [a for a in absent if a in text]
            if kept:
                raise ValidationError("Old text still present in " + file_ref + ": " + "; ".join(kept))
            if not inputs.get("load"):
                raise ValidationError("T1 needs --load <screenshot of one successful browser load>")
            results = {"in": file_ref, "in_sha256": _sha(root, file_ref), "present": present, "absent": absent,
                       "load": _artifact(root, inputs["load"], newest, "Load")}
        else:
            renders = inputs.get("render") or []
            if not 1 <= len(renders) <= 2:
                raise ValidationError("T2 needs one or two --render artifacts")
            if not inputs.get("checks"):
                raise ValidationError("T2 needs --checks <cc verify run id>")
            results = {"renders": [_artifact(root, r, newest, "Render") for r in renders], "checks": _verify_run(root, inputs["checks"])}
        sources = _verify_sources(root, conn, task_id, verdict["numbers"], inputs.get("source") or [])
        payload = {"task": task_id, "tier": tier, "basis": basis, "identity": _identity(task_id, basis, changes),
                   "minimum": verdict["minimum"], "files": sorted(c["path"] for c in changes), "results": results, "sources": sources}
        receipt = _receipt(payload)
        lines = [f"ATTESTATION: {tier} for task #{task_id}", f"MINIMUM-TIER: {verdict['minimum']}",
                 *[f"FILE: {p}" for p in payload["files"]], f"CHECK: {json.dumps(results, sort_keys=True)}",
                 *[f"SOURCE: {s['value']} = {s['source']}" for s in sources], "RESULT: PASSED", f"ATTEST-RECEIPT: {receipt}"]
        ensure_tables(conn)
        wp = store_wp(task_id=task_id, type_="test", title=f"{tier} attestation", content="\n".join(lines), agent=agent, conn=conn)
        conn.execute("INSERT INTO attestations (task_id, tier, identity_sha, receipt, payload, wp_id) VALUES (?,?,?,?,?,?)",
                     (task_id, tier, payload["identity"], receipt, json.dumps(payload, sort_keys=True), wp["id"]))
        conn.commit()
        return {"task_id": task_id, "tier": tier, "minimum": verdict["minimum"], "receipt": receipt, "work_product_id": wp["id"], "files": payload["files"]}
    finally:
        if owns:
            conn.close()


def attestation_status(task: dict, conn) -> dict | None:
    """None when the task has no attestation story; else {approved, reason, wp_id}."""
    from tc.services.qa import task_metadata
    metadata = task_metadata(task["metadata"])
    entry = recorded_tier(metadata)
    try:
        rows = conn.execute("SELECT * FROM attestations WHERE task_id=? ORDER BY id DESC", (task["id"],)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    forged = _forged_receipts(task["id"], conn, {r["receipt"] for r in rows})
    if entry is None or entry["tier"] == "T3":
        return None
    if not rows:
        reason = "Forged attestation: ATTEST-RECEIPT work product has no matching tc record; run tc task attest" if forged else "T1/T2 task needs a tc attestation (tc task attest) or a full QA packet"
        return {"approved": False, "reason": reason, "wp_id": None}
    row = rows[0]
    payload = json.loads(row["payload"])
    if _receipt(payload) != row["receipt"]:
        return {"approved": False, "reason": "Attestation record was altered", "wp_id": row["wp_id"]}
    try:
        _, changes = _replay(task, conn, payload["basis"])
        verdict = classify(changes, _map_tiers(conn))
    except (ValidationError, OSError, ValueError) as exc:
        return {"approved": False, "reason": f"Attestation cannot be re-checked: {exc}", "wp_id": row["wp_id"]}
    if _identity(task["id"], payload["basis"], changes) != payload["identity"]:
        return {"approved": False, "reason": "Attestation is stale: changed files differ from what was attested; attest again", "wp_id": row["wp_id"]}
    needed = highest(verdict["minimum"], entry["tier"])
    if rank(payload["tier"]) < rank(needed):
        return {"approved": False, "reason": f"Attested {payload['tier']} but the change needs {needed}", "wp_id": row["wp_id"]}
    return {"approved": True, "reason": f"{payload['tier']} attestation passes (receipt {row['receipt'][:12]})", "wp_id": row["wp_id"]}


def _replay(task: dict, conn, basis: dict) -> tuple[dict, list[dict]]:
    root = _task_root(task, conn)
    if basis["kind"] == "approval":
        from tc.services.qa import task_metadata
        row = conn.execute("SELECT files FROM qa_approvals WHERE id=? AND task_id=?", (basis["id"], task["id"])).fetchone()
        contract = task_metadata(task["metadata"]).get("acceptanceContract") or {}
        if row is None or not contract.get("sources"):
            raise ValidationError("approval manifest is gone")
        return basis, delta_changes(root, json.loads(row["files"]), contract["sources"])
    return basis, git_changes(root, basis.get("base"))


def _forged_receipts(task_id: int, conn, known: set) -> list[str]:
    found = []
    for row in conn.execute("SELECT content FROM work_products WHERE task_id=? AND content LIKE '%ATTEST-RECEIPT:%'", (task_id,)):
        for receipt in re.findall(r"(?m)^ATTEST-RECEIPT:\s*([0-9a-f]{64})\s*$", row["content"] or ""):
            if receipt not in known:
                found.append(receipt)
    return found


# --- T3 friction cut --------------------------------------------------------

def qa_packet(*, task_id: int, carry: Optional[list[str]] = None, conn=None, db_path=None) -> str:
    """A packet pre-filled with the captured IDENTITY and each criterion's exact text.

    QA fills OBSERVED, BASELINE, ARTIFACT, UNTESTED and VERDICT. ``carry`` entries
    ``WP-N:C1,C2`` pre-fill those criteria's OBSERVED from WP-N and cite it; whether
    the carried result still holds is QA's judgment.
    """
    from tc.evidence import parse_packet
    from tc.services.tasks import get_task, _open_conn, _require_db_path
    from tc.services.qa_contract import capture_for_task, bound_contract
    from tc.services.wp import get_wp

    owns = conn is None
    if owns:
        conn = _open_conn(_require_db_path(db_path))
    try:
        task = get_task(task_id=task_id, conn=conn)
        criteria = bound_contract(task, conn)["contract"]["criteria"]
        carried: dict[str, tuple[int, str]] = {}
        for item in carry or []:
            match = re.fullmatch(r"WP-(\d+):([A-Za-z0-9_,-]+)", item)
            if not match:
                raise ValidationError("--carry must look like WP-N:C1,C2")
            wp = get_wp(wp_id=int(match.group(1)), conn=conn)
            if wp.get("task_id") != task_id:
                raise ValidationError(f"WP-{match.group(1)} belongs to another task")
            observed = {r["criterion"]: r.get("observed") for r in parse_packet(wp.get("content") or "")["records"]}
            for cid in match.group(2).split(","):
                if cid not in {c["id"] for c in criteria} or cid not in observed:
                    raise ValidationError(f"WP-{match.group(1)} has no result for criterion {cid}")
                carried[cid] = (int(match.group(1)), observed[cid] or "")
        lines = []
        for c in criteria:
            lines += [f"CRITERION: {c['id']}", f"EXPECTED: {c['expected']}"]
            if c["id"] in carried:
                wp_id, text = carried[c["id"]]
                lines.append(f"OBSERVED: Carried forward from WP-{wp_id}: {text}")
            else:
                lines.append("OBSERVED: <fill>")
        lines.append(capture_for_task(task, conn)["identity_line"])
        lines += ["BASELINE: <fill>"]
        lines += [f"ARTIFACT: file-check|carried forward {','.join(sorted(k for k, v in carried.items() if v[0] == w))} from WP-{w}" for w in sorted({v[0] for v in carried.values()})]
        lines += ["ARTIFACT: <fill>", "UNTESTED: <fill, or none>", "VERDICT: <APPROVED | REJECTED>"]
        return "\n".join(lines)
    finally:
        if owns:
            conn.close()
