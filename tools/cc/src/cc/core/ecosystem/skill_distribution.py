"""Make organization-tier skills visible to BOTH Claude Code and Codex.

Claude: `materialize()` already copies each signed organization/department
skill into the Claude root (`~/.claude/skills/<name>`), verified against the
layer's signed release. Codex has no equivalent target, so org skills never
reached `~/.codex/skills`. This module is the single implementation that
closes that gap for every machine: after a successful `cc update`, each
organization/department skill that was materialized (or is already current)
for Claude is linked into the Codex skills directory, pointing at the
verified Claude copy -- one canonical folder, two harnesses.

Safety (never-destroy):
  * Only organization/department layers are projected. Personal and
    foundation content is not touched here (personal stays unsigned and is
    never materialized by cc).
  * Only items `materialize()` placed or confirmed are projected; held,
    blocked or unverified items are not.
  * A Codex path that is a real directory/file, or a link pointing anywhere
    other than the canonical folder, is reported as a conflict and left
    alone.
  * Links this module created are recorded in a state file beside the
    lockfile. Only a recorded link still pointing at its recorded target is
    ever removed, and only once the skill no longer resolves in any layer.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Optional

PROJECTED_ROLES = frozenset({"organization", "department"})
STATE_FILENAME = "skill-distribution.json"
_OK_OPS = frozenset({"added", "updated", "unchanged"})


def state_path_for(lockfile_path: Path | str) -> Path:
    return Path(lockfile_path).parent / STATE_FILENAME


def codex_skills_dir(env: Optional[dict[str, str]] = None) -> Path:
    env = os.environ if env is None else env
    codex_home = env.get("CODEX_HOME")
    base = Path(codex_home).expanduser() if codex_home else Path.home() / ".codex"
    return base / "skills"


def read_state(path: Path) -> dict[str, dict[str, str]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    skills = raw.get("skills") if isinstance(raw, dict) else None
    if not isinstance(skills, dict):
        return {}
    return {
        str(k): {"target": str(v["target"]), "layer": str(v.get("layer", ""))}
        for k, v in skills.items()
        if isinstance(v, dict) and v.get("target")
    }


def _write_state(path: Path, skills: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"version": 1, "skills": dict(sorted(skills.items()))}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _points_to(link: Path, target: Path) -> bool:
    try:
        if not link.is_symlink():
            return False
        return link.resolve() == target.resolve()
    except OSError:
        return False


def has_work(
    ops: Iterable[dict[str, Any]], layer_roles: dict[str, str], state_path: Path
) -> bool:
    """True when an org/department Claude skill op exists or links are recorded,
    so callers resolve the Codex directory only when something may be touched."""
    if read_state(state_path):
        return True
    return any(
        op.get("product") == "claude"
        and op.get("dimension") == "skills"
        and layer_roles.get(str(op.get("layer", ""))) in PROJECTED_ROLES
        for op in ops
    )


def project_org_skills(
    ops: Iterable[dict[str, Any]],
    resolved: Iterable[dict[str, Any]],
    *,
    layer_roles: dict[str, str],
    codex_dir: Path,
    state_path: Path,
    dry_run: bool = False,
) -> list[dict[str, str]]:
    """Link each materialized org/department Claude skill into `codex_dir`.

    Returns report rows `{skill, action, path, target, reason}` with action in
    linked | unchanged | conflict | removed | skipped.
    """
    rows: list[dict[str, str]] = []
    state = read_state(state_path)
    new_state = dict(state)
    wanted: dict[str, tuple[Path, str]] = {}

    resolved_skill_names = {
        e["item"]
        for e in resolved
        if e.get("dimension") == "skills" and (e.get("product") or "claude") == "claude"
    }

    for op in ops:
        if op.get("product") != "claude" or op.get("dimension") != "skills":
            continue
        layer = str(op.get("layer", ""))
        if layer_roles.get(layer) not in PROJECTED_ROLES:
            continue
        if op.get("op") == "pruned":
            continue  # removal is handled from the recorded state below
        path = Path(str(op["path"]))
        name = path.name
        if op.get("op") not in _OK_OPS:
            rows.append(
                {
                    "skill": name,
                    "action": "skipped",
                    "path": str(codex_dir / name),
                    "target": str(path),
                    "reason": f"Claude copy not verified/placed ({op.get('op')}: {op.get('reason') or 'no reason'})",
                }
            )
            continue
        if not dry_run and not (path / "SKILL.md").is_file():
            rows.append(
                {
                    "skill": name,
                    "action": "skipped",
                    "path": str(codex_dir / name),
                    "target": str(path),
                    "reason": "no SKILL.md in the Claude copy",
                }
            )
            continue
        wanted[name] = (path, layer)

    for name, (target, layer) in sorted(wanted.items()):
        link = codex_dir / name
        row = {"skill": name, "path": str(link), "target": str(target), "reason": ""}
        if link.is_symlink() or link.exists():
            if _points_to(link, target):
                row["action"] = "unchanged"
                rows.append(row)
                if name in state:
                    new_state[name] = {"target": str(target), "layer": layer}
                continue
            row["action"] = "conflict"
            row["reason"] = (
                "a real directory or file is already there; left in place, review and replace it by hand"
                if not link.is_symlink()
                else f"a link to {os.readlink(link)} is already there; left in place"
            )
            rows.append(row)
            continue
        row["action"] = "linked"
        if not dry_run:
            codex_dir.mkdir(parents=True, exist_ok=True)
            link.symlink_to(target)
            new_state[name] = {"target": str(target), "layer": layer}
        rows.append(row)

    for name, rec in sorted(state.items()):
        if name in resolved_skill_names or name in wanted:
            continue
        link = codex_dir / name
        if link.is_symlink() and os.readlink(link) == rec["target"]:
            if not dry_run:
                link.unlink()
            new_state.pop(name, None)
            rows.append(
                {
                    "skill": name,
                    "action": "removed",
                    "path": str(link),
                    "target": rec["target"],
                    "reason": "skill no longer provided by any layer",
                }
            )
        elif not link.is_symlink() and not link.exists():
            new_state.pop(name, None)

    if not dry_run and new_state != state:
        _write_state(state_path, new_state)
    return rows


def verify_distribution(
    *, claude_dir: Path, codex_dir: Path, state_path: Path
) -> list[dict[str, str]]:
    """Check that both harnesses see every skill cc distributed.

    Returns problem rows `{skill, problem}`; empty means healthy.
    """
    problems: list[dict[str, str]] = []
    for name, rec in sorted(read_state(state_path).items()):
        canonical = Path(rec["target"])
        if not (canonical / "SKILL.md").is_file():
            problems.append(
                {"skill": name, "problem": f"Claude copy missing SKILL.md: {canonical}"}
            )
            continue
        claude_view = claude_dir / name
        try:
            claude_ok = (
                claude_view / "SKILL.md"
            ).is_file() and claude_view.resolve() == canonical.resolve()
        except OSError:
            claude_ok = False
        if not claude_ok:
            problems.append(
                {
                    "skill": name,
                    "problem": f"Claude does not see {name} at {claude_view}",
                }
            )
        codex_view = codex_dir / name
        try:
            codex_ok = (
                codex_view / "SKILL.md"
            ).is_file() and codex_view.resolve() == canonical.resolve()
        except OSError:
            codex_ok = False
        if not codex_ok:
            problems.append(
                {"skill": name, "problem": f"Codex does not see {name} at {codex_view}"}
            )
    return problems
