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
) -> bool:
    """
    Store `secret` in the macOS Keychain under (`service`, `account`).

    `-U` (update) overwrites any existing item for the same service/account
    pair instead of erroring on a duplicate. Returns whether Keychain
    confirmed the write. NEVER logs or echoes `secret` -- it is passed only
    as a subprocess argv element and never appears in any message this
    module emits, including on failure.
    """
    _ensure_darwin()
    result = _run(
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
    return result.returncode == 0


def _quote(text: str) -> str:
    """Double-quote *text* for one line of `security -i`'s batch-command
    protocol, escaping the two characters that protocol treats specially
    inside a double-quoted token (`\\` and `"`) -- verified round-trip
    correct against a live `security -i` invocation (spaces, embedded
    quotes, backslashes, a leading `-`, and the empty string all survive
    byte-for-byte) before this function was written."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def set_secret_stdin(
    account: str,
    secret: str,
    *,
    service: str,
    _run: RunFn = subprocess.run,
) -> bool:
    """
    Store `secret` in the macOS Keychain under (`service`, `account`)
    WITHOUT ever placing the value in a subprocess argv element -- the
    writer `cc connect` uses (WP-395's manual keychain floor, D-6), where
    the value originates from a human typing it into a non-technical
    surface and must never become visible to `ps`/`/proc`/any other
    process-listing tool for the lifetime of the call.

    `add-generic-password`'s `-w`/`-p` flags normally take the value as an
    argv token -- exactly that leak (`security`'s own `-h` usage text
    agrees: "Use of the -p or -w options is insecure"). `-w` with no
    trailing value instead prompts via `getpass()`-equivalent, but that
    reads the controlling TTY directly, not this process's stdin pipe --
    unusable from a non-interactive `cc` subprocess call (verified live:
    piping a value at it does not satisfy the prompt).

    The non-leaking mechanism this function uses instead is `security`'s
    documented **interactive/batch mode** (`-i`, "allow the user to enter
    multiple commands on stdin"): the whole `add-generic-password ...`
    invocation, VALUE INCLUDED, is written as one line of the *stdin
    stream* `security` itself reads, never as an execve() argv element --
    so the value never appears in `ps`, a core dump of the argv vector, or
    any process-listing tool. `account`/`service`/`secret` are each
    double-quoted and backslash/double-quote-escaped (`_quote()`) so a
    value containing spaces, quotes, backslashes, or a leading `-`
    round-trips byte-for-byte.

    A `secret` containing a line break (`\\n`/`\\r`) cannot be represented
    on `-i`'s one-line command protocol at all -- forcing it through would
    either truncate the value or (worse, verified live against a real
    `security -i`) leak the REMAINDER of the value into `security`'s own
    stderr as an "unknown command" parse error. This function refuses that
    case outright (`ValueError`) rather than risk either outcome; `cc
    connect` validates for this up front (before ever calling this
    function) so it can report a structured, value-free per-credential
    `failed` outcome instead of raising.

    `-U` (update) matches `set_secret()`'s existing semantics: overwrites
    any existing item for the same service/account pair instead of
    erroring on a duplicate.

    NEVER logs or echoes `secret` -- it is written only into the `-i`
    stdin stream and never appears in any message this function emits,
    including on failure. Deliberately does NOT reuse `set_secret()`
    above: that function is the established GitHub device-flow writer
    (locked in by its own tests' exact-argv assertions) and this codebase's
    convention is to add a new, separately-tested function rather than
    change an existing one's observable behavior for an unrelated caller.
    """
    _ensure_darwin()
    if "\n" in secret or "\r" in secret:
        raise ValueError("secret value must not contain a line break")
    command = (
        f"add-generic-password -a {_quote(account)} -s {_quote(service)} "
        f"-w {_quote(secret)} -U\n"
    )
    try:
        result = _run(
            ["security", "-i"],
            input=command,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


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
