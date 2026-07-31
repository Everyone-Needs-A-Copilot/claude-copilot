"""Tests for cc.core.ecosystem.github_device -- the pure GitHub OAuth
Device Flow protocol mapping.

`post_json`/`get_json` are ALWAYS injected fakes here, so this module
never makes a real network call in the test suite (see the module
docstring's transport-injection convention, mirrored from
core/keychain.py's `_run`).
"""

from __future__ import annotations

from typing import Any

import pytest
from cc.core.ecosystem.github_device import (
    fetch_identity,
    poll_token,
    request_device_code,
)


class _RecordingPostJson:
    """Fake `post_json` that records every call and returns a pre-scripted
    response (or the next in a queue of responses, for multi-poll tests)."""

    def __init__(self, response: Any = None, *, responses: list[Any] | None = None) -> None:
        self._responses = list(responses) if responses is not None else None
        self._single = response
        self.calls: list[tuple[str, dict, dict]] = []

    def __call__(self, url: str, data: dict, headers: dict) -> dict:
        self.calls.append((url, data, headers))
        if self._responses is not None:
            return self._responses.pop(0)
        return self._single


class _RecordingGetJson:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, headers: dict) -> dict:
        self.calls.append((url, headers))
        return self.response


# ---------------------------------------------------------------------------
# request_device_code()
# ---------------------------------------------------------------------------


def test_request_device_code_posts_client_id_and_scope():
    post_json = _RecordingPostJson(
        {
            "device_code": "devcode123",
            "user_code": "ABCD-1234",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        }
    )

    result = request_device_code("client-abc", "read:org repo", post_json=post_json)

    assert len(post_json.calls) == 1
    url, data, headers = post_json.calls[0]
    assert url == "https://github.com/login/device/code"
    assert data == {"client_id": "client-abc", "scope": "read:org repo"}
    assert headers["Accept"] == "application/json"

    assert result == {
        "device_code": "devcode123",
        "user_code": "ABCD-1234",
        "verification_uri": "https://github.com/login/device",
        "expires_in": 900,
        "interval": 5,
    }


def test_request_device_code_never_returns_a_token_shaped_field():
    post_json = _RecordingPostJson(
        {
            "device_code": "devcode123",
            "user_code": "ABCD-1234",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        }
    )
    result = request_device_code("client-abc", "read:org repo", post_json=post_json)
    assert "access_token" not in result
    assert "token" not in result


# ---------------------------------------------------------------------------
# poll_token() -- status mapping
# ---------------------------------------------------------------------------


def test_poll_token_authorization_pending_maps_to_pending():
    post_json = _RecordingPostJson({"error": "authorization_pending"})
    result = poll_token("client-abc", "devcode123", post_json=post_json)
    assert result == {"status": "pending"}

    url, data, headers = post_json.calls[0]
    assert url == "https://github.com/login/oauth/access_token"
    assert data == {
        "client_id": "client-abc",
        "device_code": "devcode123",
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }
    assert headers["Accept"] == "application/json"


def test_poll_token_slow_down_maps_to_pending_and_carries_new_interval():
    post_json = _RecordingPostJson({"error": "slow_down", "interval": 10})
    result = poll_token("client-abc", "devcode123", post_json=post_json)
    assert result == {"status": "pending", "interval": 10}


def test_poll_token_slow_down_without_interval_field_still_pending():
    post_json = _RecordingPostJson({"error": "slow_down"})
    result = poll_token("client-abc", "devcode123", post_json=post_json)
    assert result == {"status": "pending"}


def test_poll_token_expired_token_maps_to_expired():
    post_json = _RecordingPostJson({"error": "expired_token"})
    result = poll_token("client-abc", "devcode123", post_json=post_json)
    assert result == {"status": "expired"}


def test_poll_token_access_denied_maps_to_denied():
    post_json = _RecordingPostJson({"error": "access_denied"})
    result = poll_token("client-abc", "devcode123", post_json=post_json)
    assert result == {"status": "denied"}


def test_poll_token_unrecognized_error_treated_as_denied_fail_closed():
    post_json = _RecordingPostJson({"error": "incorrect_client_credentials"})
    result = poll_token("client-abc", "devcode123", post_json=post_json)
    assert result["status"] == "denied"


def test_poll_token_success_maps_to_authorized_and_carries_token_internally():
    post_json = _RecordingPostJson(
        {"access_token": "gho_supersecret", "token_type": "bearer", "scope": "read:org repo"}
    )
    result = poll_token("client-abc", "devcode123", post_json=post_json)
    assert result["status"] == "authorized"
    assert result["access_token"] == "gho_supersecret"
    assert result["token_type"] == "bearer"
    assert result["scope"] == "read:org repo"


def test_poll_token_response_with_neither_error_nor_token_defensively_pending():
    post_json = _RecordingPostJson({})
    result = poll_token("client-abc", "devcode123", post_json=post_json)
    assert result == {"status": "pending"}


def test_poll_token_realistic_pending_then_authorized_sequence():
    post_json = _RecordingPostJson(
        responses=[
            {"error": "authorization_pending"},
            {"error": "authorization_pending"},
            {"access_token": "gho_final", "token_type": "bearer", "scope": "read:org repo"},
        ]
    )

    first = poll_token("client-abc", "devcode123", post_json=post_json)
    second = poll_token("client-abc", "devcode123", post_json=post_json)
    third = poll_token("client-abc", "devcode123", post_json=post_json)

    assert first == {"status": "pending"}
    assert second == {"status": "pending"}
    assert third["status"] == "authorized"
    assert third["access_token"] == "gho_final"
    assert len(post_json.calls) == 3


# ---------------------------------------------------------------------------
# fetch_identity()
# ---------------------------------------------------------------------------


def test_fetch_identity_gets_user_with_bearer_token():
    get_json = _RecordingGetJson({"login": "octocat", "id": 1})
    result = fetch_identity("gho_supersecret", get_json=get_json)

    assert result == {"login": "octocat", "id": 1}
    assert len(get_json.calls) == 1
    url, headers = get_json.calls[0]
    assert url == "https://api.github.com/user"
    assert headers["Authorization"] == "Bearer gho_supersecret"
    assert headers["Accept"] == "application/vnd.github+json"


def test_fetch_identity_never_echoes_the_token_in_its_return_value():
    get_json = _RecordingGetJson({"login": "octocat"})
    result = fetch_identity("gho_supersecret", get_json=get_json)
    assert "gho_supersecret" not in repr(result)
    assert "access_token" not in result
    assert "token" not in result
