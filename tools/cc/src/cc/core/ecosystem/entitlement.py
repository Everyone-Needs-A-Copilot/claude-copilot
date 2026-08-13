"""GitHub repo-access entitlement check (D3, the entitlement spine).

copilot-control-tower/docs/01-architecture/cli-contract.md D7.1: entitlement
to a department/org layer is defined as "has GitHub repo access to it" --
computed CLI-side (invariant #1: parse, never compute -- Control Tower only
ever renders the `entitled` bool/null this module produces, it never
evaluates repo permissions itself).

Backs `cc layers --json` / `cc layers join --json` (commands/layers.py).

Transport is injectable (`get_json`) so tests never make a real network
call: the stdlib `urllib` default is the only production implementation,
no new dependency. `repo_accessible()` never raises -- any transport
failure (DNS, timeout, TLS, `git`/network unreachable) degrades to `None`
("could not determine" -- offline), mirroring
core/ecosystem/mirror.py's `latest_lock_sha()` / `clone_or_update_mirror()`
"never a fabricated answer" rule.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from contextlib import ExitStack
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional, TypeVar

from cc.core import authstore
from cc.core.config_paths import machine_config_path
from cc.core.ecosystem.project_locking import advisory_file_lock, atomic_json_write

# Injectable transport: (url, token) -> HTTP status code, or None on a
# network-level failure (offline/unreachable/timeout). Kept to the minimum
# signature `repo_accessible()` needs -- callers/tests supply a fake that
# never touches the network.
GetJsonFn = Callable[..., Optional[int]]

_GITHUB_API_BASE = "https://api.github.com/repos"
ENTITLEMENT_SCHEMA_VERSION = "1.0"
OFFLINE_GRACE = timedelta(hours=72)
_PROTECTED_ROLES = frozenset({"org", "organization", "department"})
_BLOCKING_STATES = frozenset({"signed-out", "unentitled", "revoked"})
_OFFLINE_CACHE_SOURCE_STATES = frozenset({"entitled", "offline"})
_SLUG = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_T = TypeVar("_T")


@dataclass(frozen=True)
class EntitlementDecision:
    layer: str
    state: str
    eligible: bool
    responsible_actor: str
    recovery: str
    checked_at: str | None = None
    expires_at: str | None = None
    revision: int | None = None
    superseded: bool = False


@dataclass(frozen=True)
class EntitlementBinding:
    """Private plan binding between one layer decision and its local ledger."""

    state_path: str
    layer: str
    repo: str
    login: str | None
    revision: int
    state: str
    eligible: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "state_path": self.state_path,
            "layer": self.layer,
            "repo": self.repo,
            "login": self.login,
            "revision": self.revision,
            "state": self.state,
            "eligible": self.eligible,
        }

    @classmethod
    def from_value(cls, value: object) -> "EntitlementBinding":
        if isinstance(value, cls):
            return value
        if not isinstance(value, dict) or set(value) != {
            "state_path",
            "layer",
            "repo",
            "login",
            "revision",
            "state",
            "eligible",
        }:
            raise ValueError("An entitlement binding is invalid.")
        state_path = value.get("state_path")
        layer = value.get("layer")
        repo = value.get("repo")
        login = value.get("login")
        revision = value.get("revision")
        state = value.get("state")
        eligible = value.get("eligible")
        if (
            not isinstance(state_path, str)
            or not Path(state_path).is_absolute()
            or not isinstance(layer, str)
            or not layer
            or not isinstance(repo, str)
            or github_repo_slug(repo) != repo
            or not (login is None or isinstance(login, str) and login)
            or not isinstance(revision, int)
            or isinstance(revision, bool)
            or revision < 0
            or not isinstance(state, str)
            or not state
            or not isinstance(eligible, bool)
        ):
            raise ValueError("An entitlement binding is invalid.")
        canonical = Path(state_path).expanduser()
        if canonical != Path(state_path) or canonical.name in {"", ".", ".."}:
            raise ValueError("An entitlement binding state path is invalid.")
        return cls(state_path, layer, repo, login, revision, state, eligible)


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _utc(parsed)


def entitlement_state_path() -> Path:
    """Machine-local identity/access observations; never a shareable lock."""
    return machine_config_path().parent / "entitlements.json"


def github_repo_slug(source: object) -> str | None:
    """Normalize supported GitHub HTTPS/SSH repository spellings."""
    if not isinstance(source, str) or not source:
        return None
    candidate = source.strip()
    if _SLUG.fullmatch(candidate):
        return candidate.removesuffix(".git")
    match = re.fullmatch(r"https?://github\.com/([^/]+/[^/]+?)(?:\.git)?/?", candidate)
    if match is None:
        match = re.fullmatch(
            r"git@github(?:\.com|-[A-Za-z0-9_.-]+)?:(.+?)(?:\.git)?", candidate
        )
    slug = match.group(1) if match else None
    return slug if slug and _SLUG.fullmatch(slug) else None


def is_protected_layer(layer: dict[str, object]) -> bool:
    return (
        str(layer.get("role", "")).lower() in _PROTECTED_ROLES
        and str(layer.get("auth", "")).lower() != "anon"
    )


def _load_ledger(path: Path) -> tuple[dict[str, dict[str, object]], int]:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not path.is_file() or metadata.st_mode & 0o077:
            return {}, 1
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}, 1
    if (
        not isinstance(raw, dict)
        or raw.get("schema_version") != ENTITLEMENT_SCHEMA_VERSION
        or not isinstance(raw.get("layers"), dict)
    ):
        return {}, 1
    layers = {
        str(key): dict(value)
        for key, value in raw["layers"].items()
        if isinstance(key, str) and isinstance(value, dict)
    }
    revisions = [
        revision
        for record in layers.values()
        for revision in (record.get("revision"),)
        if isinstance(revision, int)
        and not isinstance(revision, bool)
        and revision >= 0
    ]
    declared = raw.get("next_sequence")
    next_sequence = (
        declared
        if isinstance(declared, int) and not isinstance(declared, bool) and declared > 0
        else 1
    )
    return layers, max(next_sequence, max(revisions, default=0) + 1)


def _load_state(path: Path) -> dict[str, dict[str, object]]:
    return _load_ledger(path)[0]


def _write_state(
    path: Path, layers: dict[str, dict[str, object]], *, next_sequence: int
) -> None:
    atomic_json_write(
        path,
        {
            "schema_version": ENTITLEMENT_SCHEMA_VERSION,
            "next_sequence": next_sequence,
            "layers": layers,
        },
    )


def _ledger_lock_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.lock")


def _reserve_observation(path: Path) -> int:
    """Reserve an unforgeable process-order sequence before a live probe."""
    with advisory_file_lock(_ledger_lock_path(path), blocking=True):
        layers, next_sequence = _load_ledger(path)
        sequence = next_sequence
        _write_state(path, layers, next_sequence=sequence + 1)
    return sequence


def _recovery(state: str) -> tuple[str, str]:
    if state == "signed-out":
        return "person", "Sign in to GitHub, then run cc update."
    if state in _BLOCKING_STATES:
        return (
            "organization-access-owner",
            "Restore GitHub repository access, then have the person run cc update.",
        )
    if state in {"offline-unverified", "offline-cached", "stale-entitlement"}:
        return "person", "Restore network access, then run cc update."
    if state == "invalid-source":
        return "ecosystem-owner", "Repair the protected layer repository declaration."
    return "none", "No recovery action is required."


def _decision(
    layer_id: str,
    state: str,
    eligible: bool,
    *,
    checked_at: str | None = None,
    expires_at: str | None = None,
    revision: int | None = None,
    superseded: bool = False,
) -> EntitlementDecision:
    actor, recovery = _recovery(state)
    return EntitlementDecision(
        layer_id,
        state,
        eligible,
        actor,
        recovery,
        checked_at,
        expires_at,
        revision,
        superseded,
    )


def _cached_decision(
    layer: dict[str, object],
    record: dict[str, object] | None,
    *,
    login: str | None,
    now: datetime,
) -> EntitlementDecision:
    layer_id = str(layer.get("id", ""))
    if not is_protected_layer(layer):
        return _decision(layer_id, "not-required", True)
    slug = (
        github_repo_slug((layer.get("source") or {}).get("repo"))
        if isinstance(layer.get("source"), dict)
        else None
    )
    if slug is None:
        return _decision(layer_id, "invalid-source", False)
    revision_value = record.get("revision") if isinstance(record, dict) else None
    revision = (
        revision_value
        if isinstance(revision_value, int)
        and not isinstance(revision_value, bool)
        and revision_value >= 0
        else None
    )
    if record is None or record.get("repo") != slug or record.get("login") != login:
        return _decision(
            layer_id,
            "signed-out" if not login else "offline-unverified",
            False,
            revision=revision,
        )
    checked = _parse_timestamp(record.get("checked_at"))
    last_entitled = _parse_timestamp(record.get("last_entitled_at"))
    # A local clock rollback or tampered/future record must never mint extra
    # offline eligibility. No positive skew is tolerated: a fresh live 200 is
    # the recovery path for an impossible temporal record.
    if (
        checked is None
        or checked > now
        or (last_entitled is not None and last_entitled > now)
        or (last_entitled is not None and last_entitled > checked)
    ):
        return _decision(layer_id, "offline-unverified", False, revision=revision)
    state = str(record.get("state", ""))
    if state in _BLOCKING_STATES:
        return _decision(
            layer_id,
            state,
            False,
            checked_at=record.get("checked_at")
            if isinstance(record.get("checked_at"), str)
            else None,
            revision=revision,
        )
    if state not in _OFFLINE_CACHE_SOURCE_STATES or last_entitled is None:
        return _decision(layer_id, "offline-unverified", False, revision=revision)
    expires = last_entitled + OFFLINE_GRACE
    eligible = now <= expires
    return _decision(
        layer_id,
        "offline-cached" if eligible else "stale-entitlement",
        eligible,
        checked_at=_timestamp(checked) if checked else None,
        expires_at=_timestamp(expires),
        revision=revision,
    )


def run_under_revision_lease(
    *,
    state_path: Path | str,
    decisions: list[EntitlementDecision],
    action: Callable[[], _T],
) -> tuple[bool, _T | None]:
    """Run mutation only while every protected decision revision is current.

    The ledger lock is held from validation through the callback. Observers
    cannot reserve a newer generation until the filesystem/lock transaction
    finishes or the process exits, so a validated plan cannot be superseded
    midway through its commit.
    """
    protected = [decision for decision in decisions if decision.revision is not None]
    if not protected:
        return True, action()
    path = Path(state_path).expanduser()
    with advisory_file_lock(_ledger_lock_path(path), blocking=True):
        records, _next_sequence = _load_ledger(path)
        for decision in protected:
            record = records.get(decision.layer)
            if (
                decision.superseded
                or not isinstance(record, dict)
                or record.get("revision") != decision.revision
            ):
                return False, None
        return True, action()


def current_login() -> str | None:
    try:
        identity = authstore.read_identity()
    except Exception:
        return None
    login = identity.get("login") if isinstance(identity, dict) else None
    return login if isinstance(login, str) and login else None


def filter_eligible_layers(
    layers: list[dict[str, object]],
    *,
    state_path: Path | str | None = None,
    login: str | None = None,
    now: datetime | None = None,
) -> tuple[list[dict[str, object]], list[EntitlementDecision]]:
    """Filter protected layers using only bounded, machine-local observations."""
    if not any(is_protected_layer(layer) for layer in layers):
        return (
            list(layers),
            [
                _decision(str(layer.get("id", "")), "not-required", True)
                for layer in layers
            ],
        )
    path = (
        Path(state_path).expanduser()
        if state_path is not None
        else entitlement_state_path()
    )
    records = _load_state(path)
    identity = current_login() if login is None else login
    current = _utc(now)
    eligible: list[dict[str, object]] = []
    decisions: list[EntitlementDecision] = []
    for layer in layers:
        decision = _cached_decision(
            layer, records.get(str(layer.get("id", ""))), login=identity, now=current
        )
        decisions.append(decision)
        if decision.eligible:
            eligible.append(layer)
    return eligible, decisions


def bind_layer_decisions(
    layers: list[dict[str, object]],
    decisions: list[EntitlementDecision],
    *,
    state_path: Path | str,
    login: str | None,
) -> tuple[EntitlementBinding, ...]:
    """Bind every protected layer decision for a private executable plan.

    Revision zero represents an absent/unversioned row.  It is deliberately
    useful: a plan that selected the public fallback while a protected layer
    was unavailable must become stale when a later live observation creates or
    upgrades that row.
    """

    if len(layers) != len(decisions):
        raise ValueError("Layer decisions do not match their manifest.")
    path = Path(state_path).expanduser()
    if not path.is_absolute():
        raise ValueError("Entitlement state must use an absolute private path.")
    records = _load_state(path)
    result: list[EntitlementBinding] = []
    for layer, decision in zip(layers, decisions):
        if not is_protected_layer(layer):
            continue
        source = layer.get("source")
        repo = github_repo_slug(source.get("repo")) if isinstance(source, dict) else None
        if repo is None:
            continue
        current = _cached_decision(
            layer,
            records.get(str(layer.get("id", ""))),
            login=login,
            now=_utc(),
        )
        if current.revision == decision.revision:
            decision = current
        result.append(
            EntitlementBinding(
                state_path=str(path),
                layer=str(layer.get("id", "")),
                repo=repo,
                login=login,
                revision=decision.revision or 0,
                state=decision.state,
                eligible=decision.eligible,
            )
        )
    return tuple(result)


def run_under_binding_leases(
    bindings: list[EntitlementBinding] | tuple[EntitlementBinding, ...],
    action: Callable[[], _T],
) -> tuple[bool, _T | None]:
    """Validate private plan bindings and run while their ledgers are locked.

    All ledger locks are acquired in lexical path order before any row is
    inspected.  That gives multi-ledger batches one deterministic lock order
    and keeps validation authoritative through apply, verification, rollback,
    and durable transaction finalization.
    """

    normalized = tuple(EntitlementBinding.from_value(item) for item in bindings)
    if not normalized:
        return True, action()
    by_path: dict[Path, list[EntitlementBinding]] = {}
    for binding in normalized:
        path = Path(binding.state_path)
        by_path.setdefault(path, []).append(binding)
    with ExitStack() as stack:
        for path in sorted(by_path, key=lambda item: item.as_posix()):
            stack.enter_context(
                advisory_file_lock(_ledger_lock_path(path), blocking=True)
            )
        for path, path_bindings in by_path.items():
            records, _next_sequence = _load_ledger(path)
            for binding in path_bindings:
                record = records.get(binding.layer)
                if binding.revision == 0:
                    if isinstance(record, dict):
                        return False, None
                    continue
                if (
                    not isinstance(record, dict)
                    or record.get("revision") != binding.revision
                    or record.get("repo") != binding.repo
                    or (
                        binding.login is not None
                        and record.get("login") != binding.login
                    )
                ):
                    return False, None
                current = _cached_decision(
                    {
                        "id": binding.layer,
                        "role": "organization",
                        "auth": "work",
                        "source": {"repo": binding.repo},
                    },
                    record,
                    login=binding.login,
                    now=_utc(),
                )
                if (
                    current.eligible != binding.eligible
                    or current.state != binding.state
                    or current.revision != binding.revision
                ):
                    return False, None
        return True, action()


def observe_layer(
    layer: dict[str, object],
    *,
    login: str | None,
    token: str | None,
    get_json: GetJsonFn | None = None,
    state_path: Path | str | None = None,
    now: datetime | None = None,
    defer_eligible_knowledge_snapshot_rollover: bool = False,
) -> EntitlementDecision:
    """Record one live GitHub access observation and return current eligibility.

    Canonical ecosystem update may defer cleanup for an eligible Knowledge
    generation so its projector can integrity-check and roll the prior receipt
    under the update transaction.  Terminal decisions are never deferred, and
    ordinary observations retain immediate cleanup.
    """
    layer_id = str(layer.get("id", ""))
    if not is_protected_layer(layer):
        return _decision(layer_id, "not-required", True)
    path = (
        Path(state_path).expanduser()
        if state_path is not None
        else entitlement_state_path()
    )
    current = _utc(now)
    source = layer.get("source")
    slug = github_repo_slug(source.get("repo")) if isinstance(source, dict) else None
    sequence = _reserve_observation(path)
    if slug is None:
        observed_state = "invalid-source"
    elif not login or not token:
        observed_state = "signed-out"
    else:
        accessible = repo_accessible(slug, token, get_json=get_json or default_get_json)
        if accessible is True:
            observed_state = "entitled"
        elif accessible is False:
            observed_state = "denied"
        else:
            observed_state = "offline"

    # Commit is a versioned CAS under a private cross-process ledger lock.
    # The sequence was reserved before the probe, so a slower earlier probe can
    # never overwrite a later observation. Gaps are harmless after a crash.
    with advisory_file_lock(_ledger_lock_path(path), blocking=True):
        records, next_sequence = _load_ledger(path)
        record = records.get(layer_id)
        record_revision = record.get("revision", 0) if isinstance(record, dict) else 0
        if (
            isinstance(record_revision, int)
            and not isinstance(record_revision, bool)
            and record_revision >= sequence
        ):
            authoritative_login = (
                record.get("login")
                if isinstance(record, dict) and isinstance(record.get("login"), str)
                else None
            )
            current_decision = replace(
                _cached_decision(
                    layer, record, login=authoritative_login, now=current
                ),
                superseded=True,
            )
            _reconcile_knowledge_snapshot_authority(
                layer,
                current_decision,
                state_path=path,
                login=authoritative_login,
                defer_eligible_rollover=(defer_eligible_knowledge_snapshot_rollover),
            )
            return current_decision

        if record is not None:
            checked = _parse_timestamp(record.get("checked_at"))
            previous_grant = _parse_timestamp(record.get("last_entitled_at"))
            if (
                checked is None
                or checked > current
                or (previous_grant is not None and previous_grant > current)
                or (previous_grant is not None and previous_grant > checked)
            ):
                # Quarantine an impossible record by refusing to use any of
                # its prior grant facts. This observation replaces it below.
                record = None

        same_binding = bool(
            record
            and record.get("repo") == slug
            and (not login or record.get("login") == login)
        )
        if observed_state == "denied":
            previously_entitled = bool(
                same_binding and record and record.get("last_entitled_at")
            )
            state = "revoked" if previously_entitled else "unentitled"
        else:
            state = observed_state
        if (
            state in {"offline", "signed-out"}
            and same_binding
            and record
            and record.get("state") in _BLOCKING_STATES
        ):
            state = str(record["state"])
        stored_login = (
            record.get("login")
            if state in _BLOCKING_STATES and not login and record
            else login
        )
        last_entitled = (
            _timestamp(current)
            if state == "entitled"
            else record.get("last_entitled_at")
            if record
            and record.get("repo") == slug
            and record.get("login") == stored_login
            else None
        )
        records[layer_id] = {
            "layer": layer_id,
            "product": str(layer.get("product", "")),
            "repo": slug,
            "login": stored_login,
            "state": state,
            "checked_at": _timestamp(current),
            "last_entitled_at": last_entitled,
            "revision": sequence,
        }
        _write_state(path, records, next_sequence=next_sequence)
        if state == "entitled":
            decision = _decision(
                layer_id,
                state,
                True,
                checked_at=_timestamp(current),
                expires_at=_timestamp(current + OFFLINE_GRACE),
                revision=sequence,
            )
        elif state == "offline":
            decision = replace(
                _cached_decision(
                    layer, records[layer_id], login=stored_login, now=current
                ),
                revision=sequence,
            )
        else:
            decision = _decision(
                layer_id,
                state,
                False,
                checked_at=_timestamp(current),
                revision=sequence,
            )
        _reconcile_knowledge_snapshot_authority(
            layer,
            decision,
            state_path=path,
            login=stored_login,
            defer_eligible_rollover=defer_eligible_knowledge_snapshot_rollover,
        )
    return decision


def _reconcile_knowledge_snapshot_authority(
    layer: dict[str, object],
    decision: EntitlementDecision,
    *,
    state_path: Path,
    login: str | None,
    defer_eligible_rollover: bool = False,
) -> None:
    """Keep protected Knowledge snapshots only for the current eligible row.

    The caller holds the entitlement ledger lock, establishing the global
    ledger-before-snapshot lock order used by the resolver as well. A terminal,
    stale, or superseded decision atomically removes the prior pathname before
    the observation returns.
    """
    if str(layer.get("product", "")).lower() != "knowledge":
        return
    if defer_eligible_rollover and decision.eligible:
        return
    source = layer.get("source")
    repository = github_repo_slug(source.get("repo")) if isinstance(source, dict) else None
    if repository is None:
        return
    from cc.core.ecosystem.knowledge_skill_source import (
        prune_protected_knowledge_snapshots,
    )

    prune_protected_knowledge_snapshots(
        layer=decision.layer,
        repository=repository.casefold(),
        state_path=state_path,
        keep_login=login if decision.eligible else None,
        keep_revision=decision.revision if decision.eligible else None,
    )


def default_get_json(url: str, token: str, *, timeout: float = 10.0) -> Optional[int]:
    """
    Real transport: GET `url` with `token` as a GitHub bearer token, stdlib
    `urllib` only (no new dependency). Returns the HTTP status code on any
    response (including 4xx -- an `HTTPError` still carries a real status
    code), or `None` when the request could not complete at all (DNS
    failure, connection refused, timeout, TLS error, ...) -- i.e. "offline",
    never a fabricated status.
    """
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "cc-layers-entitlement",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        # A well-formed HTTP error response (e.g. 403/404) IS a real,
        # reachable answer -- not an offline condition.
        return exc.code
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


def repo_accessible(
    repo: str,
    token: Optional[str],
    *,
    get_json: GetJsonFn = default_get_json,
) -> Optional[bool]:
    """
    Whether `token`'s GitHub identity has access to `repo` (an
    `"owner/name"` slug): `GET https://api.github.com/repos/{repo}`.

      200          -> True  (entitled)
      403/404      -> False (not entitled -- GitHub returns 404, not 403,
                              for a private repo the token cannot see, so
                              both codes are treated identically here)
      network fail -> None  (offline / could not determine -- caller must
                              treat this as an honest unknown, never as
                              either True or False)
      any other status (5xx, unexpected 3xx, ...) -> None, same "unknown"
      treatment -- this function never guesses.

    Returns `None` immediately (no request attempted) when `repo` or
    `token` is falsy -- there is nothing to check without both.
    """
    if not repo or not token:
        return None

    url = f"{_GITHUB_API_BASE}/{repo}"
    try:
        status = get_json(url, token)
    except Exception:
        # Defense in depth: an injected/custom transport that raises
        # instead of returning None is still treated as an honest
        # "could not determine", never propagated as a crash.
        return None

    if status == 200:
        return True
    if status in (403, 404):
        return False
    return None
