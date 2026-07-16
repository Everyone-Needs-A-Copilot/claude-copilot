"""WS-A contract test: `cc auth` (GitHub device-flow sign-in, Stream-A).

Schema source of truth: copilot-control-tower/docs/01-architecture/schemas/.
Vendored copy: tests/fixtures/schemas/auth.schema.json (same precedent as
test_doctor_contract.py / test_freshness_contract.py / test_deprovision_contract.py).

`auth_app` is invoked directly (never `cc.main.app` -- main.py wiring is
integration's job, this stream is fully self-sufficient without it).

Every GitHub HTTP call is a fake `post_json`/`get_json` (see
test_github_device.py's fakes) -- this file never makes a real network
call. The `_no_real_home` autouse fixture additionally asserts
`Path.home()` is never resolved as a fallback anywhere in the call graph
(mirrors test_deprovision_contract.py / test_freshness_contract.py's
precedent) -- every config lookup and filesystem root touched by a test
here is monkeypatched or explicitly injected.

The central invariant under test (beyond schema-shape validity) is
NO-SECRET: an `authorized` poll (via `build_auth_poll_report()`,
`execute_auth_login()`, and the CLI) must never let the OAuth token
appear anywhere in the returned report dict or its `json.dumps()`
serialization, while a keychain spy asserts the token WAS actually
delivered to `core/keychain.py`'s `set_secret()`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from cc.commands.auth import (
    auth_app,
    build_auth_initiate_report,
    build_auth_poll_report,
    build_auth_status_report,
    compute_exit_code,
    execute_auth_login,
)
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from typer.testing import CliRunner

runner = CliRunner()

_SCHEMA_DIR = Path(__file__).parent / "fixtures" / "schemas"

_SECRET_KEYS = frozenset({"access_token", "token", "refresh_token", "secret"})

_TOKEN = "gho_SUPER_SECRET_TOKEN_VALUE_DO_NOT_LEAK"  # noqa: S105 -- test fixture literal


def _load_schema(name: str) -> dict:
    return json.loads((_SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _auth_validator() -> Draft202012Validator:
    auth_schema = _load_schema("auth.schema.json")
    envelope_schema = _load_schema("_envelope.schema.json")

    registry = Registry().with_resources(
        [
            ("_envelope.schema.json", Resource.from_contents(envelope_schema)),
            (auth_schema["$id"], Resource.from_contents(auth_schema)),
        ]
    )
    return Draft202012Validator(auth_schema, registry=registry)


def _validate(payload: dict) -> None:
    validator = _auth_validator()
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)


def _assert_no_secret_shaped_keys(obj: Any, path: str = "$") -> None:
    """Recursively assert no key literally named access_token/token/
    refresh_token/secret appears anywhere in `obj` -- mirrors the
    vendored schema's `noSecretKeys` fitness invariant, asserted directly
    against real report output (not just schema-shape fixtures)."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            assert key not in _SECRET_KEYS, f"forbidden key {key!r} found at {path}"
            _assert_no_secret_shaped_keys(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            _assert_no_secret_shaped_keys(value, f"{path}[{idx}]")


@pytest.fixture(autouse=True)
def _no_real_home(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError(
            "auth contract test attempted to resolve Path.home() -- "
            "inject tmp_path instead"
        )

    monkeypatch.setattr(Path, "home", staticmethod(_boom))


class _FakePostJson:
    def __init__(self, response: Any = None, *, responses: list[Any] | None = None) -> None:
        self._responses = list(responses) if responses is not None else None
        self._single = response
        self.calls: list[tuple[str, dict, dict]] = []

    def __call__(self, url: str, data: dict, headers: dict) -> dict:
        self.calls.append((url, data, headers))
        if self._responses is not None:
            return self._responses.pop(0)
        return self._single


class _FakeGetJson:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, headers: dict) -> dict:
        self.calls.append((url, headers))
        return self.response


class _SetSecretSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, account: str, secret: str, *, service: str) -> None:
        self.calls.append((account, secret, service))


class _WriteIdentitySpy:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, identity: dict, **_kwargs: Any) -> Path:
        self.calls.append(identity)
        return Path("unused")


def _never_call(*_args, **_kwargs):
    raise AssertionError("this transport must never be invoked (offline-safe path)")


# ---------------------------------------------------------------------------
# build_auth_initiate_report() -- device-code kind
# ---------------------------------------------------------------------------


def test_initiate_report_validates_against_contract_schema():
    post_json = _FakePostJson(
        {
            "device_code": "devcode123",
            "user_code": "ABCD-1234",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        }
    )

    report = build_auth_initiate_report(
        _client_id="client-abc", _scopes="read:org repo", _post_json=post_json
    )

    _validate(report)
    assert report["kind"] == "device-code"
    assert report["user_code"] == "ABCD-1234"
    assert report["device_code"] == "devcode123"
    assert compute_exit_code(report) == 0

    url, data, _headers = post_json.calls[0]
    assert url == "https://github.com/login/device/code"
    assert data == {"client_id": "client-abc", "scope": "read:org repo"}


def test_initiate_report_no_company_app_error_envelope_validates_and_exits_2(monkeypatch):
    monkeypatch.setattr(
        "cc.commands.auth.ecosystem_config.github_client_id", lambda *_a, **_k: None
    )

    report = build_auth_initiate_report(_client_id=None, _post_json=_never_call)

    _validate(report)
    assert report["error"]["code"] == "no-company-app"
    assert "admin standup" in report["error"]["message"]
    assert compute_exit_code(report) == 2


# ---------------------------------------------------------------------------
# build_auth_poll_report() -- poll kind, all four terminal/pending statuses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "github_response,expected_status,expected_exit",
    [
        ({"error": "authorization_pending"}, "pending", 0),
        ({"error": "slow_down", "interval": 10}, "pending", 0),
        ({"error": "expired_token"}, "expired", 1),
        ({"error": "access_denied"}, "denied", 1),
    ],
)
def test_poll_report_non_authorized_statuses_validate_and_exit_correctly(
    github_response, expected_status, expected_exit
):
    post_json = _FakePostJson(github_response)

    report = build_auth_poll_report(
        "devcode123", _client_id="client-abc", _post_json=post_json
    )

    _validate(report)
    assert report == {"schema_version": "1.0", "kind": "poll", "status": expected_status}
    assert compute_exit_code(report) == expected_exit


def test_poll_report_no_company_app_error_envelope(monkeypatch):
    monkeypatch.setattr(
        "cc.commands.auth.ecosystem_config.github_client_id", lambda *_a, **_k: None
    )

    report = build_auth_poll_report("devcode123", _client_id=None, _post_json=_never_call)

    _validate(report)
    assert report["error"]["code"] == "no-company-app"
    assert compute_exit_code(report) == 2


# ---------------------------------------------------------------------------
# build_auth_poll_report() authorized -- the NO-SECRET fitness test
# ---------------------------------------------------------------------------


def test_poll_authorized_validates_persists_and_never_leaks_the_token(tmp_path):
    post_json = _FakePostJson(
        {"access_token": _TOKEN, "token_type": "bearer", "scope": "read:org repo"}
    )
    get_json = _FakeGetJson({"login": "octocat", "id": 1})
    set_secret_spy = _SetSecretSpy()
    write_identity_spy = _WriteIdentitySpy()

    report = build_auth_poll_report(
        "devcode123",
        _client_id="client-abc",
        _post_json=post_json,
        _get_json=get_json,
        _keychain_service="com.everyoneneedsacopilot.copilot.github",
        _set_secret=set_secret_spy,
        _write_identity=write_identity_spy,
        _auth_root=tmp_path,
    )

    # 1. Schema-valid `poll`/`authorized` shape.
    _validate(report)
    assert report == {"schema_version": "1.0", "kind": "poll", "status": "authorized"}
    assert compute_exit_code(report) == 0

    # 2. NO-SECRET: recursively, and in the exact bytes that would be
    #    emitted on `--json` output.
    _assert_no_secret_shaped_keys(report)
    serialized = json.dumps(report)
    assert _TOKEN not in serialized
    assert "access_token" not in serialized

    # 3. The token WAS actually delivered to the keychain (once, for the
    #    right account/service) -- proving persistence happened, not that
    #    it was silently dropped.
    assert set_secret_spy.calls == [
        ("octocat", _TOKEN, "com.everyoneneedsacopilot.copilot.github")
    ]

    # 4. The non-secret identity pointer recorded login + GRANTED scope
    #    (from GitHub's token response, not a re-resolved config default)
    #    -- and, redundantly, itself carries no token-shaped key.
    assert len(write_identity_spy.calls) == 1
    identity = write_identity_spy.calls[0]
    assert identity["login"] == "octocat"
    assert identity["scopes"] == "read:org repo"
    assert "obtained_at" in identity
    _assert_no_secret_shaped_keys(identity)
    assert _TOKEN not in json.dumps(identity)


def test_poll_authorized_fetches_identity_using_bearer_token(tmp_path):
    post_json = _FakePostJson({"access_token": _TOKEN, "scope": "read:org repo"})
    get_json = _FakeGetJson({"login": "octocat"})

    build_auth_poll_report(
        "devcode123",
        _client_id="client-abc",
        _post_json=post_json,
        _get_json=get_json,
        _keychain_service="svc",
        _set_secret=_SetSecretSpy(),
        _write_identity=_WriteIdentitySpy(),
        _auth_root=tmp_path,
    )

    assert len(get_json.calls) == 1
    url, headers = get_json.calls[0]
    assert url == "https://api.github.com/user"
    assert headers["Authorization"] == f"Bearer {_TOKEN}"


# ---------------------------------------------------------------------------
# build_auth_status_report() -- offline-safe
# ---------------------------------------------------------------------------


def test_status_report_signed_out_when_no_identity_pointer():
    report = build_auth_status_report(_identity={})

    _validate(report)
    assert report == {"schema_version": "1.0", "kind": "status", "status": "signed-out"}
    assert compute_exit_code(report) == 0


def test_status_report_signed_out_when_identity_present_but_keychain_absent():
    """A stale/partial identity pointer with no matching keychain entry is
    still honestly reported as signed-out, never a false authorized."""
    report = build_auth_status_report(
        _identity={"login": "octocat", "scopes": "read:org repo"},
        _keychain_present=False,
    )

    _validate(report)
    assert report["status"] == "signed-out"


def test_status_report_authorized_when_identity_and_keychain_both_present():
    report = build_auth_status_report(
        _identity={
            "login": "octocat",
            "scopes": "read:org repo",
            "obtained_at": "2026-07-16T00:00:00Z",
        },
        _keychain_present=True,
    )

    _validate(report)
    assert report == {
        "schema_version": "1.0",
        "kind": "status",
        "status": "authorized",
        "identity": {"login": "octocat"},
        "scope": "read:org repo",
    }
    assert compute_exit_code(report) == 0


def test_status_report_never_makes_a_network_call(tmp_path):
    """Offline-safe: reads only the identity pointer (injected `_auth_root`,
    a tmp_path -- never Path.home()) + a keychain presence spy. No
    post_json/get_json parameter exists on this function at all; this
    test additionally pins that the identity pointer itself is read from
    the injected root, not a real file."""
    from cc.core import authstore

    authstore.write_identity({"login": "octocat", "scopes": "repo"}, _root=tmp_path)

    report = build_auth_status_report(_auth_root=tmp_path, _keychain_present=True)

    _validate(report)
    assert report["status"] == "authorized"
    assert report["identity"]["login"] == "octocat"


# ---------------------------------------------------------------------------
# execute_auth_login() -- initiate -> poll-until-terminal convenience loop
# ---------------------------------------------------------------------------


def test_execute_auth_login_polls_until_authorized_honoring_interval(tmp_path):
    post_json = _FakePostJson(
        responses=[
            # device-code request
            {
                "device_code": "devcode123",
                "user_code": "ABCD-1234",
                "verification_uri": "https://github.com/login/device",
                "expires_in": 900,
                "interval": 5,
            },
            # poll 1: pending
            {"error": "authorization_pending"},
            # poll 2: slow_down -- interval bumped to 10
            {"error": "slow_down", "interval": 10},
            # poll 3: authorized
            {"access_token": _TOKEN, "scope": "read:org repo"},
        ]
    )
    get_json = _FakeGetJson({"login": "octocat"})
    set_secret_spy = _SetSecretSpy()
    write_identity_spy = _WriteIdentitySpy()

    sleep_calls: list[float] = []

    report, exit_code = execute_auth_login(
        _client_id="client-abc",
        _scopes="read:org repo",
        _post_json=post_json,
        _get_json=get_json,
        _keychain_service="svc",
        _set_secret=set_secret_spy,
        _write_identity=write_identity_spy,
        _auth_root=tmp_path,
        _sleep=sleep_calls.append,
    )

    _validate(report)
    assert report == {"schema_version": "1.0", "kind": "poll", "status": "authorized"}
    assert exit_code == 0

    # Honored the initial interval (5) for the first two polls, then the
    # slow_down-updated interval (10) for the third.
    assert sleep_calls == [5, 5, 10]

    # NO-SECRET, asserted again at this call site (independent of the
    # build_auth_poll_report()-level test above).
    _assert_no_secret_shaped_keys(report)
    assert _TOKEN not in json.dumps(report)
    assert set_secret_spy.calls == [("octocat", _TOKEN, set_secret_spy.calls[0][2])]


def test_execute_auth_login_stops_on_expired():
    post_json = _FakePostJson(
        responses=[
            {
                "device_code": "devcode123",
                "user_code": "ABCD-1234",
                "verification_uri": "https://github.com/login/device",
                "expires_in": 900,
                "interval": 5,
            },
            {"error": "expired_token"},
        ]
    )

    report, exit_code = execute_auth_login(
        _client_id="client-abc",
        _scopes="read:org repo",
        _post_json=post_json,
        _sleep=lambda _seconds: None,
    )

    _validate(report)
    assert report["status"] == "expired"
    assert exit_code == 1


def test_execute_auth_login_propagates_no_company_app(monkeypatch):
    monkeypatch.setattr(
        "cc.commands.auth.ecosystem_config.github_client_id", lambda *_a, **_k: None
    )

    report, exit_code = execute_auth_login(
        _client_id=None, _post_json=_never_call, _sleep=lambda _seconds: None
    )

    assert report["error"]["code"] == "no-company-app"
    assert exit_code == 2


def test_execute_auth_login_times_out_after_max_polls():
    post_json = _FakePostJson(
        {
            "device_code": "devcode123",
            "user_code": "ABCD-1234",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 1,
        },
    )
    # Every poll after initiation returns pending forever.
    always_pending_post_json = _FakePostJson(
        responses=[post_json._single] + [{"error": "authorization_pending"}] * 5
    )

    report, exit_code = execute_auth_login(
        _client_id="client-abc",
        _scopes="read:org repo",
        _post_json=always_pending_post_json,
        _sleep=lambda _seconds: None,
        _max_polls=5,
    )

    assert report["error"]["code"] == "poll-timeout"
    assert exit_code == 2


# ---------------------------------------------------------------------------
# CLI surface (auth_app invoked directly -- never cc.main.app; wiring
# main.py into cc.main.app is integration's job, see commands/auth.py's
# module docstring)
# ---------------------------------------------------------------------------


def _patch_cli_transport(
    monkeypatch,
    *,
    client_id="client-abc",
    scopes="read:org repo",
    keychain_service="svc",
    request_device_code=None,
    poll_token=None,
    fetch_identity=None,
    set_secret=None,
    write_identity=None,
    read_identity=None,
    get_secret=None,
) -> None:
    monkeypatch.setattr(
        "cc.commands.auth.resolve_key",
        lambda key, **_kw: {
            "github_app.client_id": client_id,
            "auth.scopes": scopes,
            "auth.keychain_service": keychain_service,
        }.get(key),
    )
    if request_device_code is not None:
        monkeypatch.setattr("cc.commands.auth.github_device.request_device_code", request_device_code)
    if poll_token is not None:
        monkeypatch.setattr("cc.commands.auth.github_device.poll_token", poll_token)
    if fetch_identity is not None:
        monkeypatch.setattr("cc.commands.auth.github_device.fetch_identity", fetch_identity)
    if set_secret is not None:
        monkeypatch.setattr("cc.commands.auth.keychain.set_secret", set_secret)
    if get_secret is not None:
        monkeypatch.setattr("cc.commands.auth.keychain.get_secret", get_secret)
    if write_identity is not None:
        monkeypatch.setattr("cc.commands.auth.authstore.write_identity", write_identity)
    if read_identity is not None:
        monkeypatch.setattr("cc.commands.auth.authstore.read_identity", read_identity)


def test_cli_login_initiate_json_validates(monkeypatch):
    def fake_request_device_code(client_id, scopes, **_kwargs):
        assert client_id == "client-abc"
        assert scopes == "read:org repo"
        return {
            "device_code": "devcode123",
            "user_code": "ABCD-1234",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        }

    _patch_cli_transport(monkeypatch, request_device_code=fake_request_device_code)

    result = runner.invoke(auth_app, ["login", "--json"])
    payload = json.loads(result.output)

    _validate(payload)
    assert payload["kind"] == "device-code"
    assert result.exit_code == 0


def test_cli_bare_auth_behaves_like_login_initiate(monkeypatch):
    """Bare `cc auth --json` (no subcommand) == `cc auth login --json`."""

    def fake_request_device_code(client_id, scopes, **_kwargs):
        return {
            "device_code": "devcode123",
            "user_code": "ABCD-1234",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        }

    _patch_cli_transport(monkeypatch, request_device_code=fake_request_device_code)

    result = runner.invoke(auth_app, ["--json"])
    payload = json.loads(result.output)

    _validate(payload)
    assert payload["kind"] == "device-code"
    assert result.exit_code == 0


def test_cli_login_no_company_app_json_exits_2(monkeypatch):
    _patch_cli_transport(monkeypatch, client_id=None)
    monkeypatch.setattr(
        "cc.commands.auth.ecosystem_config.github_client_id", lambda *_a, **_k: None
    )

    result = runner.invoke(auth_app, ["login", "--json"])
    payload = json.loads(result.output)

    _validate(payload)
    assert payload["error"]["code"] == "no-company-app"
    assert result.exit_code == 2


def test_cli_login_poll_without_device_code_is_a_missing_argument_error():
    result = runner.invoke(auth_app, ["login", "--poll", "--json"])
    payload = json.loads(result.output)

    assert payload["error"]["code"] == "missing-argument"
    assert result.exit_code == 2


def test_cli_login_poll_authorized_never_leaks_token_and_exits_0(monkeypatch):
    def fake_poll_token(client_id, device_code, **_kwargs):
        assert client_id == "client-abc"
        assert device_code == "devcode123"
        return {"status": "authorized", "access_token": _TOKEN, "scope": "read:org repo"}

    def fake_fetch_identity(token, **_kwargs):
        assert token == _TOKEN
        return {"login": "octocat"}

    set_secret_spy = _SetSecretSpy()
    write_identity_spy = _WriteIdentitySpy()

    _patch_cli_transport(
        monkeypatch,
        poll_token=fake_poll_token,
        fetch_identity=fake_fetch_identity,
        set_secret=set_secret_spy,
        write_identity=write_identity_spy,
    )

    result = runner.invoke(
        auth_app, ["login", "--poll", "--device-code", "devcode123", "--json"]
    )
    payload = json.loads(result.output)

    _validate(payload)
    assert payload == {"schema_version": "1.0", "kind": "poll", "status": "authorized"}
    assert result.exit_code == 0

    _assert_no_secret_shaped_keys(payload)
    assert _TOKEN not in result.output

    assert set_secret_spy.calls == [("octocat", _TOKEN, "svc")]
    assert write_identity_spy.calls == [
        {"login": "octocat", "scopes": "read:org repo", "obtained_at": write_identity_spy.calls[0]["obtained_at"]}
    ]


def test_cli_login_poll_expired_exits_1(monkeypatch):
    _patch_cli_transport(
        monkeypatch, poll_token=lambda *_a, **_k: {"status": "expired"}
    )

    result = runner.invoke(
        auth_app, ["login", "--poll", "--device-code", "devcode123", "--json"]
    )
    payload = json.loads(result.output)

    _validate(payload)
    assert payload["status"] == "expired"
    assert result.exit_code == 1


def test_cli_status_signed_out_by_default_never_touches_network(monkeypatch):
    _patch_cli_transport(
        monkeypatch,
        read_identity=lambda **_k: {},
        get_secret=_never_call,
    )

    result = runner.invoke(auth_app, ["status", "--json"])
    payload = json.loads(result.output)

    _validate(payload)
    assert payload == {"schema_version": "1.0", "kind": "status", "status": "signed-out"}
    assert result.exit_code == 0


def test_cli_status_authorized_when_signed_in(monkeypatch):
    _patch_cli_transport(
        monkeypatch,
        read_identity=lambda **_k: {"login": "octocat", "scopes": "read:org repo"},
        get_secret=lambda *_a, **_k: "some-stored-token",
    )

    result = runner.invoke(auth_app, ["status", "--json"])
    payload = json.loads(result.output)

    _validate(payload)
    assert payload["status"] == "authorized"
    assert payload["identity"]["login"] == "octocat"
    # NO-SECRET even though get_secret() returned a token-shaped value --
    # build_auth_status_report() only ever forwards a presence boolean.
    assert "some-stored-token" not in result.output
    _assert_no_secret_shaped_keys(payload)


def test_cli_status_human_readable_rendering_smoke(monkeypatch):
    """Non-JSON path renders via Rich without raising."""
    _patch_cli_transport(monkeypatch, read_identity=lambda **_k: {}, get_secret=_never_call)

    result = runner.invoke(auth_app, ["status"])
    assert result.exit_code == 0
    assert "signed out" in result.output.lower()
