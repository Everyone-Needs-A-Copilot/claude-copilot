"""Read the newest private, redacted Control Tower support report."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

import typer

from cc.core.config_paths import machine_diagnostics_root

support_app = typer.Typer(
    help="Access redacted setup support reports.", no_args_is_help=True
)


def _latest_record(
    *, root: Optional[Path] = None
) -> tuple[Optional[Path], Optional[dict]]:
    diagnostics_root = (root or machine_diagnostics_root()).expanduser()
    directory = diagnostics_root / "control-tower"
    try:
        candidates = sorted(
            (
                candidate
                for candidate in directory.glob("setup-journey-*.json")
                if not candidate.is_symlink() and candidate.is_file()
            ),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
            reverse=True,
        )
    except OSError:
        return None, None
    for path in candidates:
        try:
            metadata = path.stat()
            if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
                continue
            payload: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (
            isinstance(payload, dict)
            and payload.get("schema_version") == "1.0"
            and payload.get("kind") == "setup-journey-support-report"
        ):
            return path, payload
    return None, None


def build_support_latest_report(*, root: Optional[Path] = None) -> dict[str, Any]:
    path, record = _latest_record(root=root)
    if path is None or record is None:
        return {
            "schema_version": "1.0",
            "result": "unavailable",
            "detail": "No private setup support report is available yet.",
            "path": None,
            "report": None,
        }
    return {
        "schema_version": "1.0",
        "result": "ready",
        "detail": "The newest private, redacted setup support report is available.",
        "path": str(path),
        "report": record,
    }


@support_app.command("latest")
def support_latest(
    output_json: bool = typer.Option(
        False,
        "--json",
        help="Print a paste-ready JSON envelope containing the redacted report.",
    ),
) -> None:
    report = build_support_latest_report()
    if output_json:
        typer.echo(json.dumps(report, indent=2, sort_keys=True))
    elif report["result"] == "ready":
        typer.echo(report["path"])
        typer.echo(json.dumps(report["report"], indent=2, sort_keys=True))
    else:
        typer.echo(report["detail"], err=True)
    raise typer.Exit(0 if report["result"] == "ready" else 1)
