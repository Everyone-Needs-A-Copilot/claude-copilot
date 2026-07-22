"""Fail-closed repository discovery and provisioning for desktop onboarding."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Sequence

import typer

SCHEMA_VERSION = "1.0"
COMPONENTS = ("knowledge", "cli", "claude", "codex")
Run = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class Probe:
    state: str
    visibility: str | None
    detail: str


def _run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)


def _probe(owner: str, name: str, *, run: Run) -> Probe:
    result = run(("gh", "api", f"repos/{owner}/{name}"))
    if result.returncode == 0:
        try:
            payload = json.loads(result.stdout)
            private = payload["private"]
            if not isinstance(private, bool):
                raise ValueError("private is not boolean")
        except (json.JSONDecodeError, KeyError, ValueError):
            return Probe("unknown", None, "GitHub returned an unreadable repository response.")
        if private:
            return Probe("existing-private", "private", "Existing private repository will be reused.")
        return Probe("conflict-public", "public", "A public repository already uses this name.")

    if "HTTP 404" in result.stderr:
        return Probe("missing", None, "Repository does not exist and can be created privately.")
    return Probe("unknown", None, "GitHub could not confirm whether this repository exists.")


def _owner(*, run: Run) -> str:
    result = run(("gh", "api", "user", "--jq", ".login"))
    owner = result.stdout.strip()
    if result.returncode != 0 or not owner:
        raise RuntimeError("GitHub could not confirm the authenticated personal account.")
    return owner


def _row(component: str, owner: str, probe: Probe) -> dict[str, Any]:
    return {
        "component": component,
        "role": "personal",
        "unit": None,
        "owner": owner,
        "name": f"{component}-copilot-private",
        "visibility": probe.visibility,
        "state": probe.state,
        "action": "create" if probe.state == "missing" else ("none" if probe.state == "existing-private" else "blocked"),
        "detail": probe.detail,
    }


def _report(owner: str, mode: str, rows: list[dict[str, Any]], result: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": "personal",
        "owner": owner,
        "mode": mode,
        "result": result,
        "repositories": rows,
        "summary": {
            "existing": sum(row["state"] == "existing-private" for row in rows),
            "missing": sum(row["state"] == "missing" for row in rows),
            "created": sum(row["state"] == "created" for row in rows),
            "blocked": sum(row["action"] == "blocked" for row in rows),
        },
    }


def build_personal_onboard_report(
    *, components: Sequence[str] = COMPONENTS, apply: bool = False, run: Run = _run
) -> dict[str, Any]:
    """Plan or apply personal repositories. Apply always repeats the full probe."""
    normalized = tuple(dict.fromkeys(component.strip().lower() for component in components))
    invalid = [component for component in normalized if component not in COMPONENTS]
    if not normalized or invalid:
        raise ValueError(f"Unsupported components: {', '.join(invalid) or 'none'}")

    owner = _owner(run=run)
    rows = [_row(component, owner, _probe(owner, f"{component}-copilot-private", run=run)) for component in normalized]
    blocked = any(row["action"] == "blocked" for row in rows)
    if blocked:
        return _report(owner, "apply" if apply else "plan", rows, "blocked")
    if not apply:
        return _report(owner, "plan", rows, "changes-required" if any(row["state"] == "missing" for row in rows) else "ready")

    for row in rows:
        if row["state"] != "missing":
            continue
        created = run(
            (
                "gh", "api", "-X", "POST", "user/repos",
                "-f", f"name={row['name']}", "-F", "private=true", "-F", "auto_init=true",
                "-f", f"description=Private personal layer for {row['component'].title()} Copilot",
            )
        )
        if created.returncode == 0:
            row.update(state="created", visibility="private", action="none", detail="Created private repository.")
        else:
            row.update(state="unknown", action="blocked", detail="GitHub did not confirm repository creation.")
            return _report(owner, "apply", rows, "blocked")
    return _report(owner, "apply", rows, "applied")


def onboard_cmd(
    scope: str = typer.Option("personal", "--scope", help="Repository scope; currently personal."),
    components: str = typer.Option(",".join(COMPONENTS), "--components", help="Comma-separated ecosystem components."),
    apply: bool = typer.Option(False, "--apply", help="Create confirmed-missing private repositories."),
    output_json: bool = typer.Option(False, "--json", help="Emit the versioned onboarding report."),
) -> None:
    """Discover personal repositories, then optionally create confirmed-missing ones."""
    if scope != "personal":
        message = "Only personal onboarding is available from the user CLI."
        if output_json:
            typer.echo(json.dumps({"schema_version": SCHEMA_VERSION, "error": {"code": "unsupported-scope", "message": message}}))
        raise typer.Exit(2)
    try:
        report = build_personal_onboard_report(components=components.split(","), apply=apply)
    except (RuntimeError, ValueError) as exc:
        if output_json:
            typer.echo(json.dumps({"schema_version": SCHEMA_VERSION, "error": {"code": "onboard-unavailable", "message": str(exc)}}))
        else:
            typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(report) if output_json else f"{report['result']}: {report['owner']}")
    if report["result"] == "blocked":
        raise typer.Exit(1)
