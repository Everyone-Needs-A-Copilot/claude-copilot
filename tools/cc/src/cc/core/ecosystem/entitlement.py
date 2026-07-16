"""GitHub repo-access entitlement check (D3, the entitlement spine).

copilot-control-tower/docs/01-architecture/cli-contract.md D7.1: entitlement
to a department/org layer is defined as "has GitHub repo access to it" --
computed CLI-side (invariant #1: parse, never compute -- Control Tower only
ever renders the `entitled` bool/null this module produces, it never
evaluates repo permissions itself).

Backs `cc layers --json` / `cc layers join --json` (commands/layers.py).

Transport is injectable (`get_json`) so tests never make a real network
call: the stdlib `urllib` default is the only production implementation,
no new dependency. `repo_accessible()` never raises -- any transport
failure (DNS, timeout, TLS, `git`/network unreachable) degrades to `None`
("could not determine" -- offline), mirroring
core/ecosystem/mirror.py's `latest_lock_sha()` / `clone_or_update_mirror()`
"never a fabricated answer" rule.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Callable, Optional

# Injectable transport: (url, token) -> HTTP status code, or None on a
# network-level failure (offline/unreachable/timeout). Kept to the minimum
# signature `repo_accessible()` needs -- callers/tests supply a fake that
# never touches the network.
GetJsonFn = Callable[..., Optional[int]]

_GITHUB_API_BASE = "https://api.github.com/repos"


def default_get_json(url: str, token: str, *, timeout: float = 10.0) -> Optional[int]:
    """
    Real transport: GET `url` with `token` as a GitHub bearer token, stdlib
    `urllib` only (no new dependency). Returns the HTTP status code on any
    response (including 4xx -- an `HTTPError` still carries a real status
    code), or `None` when the request could not complete at all (DNS
    failure, connection refused, timeout, TLS error, ...) -- i.e. "offline",
    never a fabricated status.
    """
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "cc-layers-entitlement",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        # A well-formed HTTP error response (e.g. 403/404) IS a real,
        # reachable answer -- not an offline condition.
        return exc.code
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


def repo_accessible(
    repo: str,
    token: Optional[str],
    *,
    get_json: GetJsonFn = default_get_json,
) -> Optional[bool]:
    """
    Whether `token`'s GitHub identity has access to `repo` (an
    `"owner/name"` slug): `GET https://api.github.com/repos/{repo}`.

      200          -> True  (entitled)
      403/404      -> False (not entitled -- GitHub returns 404, not 403,
                              for a private repo the token cannot see, so
                              both codes are treated identically here)
      network fail -> None  (offline / could not determine -- caller must
                              treat this as an honest unknown, never as
                              either True or False)
      any other status (5xx, unexpected 3xx, ...) -> None, same "unknown"
      treatment -- this function never guesses.

    Returns `None` immediately (no request attempted) when `repo` or
    `token` is falsy -- there is nothing to check without both.
    """
    if not repo or not token:
        return None

    url = f"{_GITHUB_API_BASE}/{repo}"
    try:
        status = get_json(url, token)
    except Exception:
        # Defense in depth: an injected/custom transport that raises
        # instead of returning None is still treated as an honest
        # "could not determine", never propagated as a crash.
        return None

    if status == 200:
        return True
    if status in (403, 404):
        return False
    return None
