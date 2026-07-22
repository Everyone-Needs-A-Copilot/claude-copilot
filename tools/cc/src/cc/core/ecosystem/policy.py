"""Fail-closed capability and Git-signature policy for materialization.

Executable-adjacent content is accepted only when the Git commit that last
changed the item has a valid signature from the layer's declared signer
allow-list. Non-executable knowledge is still integrity-pinned by the
materializer, but it does not gain code-execution privileges and therefore
does not require an executable-content signer.

Missing Git context, a missing signer policy, an unknown signer, or an invalid
signature blocks. Callers may inject a policy in tests; production has no
"skip verification" switch.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable, Literal, Sequence

Verdict = Literal["allow", "hold", "block"]
PolicyFn = Callable[[dict[str, Any]], Verdict]

EXECUTABLE_DIMENSIONS = frozenset(
    {"agents", "skills", "commands", "protocol", "cli-integrations", "plugins"}
)


def _normalize_fingerprint(value: str) -> str:
    return "".join(value.split()).upper()


def verify_git_item(
    source_root: Path | str,
    relative_path: str,
    allowed_signers: Sequence[str],
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[bool, str | None]:
    """Verify the last commit touching one item and return its signer.

    Git's ``%G?`` performs cryptographic verification with the configured
    GPG/SSH verifier. ``%GF`` returns the key fingerprint. A good signature is
    still refused unless that fingerprint is explicitly allowlisted.
    """
    root = Path(source_root).expanduser()
    allowed = {_normalize_fingerprint(value) for value in allowed_signers if value}
    if not allowed or not (root / ".git").exists():
        return False, None
    try:
        result = run(
            [
                "git",
                "-C",
                str(root),
                "log",
                "-1",
                "--format=%G?%n%GF%n%GS",
                "--",
                relative_path,
            ],
            capture_output=True,
            text=True,
            timeout=8.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False, None

    lines = result.stdout.splitlines()
    if result.returncode != 0 or len(lines) < 2 or lines[0].strip() not in {"G", "U"}:
        return False, None
    fingerprint = lines[1].strip()
    if _normalize_fingerprint(fingerprint) not in allowed:
        return False, fingerprint or None
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

    verified, _signer = verify_git_item(source_root, relative_path, signers)
    return "allow" if verified else "block"


def permissive_policy(_item: dict[str, Any]) -> Verdict:
    """Test-only policy used to exercise reconciliation mechanics."""
    return "allow"
