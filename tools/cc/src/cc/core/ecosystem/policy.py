"""Fail-closed capability and Git-signature policy for materialization.

Executable-adjacent content is accepted only when the signed release TAG
pinned by the layer's manifest covers the item -- both a valid signature
from the layer's declared signer allow-list AND the item's real presence in
the exact tree that tag points at. Non-executable knowledge is still
integrity-pinned by the materializer, but it does not gain code-execution
privileges and therefore does not require an executable-content signer.

Missing Git context, a missing pinned tag, a missing signer policy, an
unknown signer, or an invalid signature blocks. Callers may inject a policy
in tests; production has no "skip verification" switch.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Literal, Sequence

Verdict = Literal["allow", "hold", "block"]
PolicyFn = Callable[[dict[str, Any]], Verdict]

EXECUTABLE_DIMENSIONS = frozenset(
    {"agents", "skills", "commands", "protocol", "cli-integrations", "plugins"}
)


def _normalize_fingerprint(value: str) -> str:
    return "".join(value.split()).upper()


FOUNDATION_SSH_SIGNING_KEYS: dict[str, str] = {
    _normalize_fingerprint(
        "SHA256:FIfppOkzwXZUAamELQzYoSUQXiEAmTYiVewHe1ACMZo"
    ): (
        "ssh-ed25519 "
        "AAAAC3NzaC1lZDI1NTE5AAAAINah8Gf036FQkhMcUU35m2p7Nqa41oBtVS/QV9tYZX8H"
    ),
}

# `git verify-tag`'s human-readable success/failure line (ssh format) always
# contains `... key SHA256:<base64>`, on both the "Good ... signature for
# <principal> with <type> key <fp>" success line and the "Good ... signature
# with <type> key <fp>" + "No principal matched." unapproved-signer line.
# `git verify-tag --format=...` suppresses this line entirely (it only
# templates ref-filter atoms, and the commit-only `%(signature:*)` atoms are
# not populated for a tag's OWN signature), so the fingerprint is recovered
# by pattern-matching the one message format `verify-tag` actually prints.
_SSH_SIGNATURE_FINGERPRINT_RE = re.compile(r"key (SHA256:\S+)")


def _ssh_signer_fingerprint(*streams: str) -> str | None:
    match = _SSH_SIGNATURE_FINGERPRINT_RE.search("\n".join(streams))
    return match.group(1) if match else None


def _containing_git_root(path: Path) -> Path | None:
    """Return the nearest repository root for a layer path.

    Layer manifests may expose a verified subpath (for example the Claude
    foundation's ``.claude`` directory) rather than the mirror root itself.
    A worktree's ``.git`` can be either a directory or a pointer file, so
    existence—not ``is_dir``—is the correct boundary check.
    """
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def verify_git_item(
    source_root: Path | str,
    relative_path: str,
    allowed_signers: Sequence[str],
    *,
    ref: str | None = None,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    _trusted_keys: dict[str, str] = FOUNDATION_SSH_SIGNING_KEYS,
) -> tuple[bool, str | None]:
    """Verify ``ref`` is a signed release tag covering ``relative_path`` and
    return its signer.

    Blocker 2 fix (security review, 2026-08-10): this used to walk
    ``git log -1 <ref> -- <path>`` to find "the commit that introduced this
    item" and check THAT commit's own signature. That technique only ever
    worked because every release tag was a fabricated PARENTLESS commit (a
    root commit trivially "introduces" every path in its tree). Now that
    ``foundation-snapshot-release.py`` signs the real branch commit directly
    (RC-3's fix), ``git log``'s default pathspec history simplification
    TREESAME-prunes straight past the signed tag to whatever ordinary,
    unsigned ancestor last touched the path -- ``%G?`` reports ``N`` for
    that ancestor and this function returned ``(False, None)`` for every
    single item on every real, non-orphan release. That fails closed (never
    a trust hole), but it is a functional landmine that blocks nearly the
    entire ecosystem on first use.

    The fix mirrors ``verify_item_provenance`` in
    ``copilot-control-tower/scripts/foundation-snapshot-release.py``: the
    security-relevant question for a release tag is never "who committed
    this path", it's "does the exact tree the SIGNED TAG points at contain
    this item" -- a signed, annotated tag's signature covers the tagged
    object's id, which recursively covers its entire tree, so any file
    present in that tree is exactly as trusted as the tag itself, whether or
    not the commit that tag points to is itself signed. Verification is
    therefore two independent steps against the SAME ``ref``: (1) ``git
    verify-tag`` proves the tag carries a valid signature from an
    allowlisted signer; (2) ``git cat-file -e <commit>:<path>`` proves the
    item exists in the tree at the commit embedded in that same tag object
    -- content-pinned by construction, since a tag's signature cannot be
    forged onto a different target commit without invalidating it.

    A fresh machine has no global ``gpg.ssh.allowedSignersFile``. Build an
    invocation-scoped trust file only from public keys compiled into cc whose
    fingerprints are also requested by the signed layer manifest. The two
    independent gates mean a manifest cannot introduce a new trust root, and
    a compiled key cannot authorize a layer unless the manifest names it.

    ``ref`` is now REQUIRED, not merely an optional precision improvement:
    the layer's actually-RESOLVED and PINNED revision (``layer["source"]["ref"]``
    -- e.g. a signed foundation snapshot tag such as ``v5.13.23``). There is
    no safe fallback left to run without it -- the retired blind-HEAD/history
    walk is exactly the broken technique this fix replaces, so a missing or
    unresolvable ``ref`` blocks rather than silently reverting to it.
    """
    source = Path(source_root).expanduser().resolve()
    allowed = {_normalize_fingerprint(value) for value in allowed_signers if value}
    if not allowed:
        return False, None

    trusted = {
        fingerprint: public_key
        for fingerprint, public_key in _trusted_keys.items()
        if _normalize_fingerprint(fingerprint) in allowed
    }
    if not trusted:
        return False, None

    root = _containing_git_root(source)
    if root is None:
        return False, None
    item_path = (source / relative_path).resolve()
    try:
        repo_relative_path = item_path.relative_to(root).as_posix()
    except ValueError:
        return False, None

    if not ref:
        return False, None

    try:
        with tempfile.TemporaryDirectory(prefix="cc-allowed-signers-") as temp_root:
            trust_file = Path(temp_root) / "allowed_signers"
            trust_file.write_text(
                "".join(
                    f'enac-foundation namespaces="git" {public_key}\n'
                    for public_key in trusted.values()
                ),
                encoding="utf-8",
            )
            os.chmod(trust_file, 0o600)

            # Step 1: the tag itself must carry a valid signature from an
            # allowlisted signer. Stop here on any failure -- an unsigned or
            # wrongly-signed tag never earns a tree lookup.
            tag_result = run(
                [
                    "git",
                    "-c",
                    "gpg.format=ssh",
                    "-c",
                    f"gpg.ssh.allowedSignersFile={trust_file}",
                    "-C",
                    str(root),
                    "verify-tag",
                    ref,
                ],
                capture_output=True,
                text=True,
                timeout=8.0,
                check=False,
            )
            if tag_result.returncode != 0:
                return False, None
            fingerprint = _ssh_signer_fingerprint(tag_result.stdout, tag_result.stderr)
            if fingerprint is None or _normalize_fingerprint(fingerprint) not in allowed:
                # Defense in depth: even a git-reported "good" signature is
                # refused unless ITS OWN fingerprint is explicitly
                # allowlisted, never trusting the allowed-signers file
                # membership alone.
                return False, fingerprint

            # Step 2: resolve the SAME ref to the commit its signature
            # covers -- never a second, independently-supplied commit -- so
            # the tree check below is provably the tag's own target.
            commit_result = run(
                ["git", "-C", str(root), "rev-parse", f"{ref}^{{commit}}"],
                capture_output=True,
                text=True,
                timeout=8.0,
                check=False,
            )
            if commit_result.returncode != 0 or not commit_result.stdout.strip():
                return False, None
            pinned_commit = commit_result.stdout.strip()

            # Step 3: confirm the item genuinely exists in that exact tree
            # -- never a `git log` walk, which is precisely the technique
            # that TREESAME-prunes past a signed tag on a real branch commit.
            tree_result = run(
                [
                    "git",
                    "-C",
                    str(root),
                    "cat-file",
                    "-e",
                    f"{pinned_commit}:{repo_relative_path}",
                ],
                capture_output=True,
                text=True,
                timeout=8.0,
                check=False,
            )
            if tree_result.returncode != 0:
                return False, None
    except (OSError, subprocess.SubprocessError):
        return False, None

    return True, fingerprint


def evaluate(item: dict[str, Any]) -> Verdict:
    """Apply the production signature policy to one candidate item."""
    if item.get("dimension") not in EXECUTABLE_DIMENSIONS:
        return "allow"

    policy = item.get("layer_policy")
    if not isinstance(policy, dict):
        return "block"
    signers = policy.get("allowed_signers")
    if not isinstance(signers, list):
        return "block"
    source_root = item.get("source_root")
    relative_path = item.get("relative_path")
    if not source_root or not relative_path:
        return "block"

    # `ref` (task 215 blocker fix, G-9; now REQUIRED by `verify_git_item`,
    # security review blocker 2, 2026-08-10): the layer's own resolved,
    # signed release tag -- see `verify_git_item`'s docstring for why the
    # verification target is the TAG's tree, never a `git log` walk.
    ref = item.get("ref")
    verified, _signer = verify_git_item(
        source_root, relative_path, signers, ref=ref if isinstance(ref, str) else None
    )
    return "allow" if verified else "block"


def permissive_policy(_item: dict[str, Any]) -> Verdict:
    """Test-only policy used to exercise reconciliation mechanics."""
    return "allow"
