"""The Codex part of `cc release publish`: configure, refresh, verify, doctor checks."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from cc.core.release.engine import layout
from cc.core.release.engine.doctor import Check

from . import config, marketplace

Runner = Callable[[Sequence[str], dict[str, str]], "subprocess.CompletedProcess[str]"]


class ReleaseStepError(RuntimeError):
    """The Codex step failed; the release is a failed release (offer rollback)."""


def default_codex_home(home: Path | str | None = None) -> Path:
    """An isolated run (explicit home or $COPILOT_HOME) never inherits the ambient $CODEX_HOME."""
    from ..engine import layout

    if home is not None or os.environ.get("COPILOT_HOME"):
        return layout.home_root(home) / ".codex"
    return Path(os.environ.get("CODEX_HOME") or layout.home_root() / ".codex")


def default_runner(argv: Sequence[str], env: dict[str, str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(list(argv), env=env, capture_output=True, text=True, timeout=300)


def marketplace_source(home: Path | str | None = None) -> str:
    return str(layout.current_path(home) / layout.MARKETPLACE_DIRNAME)


def cache_dir(codex_home: Path | str, plugin: str, version: str) -> Path:
    return Path(codex_home) / "plugins" / "cache" / marketplace.MARKETPLACE_NAME / plugin / version


def verify_cache(codex_home: Path | str, receipt: dict) -> list[str]:
    """Problems between the Codex cache and the release receipt (empty when equal)."""
    problems = []
    for plugin in receipt["plugins"]:
        path = cache_dir(codex_home, plugin["name"], plugin["version"])
        if not path.is_dir():
            problems.append(f"{plugin['name']}: cache version {plugin['version']} missing")
        elif marketplace.tree_digest(path) != plugin["digest"]:
            problems.append(f"{plugin['name']}: cache {plugin['version']} content differs from release")
    return problems


@dataclass(frozen=True)
class StepResult:
    config: config.ConfigResult
    refreshed_with: str
    plugins: list[str]


def run(home: Path | str | None = None, codex_home: Path | str | None = None, *,
        codex_bin: str = "codex", runner: Runner = default_runner,
        prune_trust: bool = False) -> StepResult:
    """Register the marketplace once, refresh the Codex cache, verify it matches the release."""
    codex_home = Path(codex_home) if codex_home else default_codex_home(home)
    root = layout.current_path(home)
    try:
        receipt = marketplace.load_receipt(root.resolve())
    except marketplace.MarketplaceError as exc:
        raise ReleaseStepError(str(exc)) from exc
    names = [p["name"] for p in receipt["plugins"]]
    try:
        result = config.apply(codex_home, home, source=marketplace_source(home),
                              plugins=names, prune_trust=prune_trust)
    except config.ConfigError as exc:
        raise ReleaseStepError(str(exc)) from exc
    env = {**os.environ, "CODEX_HOME": str(codex_home)}
    name = marketplace.MARKETPLACE_NAME
    upgrade = runner([codex_bin, "plugin", "marketplace", "upgrade", name], env)
    used = "marketplace upgrade"
    if upgrade.returncode != 0:  # local-source marketplaces are not upgradable; re-add refreshes
        used = "plugin add"
        for plugin in names:
            added = runner([codex_bin, "plugin", "add", config.plugin_key(plugin)], env)
            if added.returncode != 0:
                raise ReleaseStepError(
                    f"codex plugin add {config.plugin_key(plugin)} failed: "
                    f"{(added.stderr or added.stdout).strip()}; roll back with config.rollback()"
                )
    problems = verify_cache(codex_home, receipt)
    if problems:
        raise ReleaseStepError("Codex cache does not match the release: " + "; ".join(problems))
    return StepResult(result, used, names)


def doctor_checks(codex_home: Path | str | None = None,
                  home: Path | str | None = None) -> Callable[[Path], list[Check]]:
    """An `engine.doctor.run(extra=[...])` hook: cache equals release, one plugin source."""
    def check(root: Path) -> list[Check]:
        codex = Path(codex_home) if codex_home else default_codex_home(home)
        try:
            receipt = marketplace.load_receipt(root)
        except marketplace.MarketplaceError as exc:
            return [Check("codex-marketplace", False, str(exc))]
        out = [Check("codex-marketplace", True, f"{len(receipt['plugins'])} plugins")]
        problems = verify_cache(codex, receipt)
        out.append(Check("codex-cache", not problems, "; ".join(problems) or "cache equals release"))
        try:
            cfg = config.read(codex)
        except Exception as exc:  # unreadable config is a failed check, not a crash
            return out + [Check("codex-single-source", False, f"config unreadable: {exc}")]
        names = {p["name"] for p in receipt["plugins"]}
        bad = [f"{k} enabled" for k, v in cfg.get("plugins", {}).items()
               if k.partition("@")[0] in names and k.rpartition("@")[2] != marketplace.MARKETPLACE_NAME
               and v.get("enabled")]
        bad += [f"marketplace {m} registered" for m in config.RETIRED_MARKETPLACES
                if m in cfg.get("marketplaces", {})]
        registered = cfg.get("marketplaces", {}).get(marketplace.MARKETPLACE_NAME, {})
        if registered.get("source") != marketplace_source(home):
            bad.append(f"{marketplace.MARKETPLACE_NAME} source is {registered.get('source')!r}")
        missing = [n for n in names if not cfg.get("plugins", {}).get(
            config.plugin_key(n), {}).get("enabled")]
        bad += [f"{n} not enabled" for n in missing]
        out.append(Check("codex-single-source", not bad, "; ".join(bad) or marketplace.MARKETPLACE_NAME))
        return out
    return check
