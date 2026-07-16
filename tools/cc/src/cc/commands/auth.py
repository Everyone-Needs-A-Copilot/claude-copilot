"""`cc auth` -- the WS-A GitHub device-flow sign-in seam (Stream-A).

WS-A slice (auth-slice). Wires `core/ecosystem/github_device.py`'s pure
device-flow protocol to this codebase's config/keychain/authstore:
  - `core/config.py` -- `github_app.client_id` / `auth.keychain_service` /
    `auth.scopes` (config cascade), plus (as a fallback) the org's
    inherited `ecosystem.yml` (`core/ecosystem/ecosystem_config.py`'s
    `github_client_id()`).
  - `core/keychain.py` -- the ONLY place the OAuth access token is ever
    written to disk (the per-user OS keychain), account=`login`.
  - `core/authstore.py` -- the non-secret `{login, scopes, obtained_at}`
    identity pointer (`~/.copilot/auth/active.json` by default).

Schema: copilot-control-tower/docs/01-architecture/schemas/auth.schema.json
(vendored copy: tools/cc/tests/fixtures/schemas/auth.schema.json). Three
payload kinds, discriminated by `kind`:
  - `device-code` -- `build_auth_initiate_report()` (`cc auth login --json`)
  - `poll`        -- `build_auth_poll_report()` (`cc auth login --poll
                      --device-code <code> --json`)
  - `status`      -- `build_auth_status_report()` (`cc auth status --json`,
                      offline-safe, no network)

NO-SECRET DISCIPLINE (this module's central invariant, enforced by the
schema's fitness `allOf` and by tests/test_auth_contract.py's recursive
fitness test): none of the three report dicts this module builds EVER
contains an access-token/token/secret-shaped value. The token exists only
as a local variable inside `_persist_authorized()`, for exactly as long as
it takes to fetch the identity and hand it to `keychain.set_secret()`.

Read-only / mutating split: `build_auth_initiate_report()` and
`build_auth_poll_report()` both perform network I/O (device-flow HTTP
calls) but never touch `core/locking.py`'s `copilot_lock()` -- auth only
ever writes the OS keychain + the small non-secret identity pointer file,
neither of which is part of the materialize/mirror tree `copilot_lock()`
serializes. `build_auth_status_report()` is fully offline-safe (no
network call at all).

Every filesystem root this module touches (the identity pointer's
`_root`) is injectable, mirroring `core/authstore.py`'s own `_root`
convention -- this module itself never calls `Path.home()` directly.

`auth_app` is a self-contained `typer.Typer()`: `login` (bare = initiate,
`--poll --device-code <code>` = one poll step) and `status`. A
`invoke_without_command` callback makes bare `cc auth` (no subcommand)
behave identically to `cc auth login`, so `cc auth --json` ==
`cc auth login --json`. Wiring `auth_app` into `cc.main`'s top-level
`app` (`app.add_typer(auth_app, name="auth")`) is integration's job --
this module is fully self-sufficient without it (every test here invokes
`auth_app` directly via `CliRunner`).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import typer

from cc.core import authstore, keychain
from cc.core.config import resolve_key
from cc.core.ecosystem import ecosystem_config, github_device
from cc.core.keychain import KeychainUnavailable

SCHEMA_VERSION = "1.0"

# Sentinel distinguishing "no override passed" from an explicit None
# argument -- mirrors commands/freshness.py's/commands/deprovision.py's
# `_UNSET` injection convention.
_UNSET: Any = object()

_NO_COMPANY_APP_MESSAGE = (
    "Sign-in isn't set up yet -- the company's GitHub app connection "
    "hasn't been created. It's created once during admin standup; check "
    "back once your organization has been provisioned."
)


def _error_envelope(code: str, message: str) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "error": {"code": code, "message": message}}


def _resolve_client_id(_client_id: Any) -> Optional[str]:
    """
    Resolve the GitHub App client id: an explicit override (test/local
    config) first, falling back to the org's inherited `ecosystem.yml`
    (`ecosystem_config.github_client_id()`). Returns `None` when neither
    resolves -- callers turn that into the `no-company-app` error
    envelope; a client id is not a secret (public by design), so this
    never touches the keychain.
    """
    client_id = resolve_key("github_app.client_id") if _client_id is _UNSET else _client_id
    if not client_id:
        client_id = ecosystem_config.github_client_id()
    return client_id


# ---------------------------------------------------------------------------
# build_auth_initiate_report()
# ---------------------------------------------------------------------------


def build_auth_initiate_report(
    *,
    _client_id: Any = _UNSET,
    _scopes: Any = _UNSET,
    _post_json: Any = _UNSET,
) -> dict[str, Any]:
    """
    Build the `auth login --json` (`kind: "device-code"`) contract object:
    initiate a GitHub device-flow request and return the ceremony details
    the user needs (`user_code`/`verification_uri`) plus the `device_code`
    flow handle the caller polls with next.

    Absent client id (no local override AND no inherited `ecosystem.yml`
    entry) -> the `no-company-app` error envelope: the org's GitHub App
    connection hasn't been set up yet (created during admin standup, not
    something an individual user can self-serve).
    """
    client_id = _resolve_client_id(_client_id)
    if not client_id:
        return _error_envelope("no-company-app", _NO_COMPANY_APP_MESSAGE)

    scopes = resolve_key("auth.scopes") if _scopes is _UNSET else _scopes
    scopes = scopes or ""

    kwargs: dict[str, Any] = {}
    if _post_json is not _UNSET:
        kwargs["post_json"] = _post_json
    device = github_device.request_device_code(client_id, scopes, **kwargs)

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "device-code",
        "user_code": device["user_code"],
        "verification_uri": device["verification_uri"],
        "expires_in": device["expires_in"],
        "interval": device["interval"],
        "device_code": device["device_code"],
    }


# ---------------------------------------------------------------------------
# build_auth_poll_report()
# ---------------------------------------------------------------------------


def _persist_authorized(
    access_token: str,
    *,
    _granted_scope: Optional[str],
    _get_json: Any,
    _fetch_identity: Any,
    _keychain_service: Any,
    _set_secret: Any,
    _write_identity: Any,
    _auth_root: Any,
) -> dict[str, Any]:
    """
    Shared "authorized" tail: fetch the GitHub identity, store the token
    in the keychain, write the non-secret identity pointer, and return
    the `kind: "poll", status: "authorized"` report -- NEVER the token
    itself. Shared by `build_auth_poll_report()` and
    `execute_auth_login()` so the poll loop never re-polls GitHub just to
    reuse this tail.

    `_granted_scope` is the `scope` GitHub's token response actually
    carried (`github_device.poll_token()`'s return value) -- the
    AUTHORITATIVE granted scopes, recorded on the identity pointer as-is.
    This deliberately does NOT re-resolve `auth.scopes` from config here:
    that key is only the originally-REQUESTED scope string
    (`build_auth_initiate_report()`'s input to the device-code request),
    which may differ from what GitHub actually granted.
    """
    fetch_kwargs: dict[str, Any] = {}
    if _get_json is not _UNSET:
        fetch_kwargs["get_json"] = _get_json
    fetch_fn = _fetch_identity if _fetch_identity is not _UNSET else github_device.fetch_identity
    identity = fetch_fn(access_token, **fetch_kwargs)
    login = identity.get("login")

    service = (
        resolve_key("auth.keychain_service") if _keychain_service is _UNSET else _keychain_service
    )
    set_secret_fn = _set_secret if _set_secret is not _UNSET else keychain.set_secret
    set_secret_fn(login, access_token, service=service)

    scopes = _granted_scope or ""
    obtained_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_kwargs: dict[str, Any] = {}
    if _auth_root is not _UNSET:
        write_kwargs["_root"] = _auth_root
    write_identity_fn = _write_identity if _write_identity is not _UNSET else authstore.write_identity
    write_identity_fn({"login": login, "scopes": scopes, "obtained_at": obtained_at}, **write_kwargs)

    return {"schema_version": SCHEMA_VERSION, "kind": "poll", "status": "authorized"}


def build_auth_poll_report(
    device_code: str,
    *,
    _client_id: Any = _UNSET,
    _post_json: Any = _UNSET,
    _get_json: Any = _UNSET,
    _fetch_identity: Any = _UNSET,
    _keychain_service: Any = _UNSET,
    _set_secret: Any = _UNSET,
    _write_identity: Any = _UNSET,
    _auth_root: Any = _UNSET,
) -> dict[str, Any]:
    """
    Build the `auth login --poll --json` (`kind: "poll"`) contract object:
    ONE GitHub device-flow poll step.

    On `authorized`: fetches the identity (`github_device.fetch_identity`),
    stores the OAuth token in the macOS Keychain
    (`core/keychain.py`'s `set_secret()`, account=login), and writes the
    non-secret identity pointer (`core/authstore.py`'s `write_identity()`).
    The returned dict NEVER contains the token -- see this module's
    docstring and the NO-SECRET fitness test in
    `tests/test_auth_contract.py`.
    """
    client_id = _resolve_client_id(_client_id)
    if not client_id:
        return _error_envelope("no-company-app", _NO_COMPANY_APP_MESSAGE)

    poll_kwargs: dict[str, Any] = {}
    if _post_json is not _UNSET:
        poll_kwargs["post_json"] = _post_json
    result = github_device.poll_token(client_id, device_code, **poll_kwargs)

    status = result["status"]
    if status != "authorized":
        return {"schema_version": SCHEMA_VERSION, "kind": "poll", "status": status}

    return _persist_authorized(
        result["access_token"],
        _granted_scope=result.get("scope"),
        _get_json=_get_json,
        _fetch_identity=_fetch_identity,
        _keychain_service=_keychain_service,
        _set_secret=_set_secret,
        _write_identity=_write_identity,
        _auth_root=_auth_root,
    )


# ---------------------------------------------------------------------------
# build_auth_status_report()
# ---------------------------------------------------------------------------


def build_auth_status_report(
    *,
    _identity: Any = _UNSET,
    _auth_root: Any = _UNSET,
    _keychain_present: Any = _UNSET,
    _keychain_service: Any = _UNSET,
) -> dict[str, Any]:
    """
    Build the `auth status --json` (`kind: "status"`) contract object.

    OFFLINE-SAFE: reads ONLY the non-secret identity pointer
    (`core/authstore.py`'s `read_identity()`) plus a keychain PRESENCE
    check (`core/keychain.py`'s `get_secret()` -- existence only, the
    value itself is never forwarded into the report) -- no network call
    is ever made by this function.
    """
    if _identity is not _UNSET:
        identity = _identity
    else:
        read_kwargs: dict[str, Any] = {}
        if _auth_root is not _UNSET:
            read_kwargs["_root"] = _auth_root
        identity = authstore.read_identity(**read_kwargs)

    login = identity.get("login")
    if not login:
        return {"schema_version": SCHEMA_VERSION, "kind": "status", "status": "signed-out"}

    if _keychain_present is not _UNSET:
        present = _keychain_present
    else:
        service = (
            resolve_key("auth.keychain_service")
            if _keychain_service is _UNSET
            else _keychain_service
        )
        try:
            present = keychain.get_secret(login, service=service) is not None
        except KeychainUnavailable:
            present = False

    if not present:
        return {"schema_version": SCHEMA_VERSION, "kind": "status", "status": "signed-out"}

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": "status",
        "status": "authorized",
        "identity": {"login": login},
    }
    scopes = identity.get("scopes")
    if scopes:
        report["scope"] = scopes
    return report


# ---------------------------------------------------------------------------
# compute_exit_code()
# ---------------------------------------------------------------------------


def compute_exit_code(report: dict[str, Any]) -> int:
    """
    Map any of this module's three report kinds to a process exit code
    (mirrors `commands/doctor.py`/`commands/deprovision.py`'s
    `compute_exit_code()` precedent):
      0 = success / nothing wrong (device-code issued, poll pending or
          authorized, status computed)
      1 = terminal non-success the caller should react to by restarting
          the flow (`poll` expired/denied)
      2 = error envelope (`{schema_version, error}`) -- setup/environment
          error (e.g. `no-company-app`)
    """
    if "error" in report:
        return 2
    if report.get("kind") == "poll" and report.get("status") in ("expired", "denied"):
        return 1
    return 0


# ---------------------------------------------------------------------------
# execute_auth_login() -- initiate -> poll-until-terminal convenience loop
# ---------------------------------------------------------------------------


def execute_auth_login(
    *,
    _client_id: Any = _UNSET,
    _scopes: Any = _UNSET,
    _post_json: Any = _UNSET,
    _get_json: Any = _UNSET,
    _fetch_identity: Any = _UNSET,
    _keychain_service: Any = _UNSET,
    _set_secret: Any = _UNSET,
    _write_identity: Any = _UNSET,
    _auth_root: Any = _UNSET,
    _sleep: Callable[[float], None] = time.sleep,
    _max_polls: int = 120,
) -> tuple[dict[str, Any], int]:
    """
    Convenience loop: initiate, then poll until a terminal status
    (`authorized`/`expired`/`denied`), honoring GitHub's poll `interval`
    (including any `slow_down`-updated interval) between attempts.

    `_sleep` is injectable (mirrors `_run`/`_run_git()` conventions
    elsewhere in this codebase) so tests never actually sleep. `_max_polls`
    is a belt-and-suspenders safety bound against a misbehaving/faked
    transport that never returns a terminal status -- real GitHub device
    codes always terminate via their own `expires_in`, so this should
    never be hit in production.

    Returns `(report, exit_code)`, same shape as `execute_update()`/
    `execute_deprovision()`.
    """
    initiate_kwargs: dict[str, Any] = {}
    if _client_id is not _UNSET:
        initiate_kwargs["_client_id"] = _client_id
    if _scopes is not _UNSET:
        initiate_kwargs["_scopes"] = _scopes
    if _post_json is not _UNSET:
        initiate_kwargs["_post_json"] = _post_json

    initiate_report = build_auth_initiate_report(**initiate_kwargs)
    if "error" in initiate_report:
        return initiate_report, compute_exit_code(initiate_report)

    client_id = _resolve_client_id(_client_id)
    device_code = initiate_report["device_code"]
    interval = initiate_report["interval"]

    poll_transport_kwargs: dict[str, Any] = {}
    if _post_json is not _UNSET:
        poll_transport_kwargs["post_json"] = _post_json

    for _ in range(_max_polls):
        _sleep(interval)
        result = github_device.poll_token(client_id, device_code, **poll_transport_kwargs)
        status = result["status"]

        if status == "pending":
            if "interval" in result:
                interval = result["interval"]
            continue

        if status == "authorized":
            report = _persist_authorized(
                result["access_token"],
                _granted_scope=result.get("scope"),
                _get_json=_get_json,
                _fetch_identity=_fetch_identity,
                _keychain_service=_keychain_service,
                _set_secret=_set_secret,
                _write_identity=_write_identity,
                _auth_root=_auth_root,
            )
            return report, compute_exit_code(report)

        # expired | denied -- terminal, non-authorized
        report = {"schema_version": SCHEMA_VERSION, "kind": "poll", "status": status}
        return report, compute_exit_code(report)

    timeout_report = _error_envelope(
        "poll-timeout", "Sign-in timed out waiting for authorization."
    )
    return timeout_report, compute_exit_code(timeout_report)


# ---------------------------------------------------------------------------
# Rich rendering
# ---------------------------------------------------------------------------


def render_auth_report_rich(report: dict[str, Any], *, console: Any = None) -> None:
    """Human-readable (Rich) rendering for any of this module's report
    kinds (`device-code` | `poll` | `status`) or the error envelope."""
    from rich.console import Console

    con = console or Console()

    if "error" in report:
        con.print(f"[red]auth: {report['error'].get('message')}[/red]")
        return

    kind = report.get("kind")
    if kind == "device-code":
        con.print(f"[bold]Go to:[/bold] {report.get('verification_uri')}")
        con.print(f"[bold]Enter code:[/bold] {report.get('user_code')}")
        con.print(f"[dim]Expires in {report.get('expires_in')}s.[/dim]")
    elif kind == "poll":
        status = report.get("status")
        color = {
            "authorized": "green",
            "pending": "yellow",
            "expired": "red",
            "denied": "red",
        }.get(status, "red")
        con.print(f"[{color}]auth: {status}[/{color}]")
    elif kind == "status":
        status = report.get("status")
        if status == "authorized":
            identity = report.get("identity", {})
            con.print(f"[green]signed in as {identity.get('login')}[/green]")
        else:
            con.print("[yellow]signed out[/yellow]")
    else:
        con.print(f"[dim]auth: {report}[/dim]")


# ---------------------------------------------------------------------------
# Typer CLI surface
# ---------------------------------------------------------------------------

auth_app = typer.Typer(
    help="GitHub device-flow sign-in (WS-A `auth` contract).",
    invoke_without_command=True,
)


def _run_login(*, poll: bool, device_code: Optional[str], output_json: bool) -> None:
    import json as _json

    if poll:
        if not device_code:
            message = "cc auth login --poll requires --device-code <code>."
            if output_json:
                typer.echo(_json.dumps(_error_envelope("missing-argument", message)))
            else:
                typer.echo(f"auth: {message}", err=True)
            raise typer.Exit(2)

        report = build_auth_poll_report(device_code)
    else:
        report = build_auth_initiate_report()

    if output_json:
        typer.echo(_json.dumps(report))
    else:
        render_auth_report_rich(report)

    raise typer.Exit(compute_exit_code(report))


@auth_app.command("login")
def login_cmd(
    poll: bool = typer.Option(
        False, "--poll", help="Perform one device-flow poll step instead of initiating."
    ),
    device_code: Optional[str] = typer.Option(
        None, "--device-code", help="The device_code from a prior `cc auth login --json`."
    ),
    output_json: bool = typer.Option(
        False, "--json", help="Output the WS-A auth contract as JSON."
    ),
) -> None:
    """Initiate GitHub device-flow sign-in (no flags), or perform one poll
    step (`--poll --device-code <code>`). Read-only w.r.t. the copilot
    lock -- auth never acquires it."""
    _run_login(poll=poll, device_code=device_code, output_json=output_json)


@auth_app.command("status")
def status_cmd(
    output_json: bool = typer.Option(
        False, "--json", help="Output the WS-A auth contract as JSON."
    ),
) -> None:
    """Report who is currently signed in, if anyone. Offline-safe -- never
    touches the network."""
    import json as _json

    report = build_auth_status_report()

    if output_json:
        typer.echo(_json.dumps(report))
    else:
        render_auth_report_rich(report)

    raise typer.Exit(compute_exit_code(report))


@auth_app.callback(invoke_without_command=True)
def auth_callback(
    ctx: typer.Context,
    poll: bool = typer.Option(
        False, "--poll", help="Perform one device-flow poll step instead of initiating."
    ),
    device_code: Optional[str] = typer.Option(
        None, "--device-code", help="The device_code from a prior `cc auth --json`."
    ),
    output_json: bool = typer.Option(
        False, "--json", help="Output the WS-A auth contract as JSON."
    ),
) -> None:
    """Bare `cc auth` behaves like `cc auth login`: initiate (or, with
    `--poll --device-code <code>`, one poll step) -- so `cc auth --json`
    and `cc auth login --json` are equivalent. Only fires when no
    subcommand (`login`/`status`) was invoked."""
    if ctx.invoked_subcommand is not None:
        return
    _run_login(poll=poll, device_code=device_code, output_json=output_json)
