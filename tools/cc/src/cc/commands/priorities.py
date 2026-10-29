"""cc priorities — weekly outcomes read from every project's Task Copilot database."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any, Optional

import typer

STALE_DAYS = 14
_OWNER_RE = re.compile(r"DECISION NEEDED|approval|approve", re.IGNORECASE)
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
_OPEN = ("pending", "in_progress", "blocked")


def _registry_paths() -> list[Path]:
    registry = Path.home() / ".copilot" / "known-projects.json"
    try:
        roots = json.loads(registry.read_text(encoding="utf-8")).get("roots", {})
    except (OSError, json.JSONDecodeError, AttributeError):
        return []
    if not isinstance(roots, dict):
        return []
    return [Path(p).expanduser() for items in roots.values() if isinstance(items, list) for p in items if isinstance(p, str)]


def _home_sites_paths() -> list[Path]:
    sites = Path.home() / "Sites"
    return [child for group in sorted(sites.glob("*")) if group.is_dir() for child in sorted(group.glob("*"))]


def discover_dbs() -> list[Path]:
    override = os.environ.get("CC_PROJECT_ROOTS")
    if override:
        roots = [Path(p).expanduser() for p in override.split(":") if p]
    else:
        roots = _registry_paths() or _home_sites_paths()
    out = []
    for p in sorted({r / ".copilot" / "tasks.db" for r in roots}):
        s = p.as_posix()
        if "/.worktrees/" in s or "/.claude/worktrees/" in s or not p.is_file():
            continue
        out.append(p)
    return out


def _day(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _latest(*values: Any) -> date | None:
    days = [d for d in (_day(v) for v in values) if d]
    return max(days) if days else None


def _meta(raw: Any) -> dict[str, Any]:
    try:
        data = json.loads(raw) if raw else {}
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def blocked_on_owner(task: dict[str, Any]) -> bool:
    if task["status"] == "blocked":
        return True
    if _meta(task["metadata"]).get("awaiting") == "owner":
        return True
    haystack = " ".join(str(task.get(k) or "") for k in ("title", "description", "metadata"))
    return bool(_OWNER_RE.search(haystack))


def _depth(task_id: int, deps: dict[int, list[int]], seen: frozenset[int] = frozenset()) -> int:
    if task_id in seen:
        return 0
    parents = deps.get(task_id, [])
    return 0 if not parents else 1 + max(_depth(p, deps, seen | {task_id}) for p in parents)


def read_project(db: Path, today: date) -> dict[str, Any] | None:
    uri = f"file:{db}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return None
    conn.row_factory = sqlite3.Row
    try:
        tasks = [dict(r) for r in conn.execute("SELECT * FROM tasks")]
        prds = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM prds")}
        deps: dict[int, list[int]] = {}
        for r in conn.execute("SELECT task_id, depends_on FROM task_dependencies"):
            deps.setdefault(r["task_id"], []).append(r["depends_on"])
        wp = {r["task_id"]: r["m"] for r in conn.execute("SELECT task_id, MAX(created_at) m FROM work_products GROUP BY task_id")}
        log = {r["task_id"]: r["m"] for r in conn.execute("SELECT task_id, MAX(created_at) m FROM agent_log GROUP BY task_id")}
    except sqlite3.Error:
        return None
    finally:
        conn.close()

    by_id = {t["id"]: t for t in tasks}
    open_tasks = [t for t in tasks if t["status"] in _OPEN]
    if not open_tasks:
        return None
    activity: dict[int, date | None] = {
        t["id"]: _latest(t["updated_at"], wp.get(t["id"]), log.get(t["id"])) for t in tasks
    }
    last = _latest(*[activity[t["id"]] for t in tasks if activity[t["id"]]], *[p["updated_at"] for p in prds.values()])
    prd_activity: dict[int, date | None] = {}
    for pid, prd in prds.items():
        prd_activity[pid] = _latest(prd["updated_at"], *[activity[t["id"]] for t in tasks if t["prd_id"] == pid])

    ready = [
        t for t in open_tasks
        if all(by_id.get(d, {}).get("status") == "completed" for d in deps.get(t["id"], []))
    ]
    ready.sort(key=lambda t: (t["priority"], t["id"]))
    nxt = None
    if ready:
        t = ready[0]
        prd = prds.get(t["prd_id"])
        nxt = {
            "id": f"TASK-{t['id']}", "title": t["title"], "priority": t["priority"],
            "status": t["status"], "prd": prd["title"] if prd else None,
            "blockedOnOwner": blocked_on_owner(t), "dependencyDepth": _depth(t["id"], deps),
        }

    waiting = []
    for t in open_tasks:
        pa = prd_activity.get(t["prd_id"]) if t["prd_id"] in prds else None
        if pa and (today - pa).days >= STALE_DAYS:
            waiting.append({"id": f"TASK-{t['id']}", "title": t["title"], "prd": prds[t["prd_id"]]["title"], "prdLastActivity": pa.isoformat()})

    missing = []
    urgent = [t for t in open_tasks if t["priority"] <= 1]
    if urgent and not prds:
        missing.append({"kind": "no-prd", "detail": f"{len(urgent)} open P0/P1 task(s) and no PRD"})
    for t in open_tasks:
        raw = t["metadata"] or ""
        if "deadline" in raw.lower() and not _ISO.search(raw):
            missing.append({"kind": "deadline-without-date", "id": f"TASK-{t['id']}", "detail": "deadline mentioned with no date"})

    return {
        "project": db.parent.parent.name, "path": str(db.parent.parent),
        "openTasks": len(open_tasks), "openUrgent": len(urgent),
        "lastActivity": last.isoformat() if last else None,
        "stale": bool(last and (today - last).days >= STALE_DAYS),
        "nextAction": nxt, "shouldWait": waiting, "missing": missing,
    }


def build_report(dbs: list[Path], today: date) -> dict[str, Any]:
    projects = [p for p in (read_project(db, today) for db in dbs) if p]
    recent = sorted(projects, key=lambda p: p["lastActivity"] or "", reverse=True)
    candidates = [p for p in recent if p["openUrgent"] and p["nextAction"]]
    outcomes = candidates[:3]
    chosen = {p["project"] for p in outcomes}
    proceed = [
        p for p in recent
        if p["project"] not in chosen and p["nextAction"] and not p["nextAction"]["blockedOnOwner"]
    ]
    return {
        "week": today.isoformat(),
        "outcomes": [
            {
                "project": p["project"], "task": p["nextAction"]["id"], "nextAction": p["nextAction"]["title"],
                "prd": p["nextAction"]["prd"], "blockedOn": "owner decision" if p["nextAction"]["blockedOnOwner"] else "nothing",
                "dependencyDepth": p["nextAction"]["dependencyDepth"], "lastActivity": p["lastActivity"], "stale": p["stale"],
            }
            for p in outcomes
        ],
        "canProceedWithoutYou": [
            {"project": p["project"], "task": p["nextAction"]["id"], "nextAction": p["nextAction"]["title"],
             "prd": p["nextAction"]["prd"], "lastActivity": p["lastActivity"], "stale": p["stale"]}
            for p in proceed
        ],
        "shouldWait": [{"project": p["project"], "tasks": p["shouldWait"]} for p in recent if p["shouldWait"]],
        "missingInformation": [{"project": p["project"], "items": p["missing"]} for p in recent if p["missing"]],
    }


def render_text(report: dict[str, Any]) -> str:
    out = ["This week's three outcomes"]
    if not report["outcomes"]:
        out.append("  None: no project has open P0/P1 work with a ready next action.")
    for i, o in enumerate(report["outcomes"], 1):
        out.append(f"  {i}. {o['project']}: {o['nextAction']} ({o['task']}). Blocked on: {o['blockedOn']}.")
    out += ["", "Can proceed without you"]
    out += [f"  {p['project']}: {p['nextAction']} ({p['task']})" for p in report["canProceedWithoutYou"]] or ["  None."]
    out += ["", "Should wait"]
    for w in report["shouldWait"]:
        out.append(f"  {w['project']}:")
        out += [f"    {t['id']} {t['title']} (PRD '{t['prd']}' quiet since {t['prdLastActivity']})" for t in w["tasks"]]
    if not report["shouldWait"]:
        out.append("  None.")
    out += ["", "Missing information"]
    for m in report["missingInformation"]:
        for item in m["items"]:
            ref = f" {item['id']}" if item.get("id") else ""
            out.append(f"  {m['project']}{ref}: {item['detail']}")
    if not report["missingInformation"]:
        out.append("  None.")
    return "\n".join(out)


def priorities_cmd(
    week: Optional[str] = typer.Option(None, "--week", help="Reference date YYYY-MM-DD; default today."),
    output_json: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Weekly outcomes from every project's open tasks. Read-only."""
    try:
        today = date.fromisoformat(week) if week else date.today()
    except ValueError:
        typer.echo("error: --week must be YYYY-MM-DD", err=True)
        raise typer.Exit(1)
    report = build_report(discover_dbs(), today)
    typer.echo(json.dumps(report, indent=2) if output_json else render_text(report))
