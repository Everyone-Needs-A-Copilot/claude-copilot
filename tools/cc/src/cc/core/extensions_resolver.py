"""Extension resolver: `knowledge-manifest.json` discovery, agent-id
matching, personal-over-org precedence, `override` vs `extension` typing,
`requiredSkills` verification, and `fallbackBehavior` enforcement.

This is the code half of the extension system. `docs/40-extensions/
00-extension-spec.md` and (pre-fix) `.claude/commands/protocol.md` described
a nine-step algorithm for a MODEL to hand-execute against two hardcoded
manifest paths -- one of which (`~/.claude/knowledge/knowledge-manifest.json`)
is not among the machine's actual configured knowledge sources
(`CC_KNOWLEDGE_REPOS`, see `core/config.py`'s `resolve_knowledge_repos()`).
That produced a *confident false provenance claim*: a model following the
documented algorithm perfectly resolves nothing real, then still announces
an extension source in its protocol banner.

Architecture
------------
- `resolve_extension(agent, ...)` -- deterministic resolution. Walks the
  REAL configured knowledge repos (`resolve_knowledge_repos()`, already
  personal-over-org ordered -- see WP-372 P3.1's `CC_PERSONAL_KNOWLEDGE_REPO`
  convention), parses each repo's manifest, and returns the first match for
  `agent`. Missing/malformed manifests are skipped with a logged warning --
  never raises, never blocks an agent invocation.
- `compose_agent_content(...)` -- the one piece of composition that IS safe
  to do in code. `override` is a pure substitution (use the extension file
  verbatim instead of the base agent) -- there is no ambiguity to resolve,
  so it needs no model judgment and is implemented fully here. `extension`
  is NOT given a pretend section-level merge: the framework's own docs
  called that "aspirational" twice, because matching prose sections and
  deciding which content "wins" is a semantic judgment call, not a
  mechanical one. Instead `extension` gets a defined, honest, 100%
  deterministic behavior -- append the extension content after the base
  agent content, under an explicit heading that says outright it was
  appended (not merged) and that later content wins on conflict, per the
  same "content outranks form" precedence convention every agent already
  carries in its own Runtime Precedence block. That is the honest limit:
  code guarantees BOTH bodies of text reach the model every time; it does
  not pretend to resolve conflicts between them.
- `type: "skills"` entries (schema-legal, no real manifest uses it today)
  leave the base agent content untouched -- they only assert the declared
  skills should be available, same as an `extension`/`override` entry's
  `requiredSkills` list.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)

_VALID_TYPES = frozenset({"override", "extension", "skills"})
_VALID_FALLBACKS = frozenset({"use_base", "use_base_with_warning", "fail"})
_DEFAULT_FALLBACK = "use_base_with_warning"

# Actions a caller (CLI, /protocol) must branch on. Exactly one of these is
# ever set on a resolved ExtensionResolution.
ACTION_NO_EXTENSION = "no_extension"        # no repo declares an entry for this agent
ACTION_APPLY = "apply"                       # matched, requiredSkills satisfied -- use it
ACTION_FALLBACK_USE_BASE = "fallback_use_base"              # matched, skills missing, fallbackBehavior=use_base
ACTION_FALLBACK_WARNING = "fallback_use_base_with_warning"  # matched, skills missing, fallbackBehavior=use_base_with_warning
ACTION_FALLBACK_FAIL = "fallback_fail"       # matched, skills missing, fallbackBehavior=fail


@dataclass
class ExtensionResolution:
    """Result of resolving one agent's extension across the configured
    knowledge repos. `to_dict()` is the `cc extensions resolve --json`
    wire shape."""

    agent: str
    action: str = ACTION_NO_EXTENSION
    matched: bool = False
    type: Optional[str] = None
    file: Optional[str] = None  # absolute path to the extension file
    source_repo: Optional[str] = None
    description: Optional[str] = None
    required_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    fallback_behavior: Optional[str] = None
    warning: Optional[str] = None
    contributions: tuple[Any, ...] = ()
    composed_content_sha256: Optional[str] = None

    @property
    def skills_ok(self) -> bool:
        return not self.missing_skills

    @property
    def fallback_applied(self) -> bool:
        return self.action in (
            ACTION_FALLBACK_USE_BASE,
            ACTION_FALLBACK_WARNING,
            ACTION_FALLBACK_FAIL,
        )

    @property
    def use_extension(self) -> bool:
        """Whether the resolved extension content should actually be
        applied (as opposed to falling back to the base agent)."""
        return self.action == ACTION_APPLY

    def to_dict(self) -> dict:
        return {
            "agent": self.agent,
            "action": self.action,
            "matched": self.matched,
            "type": self.type,
            "file": self.file,
            "source_repo": self.source_repo,
            "description": self.description,
            "requiredSkills": self.required_skills,
            "missingSkills": self.missing_skills,
            "skillsOk": self.skills_ok,
            "fallbackBehavior": self.fallback_behavior,
            "fallbackApplied": self.fallback_applied,
            "useExtension": self.use_extension,
            "warning": self.warning,
            "contributions": [item.to_dict(include_content=False) for item in self.contributions],
            "composedContentSha256": self.composed_content_sha256,
        }


@dataclass(frozen=True)
class AuthenticatedComposition:
    content: str
    receipts: tuple[Any, ...]
    content_sha256: str


def _load_manifest(repo: str) -> Optional[dict]:
    """Parse `<repo>/knowledge-manifest.json`. Returns None (with a logged
    warning) for anything short of a well-formed JSON object -- absent
    file, unreadable file, malformed JSON, or a non-object top level.
    Never raises."""
    manifest_path = Path(repo).expanduser() / "knowledge-manifest.json"
    if not manifest_path.exists():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        _log.warning(
            "extensions resolver: skipping malformed manifest %s: %s", manifest_path, exc
        )
        return None
    if not isinstance(data, dict):
        _log.warning(
            "extensions resolver: skipping non-object manifest %s", manifest_path
        )
        return None
    return data


def _signed_source_for_repo(repo: str) -> tuple[bool, Any]:
    """Return ``(authentication_required, source)`` for one repository.

    The first value is deliberately independent of source availability.  A
    revoked or unverifiable manifest-declared source therefore remains an
    authenticated source and cannot fall through to mutable checkout bytes.
    """
    try:
        from cc.core.ecosystem.knowledge_skill_source import (
            knowledge_repository_requires_authenticated_source,
            resolve_knowledge_skill_sources,
        )

        nominal = Path(repo).expanduser().absolute()
        authentication_required = knowledge_repository_requires_authenticated_source(
            nominal
        )
        if not authentication_required:
            return False, None
        source = next(
            (
                source
                for _root, source in resolve_knowledge_skill_sources()
                if source is not None and source.repository_root == nominal
            ),
            None,
        )
        return True, source
    except Exception:
        _log.debug("extensions resolver: signed source lookup failed", exc_info=True)
        # A configured manifest that cannot be classified or verified cannot
        # grant the checkout legacy unsigned authority.
        return True, None


def _load_manifest_authenticated(
    repo: str, source: Any, *, authentication_required: bool
) -> Optional[dict]:
    if source is None:
        if authentication_required:
            return None
        return _load_manifest(repo)
    try:
        receipt = source.authenticated_contribution(
            "knowledge-manifest.json", runtime="claude"
        )
        data = json.loads(receipt.content)
    except Exception as exc:
        _log.warning("extensions resolver: signed manifest unavailable for %s: %s", repo, exc)
        return None
    return data if isinstance(data, dict) else None


def _find_agent_extension(manifest: dict, agent: str) -> Optional[dict]:
    extensions = manifest.get("extensions")
    if not isinstance(extensions, list):
        return None
    for entry in extensions:
        if isinstance(entry, dict) and entry.get("agent") == agent:
            return entry
    return None


def _default_missing_skills(required: list[str]) -> list[str]:
    """Verify `required` skill names via the exact same lookup `cc skill
    get` uses (`core/skill_store.py`'s `default_skill_paths()` +
    `discover_skills_with_sources()`), so a skill this resolver says is
    available is guaranteed retrievable by the agent that reads it next.
    Returns the subset of `required` that could NOT be found. Never
    raises -- an unreadable skill tree is treated as "missing", not a
    crash."""
    if not required:
        return []
    try:
        from cc.core.skill_store import (
            default_skill_paths,
            discover_skills_with_sources,
            find_skill_by_name,
        )

        pairs = default_skill_paths()
        skills = discover_skills_with_sources(pairs, cache_dir=None)
        return [name for name in required if find_skill_by_name(name, skills) is None]
    except Exception:
        _log.debug("extensions resolver: skill availability check failed", exc_info=True)
        return list(required)


def _required_skill_receipts(required: list[str]) -> tuple[Any, ...]:
    if not required:
        return ()
    try:
        from cc.core.skill_store import (
            default_skill_paths,
            discover_skills_with_sources,
            find_skill_by_name,
            get_skill_content_with_receipt,
        )

        skills = discover_skills_with_sources(default_skill_paths(), cache_dir=None)
        receipts = []
        for name in required:
            skill = find_skill_by_name(name, skills)
            if skill is None:
                continue
            result = get_skill_content_with_receipt(skill, runtime="claude")
            if result.receipt is not None:
                receipts.append(result.receipt)
        return tuple(receipts)
    except Exception:
        _log.debug("extensions resolver: skill receipt lookup failed", exc_info=True)
        return ()


def resolve_extension(
    agent: str,
    *,
    knowledge_repos: Optional[list[str]] = None,
    missing_skills_checker: Optional[Callable[[list[str]], list[str]]] = None,
) -> ExtensionResolution:
    """Resolve the winning extension (if any) for `agent`.

    Iterates `knowledge_repos` in order -- when omitted, this is
    `resolve_knowledge_repos()` from `core/config.py`, the SAME ordered
    list `cc env` exports as `CC_KNOWLEDGE_REPOS`. That list is already
    precedence-ordered (personal entries match the `<product>-copilot-
    private` convention `cc env` itself uses to derive
    `CC_PERSONAL_KNOWLEDGE_REPO`), so "personal wins on tie" falls out of
    list position -- there is no separate rank-comparison to get wrong.

    The FIRST repo whose manifest declares an `extensions[]` entry for
    `agent` wins outright (subsequent repos are never consulted for that
    agent, even if they also declare one) -- this is precisely what makes
    personal-over-org precedence a property of iteration order rather than
    a second comparison that could disagree with it.

    `missing_skills_checker` is an injectable seam (mirrors
    `docs_resolver.py`'s `SourceBackend` pattern) for testing the
    `requiredSkills`/`fallbackBehavior` branches without touching the real
    skill store; production callers should omit it.
    """
    if knowledge_repos is None:
        from cc.core.config import resolve_knowledge_repos

        knowledge_repos = resolve_knowledge_repos()

    checker = missing_skills_checker or _default_missing_skills

    for repo in knowledge_repos:
        authentication_required, signed_source = _signed_source_for_repo(repo)
        manifest = _load_manifest_authenticated(
            repo,
            signed_source,
            authentication_required=authentication_required,
        )
        if manifest is None:
            continue
        entry = _find_agent_extension(manifest, agent)
        if entry is None:
            continue

        ext_type = entry.get("type")
        if ext_type not in _VALID_TYPES:
            _log.warning(
                "extensions resolver: %s declares unknown type %r for agent %r -- skipping",
                repo, ext_type, agent,
            )
            continue

        file_rel = entry.get("file")
        if not file_rel or not isinstance(file_rel, str):
            _log.warning(
                "extensions resolver: %s entry for %r has no file -- skipping", repo, agent
            )
            continue
        file_abs = (Path(repo).expanduser() / file_rel).resolve()
        extension_receipt = None
        if signed_source is not None:
            try:
                extension_receipt = signed_source.authenticated_contribution(
                    file_rel, runtime="claude"
                )
            except Exception as exc:
                _log.warning(
                    "extensions resolver: signed extension unavailable for %s: %s",
                    repo,
                    exc,
                )
                continue
        elif authentication_required:
            continue
        if extension_receipt is None and not file_abs.is_file():
            _log.warning(
                "extensions resolver: declared extension file missing: %s -- skipping", file_abs
            )
            continue

        required = [s for s in (entry.get("requiredSkills") or []) if isinstance(s, str)]
        fallback = entry.get("fallbackBehavior")
        if fallback not in _VALID_FALLBACKS:
            fallback = _DEFAULT_FALLBACK

        missing = checker(required)
        skill_receipts = (
            _required_skill_receipts(required)
            if missing_skills_checker is None and not missing
            else ()
        )

        resolution = ExtensionResolution(
            agent=agent,
            matched=True,
            type=ext_type,
            file=str(file_abs),
            source_repo=repo,
            description=entry.get("description"),
            required_skills=required,
            missing_skills=missing,
            fallback_behavior=fallback,
            contributions=(
                ((extension_receipt,) if extension_receipt is not None else ())
                + skill_receipts
            ),
        )

        if not missing:
            resolution.action = ACTION_APPLY
            return resolution

        # requiredSkills unavailable -- apply fallbackBehavior.
        skill_list = ", ".join(missing)
        if fallback == "fail":
            resolution.action = ACTION_FALLBACK_FAIL
            resolution.warning = (
                f"{agent}: required skills unavailable ({skill_list}); "
                f"fallbackBehavior=fail -- not proceeding with base or extension"
            )
        elif fallback == "use_base_with_warning":
            resolution.action = ACTION_FALLBACK_WARNING
            resolution.warning = (
                f"{agent}: required skills unavailable ({skill_list}); using base agent"
            )
        else:  # use_base
            resolution.action = ACTION_FALLBACK_USE_BASE
        return resolution

    return ExtensionResolution(agent=agent)


def compose_agent_content(
    resolution: ExtensionResolution,
    base_agent_content: str,
) -> str:
    """Deterministic, code-only composition -- no model judgment required.

    - no match / any fallback action: `base_agent_content` unchanged.
    - `override`: the extension file's content verbatim, in place of
      `base_agent_content` entirely.
    - `extension`: `base_agent_content` with the extension file's content
      APPENDED (never section-merged) under an explicit heading. This is
      the honest, defined limit the framework's docs called "aspirational"
      when they described a pretend section-level merge -- deciding which
      of two overlapping prose sections "wins" is a semantic judgment,
      not a mechanical one, so this function does not attempt it. It
      guarantees both bodies of text reach the reader, in a fixed order,
      every time.
    - `skills`: `base_agent_content` unchanged (this type only asserts
      skill availability; it carries no content to apply).

    Callers still must read `resolution.file` from disk themselves (this
    function takes the already-read extension content as a plain string,
    matching `base_agent_content`, so it stays a pure function with no I/O
    and no dependency on repository layout).
    """
    return compose_agent_content_with_receipts(resolution, base_agent_content).content


def compose_agent_content_with_receipts(
    resolution: ExtensionResolution,
    base_agent_content: str,
) -> AuthenticatedComposition:
    """Typed composition preserving exact authenticated source receipts."""
    if not resolution.use_extension or resolution.type is None:
        content = base_agent_content
        return AuthenticatedComposition(
            content=content,
            receipts=(),
            content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )

    extension_receipt = resolution.contributions[0] if resolution.contributions else None
    extension_content = (
        extension_receipt.content
        if extension_receipt is not None
        else (Path(resolution.file).read_text(encoding="utf-8") if resolution.file else "")
    )

    if resolution.type == "override":
        content = extension_content
        return AuthenticatedComposition(content, resolution.contributions, hashlib.sha256(content.encode()).hexdigest())

    if resolution.type == "skills":
        content = base_agent_content
        return AuthenticatedComposition(content, resolution.contributions, hashlib.sha256(content.encode()).hexdigest())

    # type == "extension": deterministic append, explicitly labeled.
    source_label = resolution.source_repo or "extension"
    heading = (
        f"\n\n---\n\n## Extension (type: extension, source: {source_label})\n\n"
        "The following content was APPENDED by the extension resolver -- it was "
        "NOT section-merged into the base agent above. Per this agent's own "
        "Runtime Precedence \"content outranks form\" convention, treat any "
        "conflict between this section and the base agent above as resolved "
        "in favor of the more specific guidance below.\n\n"
    )
    content = base_agent_content + heading + extension_content
    return AuthenticatedComposition(content, resolution.contributions, hashlib.sha256(content.encode()).hexdigest())
