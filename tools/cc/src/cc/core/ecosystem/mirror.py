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

import shutil
import subprocess
from pathlib import Path
from typing import Optional, TypedDict

from cc.core.config import resolve_key

# Default published lock-pointer ref name (owner-ratified convention --
# see module docstring). Callers may override per-tier via a manifest
# layer's own published ref name, if a future layer ever needs one.
DEFAULT_LOCK_POINTER_REF = "refs/copilot/lock"


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


def latest_lock_sha(
    source: str,
    ref: str = DEFAULT_LOCK_POINTER_REF,
    *,
    timeout: float = 5.0,
) -> Optional[str]:
    """
    Cheap, read-only check of a tier's published lock-pointer ref: a
    single `git ls-remote <source> <ref>` -- no clone, no fetch, no
    working tree. See the module docstring for the ref-target convention.

    Never raises: any unreachable/offline/misconfigured condition (DNS
    failure, auth failure, timeout, no such ref, `git` missing from PATH)
    degrades to `None` ("could not determine"). Callers (freshness.py)
    MUST treat `None` as an honest unknown, never as "up to date" -- this
    mirrors doctor.py's "never a fabricated Healthy" rule.
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
        return None

    if result.returncode != 0:
        return None

    stdout = result.stdout.strip()
    if not stdout:
        return None

    first_line = stdout.splitlines()[0]
    sha, _, _ref_name = first_line.partition("\t")
    sha = sha.strip()
    return sha or None


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


class MirrorSyncResult(TypedDict):
    tier: str
    path: str
    ok: bool
    offline: bool
    action: str  # "cloned" | "updated" | "offline" | "error"
    head_sha: Optional[str]
    error: Optional[str]


def _run_git(
    args: list[str], *, cwd: Optional[Path] = None, timeout: float
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


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
    """
    target = Path(mirror_root).expanduser() / tier

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
            )
            if cloned.returncode != 0:
                shutil.rmtree(target, ignore_errors=True)
                return _offline_result(tier, target, cloned.stderr.strip())
            action = "cloned"
        else:
            action = "updated"

        fetched = _run_git(
            ["fetch", "--quiet", "origin", ref], cwd=target, timeout=timeout
        )
        if fetched.returncode != 0:
            # Existing mirror content (if any) is left untouched -- honest
            # offline, never a destructive fallback.
            return _offline_result(tier, target, fetched.stderr.strip())

        reset = _run_git(
            ["reset", "--quiet", "--hard", "FETCH_HEAD"], cwd=target, timeout=timeout
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
