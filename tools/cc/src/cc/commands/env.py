"""cc env — emit shell-eval-able exports for the effective config.

Usage:
    eval "$(cc env)"          # hydrate CC_* exports into current shell
    cc env --json             # JSON for programmatic use
    cc env --include-secrets  # also emit values from secrets.env
"""

from __future__ import annotations

import re
from pathlib import Path

from rich.console import Console

from cc.core.config import (
    get_resolved_config,
    load_machine_secrets,
    load_project_secrets,
    resolve_knowledge_repos,
)

err_console = Console(stderr=True)

# The machine-wide personal-tier repo naming convention `cc onboard` itself
# creates/clones under (see commands/onboard.py's `_personal_seed()` /
# `build_personal_onboard_report()`: every personal package is a
# `<product>-copilot-private` repo, cloned via the `github-personal` SSH
# identity -- four-tier-topology.md's own "personal identity" convention,
# e.g. `claude-copilot-private`). Matched against every path SEGMENT (not
# just the leaf) so `.../claude-copilot-private/knowledge` still matches on
# its `claude-copilot-private` ancestor segment.
_PERSONAL_REPO_SEGMENT = re.compile(r"^.+-copilot-private$")


def _is_personal_knowledge_path(path: str) -> bool:
    return any(_PERSONAL_REPO_SEGMENT.match(part) for part in Path(path).parts)


def _key_to_env_name(key: str) -> str:
    """Convert dotted config key to CC_UPPER_UNDERSCORE env var name."""
    return "CC_" + key.replace(".", "_").upper()


def run_env(
    *,
    include_secrets: bool = False,
    output_json: bool = False,
) -> dict[str, str]:
    """
    Build the exports dict from the effective config.

    Separated from the CLI handler so it can be unit-tested directly.
    Secrets are excluded unless include_secrets=True.
    """
    cfg = get_resolved_config()
    exports: dict[str, str] = {}

    for key, value in cfg.items():
        if value is None:
            continue
        env_name = _key_to_env_name(key)
        if isinstance(value, list):
            # e.g. paths.knowledge_repo may resolve to an ordered list of
            # repo paths; emit as a comma-joined string (order preserved).
            if not value:
                continue
            exports[env_name] = ",".join(str(v) for v in value)
        else:
            exports[env_name] = str(value)

    if include_secrets:
        machine_secrets = load_machine_secrets()
        project_secrets = load_project_secrets()
        for k, v in {**machine_secrets, **project_secrets}.items():
            exports[k] = v

    # Emit short-form aliases for the knowledge repo path variables.
    # Agents reference CC_KNOWLEDGE_REPO and CC_SHARED_DOCS (not the nested
    # CC_PATHS_* form), so produce both names when the source key is set.
    _PATH_ALIASES: dict[str, str] = {
        "CC_KNOWLEDGE_REPO": "CC_PATHS_KNOWLEDGE_REPO",
        "CC_SHARED_DOCS": "CC_PATHS_SHARED_DOCS",
    }
    for alias, source in _PATH_ALIASES.items():
        if source in exports and alias not in exports:
            exports[alias] = exports[source]

    # WP-372 P3.1: paths.knowledge_repo is list-valued (a personal knowledge
    # layer rides as one more list entry), but the pre-P3.1 alias below
    # truncated to the FIRST element -- making every entry past index 0
    # (in practice: the personal one, appended last via `cc config add`)
    # structurally invisible to every agent instruction that only ever
    # reads CC_KNOWLEDGE_REPO. Two additions, both additive (never remove
    # CC_KNOWLEDGE_REPO's existing first-element back-compat behavior
    # below):
    #   - CC_KNOWLEDGE_REPOS: the full ordered comma list (same content as
    #     CC_PATHS_KNOWLEDGE_REPO, under the short-form name agents are
    #     actually instructed to read -- see knowledge-copilot's
    #     consumption contract).
    #   - CC_PERSONAL_KNOWLEDGE_REPO: whichever entry (if any) resides
    #     under a `<product>-copilot-private` repo -- the personal-tier
    #     naming convention `cc onboard` itself creates
    #     (`_is_personal_knowledge_path()` above). Never emitted if no
    #     entry matches -- an honest "no personal knowledge repo
    #     configured", never a fabricated guess.
    knowledge_repos = resolve_knowledge_repos(cfg.get("paths.knowledge_repo"))
    if knowledge_repos:
        exports["CC_KNOWLEDGE_REPOS"] = ",".join(knowledge_repos)
        personal_repo = next(
            (repo for repo in knowledge_repos if _is_personal_knowledge_path(repo)), None
        )
        if personal_repo is not None:
            exports["CC_PERSONAL_KNOWLEDGE_REPO"] = personal_repo

    # CC_KNOWLEDGE_REPO is a single-value back-compat alias: when
    # paths.knowledge_repo resolves to an ordered list (comma-joined above
    # into CC_PATHS_KNOWLEDGE_REPO), the alias carries only the FIRST
    # element so agents reading one value keep working unchanged.
    if "CC_KNOWLEDGE_REPO" in exports:
        exports["CC_KNOWLEDGE_REPO"] = exports["CC_KNOWLEDGE_REPO"].split(",")[0].strip()

    return exports
