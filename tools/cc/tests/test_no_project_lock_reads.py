"""No runtime path reads a project's `copilot.lock.json` or `.codex-copilot.json`.

Central resolution (ADR-001) retires both per-project locks: nothing may be verified, planned
or reconciled against them. The one legitimate reader is `cc project migrate`
(`core/project_migrate/`), which must still parse old records to classify copies before removing
them. The other files that name `copilot.lock.json` use the same filename for a different,
machine-level record (the ecosystem lock under the machine config directory, and the lock blob a
tier publishes in its mirror); they never open a project's file.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "cc"
NEEDLES = ("copilot.lock.json", ".codex-copilot.json")

#: file (relative to src/cc) -> why it may name the file. A prefix ending in "/" covers a directory.
ALLOWED = {
    "core/project_migrate/": "reads old project locks to classify copies before removing them",
    "core/release/links/adopt.py": "adopts the machine-level legacy record under ~/.claude/cc",
    "core/ecosystem/lockfile.py": "machine ecosystem lock path (machine config dir), not a project file",
    "core/ecosystem/freshness.py": "a tier's published lock blob inside its mirror, not a project file",
    "core/ecosystem/mirror.py": "a tier's published lock blob inside its mirror, not a project file",
    "core/write_guard.py": "protects the machine ecosystem lock path from writes",
}


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def _is_allowed(rel: str) -> bool:
    return any(rel == key or (key.endswith("/") and rel.startswith(key)) for key in ALLOWED)


def test_no_runtime_string_literal_names_a_project_lock_outside_the_allowlist():
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if _is_allowed(rel):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = _docstring_nodes(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                if any(needle in node.value for needle in NEEDLES):
                    offenders.append(f"{rel}:{node.lineno}: {node.value[:80]!r}")
    assert not offenders, "runtime code reads a retired project lock:\n" + "\n".join(offenders)


def test_codex_project_lock_is_named_only_by_project_migrate():
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel.startswith("core/project_migrate/"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = _docstring_nodes(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                assert ".codex-copilot.json" not in node.value, f"{rel}:{node.lineno}"


def test_allowlist_entries_exist():
    for key in ALLOWED:
        assert (SRC / key).exists(), f"stale allowlist entry: {key}"


def test_migrate_can_still_read_old_lock_records():
    from cc.core.project_migrate.known import CODEX_LOCK_FILE, LOCK_FILE, read_lock

    assert LOCK_FILE == "copilot.lock.json" and CODEX_LOCK_FILE == ".codex-copilot.json"
    assert callable(read_lock)
