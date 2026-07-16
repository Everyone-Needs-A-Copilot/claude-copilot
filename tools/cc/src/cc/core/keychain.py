"""macOS Keychain wrapper for the WS-A device-flow sign-in seam.

Secrets (the GitHub device-flow token) NEVER live in `cc`'s own config
files or the inheritance content ecosystem_config.py reads (copilot-
control-tower CLAUDE.md invariant #6: "secrets never enter inheritance
content or any git repo"). This module is the one place `cc` talks to a
real credential store -- a thin wrapper around the `security` CLI (the
per-user OS keychain), so a secret value only ever exists as a subprocess
argv element, never written to disk by `cc` itself and never logged.

Darwin-only by construction: the `security` CLI (and the login/System
keychains it wraps) doesn't exist on other platforms. Every public
function here raises `KeychainUnavailable` immediately on any
`sys.platform != "darwin"` rather than shelling out to a binary that isn't
there.

Injectable `_run` (mirrors core/ecosystem/mirror.py's `_run_git()`
precedent, generalized to a full `subprocess.run`-signature callable):
tests substitute a fake to assert exact argv without ever touching a real
keychain -- unlike git, there is no safe local fixture to run `security`
against, so this module's tests can never shell out for real.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Callable, Optional

# Injectable subprocess runner -- same call signature as `subprocess.run`.
RunFn = Callable[..., "subprocess.CompletedProcess[str]"]


class KeychainUnavailable(RuntimeError):
    """Raised when the macOS Keychain is unavailable on this platform.

    The `security` CLI is Darwin-only; every public function in this
    module raises this on any other `sys.platform` rather than attempting
    (and failing confusingly on) an invocation of a binary that doesn't
    exist there.
    """


def _ensure_darwin() -> None:
    if sys.platform != "darwin":
        raise KeychainUnavailable(
            f"macOS Keychain is unavailable on this platform ({sys.platform!r}); "
            "the `security` CLI is Darwin-only."
        )


def set_secret(
    account: str,
    secret: str,
    *,
    service: str,
    _run: RunFn = subprocess.run,
) -> None:
    """
    Store `secret` in the macOS Keychain under (`service`, `account`).

    `-U` (update) overwrites any existing item for the same service/account
    pair instead of erroring on a duplicate. NEVER logs or echoes `secret`
    -- it is passed only as a subprocess argv element and never appears in
    any message this module emits, including on failure (a nonzero exit is
    silently swallowed, the same fail-open posture `get_secret()` /
    `delete_secret()` use, so surfacing `security`'s own stderr can never
    leak partial secret material).
    """
    _ensure_darwin()
    _run(
        [
            "security",
            "add-generic-password",
            "-a",
            account,
            "-s",
            service,
            "-w",
            secret,
            "-U",
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def get_secret(
    account: str,
    *,
    service: str,
    _run: RunFn = subprocess.run,
) -> Optional[str]:
    """
    Return the secret stored under (`service`, `account`), or `None` if
    absent (or the Keychain lookup otherwise fails) -- fail-open, mirrors
    every other read helper in this codebase (e.g.
    core/ecosystem/lockfile.py's `read_lockfile()`).
    """
    _ensure_darwin()
    result = _run(
        ["security", "find-generic-password", "-a", account, "-s", service, "-w"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.rstrip("\n")


def delete_secret(
    account: str,
    *,
    service: str,
    _run: RunFn = subprocess.run,
) -> bool:
    """
    Delete the secret stored under (`service`, `account`).

    Returns `True` on success, `False` if absent or the Keychain delete
    otherwise fails -- never raises for "nothing to delete".
    """
    _ensure_darwin()
    result = _run(
        ["security", "delete-generic-password", "-a", account, "-s", service],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0
