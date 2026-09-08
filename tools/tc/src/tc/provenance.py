"""Explicit installation receipts; verification never creates or repairs them."""
from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from tc import __version__
from tc.db.exceptions import ValidationError


def _hash(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
        raise ValidationError(f"Unverifiable installed file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _capabilities() -> list[str]:
    from tc import api
    from tc.commands.task import task_app
    expected = {"check-qa", "contract", "evidence-identity"}
    commands = {command.name for command in task_app.registered_commands}
    if not expected <= commands or not callable(api.capture_qa_identity) or not callable(api.check_task_qa):
        raise ValidationError("Installed tc lacks required task-evidence enforcement capabilities")
    return sorted(expected)


def capture() -> dict:
    package = Path(__file__).resolve().parent
    project = package.parents[1]
    source = project.parents[1]
    files = {str(path.relative_to(project)): _hash(path) for path in sorted(package.rglob("*"))
             if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"}
    files["pyproject.toml"] = _hash(project / "pyproject.toml")
    markers = [source / ".source-commit", source / ".source-tree"]
    if all(p.is_file() and not p.is_symlink() for p in markers):
        commit, tree = (p.read_text().strip() for p in markers)
        mode = "snapshot"
    else:
        try:
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, timeout=5, text=True).strip()
            tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=source, timeout=5, text=True).strip()
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValidationError("tc installation requires a Git source or verified snapshot markers") from exc
        mode = "development"
    if any(len(v) not in (40, 64) or any(c not in "0123456789abcdef" for c in v) for v in (commit, tree)):
        raise ValidationError("Invalid tc source commit/tree identity")
    dependencies = {}
    # Full environment inventory includes transitive dependencies; extras and
    # platform markers do not need a second dependency resolver here.
    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name", "")
        if name.lower().replace("_", "-") in {"task-copilot-cli", "claude-cli"}:
            continue  # editable framework sources are verified separately
        records = {}
        for entry in distribution.files or ():
            if str(entry).endswith(".pyc") or "__pycache__" in entry.parts:
                continue
            path = Path(distribution.locate_file(entry))
            if path.is_file():
                records[str(entry)] = _hash(path)
        if not records:
            raise ValidationError(f"Dependency has no verifiable installed files: {name}")
        dependencies[name] = {"version": distribution.version, "files": records}
    return {"schema_version": "1.0", "mode": mode, "version": __version__,
            "source_commit": commit, "source_tree": tree, "source_root": str(source),
            "package_root": str(project), "module": str(package / "__init__.py"),
            "interpreter": str(Path(sys.executable).absolute()), "python": sys.version,
            "files": files, "dependencies": dependencies, "capabilities": _capabilities()}


def receipt_path() -> Path:
    return Path(sys.prefix) / "tc-provenance.json"


def record() -> dict:
    """Called explicitly by installation after all packages are installed."""
    path = receipt_path()
    if path.is_symlink():
        raise ValidationError("tc provenance receipt cannot be a symlink")
    payload = capture()
    fd, name = tempfile.mkstemp(prefix=".tc-provenance-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(payload, handle, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return verify()


def verify() -> dict:
    path = receipt_path()
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
        raise ValidationError("tc installation provenance receipt is missing or invalid; reinstall from reviewed source")
    try:
        recorded = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ValidationError("Invalid tc installation provenance receipt") from exc
    if recorded != capture():
        raise ValidationError("tc source, dependency, runtime or capability differs from installation receipt")
    return {"verified": True, "receipt": str(path), "receipt_sha256": _hash(path),
            "mode": recorded["mode"], "version": recorded["version"],
            "source_commit": recorded["source_commit"], "source_tree": recorded["source_tree"],
            "capabilities": recorded["capabilities"]}
