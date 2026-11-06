"""Layout constants for the release pointer (contract: schema 1).

Every path is derived from a copilot home directory (`~/.copilot`) that callers
may inject; nothing here touches the real home unless the caller passes it.
Downstream streams (links, hooks, marketplace, CLI installer, control tower)
import these names instead of spelling literals.
"""

from __future__ import annotations

from pathlib import Path

SCHEMA_VERSION = 1

COPILOT_DIRNAME = ".copilot"
CURRENT_NAME = "current"
RELEASES_DIRNAME = "releases"
HISTORY_NAME = "release-history.jsonl"
HISTORY_LOCK_NAME = "release-history.lock"
PRUNE_RECEIPTS_DIRNAME = "prune-receipts"
LINKS_RECEIPT_NAME = "links-receipt.json"
BIN_RELATIVE = Path(".local") / "bin"

# Files and directories generated inside a release directory.
MANIFEST_NAME = "release.json"
MARKETPLACE_DIRNAME = "codex-marketplace"
LINK_PLAN_NAME = "links.json"
CODEX_AGENTS_BLOCK_NAME = "codex-AGENTS.block.md"

# Framework components: release-relative path equals the component name.
COMPONENT_CLAUDE = "claude-copilot"
COMPONENT_CODEX = "codex-copilot"
COMPONENT_CLI = "cli-copilot"
COMPONENT_PRODUCT_CREATION = "product-creation-copilot"
COMPONENT_CONTROL_TOWER = "control-tower"  # version record only, no tree
FRAMEWORK_COMPONENTS = (
    COMPONENT_CLAUDE,
    COMPONENT_CODEX,
    COMPONENT_CLI,
    COMPONENT_PRODUCT_CREATION,
    COMPONENT_CONTROL_TOWER,
)

# Tier overlays: release-relative path is "<product>/<tier>".
TIER_FOUNDATION = "foundation"
TIER_ORGANIZATION = "organization"
TIER_DEPARTMENT_ACCOUNTING = "department-accounting"
TIER_PERSONAL = "personal"
KNOWLEDGE_TIERS = (
    TIER_FOUNDATION,
    TIER_ORGANIZATION,
    TIER_DEPARTMENT_ACCOUNTING,
    TIER_PERSONAL,
)
OVERLAY_TIERS = (TIER_ORGANIZATION, TIER_DEPARTMENT_ACCOUNTING, TIER_PERSONAL)
OVERLAY_PRODUCTS = ("claude", "codex", "cli")
KNOWLEDGE_PRODUCT = "knowledge"

# Entry kinds recorded in release.json.
KIND_SIGNED = "signed-tag"  # immutable snapshot of a verified signed tag
KIND_LIVE = "live-link"  # symlink to a live checkout (personal tier)
KIND_RECORD = "record"  # version record only (control-tower)
KINDS = (KIND_SIGNED, KIND_LIVE, KIND_RECORD)

# Stable shims in ~/.local/bin that resolve through the pointer.
SHIM_NAMES = ("cc", "tc", "tc-limits")
CC_VENV_PYTHON_RELATIVE = Path(COMPONENT_CLAUDE) / "tools" / "cc" / ".venv" / "bin" / "python"
TC_LIMITS_RELATIVE = Path(COMPONENT_CLAUDE) / "tools" / "tc" / "tc-limits"

DEFAULT_KEEP = 5


def overlay_component_names() -> tuple[str, ...]:
    """Every tier-overlay component name in canonical order."""
    names = [f"{KNOWLEDGE_PRODUCT}/{tier}" for tier in KNOWLEDGE_TIERS]
    for product in OVERLAY_PRODUCTS:
        names.extend(f"{product}/{tier}" for tier in OVERLAY_TIERS)
    return tuple(names)


def all_component_names() -> tuple[str, ...]:
    """The complete set a valid release.json must list (ADR-001 decision 1)."""
    return FRAMEWORK_COMPONENTS + overlay_component_names()


def copilot_home(home: Path | str | None = None) -> Path:
    base = Path(home) if home is not None else Path.home()
    return base / COPILOT_DIRNAME


def current_path(home: Path | str | None = None) -> Path:
    return copilot_home(home) / CURRENT_NAME


def releases_dir(home: Path | str | None = None) -> Path:
    return copilot_home(home) / RELEASES_DIRNAME


def release_dir(release_id: str, home: Path | str | None = None) -> Path:
    return releases_dir(home) / release_id


def history_path(home: Path | str | None = None) -> Path:
    return copilot_home(home) / HISTORY_NAME


def links_receipt_path(home: Path | str | None = None) -> Path:
    return copilot_home(home) / LINKS_RECEIPT_NAME


def bin_dir(home: Path | str | None = None) -> Path:
    return (Path(home) if home is not None else Path.home()) / BIN_RELATIVE
