"""GitHub SSH-key API operations backed by an explicitly supplied token.

The public helpers keep the endpoint fixed and never include the token in their
results. Callers are responsible for loading the token from an approved secret
store.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib import error, request

GITHUB_USER_KEYS_URL = "https://api.github.com/user/keys"
GITHUB_API_VERSION = "2022-11-28"

JsonRequest = Callable[
    [str, str, dict[str, str], dict[str, str] | None],
    tuple[int, Any],
]


def _decode_json(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _default_json_request(
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, str] | None,
) -> tuple[int, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = request.Request(url, data=body, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=30) as response:  # noqa: S310
            return response.status, _decode_json(response.read())
    except error.HTTPError as exc:
        return exc.code, _decode_json(exc.read())


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        "User-Agent": "claude-copilot-cc",
    }


def list_user_keys(
    token: str,
    *,
    request_json: JsonRequest = _default_json_request,
) -> dict[str, Any]:
    """Return the authenticated user's SSH keys without exposing the token."""
    try:
        status_code, payload = request_json(
            "GET",
            GITHUB_USER_KEYS_URL,
            _headers(token),
            None,
        )
    except (OSError, RuntimeError, ValueError):
        return {"status": "error", "keys": []}

    if status_code in {401, 403, 404}:
        return {"status": "not-permitted", "keys": []}
    if status_code != 200 or not isinstance(payload, list):
        return {"status": "error", "keys": []}

    keys = [
        item["key"]
        for item in payload
        if isinstance(item, dict) and isinstance(item.get("key"), str)
    ]
    return {"status": "ok", "keys": keys}


def create_user_key(
    token: str,
    *,
    title: str,
    public_key: str,
    request_json: JsonRequest = _default_json_request,
) -> dict[str, str]:
    """Create an SSH key for the authenticated user."""
    try:
        status_code, _payload = request_json(
            "POST",
            GITHUB_USER_KEYS_URL,
            _headers(token),
            {"title": title, "key": public_key},
        )
    except (OSError, RuntimeError, ValueError):
        return {"status": "error"}

    if status_code in {401, 403, 404}:
        return {"status": "not-permitted"}
    if status_code == 201:
        return {"status": "registered"}
    return {"status": "error"}
