"""Human-readable plan and receipt text."""

from __future__ import annotations

from typing import Any

from cc.core.project_migrate.model import MigrationPlan


def render_plan(plan: MigrationPlan) -> str:
    c = plan.counts()
    lines = [f"cc project migrate plan for {plan.project} (dry run: nothing written)"]
    lines.append("  " + ", ".join(f"{k}={v}" for k, v in sorted(c.items())))
    if plan.refused:
        lines.append("REFUSED: uncommitted changes on paths this plan would change:")
        lines += [f"  dirty  {d}" for d in plan.dirty]
    for title, kinds in (("REMOVE", ("delete", "unlink")), ("EDIT", ("edit-json", "edit-text")), ("WRITE", ("write",))):
        items = [a for a in plan.actions if a.kind in kinds]
        if items:
            lines.append(f"{title} ({len(items)}):")
            lines += [f"  {a.kind:9} {a.path}  [{a.reason}]" for a in items]
    if plan.holds:
        lines.append(f"HOLD ({len(plan.holds)}): kept, needs a decision:")
        lines += [f"  {h.path}  [{h.reason}]" for h in plan.holds]
    lines.append(f"KEEP ({len(plan.keeps)}):")
    lines += [f"  {k.path}  [{k.reason}]" for k in plan.keeps]
    lines += [f"note: {n}" for n in plan.notes]
    return "\n".join(lines)


def render_receipt(receipt: dict[str, Any]) -> str:
    lines = [f"Migrated. Backup and rollback manifest: {receipt['backup_dir']}"]
    if receipt.get("commit"):
        lines.append(f"Committed {receipt['commit']} on branch {receipt['branch']}")
    else:
        lines.append("Changes left uncommitted for review.")
    lines += [f"recover: {r}" for r in receipt["recovery"]]
    return "\n".join(lines)
