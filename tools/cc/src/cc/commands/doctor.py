"""cc config doctor — standalone health check for config + environment.

Separated from config.py so it can be tested in isolation.
The `config doctor` command in config.py delegates to run_doctor().

WS-A slice 1 (doctor-slice): this module also builds the versioned
`cc doctor --json` contract consumed by Control Tower. See:
  - copilot-control-tower/docs/01-architecture/cli-contract.md
  - copilot-control-tower/docs/01-architecture/schemas/doctor.schema.json
  - tools/cc/tests/fixtures/schemas/ (vendored copies used by the contract test)

WS-A doctor-completion (Stream-B): the engine slice. Folds in three more
honest signals, none of which existed in slice 1:
  - per-(product, layer) sync checkers (core/ecosystem/component_status.py),
    reading the manifest + lockfile + a tier's published lock-pointer ref.
  - a real `auth[]` (core/authstore.py's identity pointer + core/keychain.py's
    Keychain presence check) -- emits an entry ONLY for a detectably-bad
    credential state, never for "never signed in" (that is simply no entry,
    not a failure).
  - `syncing`, when (and only when) the advisory copilot lock
    (core/locking.py) is actually held by another process right now -- a
    real, non-destructive, non-blocking probe, never a fabricated guess.
  See `_compute_status()`'s docstring for the full worst-wins ladder this
  slice completes.

Naming note: the upstream design names the user-facing verb `copilot doctor`
(the `copilot` binary that wraps `cc`). The ecosystem logic itself lives here
in `cc`; `copilot doctor` can become a thin alias for `cc doctor` once that
wrapper exists. Until then, `cc doctor` IS the doctor verb.
"""

from __future__ import annotations

import fcntl
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple, Optional

from cc.core import keychain
from cc.core.authstore import read_identity
from cc.core.config import get_resolved_config, resolve_key
from cc.core.config_paths import (
    machine_config_path,
    project_config_path,
    repo_root,
)
from cc.core.ecosystem import mirror
from cc.core.ecosystem.component_status import Checker, compute_component_checkers
from cc.core.ecosystem.lockfile import default_lockfile_path, read_lockfile
from cc.core.ecosystem.manifest import ManifestError, load_layers, validate_layers
from cc.core.locking import lock_path

SCHEMA_VERSION = "1.0"

# Sentinel distinguishing "no override passed" from an explicit None argument
# (mirrors commands/update.py's / commands/resolve.py's own `_UNSET`).
_UNSET: Any = object()

# Best-effort `paths.*` config-key -> product attribution (doctor.schema.json's
# optional per-checker `product` field). Only keys unambiguously owned by a
# single one of the four products (knowledge/cli/claude/codex) are listed --
# everything else (paths.memory, paths.shared_docs, paths.mirrors_root, ...)
# is deliberately left unmapped rather than guessed; those checkers simply
# emit no `product` field.
PRODUCT_BY_PATH_KEY: dict[str, str] = {
    "paths.knowledge_repo": "knowledge",
}

# Fallback keychain service name -- mirrors core/config.py's own
# "auth.keychain_service" DEFAULTS entry; only used if that key somehow
# resolves empty (DEFAULTS always sets it, so this is defense-in-depth,
# never the expected path).
_DEFAULT_KEYCHAIN_SERVICE = "com.everyoneneedsacopilot.copilot.github"


class DoctorResult(NamedTuple):
    warnings: list[str]
    errors: list[str]


# Sentinel object used by tests to simulate "not inside a git repo".
# Pass _project_cfg_path=NOT_IN_REPO to run_doctor().
NOT_IN_REPO: Any = object()


def _run_checks(
    *,
    machine_cfg_path: Path | None = None,
    project_cfg_path: Any = ...,
    resolved_cfg: dict | None = None,
) -> list[Checker]:
    """
    Run every config health check and return discrete Checker results
    (including passing checks), in the order the legacy warnings were
    historically emitted.

    Both `run_doctor()` and `build_doctor_report()` are thin views over this
    single source of truth so the two representations cannot drift.
    """
    checkers: list[Checker] = []

    machine_cfg = machine_cfg_path or machine_config_path()

    # Resolve project config path
    if project_cfg_path is ...:
        project_cfg: Path | None = project_config_path()
    elif project_cfg_path is NOT_IN_REPO:
        project_cfg = None
    else:
        project_cfg = project_cfg_path

    # --- Machine config ---
    if machine_cfg.exists():
        checkers.append(
            Checker(
                id="machine-config",
                severity="pass",
                detail=f"Machine config found: {machine_cfg}",
            )
        )
    else:
        checkers.append(
            Checker(
                id="machine-config",
                severity="warn",
                detail=f"Machine config missing: {machine_cfg}  (run: cc config init --machine)",
            )
        )

    # --- Project config ---
    if project_cfg is None:
        checkers.append(
            Checker(
                id="project-repo",
                severity="warn",
                detail="Not inside a git repository — project config checks skipped.",
            )
        )
    elif not project_cfg.exists():
        checkers.append(
            Checker(
                id="project-config",
                severity="warn",
                detail=f"Project config missing: {project_cfg}  (run: cc config init --project)",
            )
        )
    else:
        checkers.append(
            Checker(
                id="project-config",
                severity="pass",
                detail=f"Project config found: {project_cfg}",
            )
        )

    # --- Declared paths ---
    cfg = resolved_cfg if resolved_cfg is not None else get_resolved_config()
    path_keys = sorted(k for k in cfg if k.startswith("paths."))
    for k in path_keys:
        v = cfg.get(k)
        if v is None:
            continue
        # Best-effort product attribution: only path keys unambiguously
        # owned by one of the four products get one -- everything else is
        # left absent rather than guessed (see PRODUCT_BY_PATH_KEY below).
        product = PRODUCT_BY_PATH_KEY.get(k)
        # paths.knowledge_repo (and any future list-valued path key) may
        # resolve to an ordered list of paths rather than a single scalar.
        candidates = v if isinstance(v, list) else [v]
        multi = isinstance(v, list) and len(v) > 1
        for idx, item in enumerate(candidates):
            if not item:
                continue
            checker_id = f"config-path:{k}[{idx}]" if multi else f"config-path:{k}"
            p = Path(str(item))
            if p.exists():
                checkers.append(
                    Checker(
                        id=checker_id,
                        severity="pass",
                        detail=f"Path exists: {k} = {item}",
                        path=str(item),
                        product=product,
                    )
                )
            else:
                checkers.append(
                    Checker(
                        id=checker_id,
                        severity="warn",
                        detail=f"Path not found: {k} = {item}",
                        path=str(item),
                        product=product,
                    )
                )

    # --- Machine config dir gitignore ---
    if machine_cfg.exists():
        gitignore_path = machine_cfg.parent / ".gitignore"
        if gitignore_path.exists():
            checkers.append(
                Checker(
                    id="machine-config-gitignore",
                    severity="pass",
                    detail=f".gitignore present in {machine_cfg.parent}",
                )
            )
        else:
            checkers.append(
                Checker(
                    id="machine-config-gitignore",
                    severity="warn",
                    detail=f"No .gitignore in {machine_cfg.parent} — machine config may be committed accidentally.",
                )
            )

    # --- Project secrets not gitignored ---
    if project_cfg is not None and isinstance(project_cfg, Path):
        proj_secrets = project_cfg.parent / "secrets.env"
        if proj_secrets.exists():
            root = repo_root()
            if root:
                gitignore = root / ".gitignore"
                if gitignore.exists():
                    content = gitignore.read_text(encoding="utf-8")
                    if "secrets.env" not in content:
                        checkers.append(
                            Checker(
                                id="project-secrets-gitignore",
                                severity="warn",
                                detail="Project secrets.env is not in .gitignore — risk of committing secrets.",
                            )
                        )
                    else:
                        checkers.append(
                            Checker(
                                id="project-secrets-gitignore",
                                severity="pass",
                                detail="Project secrets.env is gitignored.",
                            )
                        )

    return checkers


def run_doctor(
    *,
    _machine_cfg_path: Path | None = None,
    _project_cfg_path: Any = ...,  # ... = "use real path"; NOT_IN_REPO = "no repo"; Path = override
    _resolved_cfg: dict | None = None,
) -> DoctorResult:
    """
    Run all config health checks.

    Injectable paths/config allow unit testing without a real filesystem.

    Special values for _project_cfg_path:
      ...          — use real project_config_path() (default)
      NOT_IN_REPO  — simulate "not inside a git repository"
      Path(...)    — explicit override path

    Returns DoctorResult(warnings, errors).
    Exit semantics (legacy `cc config doctor` — unchanged by the WS-A slice):
      0 = clean
      1 = warnings only
      3 = errors present
    """
    checkers = _run_checks(
        machine_cfg_path=_machine_cfg_path,
        project_cfg_path=_project_cfg_path,
        resolved_cfg=_resolved_cfg,
    )
    warnings = [c.detail for c in checkers if c.severity == "warn"]
    errors = [c.detail for c in checkers if c.severity == "fail"]
    return DoctorResult(warnings=warnings, errors=errors)


def _compute_status(
    config_checkers: list[Checker],
    *,
    component_checkers: Optional[list[Checker]] = None,
    any_remote_offline: bool = False,
    auth_entries: Optional[list[dict[str, Any]]] = None,
    lock_held_by_other: bool = False,
) -> str:
    """
    Compute the top-level `status` field HONESTLY from available signals.

    WS-A doctor-completion ($comment): this is the full worst-wins ladder
    doctor.schema.json documents (`status` property description),
    completing what slice 1 deliberately left unfinished:

      it-config-incomplete > signed-out > needs-attention > offline >
      syncing > update-available > healthy

    `setup-needed` remains a lifecycle state checked FIRST, outside that
    ladder (a machine that has never even been configured has nothing else
    worth computing yet). `it-config-incomplete`/`waiting-for-network`/
    `updating-app` are not emitted by this slice either -- no MDM-config
    signal, first-run wizard, or self-update engine exists in `cc` yet to
    honestly drive them; fabricating one would violate the "never a
    fabricated Healthy [or other state]" rule this whole contract runs on.

      - setup-needed      : machine or project config is missing/unreachable.
      - signed-out        : any auth[] entry is present (expired/revoked --
                            `auth_entries` only ever contains failing
                            credentials, see `_build_auth_entries()`).
      - needs-attention   : any config checker failed or warned (the
                            conservative default slice 1 already chose --
                            see its own historical note, preserved here),
                            or (defensively, though this slice's sync
                            checkers never actually emit "fail") any sync
                            checker failed outright.
      - offline           : at least one sync checker could not reach its
                            remote (`any_remote_offline` -- see
                            core/ecosystem/component_status.py).
      - syncing           : the advisory copilot lock is held by another
                            process RIGHT NOW (`lock_held_by_other` -- a
                            real, non-blocking probe; see
                            `_probe_lock_held()`). Never fabricated when no
                            such live signal exists.
      - update-available  : at least one sync checker found the local tip
                            behind its remote (and nothing worse above).
      - healthy           : none of the above.
    """
    component_checkers = component_checkers or []
    auth_entries = auth_entries or []

    setup_incomplete = any(
        c.id in ("machine-config", "project-config", "project-repo")
        and c.severity != "pass"
        for c in config_checkers
    )
    if setup_incomplete:
        return "setup-needed"

    if auth_entries:
        return "signed-out"

    if any(c.severity in ("fail", "warn") for c in config_checkers):
        return "needs-attention"
    if any(c.severity == "fail" for c in component_checkers):
        return "needs-attention"

    if any_remote_offline:
        return "offline"

    if lock_held_by_other:
        return "syncing"

    if any(c.severity == "warn" for c in component_checkers):
        return "update-available"

    return "healthy"


def _build_component_checkers(
    *,
    _layers: Optional[list[dict[str, Any]]],
    _manifest_path: Any,
    _lockfile: Optional[dict[str, Any]],
    _lockfile_path: Any,
    _mirror_root: Any,
    _latest_sha_fn: Any,
) -> tuple[list[Checker], bool]:
    """
    Load the layer manifest + lockfile (mirrors `commands/resolve.py`'s own
    `build_resolve_report()` loading pattern) and fold them through
    `component_status.compute_component_checkers()`.

    A missing or invalid manifest is a fail-closed checker, never an empty
    successful result.  Control Tower treats this report as its single
    authoritative health seam; allowing an absent manifest to collapse to
    zero component checkers would let an unconfigured ecosystem report
    ``healthy`` merely because there was nothing to inspect.
    """
    if _layers is not None:
        layers = _layers
    else:
        manifest_path = (
            _manifest_path if _manifest_path is not _UNSET else resolve_key("layers.manifest")
        )
        if not manifest_path:
            return [
                Checker(
                    id="ecosystem-layer-manifest",
                    severity="fail",
                    detail="No ecosystem layer manifest is configured.",
                    repair="cc config set layers.manifest <path-to-copilot.layers.yml>",
                )
            ], False
        try:
            layers = validate_layers(load_layers(manifest_path))
        except ManifestError as exc:
            return [
                Checker(
                    id="ecosystem-layer-manifest",
                    severity="fail",
                    detail=f"Ecosystem layer manifest is unreadable or invalid: {exc}",
                    repair="repair the configured copilot.layers.yml",
                    path=str(manifest_path),
                )
            ], False

    if _lockfile is not None:
        lock = _lockfile
    else:
        lockfile_path = (
            _lockfile_path if _lockfile_path is not _UNSET else default_lockfile_path()
        )
        lock = read_lockfile(lockfile_path)

    latest_sha_fn = _latest_sha_fn if _latest_sha_fn is not _UNSET else mirror.latest_lock_sha
    mirror_root = (
        _mirror_root if _mirror_root is not _UNSET else resolve_key("paths.mirrors_root")
    )

    return compute_component_checkers(
        layers, lockfile=lock, latest_sha_fn=latest_sha_fn, mirror_root=mirror_root
    )


def _parse_timestamp(value: str) -> Optional[datetime]:
    try:
        normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _build_auth_entries(
    *,
    _auth_root: Any,
    _keychain_get_secret: Any,
) -> list[dict[str, Any]]:
    """
    Build `doctor --json`'s `auth[]` from `authstore.read_identity()` +
    a Keychain presence check.

    Fail-closed credential shape (doctor.schema.json: `state` in
    `expired|revoked`, "only failing/needs-attention entries are expected
    in this array"):
      - never signed in (no identity pointer, or one with no `login`) ->
        `[]`. Not a failure state -- there is nothing to report.
      - identity carries an `expires_at` that has already passed ->
        `expired` (transient, re-auth offered).
      - identity present but the Keychain has no matching secret for it
        (missing-token-with-identity) -> `revoked` (permanent, fail-closed
        -- the pointer claims signed-in but the credential backing it is
        gone).
      - Keychain unavailable on this platform/host (non-Darwin, or the
        lookup itself fails) -> `[]`. This is an honest "cannot determine",
        never coerced into a fabricated revoked/expired verdict.
    """
    auth_root = None if _auth_root is _UNSET else _auth_root
    identity = read_identity(_root=auth_root)
    login = identity.get("login")
    if not login:
        return []

    scope = identity.get("scopes") or identity.get("scope") or "unknown"

    expires_at = identity.get("expires_at")
    if expires_at:
        expiry = _parse_timestamp(expires_at)
        if expiry is not None and expiry <= datetime.now(timezone.utc):
            return [
                {"identity": login, "scope": scope, "state": "expired", "expires_at": expires_at}
            ]

    if _keychain_get_secret is not _UNSET:
        get_secret = _keychain_get_secret
    elif sys.platform == "darwin":
        get_secret = keychain.get_secret
    else:
        # Can't check a real Keychain on a non-Darwin host -- an honest
        # "cannot determine", never a fabricated revoked verdict from a
        # platform limitation.
        return []

    service = resolve_key("auth.keychain_service") or _DEFAULT_KEYCHAIN_SERVICE
    try:
        token = get_secret(login, service=service)
    except keychain.KeychainUnavailable:
        return []

    if token is None:
        return [{"identity": login, "scope": scope, "state": "revoked"}]

    return []


def _probe_lock_held(_lock_probe_path: Any) -> bool:
    """
    Non-destructive, non-blocking, NEVER-CREATING probe: is the advisory
    copilot lock (core/locking.py) held by ANOTHER process right now?

    `cc doctor` is read-only by design (core/locking.py's own module
    docstring: "cc doctor ... intentionally does NOT take this lock") --
    this probe honors that: if the lock file doesn't exist yet (the common
    case -- a machine that has never run a mutating verb), there is
    nothing to probe and this returns `False` without touching the
    filesystem at all. Only when the file already exists does this open it
    (never `O_CREAT`) and try a non-blocking exclusive flock; contention
    means someone else holds it (`True`); success means this process
    momentarily held and instantly released it itself, proving no one else
    has it (`False`). Never blocks, never leaves the lock held, never
    creates a file that wasn't already there.
    """
    target = _lock_probe_path if _lock_probe_path is not _UNSET else lock_path()
    if not target.exists():
        return False

    try:
        fd = os.open(target, os.O_RDWR)
    except OSError:
        return False

    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def build_doctor_report(
    *,
    _machine_cfg_path: Path | None = None,
    _project_cfg_path: Any = ...,
    _resolved_cfg: dict | None = None,
    _layers: Optional[list[dict[str, Any]]] = None,
    _manifest_path: Any = _UNSET,
    _lockfile: Optional[dict[str, Any]] = None,
    _lockfile_path: Any = _UNSET,
    _mirror_root: Any = _UNSET,
    _latest_sha_fn: Any = _UNSET,
    _auth_root: Any = _UNSET,
    _keychain_get_secret: Any = _UNSET,
    _lock_probe_path: Any = _UNSET,
) -> dict:
    """
    Build the WS-A `doctor --json` contract object.

    Schema: copilot-control-tower/docs/01-architecture/schemas/doctor.schema.json
    (vendored copy: tools/cc/tests/fixtures/schemas/doctor.schema.json).

    Every new I/O root this slice adds is injectable via the `_..._path`/
    `_..._root`/`_...fn` keyword arguments above (mirrors `update.py`'s /
    `resolve.py`'s own convention) -- production defaults only ever resolve
    through `resolve_key()`'s normal config cascade or another module's own
    already-established default (never a bare `Path.home()` call added by
    this module itself).
    """
    checkers = _run_checks(
        machine_cfg_path=_machine_cfg_path,
        project_cfg_path=_project_cfg_path,
        resolved_cfg=_resolved_cfg,
    )

    component_checkers, any_remote_offline = _build_component_checkers(
        _layers=_layers,
        _manifest_path=_manifest_path,
        _lockfile=_lockfile,
        _lockfile_path=_lockfile_path,
        _mirror_root=_mirror_root,
        _latest_sha_fn=_latest_sha_fn,
    )

    auth_entries = _build_auth_entries(
        _auth_root=_auth_root,
        _keychain_get_secret=_keychain_get_secret,
    )

    lock_held_by_other = _probe_lock_held(_lock_probe_path)

    status = _compute_status(
        checkers,
        component_checkers=component_checkers,
        any_remote_offline=any_remote_offline,
        auth_entries=auth_entries,
        lock_held_by_other=lock_held_by_other,
    )

    all_checkers = checkers + component_checkers
    total = len(all_checkers)
    passed = sum(1 for c in all_checkers if c.severity == "pass")
    score = 100 if total == 0 else round(100 * passed / total)

    return {
        "schema_version": SCHEMA_VERSION,
        "host": socket.gethostname(),
        "score": score,
        "status": status,
        "offline": any_remote_offline,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "checkers": [c.to_contract_dict() for c in all_checkers],
        "auth": auth_entries,
    }


def compute_exit_code(report: dict) -> int:
    """
    Map a build_doctor_report() payload to the WS-A contract's process exit
    code.

    Remap from the legacy `cc config doctor` exit codes (0 clean / 1 warnings
    / 3 errors) to the contract's 0/1/2:
      0 = all checkers pass
      1 = any checker has severity "fail"
      2 = reserved for environment/unexpected errors (raised by the CLI
          handler when build_doctor_report() itself throws — never returned
          from this function, since a returned report is by definition one
          the CLI could produce)

    Note: today's checkers only ever emit "pass"/"warn" (no checker currently
    computes a "fail"; that severity is reserved for future/engine-backed
    checks), so this will typically return 0 even when `status` is
    `setup-needed` or `needs-attention`. This is intentional per the WS-A
    slice's exit-code decision (env/unexpected errors, not "needs attention",
    are what should exit non-zero at the process level) but is worth
    reconfirming with the CLI owner once real `fail`-severity checkers exist.
    """
    if any(c.get("severity") == "fail" for c in report.get("checkers", [])):
        return 1
    return 0


def render_doctor_report_rich(report: dict, *, console: Any = None) -> None:
    """Human-readable (Rich) rendering of a build_doctor_report() payload."""
    from rich.console import Console

    con = console or Console()
    status = report.get("status", "unknown")
    score = report.get("score")
    status_color = {
        "healthy": "green",
        "needs-attention": "yellow",
        "setup-needed": "yellow",
        "signed-out": "yellow",
        "it-config-incomplete": "red",
    }.get(status, "red")

    con.print(
        f"[bold {status_color}]status: {status}[/bold {status_color}]  (score {score}/100)"
    )

    severity_color = {"pass": "green", "warn": "yellow", "fail": "red"}
    for c in report.get("checkers", []):
        sev = c.get("severity", "fail")
        color = severity_color.get(sev, "red")
        detail = c.get("detail") or c.get("id", "")
        product_tag = f" [dim]({c['product']})[/dim]" if c.get("product") else ""
        con.print(f"  [{color}]{sev:<4}[/{color}] {c.get('id')}{product_tag}: {detail}")

    for a in report.get("auth", []):
        con.print(
            f"  [red]auth[/red] {a.get('identity')} ({a.get('scope')}): {a.get('state')}"
        )
