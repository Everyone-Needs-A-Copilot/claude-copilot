"""`cc store verify` — prove the interactive GitHub-to-Infisical path."""

from __future__ import annotations

import json
import subprocess
from typing import Any, Callable, Optional, Sequence

import typer

from cc.core.ecosystem.ecosystem_config import load_ecosystem_config
from cc.core.executables import resolve_executable

SCHEMA_VERSION = "1.0"
Run = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]

store_app = typer.Typer(help="Verify shared-store access.", no_args_is_help=True)


def _run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    executable = resolve_executable(args[0]) if args else None
    if executable is None:
        return subprocess.CompletedProcess(args, 127, "", "copilot is not installed")
    try:
        return subprocess.run(
            (str(executable), *args[1:]),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return subprocess.CompletedProcess(
            args, 127, "", "verification process unavailable"
        )


def _report(
    *,
    result: str,
    detail: str,
    organization: Optional[str],
    scope: Optional[str],
    checks: dict[str, bool],
    evidence: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "result": result,
        "detail": detail,
        "organization": organization,
        "scope": scope,
        "checks": checks,
        "evidence": evidence,
    }


def _policy_scope(
    cfg: dict[str, Any], scope: str
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    store = cfg.get("store") if isinstance(cfg.get("store"), dict) else {}
    if store.get("status") != "connected" or store.get("type") != "infisical":
        return None, "The organization has not connected an Infisical store."
    required = (
        "endpoint",
        "workspace_id",
        "environment",
        "broker_url",
        "broker_issuer",
        "broker_audience",
    )
    missing = [
        key
        for key in required
        if not isinstance(store.get(key), str) or not store.get(key)
    ]
    if missing:
        return (
            None,
            "The organization must publish the GitHub-authorized store fields: "
            + ", ".join(missing)
            + ".",
        )
    if store["broker_url"].rstrip("/") != store["broker_issuer"].rstrip("/"):
        return None, "The organization's broker URL and issuer do not match."
    if store["endpoint"].rstrip("/") != store["broker_audience"].rstrip("/"):
        return (
            None,
            "The organization's store endpoint and broker audience do not match.",
        )
    rows = store.get("team_scopes")
    if not isinstance(rows, list):
        return (
            None,
            "The organization must publish a bounded read-only shared-store scope.",
        )
    matched = [
        row for row in rows if isinstance(row, dict) and row.get("scope") == scope
    ]
    if len(matched) != 1:
        return None, f"The organization does not declare exactly one '{scope}' scope."
    row = matched[0]
    path = row.get("secret_path")
    verification_path = store.get("verification_path")
    access = row.get("access")
    identity_id = row.get("identity_id")
    workspace = row.get("workspace_id", store.get("workspace_id"))
    environment = row.get("environment", store.get("environment"))
    if (
        access != "read"
        or not isinstance(path, str)
        or not path.startswith("/")
        or path.rstrip("/") in {"", "/"}
        or any(mark in path for mark in "*?[]{}")
        or not isinstance(identity_id, str)
        or not identity_id
        or not isinstance(workspace, str)
        or not workspace
        or not isinstance(environment, str)
        or not environment
        or not isinstance(verification_path, str)
        or not verification_path.startswith("/")
        or verification_path.rstrip("/") in {"", "/"}
        or any(mark in verification_path for mark in "*?[]{}")
        or verification_path.rstrip("/") == path.rstrip("/")
        or verification_path.rstrip("/").startswith(f"{path.rstrip('/')}/")
    ):
        return (
            None,
            f"The organization's '{scope}' scope is not a bounded read-only scope.",
        )
    return {**row, "verification_path": verification_path.rstrip("/")}, None


def build_store_verify_report(
    *,
    scope: str = "shared",
    run: Optional[Run] = None,
    ecosystem_cfg: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    run = run or _run
    cfg = ecosystem_cfg if ecosystem_cfg is not None else load_ecosystem_config()
    organization = cfg.get("org") if isinstance(cfg.get("org"), str) else None
    checks = {
        "policy_valid": False,
        "positive_read": False,
        "negative_denied": False,
        "read_only": False,
    }
    row, error = _policy_scope(cfg, scope)
    if row is None:
        return _report(
            result="not-configured",
            detail=error or "The shared-store policy is unavailable.",
            organization=organization,
            scope=scope,
            checks=checks,
        )
    checks["policy_valid"] = True
    store = cfg["store"]
    workspace = row.get("workspace_id") or store["workspace_id"]
    environment = row.get("environment") or store["environment"]
    path = row["secret_path"]
    result = run(
        (
            "copilot",
            "infisical",
            "--json",
            "access",
            "verify",
            "--project",
            workspace,
            "--env",
            environment,
            "--path",
            path,
            "--negative-path",
            row["verification_path"],
            "--scope",
            scope,
        )
    )
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        payload = None
    if not isinstance(payload, dict):
        return _report(
            result="unavailable",
            detail="The Python store verifier returned an unreadable report.",
            organization=organization,
            scope=scope,
            checks=checks,
            evidence={
                "auth_mode": None,
                "secret_count": None,
                "exit_code": result.returncode,
            },
        )
    for name in ("positive_read", "negative_denied", "read_only"):
        checks[name] = payload.get(name) is True
    ready = (
        result.returncode == 0
        and payload.get("result") == "ready"
        and all(checks.values())
    )
    reported_result = payload.get("result")
    safe_result = (
        reported_result
        if reported_result
        in {"not-configured", "unavailable", "unsafe", "invalid-config"}
        else "unavailable"
    )
    return _report(
        result="ready" if ready else safe_result,
        detail=(
            "The ecosystem's shared access path is operational and read-only."
            if ready
            else str(payload.get("detail") or "The shared access path is unavailable.")
        ),
        organization=organization,
        scope=scope,
        checks=checks,
        evidence={
            "auth_mode": payload.get("auth_mode"),
            "secret_count": payload.get("secret_count"),
            "exit_code": result.returncode,
        },
    )


def render_store_verify_report(report: dict[str, Any]) -> None:
    from rich.console import Console

    console = Console()
    color = "green" if report.get("result") == "ready" else "yellow"
    console.print(f"[{color}]{report.get('detail')}[/{color}]")


@store_app.command("verify")
def store_verify_cmd(
    scope: str = typer.Option("shared", "--scope", help="Store scope to verify."),
    output_json: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    report = build_store_verify_report(scope=scope)
    if output_json:
        typer.echo(json.dumps(report))
    else:
        render_store_verify_report(report)
    raise typer.Exit(0 if report.get("result") == "ready" else 1)
