"""cc config doctor — standalone health check for config + environment.

Separated from config.py so it can be tested in isolation.
The `config doctor` command in config.py delegates to run_doctor().
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple, Any

from cc.core.config import get_resolved_config
from cc.core.config_paths import (
    machine_config_path,
    project_config_path,
    project_secrets_path,
    repo_root,
)


class DoctorResult(NamedTuple):
    warnings: list[str]
    errors: list[str]


# Sentinel object used by tests to simulate "not inside a git repo".
# Pass _project_cfg_path=NOT_IN_REPO to run_doctor().
NOT_IN_REPO: Any = object()


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
    Exit semantics:
      0 = clean
      1 = warnings only
      3 = errors present
    """
    warnings: list[str] = []
    errors: list[str] = []

    machine_cfg = _machine_cfg_path or machine_config_path()

    # Resolve project config path
    if _project_cfg_path is ...:
        project_cfg: Path | None = project_config_path()
    elif _project_cfg_path is NOT_IN_REPO:
        project_cfg = None
    else:
        project_cfg = _project_cfg_path

    # --- Machine config ---
    if not machine_cfg.exists():
        warnings.append(
            f"Machine config missing: {machine_cfg}  (run: cc config init --machine)"
        )

    # --- Project config ---
    if project_cfg is None:
        warnings.append("Not inside a git repository — project config checks skipped.")
    elif not project_cfg.exists():
        warnings.append(
            f"Project config missing: {project_cfg}  (run: cc config init --project)"
        )

    # --- Declared paths ---
    cfg = _resolved_cfg if _resolved_cfg is not None else get_resolved_config()
    path_keys = sorted(k for k in cfg if k.startswith("paths."))
    for k in path_keys:
        v = cfg.get(k)
        if v is None:
            continue
        # paths.knowledge_repo (and any future list-valued path key) may
        # resolve to an ordered list of paths rather than a single scalar.
        candidates = v if isinstance(v, list) else [v]
        for item in candidates:
            if not item:
                continue
            p = Path(str(item))
            if not p.exists():
                warnings.append(f"Path not found: {k} = {item}")

    # --- Machine config dir gitignore ---
    gitignore_path = machine_cfg.parent / ".gitignore"
    if machine_cfg.exists() and not gitignore_path.exists():
        warnings.append(
            f"No .gitignore in {machine_cfg.parent} — machine config may be committed accidentally."
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
                        warnings.append(
                            "Project secrets.env is not in .gitignore — risk of committing secrets."
                        )

    return DoctorResult(warnings=warnings, errors=errors)
