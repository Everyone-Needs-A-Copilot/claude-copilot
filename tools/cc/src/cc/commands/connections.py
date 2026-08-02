"""`cc connections --json` -- the organization's service roster plus each
service's shared-credential-store connection state (WP-388/389/390 stage B,
Task Copilot task 221).

WP-388 traced why Control Tower's "Your connections" screen only ever shows
GitHub: `copilot --json layers` already enumerates every service the org
declares (20 live rows), but nothing in `cc` ever read it, and the one
connections-adjacent stage that existed (`onboard.py`'s `secret-store`
stage) called a `copilot infisical identity provision` subcommand that has
never existed. WP-389 confirmed the real `copilot infisical` surface
(`identity list|create`, `secret list|get|set|delete`, no per-name lookup)
and the real presence-only shape `secret list` returns (`secretKey`, never
a value). WP-390 (stage A, `cli-copilot` foundation v0.3.2) added
`id`/`requires_secret`/`store_scope` to each `services[]` row so this
module has something to project.

**Parse-never-compute discipline, restated for this verb specifically:**
the SET of services and their declared `requires_secret` names is entirely
`copilot`'s (never recomputed here -- this module only reads
`copilot --json layers`'s own `services[]`). What THIS module computes is
narrowly scoped to one thing WP-388 identified as missing entirely: whether
each declared secret NAME is present (never its value) in the org's shared
Infisical store, folded into a closed three-state `secret_state` per row
(`ready` | `needs-connect` | `no-store`) so Control Tower can render the
"Ready to use" / "Available to connect" split by filtering on that one
field alone, computing nothing itself (invariant #1).

**Store-scope resolution.** The store's endpoint/workspace/environment/path
are never hardcoded or user-supplied -- they come from the inherited org
config (`core/ecosystem/ecosystem_config.py`'s `load_ecosystem_config()`,
the same materialized `ecosystem.yml` `onboard.py`'s `_provision_store`
reads via the Admin handoff's `store:` block, here read from the local
machine's own already-materialized copy instead of a fresh `gh api` fetch
-- this verb is meant to be cheap and offline-tolerant like `doctor`/
`freshness`, not a network round-trip on every invocation). A row's own
`store_scope` (maps to `ecosystem.yml`'s `team_scopes`) is carried through
verbatim for the app to render, but is NOT yet used to select a
DIFFERENT presence-check scope than the org's single default: today's real
`ecosystem.yml` has an empty `team_scopes:`, so every real row's
`store_scope` is `null` and there is nothing to differentiate against.
Building that differentiation now, with zero live data to validate it
against, would be exactly the kind of speculative abstraction this
codebase's design discipline forbids -- flagged here as a known, honest
scope boundary rather than silently guessed at.

**`from` routing hints and what this verb can prove.** Each declared
secret carries a `from` hint (`store` | `keychain` | `any`, cli-copilot's
`$defs.requiredSecret`). This verb presence-checks names hinted `store`
or `any` against the shared store; a `keychain`-hinted name (e.g. the
real `discord` service's `DISCORD_BOT_TOKEN`) is, by the declaring
tier's own routing hint, never meant to resolve from the shared store at
all, so this verb instead presence-checks it directly against the local
OS keychain (`security find-generic-password`, presence only -- never
`-w`/a value) -- WP-395 G-1. A row whose `requires_secret` are ALL
`keychain`-hinted therefore has nothing STORE-checkable to prove, but its
keychain-checked names are still genuinely verified, never assumed
`ready`.

**Bootstrap/never-store-able names -- the WP-395 G-1 defensive backstop.**
A handful of names are structurally impossible for the shared store to
ever hold (the store cannot hold the credentials used to authenticate to
it -- `INFISICAL_CLIENT_ID`/`_SECRET` and their sibling store-config
names). cli-copilot's own `config/managed_store.py` enforces this
store-side via `_NEVER_FROM_STORE`; `cc` cannot import cli-copilot code,
so `_NEVER_FROM_STORE` below duplicates that exact name list (the
"honest mirror," not a guess -- see that module for the canonical list).
Regardless of what `from` hint a tier's overlay declares for one of these
names (including a still-buggy `from: "any"`/`"store"`, the exact defect
WP-395 found live: `cli.overlay.yml` declared the Infisical bootstrap
pair as bare strings, so they were `from: "any"` and checked against a
store that can never hold them, a permanent false `needs-connect`), this
verb always routes them to the OS keychain presence-check instead of the
shared store -- so a future overlay regression of this exact kind can
never reintroduce the false negative.

**Fail-closed structured results.** A missing/unresolvable `copilot`
binary and a missing/unmaterialized org config are DISTINCT, honestly
named top-level `result` values (`copilot-unavailable` /
`org-config-unavailable`) rather than a generic error bucket or a silently
empty payload -- see `build_connections_report()`. `org-config-unavailable`
still returns every service row it can (tier/mode/requires_secret come
from `copilot --json layers` alone, independent of the org config) with
`secret_state: "no-store"` wherever a store-checkable secret is required,
rather than emptying `connections` outright -- the app can still render
the roster even when the store portion is degraded.

SAFETY: every collaborator is injectable (`run`, `ecosystem_cfg`,
`check_keychain`) -- see `build_connections_report()`. Production
defaults only ever resolve through `resolve_executable()` (the standard
`copilot` executable registry, `core/executables.py` -- never a bare
`copilot` string handed to `subprocess`, matching this codebase's
translocation-safety convention), `load_ecosystem_config()` (the standard
inherited-config reader), and the macOS `security` CLI (presence-only,
never `-w`). NEVER prints, logs, or returns a secret VALUE -- only names
(from the overlay's own declarations) and boolean presence (from
Infisical's keys-only `secret list` and the keychain's exit code alone).

Schema: copilot-control-tower/docs/01-architecture/schemas/connections.schema.json
(vendored copy: tools/cc/tests/fixtures/schemas/connections.schema.json).
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any, Callable, NamedTuple, Optional, Sequence

from cc.core.ecosystem.ecosystem_config import load_ecosystem_config
from cc.core.executables import resolve_executable

SCHEMA_VERSION = "1.0"

# Mirrors onboard.py's `_provision_store` guard -- the three `store:` keys
# an Infisical scope needs to be usable at all. Duplicated rather than
# imported: onboard.py is an orchestration module this read-only verb has
# no other reason to depend on, and the guard is a handful of lines with
# no shared mutable state to drift.
_STORE_REQUIRED_KEYS: tuple[str, ...] = ("workspace_id", "environment", "secret_path")

# `requires_secret[].from` values this verb presence-checks against the
# shared store. A name in `_NEVER_FROM_STORE` (below) is routed to the
# keychain check instead, REGARDLESS of its declared hint -- see the
# module docstring's "bootstrap/never-store-able names" section.
_STORE_CHECKED_HINTS = frozenset({"store", "any"})

# Bootstrap/store-configuration secret NAMES the shared store can never
# hold (it cannot hold the credentials used to authenticate to it).
# Duplicates cli-copilot's `config/managed_store.py` `_NEVER_FROM_STORE`
# byte-for-byte -- `cc` cannot import cli-copilot code, so this is the
# honest mirror, not a guess (WP-395 G-1). A name in this set is always
# presence-checked against the OS keychain, never the shared store, no
# matter what `from` hint a tier's overlay declares for it -- the
# defensive backstop that keeps a future overlay regression of the exact
# live defect WP-395 found (the Infisical bootstrap pair declared bare,
# so `from: "any"`, store-checked, permanently absent) from reintroducing
# a false `needs-connect`.
_NEVER_FROM_STORE = frozenset(
    {
        "INFISICAL_CLIENT_ID",
        "INFISICAL_CLIENT_SECRET",
        "INFISICAL_BASE_URL",
        "INFISICAL_ORG_ID",
        "INFISICAL_WORKSPACE_ID",
        "INFISICAL_ENVIRONMENT",
        "INFISICAL_SECRET_PATH",
    }
)

# Matches cli-copilot's `secrets_ladder.KEYCHAIN_SERVICE` -- the one OS
# keychain service every credential-ladder-resolved name lives under.
KEYCHAIN_SERVICE = "copilot-cli"

Run = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]
CheckKeychain = Callable[[str], bool]


def _check_keychain(name: str) -> bool:
    """Default `CheckKeychain`: presence-only OS keychain lookup (macOS
    `security find-generic-password`) for *name* under service
    `copilot-cli` -- mirrors cli-copilot's `secrets_ladder._rung_keychain`
    lookup exactly, but never reads the value (`-w` is omitted; only the
    exit code is inspected) per this module's own value-blindness
    contract. Non-macOS or any subprocess failure reads "absent", never
    raises -- a probe, not a fail-closed resolution."""
    if sys.platform != "darwin":
        return False
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", name],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _run(args: Sequence[str]) -> "subprocess.CompletedProcess[str]":
    """Default `Run`: resolve `args[0]` via the standard executable
    registry and shell it directly -- the same pattern `onboard.py`'s
    `_copilot_layers_payload()`/`_sync_cli_manifest()` already use for
    `copilot` specifically (as opposed to `onboard.py`'s own more general
    `_run()`, which additionally follows `#!/usr/bin/env` shebangs to
    support version-manager shims for OTHER commands like `claude`/
    `codex`/`node` -- `copilot` only ever resolves to a fixed Homebrew/
    usr-local path, so that extra machinery has nothing to do here).
    """
    if not args:
        return subprocess.CompletedProcess(args, 127, "", "No command was provided.")
    executable = resolve_executable(args[0])
    if executable is None:
        return subprocess.CompletedProcess(
            args, 127, "", f"{args[0]} is not installed."
        )
    try:
        return subprocess.run(
            (str(executable), *args[1:]),
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(args, 127, "", str(exc))


class _StoreProbe(NamedTuple):
    """One presence-check outcome for a single (workspace, env, path) scope."""

    reachable: bool
    present: frozenset[str]
    detail: Optional[str]
    # Raw machine-only text (e.g. the underlying CLI's stderr) for logging/
    # debugging -- NEVER rendered to a user; `detail` above is the plain-
    # language sentence `cc` authors for that (invariant #1, WP-395 G-2).
    # Null whenever there is nothing further to log.
    diagnostic: Optional[str] = None


def _copilot_layers(*, run: Run) -> tuple[Optional[dict[str, Any]], str]:
    """Ask the installed `copilot` for its service roster.

    Returns `(payload, "")` on success or `(None, detail)` on any failure
    -- mirrors `onboard.py`'s `_copilot_layers_payload()` return shape.
    """
    result = run(("copilot", "--json", "layers"))
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        return None, f"The installed `copilot` reader rejected the request: {detail}"
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, "The installed `copilot` reader returned unreadable output."
    if not isinstance(payload, dict) or not isinstance(payload.get("services"), list):
        return None, "The installed `copilot` reader returned an unfamiliar report."
    return payload, ""


def _scope_summary(store_cfg: dict[str, Any]) -> Optional[str]:
    """A short, non-secret `environment:path` string for display -- never
    includes `workspace_id` (an opaque UUID, not meaningful to render),
    mirrors `onboard.py`'s `_provision_store` `scope` string convention
    minus its `:read` suffix (that suffix describes an access GRANT this
    verb never requests; this is only describing WHERE it looked)."""
    environment = store_cfg.get("environment")
    secret_path = store_cfg.get("secret_path")
    if not (isinstance(environment, str) and environment):
        return None
    if not (isinstance(secret_path, str) and secret_path):
        return None
    return f"{environment}:{secret_path}"


def _probe_store(store_cfg: dict[str, Any], *, run: Run) -> _StoreProbe:
    """Presence-check the org's declared Infisical scope ONE time (never
    once per secret name -- WP-389 confirmed `secret list` has no per-name
    filter and always returns every key at a scope). Returns which
    `secretKey` names are present; never a value."""
    if store_cfg.get("status") != "connected":
        return _StoreProbe(
            False,
            frozenset(),
            "The organization's shared credential store is not connected on this Mac.",
        )
    if store_cfg.get("type") != "infisical":
        return _StoreProbe(
            False,
            frozenset(),
            "Automated presence-checking currently supports Infisical only.",
        )
    if not all(
        isinstance(store_cfg.get(key), str) and store_cfg.get(key)
        for key in _STORE_REQUIRED_KEYS
    ):
        return _StoreProbe(
            False,
            frozenset(),
            "The organization's shared store configuration is incomplete.",
        )
    workspace_id = store_cfg["workspace_id"]
    environment = store_cfg["environment"]
    secret_path = store_cfg["secret_path"]
    result = run(
        (
            "copilot",
            "infisical",
            "--json",
            "secret",
            "list",
            "--project",
            workspace_id,
            "--env",
            environment,
            "--path",
            secret_path,
        )
    )
    if result.returncode != 0:
        # WP-395 G-2: the underlying CLI's raw stderr (e.g. "Infisical
        # credentials not configured. Set INFISICAL_CLIENT_ID and
        # INFISICAL_CLIENT_SECRET in your .env.") is a developer error
        # message, wrong advice for a non-technical user (the ladder no
        # longer reads the `.env` rung for these names at all -- G-1), and
        # jargon this invariant forbids passing through verbatim. `cc`
        # authors the human-facing sentence itself; the raw text is kept
        # only in `diagnostic`, a machine-only field never rendered to a
        # user (see `build_connections_report()`'s "store" mapping).
        diagnostic = result.stderr.strip() or result.stdout.strip() or "unknown error"
        return _StoreProbe(
            False,
            frozenset(),
            "This Mac isn't connected to your organization's shared credential "
            "store yet. Your IT admin can set that up — nothing is wrong with "
            "your setup.",
            diagnostic,
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return _StoreProbe(
            False, frozenset(), "The shared credential store returned unreadable output."
        )
    if not isinstance(payload, list):
        return _StoreProbe(
            False, frozenset(), "The shared credential store returned an unfamiliar report."
        )
    present = frozenset(
        item["secretKey"]
        for item in payload
        if isinstance(item, dict)
        and isinstance(item.get("secretKey"), str)
        and item["secretKey"]
    )
    return _StoreProbe(True, present, None)


def _connection_row(
    service: dict[str, Any],
    probe: _StoreProbe,
    *,
    check_keychain: CheckKeychain,
) -> dict[str, Any]:
    """Project one `copilot --json layers` service row into one connections
    row, folding in this run's store presence-check AND (WP-395 G-1) a real
    OS-keychain presence-check for every `keychain`-hinted or structurally
    never-store-able (`_NEVER_FROM_STORE`) name. Tolerant of an older
    `copilot` (pre-v0.3.2) that has no `id`/`requires_secret`/`store_scope`
    at all -- `.get()` with the same fallbacks the schema itself documents
    (`id` defaults to `name`; the others default empty/null), the same
    N-1 compatibility posture `onboard.py`'s `_probe_cli_candidate`
    already applies to this payload."""
    name = service.get("name")
    raw_requires = service.get("requires_secret")
    requires_secret = [
        {
            "name": item["name"],
            "from": item.get("from") if isinstance(item.get("from"), str) else "any",
        }
        for item in (raw_requires if isinstance(raw_requires, list) else [])
        if isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"]
    ]

    # Every declared name is checked exactly once, against exactly one
    # place: the OS keychain for `keychain`-hinted or never-store-able
    # names (regardless of hint -- the G-1 defensive backstop), the shared
    # store for everything else hinted `store`/`any`. `missing` preserves
    # `requires_secret` declaration order across both checks.
    any_checked = False
    store_unreachable_for_row = False
    missing: list[str] = []
    for item in requires_secret:
        item_name, hint = item["name"], item["from"]
        if hint == "keychain" or item_name in _NEVER_FROM_STORE:
            any_checked = True
            if not check_keychain(item_name):
                missing.append(item_name)
        elif hint in _STORE_CHECKED_HINTS:
            any_checked = True
            if not probe.reachable:
                store_unreachable_for_row = True
                missing.append(item_name)
            elif item_name not in probe.present:
                missing.append(item_name)

    if not any_checked:
        secret_state = "ready"
    elif store_unreachable_for_row:
        secret_state = "no-store"
    elif missing:
        secret_state = "needs-connect"
    else:
        secret_state = "ready"

    return {
        "id": service.get("id") if isinstance(service.get("id"), str) and service.get("id") else name,
        "name": name,
        "description": service.get("help") or "",
        "tier": service.get("tier"),
        "mode": service.get("mode"),
        "requires_secret": requires_secret,
        "store_scope": service.get("store_scope") if isinstance(service.get("store_scope"), str) else None,
        "secret_state": secret_state,
        "missing": missing,
    }


def build_connections_report(
    *,
    run: Optional[Run] = None,
    ecosystem_cfg: Optional[dict[str, Any]] = None,
    check_keychain: Optional[CheckKeychain] = None,
) -> dict[str, Any]:
    """Build the `cc connections --json` contract object.

    `run` defaults to `_run` (real `copilot` subprocess calls); tests
    inject a fake. `ecosystem_cfg` defaults to a fresh
    `load_ecosystem_config()` read; tests inject an already-loaded dict
    (mirrors `onboard.py`'s `_provision_store(store, ...)` taking an
    already-loaded `store:` block rather than re-reading it).
    `check_keychain` defaults to `_check_keychain` (real, presence-only
    `security` calls); tests inject a fake -- see WP-395 G-1.
    """
    if run is None:
        run = _run
    if check_keychain is None:
        check_keychain = _check_keychain
    cfg = ecosystem_cfg if ecosystem_cfg is not None else load_ecosystem_config()
    org = cfg.get("org") if isinstance(cfg.get("org"), str) and cfg.get("org") else None
    store_cfg = cfg.get("store") if isinstance(cfg.get("store"), dict) else {}
    scope = _scope_summary(store_cfg)
    store_type = store_cfg.get("type") if isinstance(store_cfg.get("type"), str) else None

    layers_payload, layers_detail = _copilot_layers(run=run)
    if layers_payload is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "result": "copilot-unavailable",
            "detail": layers_detail,
            "org": org,
            "store": {
                "type": store_type,
                "reachable": False,
                "scope": scope,
                "detail": layers_detail,
                "diagnostic": None,
            },
            "connections": [],
        }

    services = [item for item in layers_payload.get("services", []) if isinstance(item, dict)]

    if not cfg:
        detail = (
            "The organization's inherited configuration (ecosystem.yml) was "
            "not found on this Mac."
        )
        probe = _StoreProbe(False, frozenset(), detail)
        connections = [
            _connection_row(service, probe, check_keychain=check_keychain) for service in services
        ]
        return {
            "schema_version": SCHEMA_VERSION,
            "result": "org-config-unavailable",
            "detail": detail,
            "org": None,
            "store": {
                "type": None,
                "reachable": False,
                "scope": None,
                "detail": detail,
                "diagnostic": None,
            },
            "connections": connections,
        }

    probe = _probe_store(store_cfg, run=run)
    connections = [
        _connection_row(service, probe, check_keychain=check_keychain) for service in services
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "result": "ok",
        "detail": None,
        "org": org,
        "store": {
            "type": store_type,
            "reachable": probe.reachable,
            "scope": scope,
            "detail": probe.detail,
            "diagnostic": probe.diagnostic,
        },
        "connections": connections,
    }


def render_connections_report_rich(report: dict[str, Any], *, console: Any = None) -> None:
    """Human-readable (Rich) rendering of a `build_connections_report()`
    payload -- the same two-group split (READY TO USE / AVAILABLE TO
    CONNECT) WP-388 §7 prescribes for Control Tower's own rendering,
    filtering only on `secret_state` exactly as the app is meant to."""
    from rich.console import Console

    con = console or Console()
    result = report.get("result", "unknown")
    if result != "ok":
        con.print(f"[bold red]{result}[/bold red]: {report.get('detail') or 'unknown error'}")
        return

    store = report.get("store") or {}
    store_color = "green" if store.get("reachable") else "yellow"
    store_text = "connected" if store.get("reachable") else "not connected"
    con.print(
        f"[bold]org:[/bold] {report.get('org') or 'unknown'}   "
        f"[{store_color}]store: {store_text}[/{store_color}]"
    )

    connections = report.get("connections", [])
    ready = [c for c in connections if c.get("secret_state") == "ready"]
    other = [c for c in connections if c.get("secret_state") != "ready"]

    con.print("\n[bold]Ready to use[/bold]")
    for c in ready:
        con.print(f"  [green]ready[/green] {c.get('name')}: {c.get('description')}")

    con.print("\n[bold]Available to connect[/bold]")
    for c in other:
        state = c.get("secret_state")
        color = "yellow" if state == "needs-connect" else "red"
        missing = ", ".join(c.get("missing", []))
        con.print(f"  [{color}]{state}[/{color}] {c.get('name')}: {c.get('description')} (missing: {missing})")
