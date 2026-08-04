"""Read-only mirror-root resolution + cheap lock-pointer read for tiers.

WS-A slice 3 (freshness-slice) added the cheap remote-ref read a poll needs
(`latest_lock_sha()`) -- copilot-control-tower/docs/01-architecture/
cli-contract.md: "the cheap poll target -- a single SHA, not a full
`update`". WS-A slice 4 (update-slice) adds the real thing:
`clone_or_update_mirror()` -- clone-if-absent / else fetch+reset --hard,
confined to `<mirror_root>/<tier>`, backing `cc update --json`
(cc/commands/update.py).

Mirror location (owner-ratified 2026-07-06, inheritance-and-publish.md
§2.2): `~/.copilot/mirrors/<tier>` -- the READ-ONLY clone Control Tower may
freely `fetch && reset --hard`/reclone. This is NEVER `~/.claude/` (the
materialized tree the host scans) and NEVER an authoring vault (the
writable Obsidian-style checkout an author edits before `copilot publish`
-- inheritance-and-publish.md §2.2's tree table draws this exact
distinction). `mirror_root()` never resolves `Path.home()` when an
explicit `_root` is injected, so tests can point it at `tmp_path`.

Lock-pointer ref convention (owner-ratified 2026-07-06, this slice's
choice -- confirm with the CLI/schema owner at freeze): each tier's source
repo publishes `refs/copilot/lock` (default; a caller-supplied `ref`
overrides) pointing DIRECTLY at the git blob object of its own resolved
`copilot.lock.json` -- i.e. upstream, whenever a tier's lock is
(re)resolved, it runs the equivalent of
`git update-ref refs/copilot/lock $(git hash-object copilot.lock.json)`
and pushes that ref. That is what makes the ref's target directly
comparable to `freshness.current_lock_sha()` (which hashes the LOCAL
lockfile the same way) using only a `git ls-remote` -- no clone, no
fetch, no working tree, no full `update`.
"""

from __future__ import annotations

import base64
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, TypedDict

from cc.core import authstore, keychain
from cc.core.config import resolve_key
from cc.core.ecosystem.manifest import ManifestError

# Default published lock-pointer ref name (owner-ratified convention --
# see module docstring). Callers may override per-tier via a manifest
# layer's own published ref name, if a future layer ever needs one.
DEFAULT_LOCK_POINTER_REF = "refs/copilot/lock"

# Sentinel distinguishing "no override passed" (auto-resolve) from an
# explicit token/None argument -- same convention as commands/update.py's
# `_UNSET` (a caller-supplied `None` must force anonymous, never be
# confused with "not supplied at all").
_UNSET: Any = object()

_EXACT_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_CARET_SEMVER = re.compile(r"^\^v?(\d+)\.(\d+)\.(\d+)$")
_MAJOR_X_SEMVER = re.compile(r"^v?(\d+)\.x$")

# Products whose mirrors are nested one level deeper (`<mirror_root>/
# <product>/<layer id>` rather than `<mirror_root>/<layer id>`) because
# they are synced but never folded into the materialize root -- see
# `commands/update.py`'s own module docstring / `externally_consumed_
# products` local. Single source of truth for BOTH `clone_or_update_mirror()`
# callers (update.py) and `synthesize_source_path()` (update.py + resolve.py)
# below, so the two can never compute a different mirror location for the
# same layer.
EXTERNALLY_CONSUMED_PRODUCTS: frozenset[str] = frozenset({"knowledge", "cli"})


@dataclass(frozen=True)
class RemoteRefProbe:
    """Result of a read-only ``git ls-remote`` probe.

    ``sha=None`` is not enough to decide that a machine is offline: Git
    returns success with empty stdout when the repository is reachable but the
    requested ref does not exist.  Keep that proven reachability separate so
    doctor can distinguish a missing optional lock pointer from a transport,
    authentication, timeout, or executable failure.
    """

    reachable: bool
    sha: Optional[str]


def mirror_root(tier: str, *, _root: Optional[Path | str] = None) -> Path:
    """
    Resolve the read-only mirror root for `tier` (e.g. "foundation",
    "org", "dept-finance", "personal"): `<root>/<tier>`.

    `_root` is injectable so tests point this at `tmp_path` and NEVER
    resolve `Path.home()`. With no injection, resolves from config
    (`paths.mirrors_root`, defaulting to `~/.copilot/mirrors` --
    core/config.py DEFAULTS) via the same env>project>machine>default
    cascade every other `cc` path key uses -- no new resolution logic.
    """
    if _root is not None:
        base = Path(_root).expanduser()
    else:
        configured = resolve_key("paths.mirrors_root")
        base = (
            Path(configured).expanduser()
            if configured
            else Path.home() / ".copilot" / "mirrors"
        )
    return base / tier


def synthesize_source_path(
    layer: dict[str, Any],
    *,
    mirror_root_base: Path | str,
    externally_consumed_products: frozenset[str] = EXTERNALLY_CONSUMED_PRODUCTS,
) -> Optional[Path]:
    """
    Compute the on-disk content root a remote-sourced layer's mirror
    clone resolves (or WOULD resolve) to: `<mirror_root_base>/<product>/
    <layer id>` for `externally_consumed_products` (knowledge/cli),
    `<mirror_root_base>/<layer id>` for everything else, plus any declared
    `source.subpath` joined on top -- the EXACT same construction
    `clone_or_update_mirror()`'s own `target = Path(mirror_root).expanduser()
    / tier` uses.

    WP-372 P5.1: pure path arithmetic -- never touches disk or network,
    never clones/fetches anything, and never requires the mirror to
    actually exist (callers decide whether/how to check that). This is
    the SINGLE SOURCE OF TRUTH shared by:
      - `commands/update.py` (MUTATING: clones/updates the mirror first,
        then calls this to compute the resulting `source["path"]` it
        materializes from).
      - `commands/resolve.py` (READ-ONLY: calls this directly against
        whatever mirror already happens to exist on disk from a prior
        `cc update`, per its own never-clones-anything contract -- see
        resolve.py's module docstring -- so `cc resolve --explain` stops
        being blind to any layer whose manifest entry has no static
        `source.path`, which is every remote-sourced layer in the live
        manifest).
    Before this, `update.py` computed this inline and `resolve.py` had NO
    equivalent at all (`discover_contributions()` requires a static
    `source.path` that the manifest never carries), so `cc resolve` always
    reported 0 items even when materialize demonstrably worked.

    Returns `None` for a layer with no `source.repo`, or one that already
    carries an explicit local `source.path` (a local-path-sourced layer is
    not this function's concern -- its path is already static). Raises
    `ManifestError` for a `source.subpath` that escapes its mirror (`..`
    or an absolute path) -- the SAME validation `update.py` already
    performs at materialize time, now shared so `resolve --explain` can
    never silently disagree with what `update` would actually do.
    """
    source = layer.get("source") or {}
    repo = source.get("repo")
    local_path = source.get("path")
    if not repo or local_path:
        return None

    product = layer.get("product")
    base = Path(mirror_root_base).expanduser()
    product_root = (
        base / str(product) if product in externally_consumed_products else base
    )
    content_root = product_root / layer["id"]

    subpath = source.get("subpath")
    if not subpath:
        return content_root

    relative = Path(str(subpath))
    if relative.is_absolute() or ".." in relative.parts:
        raise ManifestError(
            f"Layer {layer['id']!r} source.subpath must stay inside its mirror."
        )
    return content_root / relative


def probe_remote_ref(
    source: str,
    ref: str = DEFAULT_LOCK_POINTER_REF,
    *,
    timeout: float = 5.0,
) -> RemoteRefProbe:
    """
    Cheap, read-only check of one remote ref: a
    single `git ls-remote <source> <ref>` -- no clone, no fetch, no
    working tree.

    Never raises. A successful invocation with empty stdout proves the
    repository answered but the requested ref is absent. A non-zero result or
    invocation exception means reachability could not be established.
    """
    try:
        result = subprocess.run(
            ["git", "ls-remote", source, ref],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return RemoteRefProbe(reachable=False, sha=None)

    if result.returncode != 0:
        return RemoteRefProbe(reachable=False, sha=None)

    stdout = result.stdout.strip()
    if not stdout:
        return RemoteRefProbe(reachable=True, sha=None)

    first_line = stdout.splitlines()[0]
    sha, _, _ref_name = first_line.partition("\t")
    sha = sha.strip()
    return RemoteRefProbe(reachable=True, sha=sha or None)


def latest_lock_sha(
    source: str,
    ref: str = DEFAULT_LOCK_POINTER_REF,
    *,
    timeout: float = 5.0,
) -> Optional[str]:
    """Compatibility wrapper returning only a published lock-pointer SHA.

    Freshness callers intentionally keep their existing nullable contract:
    both an absent pointer and an unreachable repository remain an honest
    unknown there. Doctor uses :func:`probe_remote_ref` directly because its
    top-level ``offline`` verdict must distinguish those causes.
    """
    return probe_remote_ref(source, ref, timeout=timeout).sha


def resolve_transport(source: str, auth: str) -> str:
    """
    Map a manifest `auth` value (`ssh-personal` / `ssh-work` / `anon` /
    `gh-app:<slug>`, four-tier-topology.md §6.1) to the URL git should
    actually use for this cheap read path.

    For `ssh-personal` / `ssh-work` / `anon`, the SSH host alias or plain
    HTTPS URL is already baked into `source` by whoever authored the
    manifest ("the SSH alias in the URL *is* the credential selector" --
    four-tier-topology.md §6.1) -- so this is the identity function today.
    Richer transport handling (verifying the aliased SSH host is actually
    configured, `BatchMode=yes` headless-fail-fast, etc.) lands with the
    full `update` clone/fetch slice, not this read-only poll.

    `gh-app:<slug>` (CI/shared-runner short-lived installation tokens) is
    NOT implemented here -- minting a token via the GitHub App API belongs
    in that same later `update` machinery. Raises `NotImplementedError`
    rather than silently returning a URL that will fail to authenticate.
    """
    if auth.startswith("gh-app"):
        raise NotImplementedError(
            "gh-app auth (GitHub App installation tokens) is not implemented "
            "in the freshness read-only slice -- lands with the `update` "
            "clone/fetch slice."
        )
    return source


def _basic_auth_header(token: str) -> str:
    """
    Build a git `http.extraHeader` value authenticating as `token` the same
    way GitHub's own tooling does for a plain access token over HTTPS: HTTP
    Basic with the literal username `x-access-token` and the token as the
    password (GitHub accepts any non-empty username for a PAT/installation
    token, `x-access-token` is the documented convention). Returned as a
    single header line ready for `-c http.extraHeader=<this>` -- never a
    URL-embedded credential (those get persisted into `.git/config`'s
    remote URL on clone; a `-c` override does not).
    """
    encoded = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode(
        "ascii"
    )
    return f"Authorization: Basic {encoded}"


def resolve_token(
    *,
    _read_identity: Callable[..., dict[str, Any]] = authstore.read_identity,
    _get_secret: Callable[..., Optional[str]] = keychain.get_secret,
    _keychain_service: Optional[str] = None,
) -> Optional[str]:
    """
    Resolve an optional access token for an authenticated HTTPS fetch:
    `authstore.read_identity()` (the non-secret "who is signed in" pointer,
    `{login, ...}`) -> `keychain.get_secret(login, service=...)` (the OS
    keychain, per credentials-and-boundary.md: "secrets are honored only
    from a per-user OS keychain entry"). Both steps are injectable so
    callers/tests never touch a real identity file or the real Keychain.

    SOFT DEPENDENCY -- never raises, degrades to `None` (anonymous,
    today's unchanged behavior) on ANY missing piece: not signed in, no
    `login` recorded, Keychain unavailable on this platform
    (`KeychainUnavailable` on non-Darwin), or a lookup miss. Mirrors this
    module's own `latest_lock_sha()` "never a fabricated success" honesty
    posture, just for "have a token" rather than "know a SHA".
    """
    try:
        identity = _read_identity()
    except Exception:
        return None

    login = identity.get("login") if isinstance(identity, dict) else None
    if not login:
        return None

    service = _keychain_service or resolve_key("auth.keychain_service")
    if not service:
        return None

    try:
        return _get_secret(login, service=service)
    except Exception:
        return None


def _resolve_effective_token(source: str, token_override: Any) -> Optional[str]:
    """
    `token_override` is `mirror.py`'s own `_UNSET` sentinel by default
    (auto-resolve), an explicit `str` (force that token), or an explicit
    `None` (force anonymous, bypassing auto-resolution entirely -- tests
    use this to keep the existing anonymous-path fixtures untouched by
    keychain/authstore machinery).

    Auto-resolution (`token_override is _UNSET`) only ever fires for
    `https://`/`http://` sources -- `ssh-*`/`anon` transports and the local
    plain-path fixtures every other test in this module uses never trigger
    an `authstore.read_identity()` call, so `Path.home()` is never resolved
    as a side effect of a plain mirror sync (the `_no_real_home` autouse
    fixture in tests/test_ecosystem_mirror.py depends on this).
    """
    if token_override is not _UNSET:
        return token_override
    if not source.startswith(("https://", "http://")):
        return None
    return resolve_token()


class MirrorSyncResult(TypedDict):
    tier: str
    path: str
    ok: bool
    offline: bool
    action: str  # "cloned" | "updated" | "offline" | "error"
    head_sha: Optional[str]
    error: Optional[str]


def _run_git(
    args: list[str],
    *,
    cwd: Optional[Path] = None,
    timeout: float,
    _auth_header: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """
    `_auth_header`, when supplied, is injected via `git -c
    http.extraHeader=<value>` -- a PER-INVOCATION config override, never
    written to any `.git/config` on disk (that only happens for `git
    config <key> <value>`, which this never calls). Ordering matters: `-c`
    must precede the subcommand for git to accept it as a config override
    rather than a positional argument.
    """
    argv = ["git"]
    if _auth_header:
        argv += ["-c", f"http.extraHeader={_auth_header}"]
    argv += args
    return subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _select_semver_tag(ref: str, tags: list[str]) -> Optional[str]:
    """Resolve a supported semver range to the highest matching git tag."""
    caret = _CARET_SEMVER.fullmatch(ref)
    major_x = _MAJOR_X_SEMVER.fullmatch(ref)
    if caret is None and major_x is None:
        return ref

    candidates: list[tuple[tuple[int, int, int], str]] = []
    for tag in tags:
        match = _EXACT_SEMVER.fullmatch(tag)
        if match is None:
            continue
        version = tuple(int(part) for part in match.groups())
        if major_x is not None:
            allowed = version[0] == int(major_x.group(1))
        else:
            floor = tuple(int(part) for part in caret.groups())
            if floor[0] > 0:
                ceiling = (floor[0] + 1, 0, 0)
            elif floor[1] > 0:
                ceiling = (0, floor[1] + 1, 0)
            else:
                ceiling = (0, 0, floor[2] + 1)
            allowed = floor <= version < ceiling
        if allowed:
            candidates.append((version, tag))
    return max(candidates)[1] if candidates else None


def _offline_result(
    tier: str, target: Path, detail: str, *, action: str = "offline"
) -> MirrorSyncResult:
    return {
        "tier": tier,
        "path": str(target),
        "ok": False,
        "offline": True,
        "action": action,
        "head_sha": None,
        "error": detail,
    }


def _error_result(tier: str, target: Path, detail: str) -> MirrorSyncResult:
    return {
        "tier": tier,
        "path": str(target),
        "ok": False,
        "offline": False,
        "action": "error",
        "head_sha": None,
        "error": detail,
    }


def clone_or_update_mirror(
    tier: str,
    source: str,
    ref: str,
    *,
    mirror_root: Path | str,
    timeout: float = 30.0,
    _token: Any = _UNSET,
) -> MirrorSyncResult:
    """
    Materialize (or refresh) the READ-ONLY mirror for `tier`: clone if the
    mirror is absent, else `fetch` + `reset --hard` to `ref` (the layer
    manifest's own `source.ref` -- e.g. a branch/tag/sha -- NOT the
    lock-pointer ref `latest_lock_sha()` reads; that ref points at a
    `copilot.lock.json` blob, not a content tree).

    PROVABLY CONFINED to `<mirror_root>/<tier>`: the clone destination and
    every `git -C <target>` invocation below is built from that single path
    -- this function never passes any other filesystem path to git, and
    never touches `mirror_root`'s other tier subdirectories or anything
    above `mirror_root`.

    Never raises: any offline/unreachable/misconfigured condition (DNS
    failure, auth failure, timeout, `git` missing) degrades to an honest
    `{"ok": False, "offline": True, ...}` result -- mirrors
    `latest_lock_sha()`'s "never a fabricated success" rule (module
    docstring). On a failed *clone* attempt, any partial half-cloned
    directory is removed so the next attempt starts clean (no partial
    corruption left behind); an existing, previously-good mirror is never
    deleted merely because a *subsequent* fetch/reset failed -- offline is
    reported and the prior cached content is left exactly as it was
    (ecosystem-architecture.md §5.2: "offline = using cached SHAs").

    PRIVATE-REPO TRANSPORT (optional, soft dependency): `_token` defaults
    to auto-resolving a token via `resolve_token()` -- but ONLY for
    `https://`/`http://` sources (`_resolve_effective_token()`), so `ssh-*`/
    `anon`/local-path sources never touch the keychain/authstore at all.
    With no signed-in identity or no keychain entry, this degrades to the
    current anonymous behavior unchanged. When a token IS resolved, it is
    injected as a `git -c http.extraHeader=...` override on the `clone`/
    `fetch` invocations ONLY (never `reset`/`rev-parse`, which need no
    network auth) -- a per-invocation override, so the token is NEVER
    written to `<target>/.git/config`, never logged (it appears only as an
    in-memory argv element for this subprocess call), and never appears in
    this function's return value.
    """
    target = Path(mirror_root).expanduser() / tier
    token = _resolve_effective_token(source, _token)
    auth_header = _basic_auth_header(token) if token else None

    try:
        if not (target / ".git").is_dir():
            # No mirror yet (or a prior failed clone left a partial dir) --
            # clean slate, then clone directly into `target`.
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            target.parent.mkdir(parents=True, exist_ok=True)

            cloned = _run_git(
                ["clone", "--quiet", "--origin", "origin", source, str(target)],
                timeout=timeout,
                _auth_header=auth_header,
            )
            if cloned.returncode != 0:
                shutil.rmtree(target, ignore_errors=True)
                return _offline_result(tier, target, cloned.stderr.strip())
            action = "cloned"
        else:
            action = "updated"

        effective_ref = ref
        if _CARET_SEMVER.fullmatch(ref) or _MAJOR_X_SEMVER.fullmatch(ref):
            tags_fetch = _run_git(
                ["fetch", "--quiet", "--tags", "--force", "origin"],
                cwd=target,
                timeout=timeout,
                _auth_header=auth_header,
            )
            if tags_fetch.returncode != 0:
                return _offline_result(tier, target, tags_fetch.stderr.strip())
            tags_result = _run_git(["tag", "--list"], cwd=target, timeout=timeout)
            if tags_result.returncode != 0:
                return _error_result(tier, target, tags_result.stderr.strip())
            effective_ref = _select_semver_tag(ref, tags_result.stdout.splitlines())
            if effective_ref is None:
                return _error_result(
                    tier,
                    target,
                    f"No published release satisfies {ref}.",
                )

        is_release_tag = _EXACT_SEMVER.fullmatch(effective_ref) is not None
        fetch_args = ["fetch", "--quiet"]
        if is_release_tag:
            # Keep the tag object and local tag ref, not just its peeled
            # commit in FETCH_HEAD. Trust verification must be able to
            # verify the signed annotated release tag after an existing
            # mirror advances to a newly published exact version.
            fetch_args += [
                "--force",
                "origin",
                f"refs/tags/{effective_ref}:refs/tags/{effective_ref}",
            ]
        else:
            fetch_args += ["origin", effective_ref]

        fetched = _run_git(
            fetch_args,
            cwd=target,
            timeout=timeout,
            _auth_header=auth_header,
        )
        if fetched.returncode != 0:
            # Existing mirror content (if any) is left untouched -- honest
            # offline, never a destructive fallback.
            return _offline_result(tier, target, fetched.stderr.strip())

        reset_target = (
            f"refs/tags/{effective_ref}^{{}}" if is_release_tag else "FETCH_HEAD"
        )
        reset = _run_git(
            ["reset", "--quiet", "--hard", reset_target],
            cwd=target,
            timeout=timeout,
        )
        if reset.returncode != 0:
            return _error_result(tier, target, reset.stderr.strip())

        head = _run_git(["rev-parse", "HEAD"], cwd=target, timeout=timeout)
        head_sha = head.stdout.strip() if head.returncode == 0 else None

        return {
            "tier": tier,
            "path": str(target),
            "ok": True,
            "offline": False,
            "action": action,
            "head_sha": head_sha,
            "error": None,
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return _offline_result(tier, target, str(exc))
