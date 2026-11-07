"""`cc settings-hook` -- user-level hook registration (central resolution).

    cc settings-hook user-add|user-remove [--home PATH] [--dry-run] [--json]

`user-add` registers the framework hook shim once in `~/.claude/settings.json`; the shim
resolves through the release pointer and gates on the project marker, so projects carry no
registration. The per-project commands (`add`, `remove`, `rollback`, `list-sources`, which kept a
`mutations[]` ledger in a project's `copilot.lock.json`) are retired and only refuse.
"""

from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Any, Optional

import typer

from cc.commands.retired import register_retired
from cc.core.ecosystem.mutations import apply_user_settings, remove_user_settings

SCHEMA_VERSION = "1.0"

settings_hook_app = typer.Typer(
    name="settings-hook",
    help="Register/revert the framework hook shim in ~/.claude/settings.json (user level).",
    no_args_is_help=True,
)

_EXIT_OK = 0
_EXIT_ENVIRONMENT_ERROR = 2


def _emit(payload: dict[str, Any], *, output_json: bool, human: str) -> None:
    typer.echo(_json.dumps(payload) if output_json else human)


def _user_home(home: Optional[str]) -> Path:
    return Path(home).expanduser() if home else Path.home()


def _user_exit(outcome: Any, output_json: bool, label: str) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": outcome.status,
        "detail": outcome.detail,
        "settings": outcome.settings_path,
        "backup": outcome.backup,
        "env": list(outcome.env_added),
    }
    _emit(payload, output_json=output_json, human=f"settings-hook {label}: {outcome.status} -- {outcome.detail}")
    raise typer.Exit(_EXIT_ENVIRONMENT_ERROR if outcome.status == "blocked" else _EXIT_OK)


for _retired in ("add", "remove", "rollback", "list-sources"):
    register_retired(
        settings_hook_app,
        _retired,
        display=f"settings-hook {_retired}",
        detail="Projects carry no hook registration; `cc settings-hook user-add` registers the shim once for every project.",
    )


@settings_hook_app.command("user-add")
def user_add_cmd(
    home: Optional[str] = typer.Option(None, "--home", help="Home directory (defaults to $HOME)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Compute without writing."),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Register the framework hook shim once in ~/.claude/settings.json (and
    the skill-listing budget env). Backs up first; preserves all other keys."""
    _user_exit(apply_user_settings(_user_home(home), dry_run=dry_run), output_json, "user-add")


@settings_hook_app.command("user-remove")
def user_remove_cmd(
    home: Optional[str] = typer.Option(None, "--home", help="Home directory (defaults to $HOME)."),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Reverse `user-add`: remove only the entries and env keys it added."""
    _user_exit(remove_user_settings(_user_home(home)), output_json, "user-remove")


__all__ = ["settings_hook_app"]
