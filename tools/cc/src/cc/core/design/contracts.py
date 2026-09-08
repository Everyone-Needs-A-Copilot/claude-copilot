"""Local, bounded design contracts. Receipts describe evidence, never QA approval."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from importlib.resources import files
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from cc.core.evaluation.schema import canonical_sha256
from cc.core.write_guard import assert_write_is_isolated

MODES = ("persuade", "operate", "read", "experience")
CHECKS = ("visual", "behavior", "keyboard", "responsive", "contrast", "motion", "content", "localization")
MAX_BYTES = 2 * 1024 * 1024


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def text(value: Any, name: str, limit: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        raise ValueError(f"{name} requires nonempty text of at most {limit} characters")
    return value


def local_path(root: Path, name: str, *, exists: bool = True) -> Path:
    root = root.resolve()
    path = root / text(name, "path")
    resolved = path.resolve()
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError(f"Path must stay within the project: {name}")
    # Reject symlink aliases even when they currently point back into the project.
    current = path.absolute()
    while current != root and current != current.parent:
        if current.is_symlink():
            raise ValueError(f"Symlink paths are not accepted: {name}")
        current = current.parent
    if exists and not resolved.is_file():
        raise ValueError(f"Regular local file required: {name}")
    return resolved


def read_bytes(path: Path, limit: int = MAX_BYTES) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Regular file required: {path}")
    with path.open("rb") as handle:
        body = handle.read(limit + 1)
    if len(body) > limit:
        raise ValueError(f"File exceeds {limit} bytes: {path}")
    return body


def read_json(path: Path) -> dict:
    value = json.loads(read_bytes(path))
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def file_record(root: Path, name: str) -> dict:
    path = local_path(root, name)
    body = read_bytes(path)
    return {"path": path.relative_to(root.resolve()).as_posix(), "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}


def source_records(root: Path, names: list[str], *, strict_links: bool = False) -> list[dict]:
    """Include the local stylesheets consumed by the pinned static HTML engine.

    Root-relative links use deployment-specific resolution: require an explicit
    local relative link for this adapter instead of guessing a filesystem root.
    Remote styles are not fetched by the static engine or this adapter.
    """
    class Stylesheets(HTMLParser):
        def __init__(self):
            super().__init__()
            self.links = []

        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if tag == "link" and "stylesheet" in (values.get("rel") or "").lower():
                self.links.append(values.get("href") or "")

    sources = {}
    for name in names:
        path = local_path(root, name)
        record = file_record(root, name)
        sources[record["path"]] = record
        if path.suffix.lower() not in (".html", ".htm"):
            continue
        parser = Stylesheets()
        parser.feed(read_bytes(path).decode("utf-8"))
        for href in parser.links:
            if not href or re.match(r"(?i)^(https?:)?//", href):
                continue
            if href.startswith("/") or ":" in href or "\\" in href:
                if strict_links:
                    raise ValueError("Static HTML audit requires project-local relative stylesheet links")
                continue
            linked = path.parent / re.split(r"[?#]", href, maxsplit=1)[0]
            try:
                linked_record = file_record(root, str(linked))
            except (ValueError, OSError):
                if strict_links:
                    raise
                continue
            sources[linked_record["path"]] = linked_record
    return [sources[key] for key in sorted(sources)]


def create_file(root: Path, name: str, content: str) -> Path:
    """Create an artifact exclusively; never overwrite a user's earlier result."""
    path = local_path(root, name, exists=False)
    assert_write_is_isolated(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Recheck after mkdir so an existing directory link cannot redirect the write.
    path = local_path(root, name, exists=False)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def save_receipt(root: Path, output: str, body: dict) -> dict:
    receipt = {**body, "receipt_sha256": canonical_sha256(body)}
    encoded = json.dumps(receipt, indent=2, ensure_ascii=False) + "\n"
    if len(encoded.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Receipt exceeds the bounded reader limit; narrow the review scope")
    create_file(root, output, encoded)
    return receipt


def verify_receipt(path: Path, kind: str) -> dict:
    body = read_json(path)
    digest = body.pop("receipt_sha256", None)
    if body.get("kind") != kind or digest != canonical_sha256(body):
        raise ValueError(f"Invalid or edited {kind} receipt")
    return {**body, "receipt_sha256": digest}


def validate_contract(contract: dict, root: Path, *, require_targets: bool = True) -> dict:
    if contract.get("schema_version") != "1.0":
        raise ValueError("Unsupported design contract schema")
    if type(contract.get("task_id")) is not int or contract["task_id"] < 1:
        raise ValueError("A positive task_id reference is required; QA checks its tc database binding")
    if type(contract.get("detector_required", False)) is not bool:
        raise ValueError("detector_required must be a boolean")
    surface = contract.get("surface")
    if not isinstance(surface, dict) or surface.get("mode") not in MODES:
        raise ValueError(f"Surface mode must be one of {', '.join(MODES)}")
    for key in ("name", "job", "target"):
        text(surface.get(key), f"surface.{key}")
    if surface.get("change") not in ("refine", "extend", "redesign"):
        raise ValueError("Surface change must be refine, extend, or redesign")
    authorities = contract.get("authority")
    if not isinstance(authorities, dict):
        raise ValueError("Explicit product and design authority required")
    names = []
    for key in ("product", "design"):
        values = authorities.get(key)
        if not isinstance(values, list) or not values or len(values) > 16:
            raise ValueError(f"authority.{key} requires 1–16 existing source files")
        names.extend(values)
    targets = contract.get("targets")
    if not isinstance(targets, list) or not targets or len(targets) > 40:
        raise ValueError("Specify 1–40 target source files")
    for name in names:
        local_path(root, name)
    for name in targets:
        local_path(root, name, exists=require_targets)
    states = contract.get("states")
    if not isinstance(states, list) or not states or len(states) > 24:
        raise ValueError("Explicit material states required")
    for state in states:
        text(state, "state", 200)
    criteria = contract.get("criteria")
    if not isinstance(criteria, list) or not criteria or len(criteria) > 40:
        raise ValueError("Specify 1–40 observable acceptance criteria")
    ids = set()
    for criterion in criteria:
        if not isinstance(criterion, dict):
            raise ValueError("Criterion must be an object")
        cid = text(criterion.get("id"), "criterion.id", 80)
        if not re.fullmatch(r"[A-Za-z0-9_-]+", cid) or cid in ids:
            raise ValueError("Criterion IDs must be unique simple identifiers")
        ids.add(cid)
        text(criterion.get("expected"), f"{cid}.expected")
        checks = criterion.get("checks")
        if not isinstance(checks, list) or not checks or any(c not in CHECKS for c in checks):
            raise ValueError(f"{cid}.checks must use known design checks")
    return contract


def identity(contract: dict, root: Path, *, allow_planned: bool = False) -> dict:
    validate_contract(contract, root, require_targets=not allow_planned)
    names = contract["targets"] + contract["authority"]["product"] + contract["authority"]["design"]
    planned = [name for name in names if not local_path(root, name, exists=False).is_file()]
    sources = source_records(root, sorted(set(names) - set(planned)))
    implementation = {name: hashlib.sha256(files("cc.core.design").joinpath(name).read_bytes()).hexdigest()
                      for name in ("contracts.py", "review.py", "tools.py", "references/catalog.json")}
    return {"project": str(root.resolve()), "contract_sha256": canonical_sha256(contract),
            "sources": sources, "planned_targets": planned, "adapter_sources": implementation}


def catalog() -> dict:
    return json.loads(files("cc.core.design").joinpath("references", "catalog.json").read_text())


def guide(action: str | None = None) -> dict:
    data = catalog()
    if action is None:
        return {"schema_version": "1.0", "actions": data, "source": "cc.core.design.references"}
    if action not in data:
        raise ValueError(f"Unknown design action: {action}; use cc design guide")
    spec = data[action]
    body = files("cc.core.design").joinpath("references", spec["reference"]).read_text()
    return {"action": action, **spec, "content": body, "source_sha256": hashlib.sha256(body.encode()).hexdigest(), "characters": len(body)}


def context(root: Path, contract_path: str, *, action: str = "shape", max_chars: int = 12000) -> dict:
    if not 0 <= max_chars <= 100000:
        raise ValueError("max_chars must be between 0 and 100000")
    contract = validate_contract(read_json(local_path(root, contract_path)), root, require_targets=False)
    selected = guide(action)
    contract_text = json.dumps(contract, ensure_ascii=False, indent=2)
    used = len(contract_text)
    loaded, excluded = [], []
    candidates = [{"path": f"cc:design/{action}", "content": selected["content"], "sha256": selected["source_sha256"]}]
    for name in dict.fromkeys(contract["authority"]["product"] + contract["authority"]["design"]):
        body = read_bytes(local_path(root, name)).decode("utf-8")
        candidates.append({**file_record(root, name), "content": body})
    seen = set()
    for candidate in candidates:
        reason = "duplicate content" if candidate["sha256"] in seen else "character budget"
        if candidate["sha256"] not in seen and used + len(candidate["content"]) <= max_chars:
            loaded.append({**candidate, "reason": "requested action" if candidate["path"].startswith("cc:") else "explicit design authority"})
            seen.add(candidate["sha256"])
            used += len(candidate["content"])
        else:
            excluded.append({k: v for k, v in candidate.items() if k != "content"} | {"reason": reason})
    return {"schema_version": "1.0", "kind": "design-context", "contract": contract, "identity": identity(contract, root, allow_planned=True),
            "loaded": loaded, "excluded": excluded, "max_chars": max_chars, "loaded_characters": used,
            "contract_over_budget": len(contract_text) > max_chars, "token_count": None,
            "boundary": "Selection receipt, not proof of consumption. Mandatory runtime/repository instructions remain in force; omitted authority must be inspected before editing."}


def template() -> dict:
    return {"schema_version": "1.0", "task_id": 1,
            "surface": {"name": "Replace with the named surface", "target": "Replace with route or component", "mode": "operate", "job": "Replace with the user's observable task", "change": "refine"},
            "authority": {"product": ["SOUL.md"], "design": ["DESIGN.md"]}, "targets": ["src/replace-with-target.tsx"],
            "states": ["default", "empty", "loading", "error"],
            "criteria": [{"id": "C1", "expected": "Replace with required behavior, input and observable outcome", "checks": ["behavior", "visual", "keyboard", "responsive"]}]}



def task_binding(contract: dict, root: Path) -> dict:
    """Check the named project's actual task contract, not a positive integer."""
    from tc import api
    from tc.db.exceptions import TcError
    from tc.services.qa_contract import digest, validate_contract as validate_acceptance
    database = root.resolve() / ".copilot" / "tasks.db"
    if not database.is_file():
        raise ValueError("Design review requires the named project's tc database and acceptance contract")
    try:
        task = api.get_task(task_id=contract["task_id"], db_path=database)
        metadata = json.loads(task["metadata"] or "{}")
        acceptance = validate_acceptance(metadata.get("acceptanceContract"))
    except (TcError, ValueError, TypeError) as exc:
        raise ValueError("Register this task's acceptance contract with tc task contract before design review") from exc
    expected = {c["id"]: c["expected"] for c in acceptance["criteria"]}
    if {c["id"]: c["expected"] for c in contract["criteria"]} != expected:
        raise ValueError("Design criteria differ from the authoritative task acceptance contract")
    for target in contract["targets"] + contract["authority"]["product"] + contract["authority"]["design"]:
        if not any(scope == "." or target == scope or target.startswith(scope + "/") for scope in acceptance["sources"]):
            raise ValueError("Task source scope must include every design target and authority")
    return {"database": str(database), "task_id": task["id"],
            "acceptance_sha256": digest({"title": task["title"], "description": task["description"], "contract": acceptance})}
