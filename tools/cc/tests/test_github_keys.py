from __future__ import annotations

from typing import Any

from cc.core.ecosystem.github_keys import (
    GITHUB_USER_KEYS_URL,
    create_user_key,
    list_user_keys,
)


class RequestSpy:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self.payload = payload
        self.calls: list[tuple[str, str, dict[str, str], dict[str, str] | None]] = []

    def __call__(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, str] | None,
    ) -> tuple[int, Any]:
        self.calls.append((method, url, headers, payload))
        return self.status_code, self.payload


def test_list_user_keys_uses_fixed_endpoint_and_bearer_token() -> None:
    request = RequestSpy(200, [{"key": "ssh-ed25519 AAAA machine"}])

    result = list_user_keys("keychain-token", request_json=request)

    assert result == {"status": "ok", "keys": ["ssh-ed25519 AAAA machine"]}
    method, url, headers, payload = request.calls[0]
    assert method == "GET"
    assert url == GITHUB_USER_KEYS_URL
    assert headers["Authorization"] == "Bearer keychain-token"
    assert payload is None
    assert "keychain-token" not in repr(result)


def test_list_user_keys_classifies_permission_failures() -> None:
    for status_code in (401, 403, 404):
        result = list_user_keys(
            "keychain-token",
            request_json=RequestSpy(status_code, {"message": "denied"}),
        )
        assert result == {"status": "not-permitted", "keys": []}


def test_create_user_key_posts_expected_payload_without_returning_token() -> None:
    request = RequestSpy(201, {"id": 123})

    result = create_user_key(
        "keychain-token",
        title="workstation",
        public_key="ssh-ed25519 AAAA workstation",
        request_json=request,
    )

    assert result == {"status": "registered"}
    method, url, headers, payload = request.calls[0]
    assert method == "POST"
    assert url == GITHUB_USER_KEYS_URL
    assert headers["Authorization"] == "Bearer keychain-token"
    assert payload == {
        "title": "workstation",
        "key": "ssh-ed25519 AAAA workstation",
    }
    assert "keychain-token" not in repr(result)


def test_create_user_key_classifies_permission_and_transport_failures() -> None:
    denied = create_user_key(
        "keychain-token",
        title="workstation",
        public_key="ssh-ed25519 AAAA workstation",
        request_json=RequestSpy(403, {"message": "denied"}),
    )
    assert denied == {"status": "not-permitted"}

    def fail(
        _method: str,
        _url: str,
        _headers: dict[str, str],
        _payload: dict[str, str] | None,
    ) -> tuple[int, Any]:
        raise OSError("offline")

    failed = create_user_key(
        "keychain-token",
        title="workstation",
        public_key="ssh-ed25519 AAAA workstation",
        request_json=fail,
    )
    assert failed == {"status": "error"}
