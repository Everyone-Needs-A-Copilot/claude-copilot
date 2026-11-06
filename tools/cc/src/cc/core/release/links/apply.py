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
from . import adopt as adoption
from .plan import FRAMEWORK_RULES_IMPORT, LinkEntry, LinkPlan, is_safe_link_path

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
    adopted: list[dict[str, str]] = field(default_factory=list)  # framework-owned copies backed up and linked
    customized: list[dict[str, str]] = field(default_factory=list)  # owner-customized copies kept (name, path, shadows, diff)
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


def _read_text(path: Path) -> str:
    """Read without newline translation so owner line endings survive."""
    if not path.is_file():
        return ""
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def _newline_of(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _atomic_write(path: Path, text: str) -> None:
    """Write beside the real target (a symlink is followed, never replaced) and rename."""
    real = Path(os.path.realpath(path))
    real.parent.mkdir(parents=True, exist_ok=True)
    tmp = real.with_name(f".{real.name}.cc-tmp-{os.getpid()}")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    try:
        os.chmod(tmp, os.stat(real).st_mode & 0o7777)
    except OSError:
        pass
    os.replace(tmp, real)


def _link_escapes(home: Path, link: str) -> bool:
    """True when the link name is unsafe or its resolved location leaves HOME."""
    if not is_safe_link_path(link):
        return True
    real_home = Path(os.path.realpath(home))
    real_dir = Path(os.path.realpath((home / link).parent))
    if real_home not in (real_dir, *real_dir.parents):
        return True
    return False


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


def _backup_copy(home: Path, link: str, release_id: str, dry_run: bool) -> str:
    """Move a framework-owned real copy into the release backup area; returns the backup path."""
    root = adoption.backup_dir(home, release_id)
    dest = root / link
    n = 0
    while dest.exists() or dest.is_symlink():
        n += 1
        dest = root / f"{link}.{n}"
    if not dry_run:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(home / link), str(dest))
    return str(dest)


def _sync_entry(home: Path, entry: LinkEntry, owned: dict[str, str], report: ApplyReport,
                dry_run: bool, adopt_paths: frozenset[str] = frozenset(), release_id: str = "",
                adopt_links: dict[str, str] | None = None) -> bool:
    """Make one link match; True if the receipt should record it."""
    if _link_escapes(home, entry.link):
        report.skipped.append({"path": entry.link, "reason": "unsafe link path rejected"})
        report.errors.append(f"unsafe link path rejected: {entry.link!r}")
        return False
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
    if entry.link in adopt_paths and (current is None or entry.link in (adopt_links or {})):
        backup = _backup_copy(home, entry.link, release_id, dry_run)
        if not dry_run:
            if entry.generated is not None:
                _materialize_generated(entry)
            _atomic_symlink(path, entry.target)
        row = {"path": entry.link, "backup": backup}
        if current is not None:
            row.update(kind="symlink", old_target=current)
        report.adopted.append(row)
        report.created.append(entry.link)
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
        if _link_escapes(home, link):
            report.skipped.append({"path": link, "reason": "unsafe link path rejected"})
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
    text = _read_text(path)
    if any(line.strip() == FRAMEWORK_RULES_IMPORT for line in text.splitlines()):
        return "unchanged", receipt.get("claude_md") or {"line": FRAMEWORK_RULES_IMPORT, "added": False}
    nl = _newline_of(text)
    prefix = "" if (not text or text.endswith("\n")) else nl
    if not dry_run:
        _atomic_write(path, text + prefix + FRAMEWORK_RULES_IMPORT + nl)
    return "added", {"line": FRAMEWORK_RULES_IMPORT, "added": True, "prefix": prefix, "nl": nl}


def _split_block(text: str) -> tuple[str, str] | None:
    start = text.find(BLOCK_BEGIN)
    end = text.find(BLOCK_END)
    if start < 0 or end < start:
        return None
    after = text[end + len(BLOCK_END):]
    if after.startswith("\r\n"):
        return text[:start], after[2:]
    return text[:start], after[1:] if after.startswith("\n") else after


def _apply_agents_md(home: Path, plan: LinkPlan, report: ApplyReport, dry_run: bool) -> bool:
    path = home / ".codex" / "AGENTS.md"
    text = _read_text(path)
    if plan.agents_block is None:
        report.codex_combined_bytes = len(text.encode())
        return False
    nl = _newline_of(text)
    body = plan.agents_block.replace("\r\n", "\n").rstrip("\n").replace("\n", nl)
    block = f"{BLOCK_BEGIN}{nl}{body}{nl}{BLOCK_END}{nl}"
    parts = _split_block(text)
    if parts is not None:
        before, after = parts
        new = before + block + after
        status = "unchanged" if new == text else "updated"
    else:
        sep = "" if not text else (nl if text.endswith("\n") else nl * 2)
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


def apply_plan(plan: LinkPlan, home: Path | str | None = None, *, dry_run: bool = False,
               adopt: adoption.FrameworkIndex | bool | None = None) -> ApplyReport:
    """Create, update and remove links so HOME matches the plan; only receipt-owned items change.

    `adopt` turns on adoption: a FrameworkIndex, or True to build `default_index` from HOME and the
    release. Real copies matching a historical framework version are backed up and linked; others are
    kept and listed in `report.customized`. Without it, real copies are skipped as before.
    """
    base = Path(home) if home is not None else Path.home()
    report = ApplyReport(description_chars=dict(plan.description_chars),
                         project_collisions=list(plan.project_collisions))
    result = adoption.AdoptionResult()
    if adopt:
        index = adopt if isinstance(adopt, adoption.FrameworkIndex) else adoption.default_index(
            base, layout.release_dir(plan.release_id, base))
        result = adoption.classify(plan, base, index)
    adopt_paths = frozenset(a.path for a in result.adopt)
    adopt_links = {a.path: a.old_target for a in result.adopt if a.kind == "symlink"}
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
            if _sync_entry(base, entry, owned, report, dry_run, adopt_paths, plan.release_id, adopt_links):
                recorded.append({"path": entry.link, "target": entry.target, "runtime": entry.runtime,
                                 "kind": entry.kind, "source": entry.source})
        for item in result.adopt:  # category folders: stale copies of skills the links already serve
            if item.path not in keep:
                if item.kind == "symlink":
                    continue  # only links the plan serves are repointed
                report.adopted.append({"path": item.path,
                                       "backup": _backup_copy(base, item.path, plan.release_id, dry_run)})
        report.customized.extend(c.as_dict() for c in result.customized)
        _remove_stale(base, owned, keep, report, dry_run)
        report.claude_md, claude_state = _apply_claude_md(base, receipt, dry_run)
        wrote_block = _apply_agents_md(base, plan, report, dry_run)
        if not dry_run:
            new_receipt = {
                "schema": RECEIPT_SCHEMA, "release": plan.release_id, "links": recorded,
                "claude_md": claude_state,
                "adopted": sorted(
                    [*({k: v for k, v in a.items()} for a in report.adopted),
                     *(row for row in receipt.get("adopted", [])
                       if row["path"] not in {a["path"] for a in report.adopted})],
                    key=lambda r: r["path"]),
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
        text = _read_text(path)
        tail = state.get("prefix", "") + state["line"] + state.get("nl", "\n")
        if text.endswith(tail):
            _atomic_write(path, text[: -len(tail)])
            report.claude_md = "removed"
    agents = base / ".codex" / "AGENTS.md"
    state_md = receipt.get("agents_md")
    if state_md and agents.is_file():
        parts = _split_block(_read_text(agents))
        if parts is not None:
            before, after = parts
            sep = state_md.get("sep", "") if isinstance(state_md, dict) else ""
            if sep and before.endswith(sep):
                before = before[: -len(sep)]
            _atomic_write(agents, before + after)
            report.agents_md = "removed"
    for row in receipt.get("adopted", []):  # put the owner's pre-adoption copies back
        dest, src = base / row["path"], Path(row["backup"])
        if not is_safe_link_path(row["path"]) or dest.exists() or dest.is_symlink():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.exists() or src.is_symlink():
            shutil.move(str(src), str(dest))
        elif row.get("kind") == "symlink" and row.get("old_target"):
            os.symlink(row["old_target"], dest)  # backup gone: recreate from the recorded target
    shutil.rmtree(layout.copilot_home(base) / "generated" / "command-skills", ignore_errors=True)
    if receipt_path.exists():
        receipt_path.unlink()
    return report
