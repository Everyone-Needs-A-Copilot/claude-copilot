"""cc rule — put a correction where it belongs, as a rewrite, never an appended exception."""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional

import typer

rule_app = typer.Typer(
    name="rule",
    help="Add, list and propose rules (rewrite in place; no appended exceptions).",
    no_args_is_help=True,
)

DESTINATIONS = ("global", "framework", "project", "memory")
_BULLET = re.compile(r"^(\s*(?:[-*]|\d+\.)\s+)")
_DATE_SUFFIX = re.compile(r"\(\d{4}-\d{2}-\d{2}\)\s*$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class RuleError(Exception):
    """A rule operation that cannot be done safely."""


def rules_log_path() -> Path:
    from cc.core.config_paths import _machine_root

    return _machine_root() / "rules-log.jsonl"


# ---------------------------------------------------------------------------
# Pure text operations
# ---------------------------------------------------------------------------


def with_date(text: str, when: str) -> str:
    text = text.strip()
    if _DATE_SUFFIX.search(text):
        return text
    return f"{text} ({when})"


def _heading_title(line: str) -> str | None:
    m = re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
    return m.group(2) if m else None


def _section_of(lines: list[str], index: int) -> str | None:
    for i in range(index, -1, -1):
        if lines[i].startswith("## "):
            return _heading_title(lines[i])
    return None


def replace_rule(lines: list[str], needle: str, text: str) -> tuple[list[str], str, str | None]:
    """Replace the one line containing *needle*. Returns (lines, old line, section)."""
    hits = [i for i, line in enumerate(lines) if needle in line]
    if not hits:
        raise RuleError(f"--replaces matched no line: {needle!r}")
    if len(hits) > 1:
        shown = ", ".join(str(i + 1) for i in hits)
        raise RuleError(f"--replaces matched {len(hits)} lines ({shown}); use a longer substring")
    i = hits[0]
    old = lines[i]
    m = _BULLET.match(old)
    prefix = m.group(1) if m and not _BULLET.match(text) else ""
    out = list(lines)
    out[i] = prefix + text
    return out, old, _section_of(lines, i)


def insert_in_section(lines: list[str], heading: str, text: str) -> list[str]:
    """Insert *text* as the last bullet under the `## heading` section."""
    wanted = heading.strip().lstrip("#").strip()
    start = next(
        (i for i, line in enumerate(lines) if line.startswith("## ") and _heading_title(line) == wanted),
        None,
    )
    if start is None:
        raise RuleError(f"--section heading not found: ## {wanted}")
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"^#{1,2}\s", lines[i]):
            end = i
            break
    last_bullet = None
    for i in range(start + 1, end):
        if _BULLET.match(lines[i]):
            last_bullet = i
    bullet = text if _BULLET.match(text) else f"- {text}"
    out = list(lines)
    if last_bullet is not None:
        out.insert(last_bullet + 1, bullet)
        return out
    # No bullets yet: after the heading and its blank line.
    at = start + 1
    if at < len(out) and out[at].strip() == "":
        out.insert(at + 1, bullet)
    else:
        out[at:at] = ["", bullet]
    return out


def propose_destination(text: str) -> dict[str, str]:
    """Placement test from the bloat guard. A proposal, not an enforcement."""
    low = text.lower()
    fact_markers = ("is at", "lives in", "the key", "credentials", "http://", "https://")
    process_markers = ("run", "before", "always", "every time", "hook", "gate")
    products = (
        "Convoco", "Insights Copilot", "Pipeline Copilot", "Method", "Forces Assessment",
        "Task Copilot", "this project", "this repo",
    )
    names_product = any(p in text if p[0].isupper() else p in low for p in products)
    if any(m in low for m in fact_markers) or re.search(r"(?:^|\s)(?:~|/)[\w.-]+/", text):
        return {
            "destination": "memory",
            "kind": "fact",
            "reason": "It is a fact to look up on demand, so it belongs in memory, not in always-loaded instructions.",
        }
    if any(re.search(rf"\b{re.escape(m)}\b", low) for m in process_markers):
        dest = "project" if names_product else "framework"
        return {
            "destination": dest,
            "kind": "procedure",
            "reason": f"It describes a process step, so prefer a default, gate, hook or command in the {dest} over prose.",
        }
    dest = "project" if names_product else "global"
    scope = "names a product, so it applies to that project" if dest == "project" else "names no product, so it applies to every project"
    return {
        "destination": dest,
        "kind": "judgment",
        "reason": f"It is judgment prose that {scope}.",
    }


# ---------------------------------------------------------------------------
# Destinations, log
# ---------------------------------------------------------------------------


def _framework_root() -> Path:
    try:
        from cc.core.config import resolve_key

        root = resolve_key("paths.claude_copilot_root", scope="machine")
        if root:
            return Path(str(root)).expanduser()
    except Exception:  # noqa: BLE001 -- config trouble falls back to the convention
        pass
    return Path.home() / ".claude" / "copilot"


def resolve_target(destination: str, file: Optional[str]) -> Path:
    if destination == "global":
        return Path(file).expanduser() if file else Path.home() / ".claude" / "CLAUDE.md"
    if destination == "project":
        return Path(file).expanduser() if file else Path.cwd() / "CLAUDE.md"
    if destination == "framework":
        if not file:
            raise RuleError("--destination framework needs --file (relative to the framework root)")
        p = Path(file).expanduser()
        return p if p.is_absolute() else _framework_root() / p
    raise RuleError(f"unknown destination: {destination}")


def _append_log(entry: dict[str, Any]) -> None:
    path = rules_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_log() -> list[dict[str, Any]]:
    path = rules_log_path()
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _fail(message: str, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps({"ok": False, "error": message}))
    else:
        typer.echo(f"error: {message}", err=True)
    raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@rule_app.command("add")
def rule_add(
    text: str = typer.Option(..., "--text", help="The rule, one current statement."),
    destination: str = typer.Option("global", "--destination", help="global|framework|project|memory"),
    replaces: Optional[str] = typer.Option(None, "--replaces", help="Substring of the one current rule line to rewrite."),
    section: Optional[str] = typer.Option(None, "--section", help="`## ` heading to insert under (last bullet)."),
    file: Optional[str] = typer.Option(None, "--file", help="Target file (required for framework)."),
    when: Optional[str] = typer.Option(None, "--date", help="YYYY-MM-DD; default today."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the result without writing or logging."),
    output_json: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Write a rule as a rewrite or a section insert, never appended at the end."""
    if destination not in DESTINATIONS:
        _fail(f"--destination must be one of {', '.join(DESTINATIONS)}", output_json)
    when = when or date.today().isoformat()
    if not _ISO_DATE.match(when):
        _fail("--date must be YYYY-MM-DD", output_json)
    if not text.strip():
        _fail("--text must not be empty", output_json)
    final = with_date(text, when)
    record: dict[str, Any] = {
        "destination": destination, "file": None, "section": section, "replaced": None, "text": final,
    }
    try:
        if destination == "memory":
            record["section"] = None
            if not dry_run:
                from cc import api

                result = api.memory_store(entry_type="lesson", content=final, scope="global")
                record["file"] = result.get("path")
        else:
            if not replaces and not section:
                raise RuleError(
                    "give --replaces (rewrite the current rule) or --section (insert in a section); "
                    "appending at the end of a rulebook is not allowed"
                )
            target = resolve_target(destination, file)
            if not target.is_file():
                raise RuleError(f"target file not found: {target}")
            record["file"] = str(target)
            original = target.read_text(encoding="utf-8")
            lines = original.split("\n")
            if replaces:
                lines, old, found_section = replace_rule(lines, replaces, final)
                record["replaced"] = old
                record["section"] = found_section
            else:
                lines = insert_in_section(lines, section or "", final)
            if not dry_run:
                target.write_text("\n".join(lines), encoding="utf-8")
    except RuleError as exc:
        _fail(str(exc), output_json)
    except Exception as exc:  # noqa: BLE001 -- memory/IO failures are reported, not traced
        _fail(f"{type(exc).__name__}: {exc}", output_json)

    record["dryRun"] = dry_run
    if not dry_run:
        from datetime import datetime, timezone

        _append_log({"recordedAt": datetime.now(timezone.utc).isoformat(), **{k: record[k] for k in ("destination", "file", "section", "replaced", "text")}})
    if output_json:
        typer.echo(json.dumps({"ok": True, **record}))
        return
    verb = "Would write" if dry_run else "Wrote"
    how = "rewrote the current rule" if record["replaced"] else ("stored a lesson" if destination == "memory" else "inserted under the section")
    typer.echo(f"{verb} to {destination}: {how}.")
    if record["file"]:
        typer.echo(f"File: {record['file']}")
    if record["section"]:
        typer.echo(f"Section: {record['section']}")
    if record["replaced"]:
        typer.echo(f"Was: {record['replaced'].strip()}")
    typer.echo(f"Now: {final}")


@rule_app.command("list")
def rule_list(
    since: Optional[str] = typer.Option(None, "--since", help="Only entries recorded on or after YYYY-MM-DD."),
    output_json: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Print the append-only rules log."""
    if since and not _ISO_DATE.match(since):
        _fail("--since must be YYYY-MM-DD", output_json)
    rows = [r for r in read_log() if not since or str(r.get("recordedAt", ""))[:10] >= since]
    if output_json:
        typer.echo(json.dumps(rows))
        return
    if not rows:
        typer.echo("No rules recorded.")
        return
    for r in rows:
        where = r.get("file") or "memory"
        typer.echo(f"{str(r.get('recordedAt', ''))[:10]}  {r.get('destination')}  {where}  {r.get('text')}")


@rule_app.command("propose")
def rule_propose(
    text: str = typer.Option(..., "--text", help="The correction."),
    output_json: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Recommend a destination using the placement test (judgment, procedure, fact)."""
    result = propose_destination(text)
    if output_json:
        typer.echo(json.dumps(result))
        return
    typer.echo(f"Recommended destination: {result['destination']}")
    typer.echo(result["reason"])
