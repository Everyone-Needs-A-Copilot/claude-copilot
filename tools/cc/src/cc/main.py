"""Claude Copilot CLI — main entry point."""

from typing import Optional

import typer

from cc import __version__
from cc.commands.auth import auth_app
from cc.commands.config import config_app
from cc.commands.docs import docs_app
from cc.commands.eval import eval_app
from cc.commands.layers import layers_app
from cc.commands.mcp import mcp_app
from cc.commands.memory import memory_app
from cc.commands.skill import skill_app
from cc.commands.usage import usage_app
from cc.core.config import resolve_key

app = typer.Typer(
    name="cc",
    help="Unified Claude Copilot CLI — memory, skills, config, and MCP in one tool.",
    no_args_is_help=True,
)

# Register subcommand groups
app.add_typer(memory_app, name="memory")
app.add_typer(skill_app, name="skill")
app.add_typer(config_app, name="config")
app.add_typer(mcp_app, name="mcp")
app.add_typer(docs_app, name="docs")
app.add_typer(usage_app, name="usage")
app.add_typer(eval_app, name="eval")
app.add_typer(auth_app, name="auth")
app.add_typer(layers_app, name="layers")


@app.command("env")
def env_cmd(
    include_secrets: bool = typer.Option(
        False,
        "--include-secrets",
        help="Also emit values from secrets.env files. CAUTION: exposes secrets to shell history.",
    ),
    output_json: bool = typer.Option(
        False, "--json", help="Output JSON instead of shell exports."
    ),
) -> None:
    """Emit shell-eval-able CC_* exports for the effective config.

    Agents call:  eval "$(cc env)"
    to hydrate CC_* environment variables for the current session.
    """
    import json as _json

    from cc.commands.env import run_env

    exports = run_env(include_secrets=include_secrets, output_json=False)

    if output_json:
        typer.echo(_json.dumps(exports))
        return

    for name in sorted(exports.keys()):
        value = exports[name]
        safe_value = value.replace("\\", "\\\\").replace('"', '\\"')
        typer.echo(f'export {name}="{safe_value}"')


@app.command("resolve")
def resolve_cmd(
    key: Optional[str] = typer.Argument(
        None,
        help=(
            "Dotted config key to resolve (e.g. paths.shared_docs). "
            "Omit together with --explain for the ecosystem-resolve report."
        ),
    ),
    scope: Optional[str] = typer.Option(
        None, "--scope", help="machine | project | effective"
    ),
    explain: bool = typer.Option(
        False,
        "--explain",
        help=(
            "Explain the layered ecosystem resolution (winning layer per item, "
            "shadow chain, override-stale flags) instead of resolving a config key. "
            "Requires no KEY argument."
        ),
    ),
    output_json: bool = typer.Option(
        False, "--json", help="Output JSON (the WS-A resolve contract, in --explain mode)."
    ),
) -> None:
    """Print the resolved value of a single config key, OR (with `--explain`
    and no KEY) report the WS-A `resolve --explain --json` ecosystem
    contract. Read-only in both modes -- does not take the copilot lock.
    """
    import json as _json

    if key is None:
        if not explain:
            message = (
                "cc resolve requires either a KEY argument (single config key) "
                "or --explain (ecosystem resolution report)."
            )
            if output_json:
                typer.echo(
                    _json.dumps(
                        {
                            "schema_version": "1.0",
                            "error": {"code": "missing-argument", "message": message},
                        }
                    )
                )
            else:
                typer.echo(f"resolve: {message}", err=True)
            raise typer.Exit(1)

        from cc.commands.resolve import build_resolve_report, render_resolve_report_rich
        from cc.core.ecosystem.manifest import ManifestError

        try:
            report = build_resolve_report()
        except ManifestError as exc:
            if output_json:
                typer.echo(
                    _json.dumps(
                        {
                            "schema_version": "1.0",
                            "error": {"code": "invalid-manifest", "message": str(exc)},
                        }
                    )
                )
            else:
                typer.echo(f"resolve: invalid layer manifest: {exc}", err=True)
            raise typer.Exit(2) from exc
        except Exception as exc:  # environment/unexpected error -> exit 2
            if output_json:
                typer.echo(
                    _json.dumps(
                        {
                            "schema_version": "1.0",
                            "error": {"code": "environment-error", "message": str(exc)},
                        }
                    )
                )
            else:
                typer.echo(f"resolve: environment error: {exc}", err=True)
            raise typer.Exit(2) from exc

        if output_json:
            typer.echo(_json.dumps(report))
        else:
            render_resolve_report_rich(report)
        raise typer.Exit(0)

    value = resolve_key(key, scope=scope)

    if output_json:
        typer.echo(_json.dumps({"key": key, "value": value}))
        return

    if value is None:
        raise typer.Exit(1)

    typer.echo(str(value))


@app.command("doctor")
def doctor_cmd(
    output_json: bool = typer.Option(
        False, "--json", help="Output the WS-A doctor contract as JSON."
    ),
) -> None:
    """Run health checks and report status (WS-A `doctor --json` contract).

    Naming note: the upstream design's user-facing verb is `copilot doctor`
    (the `copilot` binary wraps `cc`); until that wrapper exists, `cc doctor`
    IS the doctor verb. Read-only — does not take the copilot lock.
    """
    import json as _json

    from cc.commands.doctor import (
        build_doctor_report,
        compute_exit_code,
        render_doctor_report_rich,
    )

    try:
        report = build_doctor_report()
    except Exception as exc:  # environment/unexpected error -> exit 2
        if output_json:
            typer.echo(
                _json.dumps(
                    {
                        "schema_version": "1.0",
                        "error": {"code": "environment-error", "message": str(exc)},
                    }
                )
            )
        else:
            typer.echo(f"doctor: environment error: {exc}", err=True)
        raise typer.Exit(2) from exc

    if output_json:
        typer.echo(_json.dumps(report))
    else:
        render_doctor_report_rich(report)

    raise typer.Exit(compute_exit_code(report))


@app.command("freshness")
def freshness_cmd(
    output_json: bool = typer.Option(
        False, "--json", help="Output the WS-A freshness contract as JSON."
    ),
    all_projects: bool = typer.Option(
        False,
        "--all-projects",
        help=(
            "Machine-wide per-project freshness sweep (Component Sync) instead "
            "of the single-SHA tier poll -- dispatches to "
            "commands.projects.build_all_projects_freshness()."
        ),
    ),
    per_layer: bool = typer.Option(
        False,
        "--per-layer",
        help="Also fold in a per-layer freshness breakdown alongside the "
        "top-level single-SHA fields.",
    ),
) -> None:
    """Cheap single-SHA staleness poll (WS-A `freshness --json` contract).

    Read-only -- does not take the copilot lock. Compares the local
    resolved lock state against a tier's published lock-pointer ref (see
    core/ecosystem/mirror.py); never a full `update`. With no flags this
    is byte-shape-identical to the pre-existing contract (regression
    guard) -- `--all-projects` and `--per-layer` are opt-in additions.
    """
    import json as _json

    if all_projects and per_layer:
        message = "cc freshness: --all-projects and --per-layer are mutually exclusive (different report shapes)."
        if output_json:
            typer.echo(
                _json.dumps(
                    {
                        "schema_version": "1.0",
                        "error": {"code": "invalid-argument", "message": message},
                    }
                )
            )
        else:
            typer.echo(message, err=True)
        raise typer.Exit(2)

    if all_projects:
        from cc.commands.projects import (
            build_all_projects_freshness,
            render_all_projects_freshness_rich,
        )

        try:
            report = build_all_projects_freshness()
        except Exception as exc:  # environment/unexpected error -> exit 2
            if output_json:
                typer.echo(
                    _json.dumps(
                        {
                            "schema_version": "1.0",
                            "error": {"code": "environment-error", "message": str(exc)},
                        }
                    )
                )
            else:
                typer.echo(f"freshness: environment error: {exc}", err=True)
            raise typer.Exit(2) from exc

        if output_json:
            typer.echo(_json.dumps(report))
        else:
            render_all_projects_freshness_rich(report)

        raise typer.Exit(0)

    from cc.commands.freshness import (
        build_freshness_report,
        render_freshness_report_rich,
    )

    try:
        report = build_freshness_report(per_layer=per_layer)
    except Exception as exc:  # environment/unexpected error -> exit 2
        if output_json:
            typer.echo(
                _json.dumps(
                    {
                        "schema_version": "1.0",
                        "error": {"code": "environment-error", "message": str(exc)},
                    }
                )
            )
        else:
            typer.echo(f"freshness: environment error: {exc}", err=True)
        raise typer.Exit(2) from exc

    if output_json:
        typer.echo(_json.dumps(report))
    else:
        render_freshness_report_rich(report)

    raise typer.Exit(0)


@app.command("update")
def update_cmd(
    output_json: bool = typer.Option(
        False, "--json", help="Output the WS-A update contract as JSON."
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help=(
            "Compute the reconciling-sync plan WITHOUT writing/pruning "
            "materialize-root content or the lockfile."
        ),
    ),
    project: Optional[str] = typer.Option(
        None,
        "--project",
        help=(
            "Materialize a single embedding project's component instead of "
            "the machine-wide ecosystem sync (Component Sync Stream-E). "
            "Requires --component. Reuses this same --json contract shape "
            "plus an additive `path` field."
        ),
    ),
    component: Optional[str] = typer.Option(
        None,
        "--component",
        help="The component to materialize for --project (e.g. 'claude', 'codex').",
    ),
    target_version: Optional[str] = typer.Option(
        None,
        "--target-version",
        help="Target version for --project's --component (defaults to its "
        "current recorded version -- an up-to-date no-op check).",
    ),
    release_tag: Optional[str] = typer.Option(
        None,
        "--release-tag",
        help="Published release tag licensing the --project apply (required "
        "to actually apply a version change; an unverified target is blocked).",
    ),
    source_root: Optional[str] = typer.Option(
        None,
        "--source-root",
        help="Content root to materialize --project's framework-owned files from.",
    ),
    fanout: bool = typer.Option(
        False,
        "--fanout",
        help=(
            "Machine-wide fan-out materialize sweep across every discovered "
            "project's stale components (Component Sync Stream-E) instead "
            "of the machine-wide ecosystem sync."
        ),
    ),
) -> None:
    """Reconciling ecosystem sync (WS-A `update --json` contract) --
    MUTATING: acquires the copilot lock, syncs read-only mirrors, runs the
    policy gate, reconciles the materialize root (add/update/prune), and
    writes `copilot.lock.json`. See cc/commands/update.py's module
    docstring for the never-destroy guarantees.

    `--project`/`--fanout` are opt-in Component Sync additions (see
    cc/commands/projects.py) -- with neither flag this command is
    byte-shape-identical to the pre-existing contract (regression guard).
    """
    import json as _json

    if project and fanout:
        message = "cc update: --project and --fanout are mutually exclusive."
        if output_json:
            typer.echo(
                _json.dumps(
                    {
                        "schema_version": "1.0",
                        "error": {"code": "invalid-argument", "message": message},
                    }
                )
            )
        else:
            typer.echo(message, err=True)
        raise typer.Exit(2)

    if project:
        if not component:
            message = "cc update: --project requires --component."
            if output_json:
                typer.echo(
                    _json.dumps(
                        {
                            "schema_version": "1.0",
                            "error": {"code": "invalid-argument", "message": message},
                        }
                    )
                )
            else:
                typer.echo(message, err=True)
            raise typer.Exit(2)

        from cc.commands.projects import execute_materialize_project
        from cc.commands.update import render_update_report_rich

        build_kwargs: dict = {}
        if target_version is not None:
            build_kwargs["target_version"] = target_version
        if release_tag is not None:
            build_kwargs["release_tag"] = release_tag
        if source_root is not None:
            build_kwargs["source_root"] = source_root

        try:
            report, exit_code = execute_materialize_project(
                project, component=component, dry_run=dry_run, **build_kwargs
            )
        except Exception as exc:  # environment/unexpected error -> exit 2
            if output_json:
                typer.echo(
                    _json.dumps(
                        {
                            "schema_version": "1.0",
                            "error": {"code": "environment-error", "message": str(exc)},
                        }
                    )
                )
            else:
                typer.echo(f"update: environment error: {exc}", err=True)
            raise typer.Exit(2) from exc

        if "error" in report:
            exit_code = 2

        if output_json:
            typer.echo(_json.dumps(report))
        else:
            render_update_report_rich(report)

        raise typer.Exit(exit_code)

    if fanout:
        from cc.commands.projects import execute_fanout, render_fanout_report_rich

        try:
            report, exit_code = execute_fanout(dry_run=dry_run)
        except Exception as exc:  # environment/unexpected error -> exit 2
            if output_json:
                typer.echo(
                    _json.dumps(
                        {
                            "schema_version": "1.0",
                            "error": {"code": "environment-error", "message": str(exc)},
                        }
                    )
                )
            else:
                typer.echo(f"update: environment error: {exc}", err=True)
            raise typer.Exit(2) from exc

        if "error" in report:
            exit_code = 2

        if output_json:
            typer.echo(_json.dumps(report))
        else:
            render_fanout_report_rich(report)

        raise typer.Exit(exit_code)

    from cc.commands.update import execute_update, render_update_report_rich

    try:
        report, exit_code = execute_update(dry_run=dry_run)
    except Exception as exc:  # environment/unexpected error -> exit 2
        if output_json:
            typer.echo(
                _json.dumps(
                    {
                        "schema_version": "1.0",
                        "error": {"code": "environment-error", "message": str(exc)},
                    }
                )
            )
        else:
            typer.echo(f"update: environment error: {exc}", err=True)
        raise typer.Exit(2) from exc

    if "error" in report:
        exit_code = 2

    if output_json:
        typer.echo(_json.dumps(report))
    else:
        render_update_report_rich(report)

    raise typer.Exit(exit_code)


@app.command("repair")
def repair_cmd() -> None:
    """Repair the ecosystem (ENGINE-BLOCKED — WS-A doctor-slice stub only)."""
    from cc.commands.lifecycle import run_repair

    run_repair()


@app.command("deprovision")
def deprovision_cmd(
    output_json: bool = typer.Option(
        False, "--json", help="Output the WS-A deprovision contract as JSON."
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Compute the wipe plan WITHOUT removing/quarantining anything.",
    ),
    mode: str = typer.Option(
        "soft",
        "--mode",
        help=(
            "'soft' (default): wipe materialized content, quarantine mirror "
            "clones so a flip-back restores without a re-clone. 'hard': also "
            "permanently delete mirror clones (including any quarantined "
            "ones)."
        ),
    ),
    soft: bool = typer.Option(
        False, "--soft", help="Shorthand for --mode soft (the default)."
    ),
    hard: bool = typer.Option(
        False, "--hard", help="Shorthand for --mode hard."
    ),
) -> None:
    """Wipe the disposable ecosystem trees (WS-A `deprovision --json`
    contract) -- MUTATING: acquires the copilot lock, then removes every
    item `copilot.lock.json` recorded as materialized plus every mirror
    clone, retaining (never touching) any personal/dirty path. See
    cc/commands/deprovision.py's module docstring for the never-destroy
    guarantees and the soft/hard split.
    """
    import json as _json

    from cc.commands.deprovision import (
        execute_deprovision,
        render_deprovision_report_rich,
    )

    if soft and hard:
        message = "cc deprovision: --soft and --hard are mutually exclusive."
        if output_json:
            typer.echo(
                _json.dumps(
                    {
                        "schema_version": "1.0",
                        "error": {"code": "invalid-argument", "message": message},
                    }
                )
            )
        else:
            typer.echo(message, err=True)
        raise typer.Exit(2)

    if hard:
        mode = "hard"
    elif soft:
        mode = "soft"

    try:
        report, exit_code = execute_deprovision(dry_run=dry_run, _mode=mode)
    except Exception as exc:  # environment/unexpected error -> exit 2
        if output_json:
            typer.echo(
                _json.dumps(
                    {
                        "schema_version": "1.0",
                        "error": {"code": "environment-error", "message": str(exc)},
                    }
                )
            )
        else:
            typer.echo(f"deprovision: environment error: {exc}", err=True)
        raise typer.Exit(2) from exc

    if "error" in report:
        exit_code = 2

    if output_json:
        typer.echo(_json.dumps(report))
    else:
        render_deprovision_report_rich(report)

    raise typer.Exit(exit_code)


@app.command("version")
def version() -> None:
    """Show the cc version."""
    typer.echo(f"cc version {__version__}")


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"cc version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-V",
        callback=version_callback,
        is_eager=True,
        help="Show the cc version and exit.",
    ),
) -> None:
    """Claude Copilot CLI."""


if __name__ == "__main__":
    app()
