"""cc config doctor — standalone health check for config + environment.

Separated from config.py so it can be tested in isolation.
The `config doctor` command in config.py delegates to run_doctor().

WS-A slice 1 (doctor-slice): this module also builds the versioned
`cc doctor --json` contract consumed by Control Tower. See:
  - copilot-control-tower/docs/01-architecture/cli-contract.md
  - copilot-control-tower/docs/01-architecture/schemas/doctor.schema.json
  - tools/cc/tests/fixtures/schemas/ (vendored copies used by the contract test)

Naming note: the upstream design names the user-facing verb `copilot doctor`
(the `copilot` binary that wraps `cc`). The ecosystem logic itself lives here
in `cc`; `copilot doctor` can become a thin alias for `cc doctor` once that
wrapper exists. Until then, `cc doctor` IS the doctor verb.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple, Optional

from cc.core.config import get_resolved_config
from cc.core.config_paths import (
    machine_config_path,
    project_config_path,
    repo_root,
)

SCHEMA_VERSION = "1.0"

# Best-effort `paths.*` config-key -> product attribution (doctor.schema.json's
# optional per-checker `product` field). Only keys unambiguously owned by a
# single one of the four products (knowledge/cli/claude/codex) are listed --
# everything else (paths.memory, paths.shared_docs, paths.mirrors_root, ...)
# is deliberately left unmapped rather than guessed; those checkers simply
# emit no `product` field.
PRODUCT_BY_PATH_KEY: dict[str, str] = {
    "paths.knowledge_repo": "knowledge",
}


class DoctorResult(NamedTuple):
    warnings: list[str]
    errors: list[str]


# Sentinel object used by tests to simulate "not inside a git repo".
# Pass _project_cfg_path=NOT_IN_REPO to run_doctor().
NOT_IN_REPO: Any = object()


@dataclass
class Checker:
    """A single, discretely-identified health check result.

    This is the internal building block shared by both the legacy
    `run_doctor()` (warnings/errors) shape and the new `build_doctor_report()`
    (WS-A `doctor --json` contract) shape, so the two never drift apart.
    """

    id: str
    severity: str  # "pass" | "warn" | "fail"
    detail: str = ""
    path: Optional[str] = None
    product: Optional[str] = None  # best-effort; absent when not attributable

    def to_contract_dict(self) -> dict:
        d: dict = {"id": self.id, "severity": self.severity, "destructive": False}
        if self.detail:
            d["detail"] = self.detail
        if self.path:
            d["path"] = self.path
        if self.product:
            d["product"] = self.product
        return d


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


def _compute_status(checkers: list[Checker]) -> str:
    """
    Compute the top-level `status` field HONESTLY from available signals.

    WS-A slice 1 ($comment): the full ~10-state machine (syncing,
    update-available, waiting-for-network, updating-app, offline-with-cache,
    it-config-incomplete, signed-out, ...) requires the sync/resolution
    engine and an auth store, neither of which exist in `cc` yet. This
    function ONLY emits states it can truly determine today:

      - setup-needed     : machine or project config is missing/unreachable
      - needs-attention   : any checker failed, or (conservatively) any
                            checker warned
      - healthy           : zero fail/warn checkers

    It deliberately never fabricates `syncing`, `update-available`,
    `signed-out`, `it-config-incomplete`, `offline`, `waiting-for-network`,
    or `updating-app` — those require the engine / auth store this slice
    does not build. The full state machine lands with the engine (see
    cli-contract.md "Freeze status & source of truth").

    OPEN DECISION (needs owner confirmation): treating any `warn` checker as
    disqualifying for `healthy` is a conservative default beyond what the
    schema's `allOf` invariant strictly requires (it only forbids `healthy`
    with a `fail` checker or an expired/revoked auth entry). Confirm whether
    warn-only findings (e.g. a single stray path-not-found) should still be
    able to report `healthy`.
    """
    setup_incomplete = any(
        c.id in ("machine-config", "project-config", "project-repo")
        and c.severity != "pass"
        for c in checkers
    )
    if setup_incomplete:
        return "setup-needed"
    if any(c.severity == "fail" for c in checkers):
        return "needs-attention"
    if any(c.severity == "warn" for c in checkers):
        return "needs-attention"
    return "healthy"


def build_doctor_report(
    *,
    _machine_cfg_path: Path | None = None,
    _project_cfg_path: Any = ...,
    _resolved_cfg: dict | None = None,
) -> dict:
    """
    Build the WS-A `doctor --json` contract object.

    Schema: copilot-control-tower/docs/01-architecture/schemas/doctor.schema.json
    (vendored copy: tools/cc/tests/fixtures/schemas/doctor.schema.json).

    `auth`: cc has no auth store of its own (unlike cli-copilot's
    `auth_store.py`, which decodes a JWT `exp` claim for expiry). There is
    nothing to report here yet, so this always emits `[]`. Revisit once/if
    `cc` grows credentials of its own worth tracking.
    """
    checkers = _run_checks(
        machine_cfg_path=_machine_cfg_path,
        project_cfg_path=_project_cfg_path,
        resolved_cfg=_resolved_cfg,
    )

    status = _compute_status(checkers)

    total = len(checkers)
    passed = sum(1 for c in checkers if c.severity == "pass")
    score = 100 if total == 0 else round(100 * passed / total)

    return {
        "schema_version": SCHEMA_VERSION,
        "host": socket.gethostname(),
        "score": score,
        "status": status,
        "offline": False,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "checkers": [c.to_contract_dict() for c in checkers],
        "auth": [],
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
