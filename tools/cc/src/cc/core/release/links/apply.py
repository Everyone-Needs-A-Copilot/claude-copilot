"""Apply a link plan to a HOME: receipt-owned, idempotent, atomic, non-clobbering."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..engine import layout
from .plan import FRAMEWORK_RULES_IMPORT, LinkEntry, LinkPlan

RECEIPT_SCHEMA = 1
CODEX_BUDGET_BYTES = 32 * 1024
BLOCK_BEGIN = "<!-- BEGIN COPILOT FRAMEWORK (generated; do not edit) -->"
BLOCK_END = "<!-- END COPILOT FRAMEWORK -->"


@dataclass
class ApplyReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)  # non-framework / modified items
    claude_md: str = "unchanged"
    agents_md: str = "skipped"
    codex_combined_bytes: int = 0
    codex_budget_bytes: int = CODEX_BUDGET_BYTES
    errors: list[str] = field(default_factory=list)
    agents_sep: str | None = None
    description_chars: dict[str, int] = field(default_factory=dict)
    project_collisions: list[dict[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _read_receipt(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": RECEIPT_SCHEMA, "links": [], "generated": []}
    return data if isinstance(data, dict) and data.get("schema") == RECEIPT_SCHEMA else {
        "schema": RECEIPT_SCHEMA, "links": [], "generated": []}


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.cc-tmp-{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _atomic_symlink(link: Path, target: str) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    tmp = link.with_name(f".{link.name}.cc-tmp-{os.getpid()}")
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    os.symlink(target, tmp)
    os.replace(tmp, link)


def _link_target(path: Path) -> str | None:
    return os.readlink(path) if path.is_symlink() else None


def _materialize_generated(entry: LinkEntry) -> None:
    directory = Path(entry.target)
    directory.mkdir(parents=True, exist_ok=True)
    _atomic_write(directory / "SKILL.md", entry.generated or "")


def _sync_entry(home: Path, entry: LinkEntry, owned: dict[str, str], report: ApplyReport,
                dry_run: bool) -> bool:
    """Make one link match; True if the receipt should record it."""
    path = home / entry.link
    current = _link_target(path)
    if current == entry.target:
        report.unchanged.append(entry.link)
        return True
    if current is None and not path.exists():
        if not dry_run:
            if entry.generated is not None:
                _materialize_generated(entry)
            _atomic_symlink(path, entry.target)
        report.created.append(entry.link)
        return True
    if current is not None and owned.get(entry.link) == current:
        if not dry_run:
            if entry.generated is not None:
                _materialize_generated(entry)
            _atomic_symlink(path, entry.target)
        report.updated.append(entry.link)
        return True
    reason = ("modified since generated" if entry.link in owned
              else "exists and is not a framework link")
    report.skipped.append({"path": entry.link, "reason": reason})
    return False


def _remove_stale(home: Path, owned: dict[str, str], keep: set[str], report: ApplyReport,
                  dry_run: bool) -> None:
    for link, target in sorted(owned.items()):
        if link in keep:
            continue
        path = home / link
        if _link_target(path) == target:
            if not dry_run:
                path.unlink()
            report.removed.append(link)
        elif path.exists() or path.is_symlink():
            report.skipped.append({"path": link, "reason": "stale link modified; left in place"})


def _apply_claude_md(home: Path, receipt: dict[str, Any], dry_run: bool) -> tuple[str, dict[str, Any]]:
    path = home / ".claude" / "CLAUDE.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if any(line.strip() == FRAMEWORK_RULES_IMPORT for line in text.splitlines()):
        return "unchanged", receipt.get("claude_md") or {"line": FRAMEWORK_RULES_IMPORT, "added": False}
    prefix = "" if (not text or text.endswith("\n")) else "\n"
    if not dry_run:
        _atomic_write(path, text + prefix + FRAMEWORK_RULES_IMPORT + "\n")
    return "added", {"line": FRAMEWORK_RULES_IMPORT, "added": True, "prefix": prefix}


def _split_block(text: str) -> tuple[str, str] | None:
    start = text.find(BLOCK_BEGIN)
    end = text.find(BLOCK_END)
    if start < 0 or end < start:
        return None
    after = text[end + len(BLOCK_END):]
    return text[:start], after[1:] if after.startswith("\n") else after


def _apply_agents_md(home: Path, plan: LinkPlan, report: ApplyReport, dry_run: bool) -> bool:
    path = home / ".codex" / "AGENTS.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if plan.agents_block is None:
        report.codex_combined_bytes = len(text.encode())
        return False
    block = f"{BLOCK_BEGIN}\n{plan.agents_block.rstrip(chr(10))}\n{BLOCK_END}\n"
    parts = _split_block(text)
    if parts is not None:
        before, after = parts
        new = before + block + after
        status = "unchanged" if new == text else "updated"
    else:
        sep = "" if not text else ("\n" if text.endswith("\n") else "\n\n")
        new = text + sep + block
        status = "added"
        report.agents_sep = sep
    report.codex_combined_bytes = len(new.encode())
    if report.codex_combined_bytes > CODEX_BUDGET_BYTES:
        report.errors.append(
            f"~/.codex/AGENTS.md would be {report.codex_combined_bytes} bytes, over the "
            f"{CODEX_BUDGET_BYTES} byte budget; block not written (owner decision needed)")
        report.agents_md = "over-budget"
        return False
    if status != "unchanged" and not dry_run:
        _atomic_write(path, new)
    report.agents_md = status
    return True


def apply_plan(plan: LinkPlan, home: Path | str | None = None, *, dry_run: bool = False) -> ApplyReport:
    """Create, update and remove links so HOME matches the plan; only receipt-owned items change."""
    base = Path(home) if home is not None else Path.home()
    report = ApplyReport(description_chars=dict(plan.description_chars),
                         project_collisions=list(plan.project_collisions))
    receipt_path = layout.links_receipt_path(base)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    with open(receipt_path.with_name(receipt_path.name + ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        receipt = _read_receipt(receipt_path)
        owned = {row["path"]: row["target"] for row in receipt.get("links", [])}
        recorded: list[dict[str, str]] = []
        keep: set[str] = set()
        for entry in plan.entries:
            keep.add(entry.link)
            if _sync_entry(base, entry, owned, report, dry_run):
                recorded.append({"path": entry.link, "target": entry.target, "runtime": entry.runtime,
                                 "kind": entry.kind, "source": entry.source})
        _remove_stale(base, owned, keep, report, dry_run)
        report.claude_md, claude_state = _apply_claude_md(base, receipt, dry_run)
        wrote_block = _apply_agents_md(base, plan, report, dry_run)
        if not dry_run:
            new_receipt = {
                "schema": RECEIPT_SCHEMA, "release": plan.release_id, "links": recorded,
                "claude_md": claude_state,
                "agents_md": ({"sep": report.agents_sep} if report.agents_sep is not None else receipt.get("agents_md"))
                if (wrote_block or receipt.get("agents_md")) else None,
            }
            _atomic_write(receipt_path, json.dumps(new_receipt, indent=2, sort_keys=True) + "\n")
    return report


def remove_all(home: Path | str | None = None) -> ApplyReport:
    """Undo everything the receipt owns (links, import line, AGENTS block); owner items stay."""
    base = Path(home) if home is not None else Path.home()
    report = ApplyReport()
    receipt_path = layout.links_receipt_path(base)
    receipt = _read_receipt(receipt_path)
    owned = {row["path"]: row["target"] for row in receipt.get("links", [])}
    _remove_stale(base, owned, set(), report, False)
    state = receipt.get("claude_md") or {}
    path = base / ".claude" / "CLAUDE.md"
    if state.get("added") and path.is_file():
        text = path.read_text(encoding="utf-8")
        tail = state.get("prefix", "") + state["line"] + "\n"
        if text.endswith(tail):
            _atomic_write(path, text[: -len(tail)])
            report.claude_md = "removed"
    agents = base / ".codex" / "AGENTS.md"
    state_md = receipt.get("agents_md")
    if state_md and agents.is_file():
        parts = _split_block(agents.read_text(encoding="utf-8"))
        if parts is not None:
            before, after = parts
            sep = state_md.get("sep", "") if isinstance(state_md, dict) else ""
            if sep and before.endswith(sep):
                before = before[: -len(sep)]
            _atomic_write(agents, before + after)
            report.agents_md = "removed"
    shutil.rmtree(layout.copilot_home(base) / "generated" / "command-skills", ignore_errors=True)
    if receipt_path.exists():
        receipt_path.unlink()
    return report
