"""`cc auth` -- the WS-A GitHub device-flow sign-in seam (Stream-A).

WS-A slice (auth-slice). Wires `core/ecosystem/github_device.py`'s pure
device-flow protocol to this codebase's config/keychain/authstore:
  - `core/config.py` -- `github_app.client_id` / `auth.keychain_service` /
    `auth.scopes` (config cascade), plus (as a fallback, on a machine with
    no client id configured yet) the org's PUBLIC bootstrap artifact
    (`core/ecosystem/bootstrap_config.py`'s `fetch_org_client_id()` --
    fetched over plain, unauthenticated HTTPS, breaking the sign-in
    chicken-and-egg: see `_resolve_client_id()`'s docstring below).
  - `core/keychain.py` -- the ONLY place the OAuth access token is ever
    written to disk (the per-user OS keychain), account=`login`.
  - `core/authstore.py` -- the non-secret `{login, scopes, obtained_at}`
    identity pointer (`~/.copilot/auth/active.json` by default).

Schema: copilot-control-tower/docs/01-architecture/schemas/auth.schema.json
(vendored copy: tools/cc/tests/fixtures/schemas/auth.schema.json). Five
payload kinds, discriminated by `kind`:
  - `device-code` -- `build_auth_initiate_report()` (`cc auth login --json`)
  - `poll`        -- `build_auth_poll_report()` (`cc auth login --poll
                      --device-code <code> --json`)
  - `status`      -- `build_auth_status_report()` (`cc auth status --json`,
                      offline-safe, no network)
  - `grant-device-code` -- `build_auth_grant_initiate_report()`
  - `grant-poll` -- `build_auth_grant_poll_report()`

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

import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import typer

from cc.core import authstore, keychain
from cc.core.config import resolve_key
from cc.core.ecosystem import bootstrap_config, github_device
from cc.core.keychain import KeychainUnavailable

SCHEMA_VERSION = "1.0"
GRANT_PERMISSION = "write:public_key"
GRANT_ACCEPTED_SCOPES = frozenset({GRANT_PERMISSION, "admin:public_key"})

# Sentinel distinguishing "no override passed" from an explicit None
# argument -- mirrors commands/freshness.py's/commands/deprovision.py's
# `_UNSET` injection convention.
_UNSET: Any = object()

_NO_COMPANY_APP_MESSAGE = (
    "Sign-in isn't set up yet -- the company's GitHub app connection "
    "hasn't been created. It's created once during admin standup; check "
    "back once your organization has been provisioned."
)
_ORG_REQUIRED_MESSAGE = (
    "Sign-in needs to know which organization you're with before it can "
    "start. Pass --org <your-company>, or set it once with `cc config set "
    "github_app.org <your-company>`."
)
_ORG_NOT_FOUND_MESSAGE = (
    "That organization couldn't be found on GitHub -- check the spelling and try again."
)
_NETWORK_UNAVAILABLE_MESSAGE = (
    "Sign-in needs a network connection to look up your organization's "
    "GitHub app -- check your connection and try again."
)
_ERROR_MESSAGES: dict[str, str] = {
    "no-company-app": _NO_COMPANY_APP_MESSAGE,
    "org-required": _ORG_REQUIRED_MESSAGE,
    "org-not-found": _ORG_NOT_FOUND_MESSAGE,
    "network-unavailable": _NETWORK_UNAVAILABLE_MESSAGE,
}
_SIGNED_IN_REQUIRED_MESSAGE = (
    "Sign in with `cc auth login` before asking GitHub for permission to "
    "add this Mac's public key."
)
_KEYCHAIN_UNAVAILABLE_MESSAGE = (
    "The current GitHub sign-in could not be read from or saved to Keychain."
)


def _error_envelope(code: str, message: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "error": {"code": code, "message": message},
    }


def _scope_set(value: Optional[str]) -> set[str]:
    return {scope for scope in re.split(r"[\s,]+", value or "") if scope}


def _read_identity(*, _identity: Any, _auth_root: Any) -> dict[str, Any]:
    if _identity is not _UNSET:
        return _identity if isinstance(_identity, dict) else {}
    kwargs: dict[str, Any] = {}
    if _auth_root is not _UNSET:
        kwargs["_root"] = _auth_root
    return authstore.read_identity(**kwargs)


def _current_credential(
    *,
    _identity: Any,
    _auth_root: Any,
    _keychain_service: Any,
    _get_secret: Any,
) -> tuple[dict[str, Any], Optional[str], Optional[str]]:
    identity = _read_identity(_identity=_identity, _auth_root=_auth_root)
    login = identity.get("login")
    if not isinstance(login, str) or not login.strip():
        return identity, None, "signed-in-required"

    service = (
        resolve_key("auth.keychain_service")
        if _keychain_service is _UNSET
        else _keychain_service
    )
    get_secret_fn = keychain.get_secret if _get_secret is _UNSET else _get_secret
    try:
        token = get_secret_fn(login, service=service)
    except (KeychainUnavailable, OSError, RuntimeError):
        return identity, None, "keychain-unavailable"
    if not token:
        return identity, None, "signed-in-required"
    return identity, token, None


def _resolve_org(_org: Any) -> Optional[str]:
    """Resolve the org slug: an explicit override (CLI `--org`/test) first,
    else the `github_app.org` config cascade (the inherited-pointer path --
    the app sets this once via `cc config set github_app.org <org>` after
    collecting it during onboarding). Returns `None` when neither
    resolves; never raises."""
    org = resolve_key("github_app.org") if _org is _UNSET else _org
    return org.strip() if isinstance(org, str) and org.strip() else None


def _resolve_client_id(
    _client_id: Any,
    *,
    _org: Any = _UNSET,
    _fetch_bootstrap: Any = _UNSET,
    _org_exists: Any = _UNSET,
) -> tuple[Optional[str], Optional[str]]:
    """
    Resolve the GitHub App client id. Returns `(client_id, error_code)`;
    `error_code` is `None` on success, and one of:
      - `"org-required"` -- no org is known yet (no `--org`, no
        `github_app.org` config), so there is nothing to bootstrap from.
        Only reachable when `github_app.client_id` is ALSO unset --  an
        already-configured client id never needs an org at all.
      - `"network-unavailable"` -- an org IS known, but the bootstrap fetch
        could not reach the network at all (DNS failure, connection
        refused, timeout). Distinct from `no-company-app`: an offline
        person deserves an offline message, not "your organization hasn't
        finished setting up sign-in yet" -- that would be false.
      - `"org-not-found"` -- an org IS known, the bootstrap fetch failed
        for a reason OTHER than network unavailability, and an
        unauthenticated GitHub existence probe (`org_exists_on_github()`)
        AFFIRMATIVELY says no such org exists. Never surfaced on an
        inconclusive probe (rate-limited/network error) -- see that
        function's docstring for why: telling someone their real
        organization doesn't exist is worse than the alternative
        (`no-company-app`), so every ambiguous signal falls through there
        instead.
      - `"no-company-app"` -- an org IS known and (as far as this can
        tell) real, but its public bootstrap artifact is unreachable,
        malformed, or carries no client id: the org's GitHub App
        connection genuinely hasn't been set up yet.

    Resolution order:
      1. Explicit override (`_client_id`, test/local escape hatch).
      2. `resolve_key("github_app.client_id")` -- the ordinary config
         cascade (env > project > machine > default). This is how an
         already-onboarded machine (or one an admin hand-configured, e.g.
         to unblock local testing) short-circuits everything below with no
         network call at all.
      3. The org's PUBLIC bootstrap artifact
         (`bootstrap_config.fetch_org_client_id()`) -- fetched over plain,
         unauthenticated HTTPS (no `gh` CLI, no prior sign-in) once an org
         slug is known (`_resolve_org()`). This is the ONLY path that
         works on a completely fresh Mac with nothing configured yet --
         see this module's docstring for why the org's PRIVATE
         `ecosystem.yml` can never be that source.

    A client id is not a secret (public by design), so none of this ever
    touches the keychain.
    """
    client_id = (
        resolve_key("github_app.client_id") if _client_id is _UNSET else _client_id
    )
    if client_id:
        return client_id, None

    org = _resolve_org(_org)
    if not org:
        return None, "org-required"

    fetch_fn = (
        bootstrap_config.fetch_org_client_id
        if _fetch_bootstrap is _UNSET
        else _fetch_bootstrap
    )
    client_id, failure_reason = fetch_fn(org)
    if client_id:
        return client_id, None

    if failure_reason == "network-unavailable":
        return None, "network-unavailable"

    exists_fn = (
        bootstrap_config.org_exists_on_github if _org_exists is _UNSET else _org_exists
    )
    if exists_fn(org) is False:
        return None, "org-not-found"

    return None, "no-company-app"


# ---------------------------------------------------------------------------
# build_auth_initiate_report()
# ---------------------------------------------------------------------------


def build_auth_initiate_report(
    *,
    _client_id: Any = _UNSET,
    _scopes: Any = _UNSET,
    _post_json: Any = _UNSET,
    _org: Any = _UNSET,
    _fetch_bootstrap: Any = _UNSET,
    _org_exists: Any = _UNSET,
) -> dict[str, Any]:
    """
    Build the `auth login --json` (`kind: "device-code"`) contract object:
    initiate a GitHub device-flow request and return the ceremony details
    the user needs (`user_code`/`verification_uri`) plus the `device_code`
    flow handle the caller polls with next.

    Absent client id -> an error envelope: `"org-required"` when no org is
    known yet to bootstrap from (no `--org`, no `github_app.org` config);
    `"network-unavailable"` when the bootstrap fetch couldn't reach the
    network at all; `"org-not-found"` when an unauthenticated GitHub probe
    affirmatively says the org doesn't exist; `"no-company-app"` when an
    org IS known (and, as far as this can tell, real) but its public
    bootstrap artifact carries no client id -- the org's GitHub App
    connection hasn't been set up yet (created during admin standup, not
    something an individual user can self-serve). See `_resolve_client_id()`.
    """
    client_id, error_code = _resolve_client_id(
        _client_id,
        _org=_org,
        _fetch_bootstrap=_fetch_bootstrap,
        _org_exists=_org_exists,
    )
    if client_id is None:
        assert (
            error_code is not None
        )  # invariant: _resolve_client_id always pairs the two
        return _error_envelope(error_code, _ERROR_MESSAGES[error_code])

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
    fetch_fn = (
        _fetch_identity
        if _fetch_identity is not _UNSET
        else github_device.fetch_identity
    )
    identity = fetch_fn(access_token, **fetch_kwargs)
    login = identity.get("login")

    service = (
        resolve_key("auth.keychain_service")
        if _keychain_service is _UNSET
        else _keychain_service
    )
    set_secret_fn = _set_secret if _set_secret is not _UNSET else keychain.set_secret
    try:
        stored = set_secret_fn(login, access_token, service=service)
    except (KeychainUnavailable, OSError, RuntimeError):
        stored = False
    if stored is not True:
        return _error_envelope(
            "keychain-unavailable",
            _KEYCHAIN_UNAVAILABLE_MESSAGE,
        )

    scopes = _granted_scope or ""
    obtained_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_kwargs: dict[str, Any] = {}
    if _auth_root is not _UNSET:
        write_kwargs["_root"] = _auth_root
    write_identity_fn = (
        _write_identity if _write_identity is not _UNSET else authstore.write_identity
    )
    write_identity_fn(
        {"login": login, "scopes": scopes, "obtained_at": obtained_at}, **write_kwargs
    )

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
    _org: Any = _UNSET,
    _fetch_bootstrap: Any = _UNSET,
    _org_exists: Any = _UNSET,
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

    The client id must resolve identically to the `device-code` step that
    produced `device_code` (GitHub requires the same `client_id` on every
    poll) -- this CLI holds no session state between processes, so the
    caller re-supplies `--org` (or relies on the same `github_app.org`
    config) on every `--poll` invocation, exactly as it already re-supplies
    `--device-code`. See `_resolve_client_id()`.
    """
    client_id, error_code = _resolve_client_id(
        _client_id,
        _org=_org,
        _fetch_bootstrap=_fetch_bootstrap,
        _org_exists=_org_exists,
    )
    if client_id is None:
        assert (
            error_code is not None
        )  # invariant: _resolve_client_id always pairs the two
        return _error_envelope(error_code, _ERROR_MESSAGES[error_code])

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
# Least-privilege SSH-key permission grant
# ---------------------------------------------------------------------------


def build_auth_grant_initiate_report(
    *,
    _client_id: Any = _UNSET,
    _post_json: Any = _UNSET,
    _identity: Any = _UNSET,
    _get_secret: Any = _UNSET,
    _keychain_service: Any = _UNSET,
    _auth_root: Any = _UNSET,
    _org: Any = _UNSET,
    _fetch_bootstrap: Any = _UNSET,
    _org_exists: Any = _UNSET,
) -> dict[str, Any]:
    """Start a token upgrade requesting only SSH public-key write access."""
    _current, _token, credential_error = _current_credential(
        _identity=_identity,
        _auth_root=_auth_root,
        _keychain_service=_keychain_service,
        _get_secret=_get_secret,
    )
    if credential_error == "signed-in-required":
        return _error_envelope(
            "signed-in-required",
            _SIGNED_IN_REQUIRED_MESSAGE,
        )
    if credential_error is not None:
        return _error_envelope(
            "keychain-unavailable",
            _KEYCHAIN_UNAVAILABLE_MESSAGE,
        )

    client_id, error_code = _resolve_client_id(
        _client_id,
        _org=_org,
        _fetch_bootstrap=_fetch_bootstrap,
        _org_exists=_org_exists,
    )
    if client_id is None:
        assert error_code is not None
        return _error_envelope(error_code, _ERROR_MESSAGES[error_code])

    kwargs: dict[str, Any] = {}
    if _post_json is not _UNSET:
        kwargs["post_json"] = _post_json
    device = github_device.request_device_code(
        client_id,
        GRANT_PERMISSION,
        **kwargs,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "grant-device-code",
        "permission": GRANT_PERMISSION,
        "user_code": device["user_code"],
        "verification_uri": device["verification_uri"],
        "expires_in": device["expires_in"],
        "interval": device["interval"],
        "device_code": device["device_code"],
    }


def build_auth_grant_poll_report(
    device_code: str,
    *,
    _client_id: Any = _UNSET,
    _post_json: Any = _UNSET,
    _get_json: Any = _UNSET,
    _fetch_identity: Any = _UNSET,
    _identity: Any = _UNSET,
    _get_secret: Any = _UNSET,
    _keychain_service: Any = _UNSET,
    _set_secret: Any = _UNSET,
    _write_identity: Any = _UNSET,
    _auth_root: Any = _UNSET,
    _org: Any = _UNSET,
    _fetch_bootstrap: Any = _UNSET,
    _org_exists: Any = _UNSET,
) -> dict[str, Any]:
    """Poll and commit a least-privilege token upgrade transaction."""
    current, old_token, credential_error = _current_credential(
        _identity=_identity,
        _auth_root=_auth_root,
        _keychain_service=_keychain_service,
        _get_secret=_get_secret,
    )
    if credential_error == "signed-in-required":
        return _error_envelope(
            "signed-in-required",
            _SIGNED_IN_REQUIRED_MESSAGE,
        )
    if credential_error is not None:
        return _error_envelope(
            "keychain-unavailable",
            _KEYCHAIN_UNAVAILABLE_MESSAGE,
        )

    client_id, error_code = _resolve_client_id(
        _client_id,
        _org=_org,
        _fetch_bootstrap=_fetch_bootstrap,
        _org_exists=_org_exists,
    )
    if client_id is None:
        assert error_code is not None
        return _error_envelope(error_code, _ERROR_MESSAGES[error_code])

    poll_kwargs: dict[str, Any] = {}
    if _post_json is not _UNSET:
        poll_kwargs["post_json"] = _post_json
    result = github_device.poll_token(client_id, device_code, **poll_kwargs)
    status = result["status"]
    if status != "authorized":
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "grant-poll",
            "status": status,
        }

    fetch_kwargs: dict[str, Any] = {}
    if _get_json is not _UNSET:
        fetch_kwargs["get_json"] = _get_json
    fetch_fn = (
        github_device.fetch_identity if _fetch_identity is _UNSET else _fetch_identity
    )
    candidate_token = result["access_token"]
    candidate = fetch_fn(candidate_token, **fetch_kwargs)
    current_login = current.get("login")
    candidate_login = candidate.get("login")
    if (
        not isinstance(candidate_login, str)
        or not isinstance(current_login, str)
        or candidate_login.casefold() != current_login.casefold()
    ):
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "grant-poll",
            "status": "identity-mismatch",
        }

    granted_scope = result.get("scope")
    if not GRANT_ACCEPTED_SCOPES.intersection(_scope_set(granted_scope)):
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "grant-poll",
            "status": "insufficient-scope",
        }

    service = (
        resolve_key("auth.keychain_service")
        if _keychain_service is _UNSET
        else _keychain_service
    )
    set_secret_fn = keychain.set_secret if _set_secret is _UNSET else _set_secret
    try:
        stored = set_secret_fn(
            current_login,
            candidate_token,
            service=service,
        )
    except (KeychainUnavailable, OSError, RuntimeError):
        stored = False
    if stored is not True:
        return _error_envelope(
            "keychain-unavailable",
            _KEYCHAIN_UNAVAILABLE_MESSAGE,
        )

    pointer = {
        "login": current_login,
        "scopes": granted_scope or "",
        "obtained_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    write_kwargs: dict[str, Any] = {}
    if _auth_root is not _UNSET:
        write_kwargs["_root"] = _auth_root
    write_identity_fn = (
        authstore.write_identity if _write_identity is _UNSET else _write_identity
    )
    try:
        write_identity_fn(pointer, **write_kwargs)
    except (OSError, RuntimeError, ValueError):
        assert old_token is not None
        try:
            set_secret_fn(current_login, old_token, service=service)
        except (KeychainUnavailable, OSError, RuntimeError):
            pass
        return _error_envelope(
            "identity-write-failed",
            "The upgraded GitHub sign-in could not be committed safely.",
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "grant-poll",
        "status": "granted",
    }


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
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "status",
            "status": "signed-out",
        }

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
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "status",
            "status": "signed-out",
        }

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
    Map any of this module's report kinds to a process exit code
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
    if report.get("kind") == "poll" and report.get("status") in (
        "expired",
        "denied",
    ):
        return 1
    if report.get("kind") == "grant-poll" and report.get("status") in (
        "expired",
        "denied",
        "identity-mismatch",
        "insufficient-scope",
    ):
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
    _org: Any = _UNSET,
    _fetch_bootstrap: Any = _UNSET,
    _org_exists: Any = _UNSET,
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

    Resolves the client id exactly ONCE (`_resolve_client_id()`), then
    passes it straight into `build_auth_initiate_report()` as an explicit
    override -- both so GitHub sees the identical `client_id` on the
    initiate call and every poll (as it requires), and so a bootstrap
    fetch that hits the network (`_resolve_client_id()`'s org-bootstrap
    fallback) only ever happens once per call, not once per step.

    Returns `(report, exit_code)`, same shape as `execute_update()`/
    `execute_deprovision()`.
    """
    client_id, error_code = _resolve_client_id(
        _client_id,
        _org=_org,
        _fetch_bootstrap=_fetch_bootstrap,
        _org_exists=_org_exists,
    )
    if client_id is None:
        assert (
            error_code is not None
        )  # invariant: _resolve_client_id always pairs the two
        error_report = _error_envelope(error_code, _ERROR_MESSAGES[error_code])
        return error_report, compute_exit_code(error_report)

    initiate_kwargs: dict[str, Any] = {"_client_id": client_id}
    if _scopes is not _UNSET:
        initiate_kwargs["_scopes"] = _scopes
    if _post_json is not _UNSET:
        initiate_kwargs["_post_json"] = _post_json

    initiate_report = build_auth_initiate_report(**initiate_kwargs)
    if "error" in initiate_report:
        return initiate_report, compute_exit_code(initiate_report)

    device_code = initiate_report["device_code"]
    interval = initiate_report["interval"]

    poll_transport_kwargs: dict[str, Any] = {}
    if _post_json is not _UNSET:
        poll_transport_kwargs["post_json"] = _post_json

    for _ in range(_max_polls):
        _sleep(interval)
        result = github_device.poll_token(
            client_id, device_code, **poll_transport_kwargs
        )
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
    if kind in {"device-code", "grant-device-code"}:
        con.print(f"[bold]Go to:[/bold] {report.get('verification_uri')}")
        con.print(f"[bold]Enter code:[/bold] {report.get('user_code')}")
        con.print(f"[dim]Expires in {report.get('expires_in')}s.[/dim]")
    elif kind in {"poll", "grant-poll"}:
        status = report.get("status")
        color = {
            "authorized": "green",
            "granted": "green",
            "pending": "yellow",
            "expired": "red",
            "denied": "red",
            "identity-mismatch": "red",
            "insufficient-scope": "red",
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
    help="GitHub sign-in and least-privilege permission grants.",
    invoke_without_command=True,
)


def _run_login(
    *, poll: bool, device_code: Optional[str], org: Optional[str], output_json: bool
) -> None:
    import json as _json

    org_kwargs: dict[str, Any] = {"_org": org} if org else {}

    if poll:
        if not device_code:
            message = "cc auth login --poll requires --device-code <code>."
            if output_json:
                typer.echo(_json.dumps(_error_envelope("missing-argument", message)))
            else:
                typer.echo(f"auth: {message}", err=True)
            raise typer.Exit(2)

        report = build_auth_poll_report(device_code, **org_kwargs)
    else:
        report = build_auth_initiate_report(**org_kwargs)

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
        None,
        "--device-code",
        help="The device_code from a prior `cc auth login --json`.",
    ),
    org: Optional[str] = typer.Option(
        None,
        "--org",
        help=(
            "GitHub org slug to sign in through, on a machine with no "
            "github_app.client_id/org configured yet. Required again on "
            "every --poll call for the same reason --device-code is: this "
            "CLI holds no session state between processes. Falls back to "
            "the github_app.org config key (set once via `cc config set` "
            "by the app or an admin) when omitted."
        ),
    ),
    output_json: bool = typer.Option(
        False, "--json", help="Output the WS-A auth contract as JSON."
    ),
) -> None:
    """Initiate GitHub device-flow sign-in (no flags), or perform one poll
    step (`--poll --device-code <code>`). Read-only w.r.t. the copilot
    lock -- auth never acquires it."""
    _run_login(poll=poll, device_code=device_code, org=org, output_json=output_json)


@auth_app.command("grant")
def grant_cmd(
    poll: bool = typer.Option(
        False,
        "--poll",
        help="Perform one permission-grant poll step instead of initiating.",
    ),
    device_code: Optional[str] = typer.Option(
        None,
        "--device-code",
        help="The device_code from a prior `cc auth grant --json`.",
    ),
    org: Optional[str] = typer.Option(
        None,
        "--org",
        help="GitHub org slug; falls back to github_app.org.",
    ),
    output_json: bool = typer.Option(
        False,
        "--json",
        help="Output the strict auth permission-grant contract as JSON.",
    ),
) -> None:
    """Request only the permission needed to add this Mac's public SSH key."""
    import json as _json

    org_kwargs: dict[str, Any] = {"_org": org} if org else {}
    if poll:
        if not device_code:
            message = "cc auth grant --poll requires --device-code <code>."
            report = _error_envelope("missing-argument", message)
        else:
            report = build_auth_grant_poll_report(
                device_code,
                **org_kwargs,
            )
    else:
        report = build_auth_grant_initiate_report(**org_kwargs)

    if output_json:
        typer.echo(_json.dumps(report))
    else:
        render_auth_report_rich(report)
    raise typer.Exit(compute_exit_code(report))


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
    org: Optional[str] = typer.Option(
        None,
        "--org",
        help="GitHub org slug to sign in through -- see `cc auth login --help`.",
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
    _run_login(poll=poll, device_code=device_code, org=org, output_json=output_json)
