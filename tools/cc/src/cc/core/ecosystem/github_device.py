"""Pure GitHub OAuth Device Flow protocol -- transport-injected, no network
in tests (WS-A Stream-A: `cc auth` device-flow sign-in seam).

This module knows nothing about `cc`'s own config/keychain/authstore --
it is a thin, pure mapping from GitHub's device-flow HTTP API onto small
result dicts. `commands/auth.py` is the only caller that wires this to
`core/config.py` (client id/scopes), `core/keychain.py` (token storage),
and `core/authstore.py` (the non-secret identity pointer).

Every network-performing function takes an injectable transport callable
(`post_json`/`get_json`, mirroring `core/keychain.py`'s `_run` and
`core/ecosystem/mirror.py`'s `_run_git()` convention): tests substitute a
fake and this module never makes a real network call in the test suite.
The default transport is a small stdlib `urllib.request` JSON helper --
`httpx` is deliberately NOT a new dependency of this module; if a richer
HTTP client is ever wanted, it can be wired in as an alternate
`post_json`/`get_json` implementation without changing this module's
public surface.

Endpoints (GitHub's OAuth Device Flow -- see GitHub's own docs, "Device
flow" grant type):
  - POST https://github.com/login/device/code       -- request_device_code()
  - POST https://github.com/login/oauth/access_token -- poll_token()
  - GET  https://api.github.com/user                 -- fetch_identity()

NO-SECRET discipline: `poll_token()`'s return value carries the OAuth
access token INTERNALLY (under the `access_token` key) ONLY on
`status: "authorized"` -- it is the caller's job (`commands/auth.py`) to
consume that value exactly once (store it in the OS keychain) and never
let it leak into a `--json` contract payload. This module itself never
logs, prints, or persists a token.
"""

from __future__ import annotations

import json as _json
import urllib.parse
import urllib.request
from typing import Any, Callable

DEVICE_CODE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"

# Injectable transport signatures.
#   post_json(url, data, headers) -> parsed JSON response body (dict)
#   get_json(url, headers)        -> parsed JSON response body (dict)
PostJsonFn = Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]]
GetJsonFn = Callable[[str, dict[str, str]], dict[str, Any]]


def _default_post_json(url: str, data: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    """Stdlib `urllib.request`-based default POST transport (form-encoded
    body, JSON response) -- only ever exercised outside the test suite."""
    body = urllib.parse.urlencode(data).encode("utf-8")
    full_headers = {"Content-Type": "application/x-www-form-urlencoded", **headers}
    request = urllib.request.Request(url, data=body, headers=full_headers, method="POST")
    with urllib.request.urlopen(request) as response:  # noqa: S310 -- fixed https URLs above
        return _json.loads(response.read().decode("utf-8"))


def _default_get_json(url: str, headers: dict[str, str]) -> dict[str, Any]:
    """Stdlib `urllib.request`-based default GET transport (JSON response)
    -- only ever exercised outside the test suite."""
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request) as response:  # noqa: S310 -- fixed https URL above
        return _json.loads(response.read().decode("utf-8"))


def request_device_code(
    client_id: str,
    scopes: str,
    *,
    post_json: PostJsonFn = _default_post_json,
) -> dict[str, Any]:
    """
    Initiate a GitHub OAuth Device Flow authorization request.

    POSTs `{client_id, scope}` to `DEVICE_CODE_URL` with
    `Accept: application/json`. Returns
    `{device_code, user_code, verification_uri, expires_in, interval}`.

    `device_code` is a short-lived flow handle the caller polls with --
    NOT a credential by itself (GitHub also requires the originating
    `client_id` on every poll, and it expires in `expires_in` seconds).
    It is distinct from an OAuth access token, which this function never
    sees or returns.
    """
    response = post_json(
        DEVICE_CODE_URL,
        {"client_id": client_id, "scope": scopes},
        {"Accept": "application/json"},
    )
    return {
        "device_code": response["device_code"],
        "user_code": response["user_code"],
        "verification_uri": response.get("verification_uri")
        or response.get("verification_uri_complete"),
        "expires_in": response["expires_in"],
        "interval": response["interval"],
    }


def poll_token(
    client_id: str,
    device_code: str,
    *,
    post_json: PostJsonFn = _default_post_json,
) -> dict[str, Any]:
    """
    One poll step against `TOKEN_URL` using the device-flow grant type.

    Maps GitHub's response onto a small, caller-facing status dict:
      - `authorization_pending` -> `{"status": "pending"}`
      - `slow_down`             -> `{"status": "pending", "interval": <int>}`
                                    (GitHub is asking the caller to poll
                                    less often, not denying the request --
                                    the new interval is carried so the
                                    caller can honor it)
      - `expired_token`         -> `{"status": "expired"}`
      - `access_denied`         -> `{"status": "denied"}`
      - success                 -> `{"status": "authorized",
                                      "access_token": <str>,
                                      "token_type": <str|None>,
                                      "scope": <str|None>}`

    The access token is carried INTERNALLY, only in the `authorized`
    case, and only in this function's Python return value -- callers
    (`commands/auth.py`) must consume it exactly once (store it in the
    OS keychain) and never forward it into a `--json` contract payload.
    """
    response = post_json(
        TOKEN_URL,
        {
            "client_id": client_id,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        },
        {"Accept": "application/json"},
    )

    error = response.get("error")
    if error == "authorization_pending":
        return {"status": "pending"}
    if error == "slow_down":
        result: dict[str, Any] = {"status": "pending"}
        if "interval" in response:
            result["interval"] = response["interval"]
        return result
    if error == "expired_token":
        return {"status": "expired"}
    if error == "access_denied":
        return {"status": "denied"}
    if error:
        # An error code GitHub's device-flow docs don't otherwise define
        # (e.g. `incorrect_client_credentials`, `unsupported_grant_type`).
        # Treated as a terminal denial rather than an infinite pending
        # loop -- fail-closed, mirrors this codebase's general posture on
        # unrecognized states.
        return {"status": "denied", "error": error}

    access_token = response.get("access_token")
    if not access_token:
        # Defensive: neither an error nor a token -- do not fabricate a
        # terminal state for a response shape GitHub should never send.
        return {"status": "pending"}

    return {
        "status": "authorized",
        "access_token": access_token,
        "token_type": response.get("token_type"),
        "scope": response.get("scope"),
    }


def fetch_identity(token: str, *, get_json: GetJsonFn = _default_get_json) -> dict[str, Any]:
    """
    GET `USER_URL` using `token` as a Bearer credential. Returns GitHub's
    user object (`{login, id, ...}`) verbatim.

    `token` is passed only as an `Authorization` header value on this one
    request -- this function never returns, logs, or otherwise persists
    it.
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
    }
    return get_json(USER_URL, headers)


__all__ = [
    "DEVICE_CODE_URL",
    "TOKEN_URL",
    "USER_URL",
    "PostJsonFn",
    "GetJsonFn",
    "request_device_code",
    "poll_token",
    "fetch_identity",
]
