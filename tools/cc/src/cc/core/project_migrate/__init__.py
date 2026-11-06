"""`cc project migrate`: convert a synced project to the central model (library; wiring elsewhere)."""

from cc.core.project_migrate.apply import apply_migration, default_backup_root
from cc.core.project_migrate.known import Known, build_known
from cc.core.project_migrate.model import Item, MigrateError, MigrationPlan
from cc.core.project_migrate.planner import plan_migration
from cc.core.project_migrate.render import render_plan, render_receipt
from cc.core.project_migrate.rollback import find_manifest, rollback_migration
from cc.core.project_migrate.scan import find_projects, scan_project, scan_projects

__all__ = [
    "apply_migration", "default_backup_root", "Known", "build_known", "Item", "MigrateError",
    "find_manifest", "MigrationPlan", "plan_migration", "render_plan", "render_receipt", "rollback_migration",
    "find_projects", "scan_project", "scan_projects",
]
