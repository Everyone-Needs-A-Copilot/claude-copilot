"""Tests for cc.core.ecosystem.bootstrap_config -- the org's PUBLIC
bootstrap artifact fetch (Defect-2 fix: the client id never reached a
fresh Mac).

Every network call is a fake `_get_text` (never a real HTTP request) --
mirrors test_github_device.py's transport-injection precedent. The
`_no_real_home` autouse fixture additionally asserts `Path.home()` is
never resolved anywhere in the call graph -- every input here is either
an explicit `_url_template` override or the ordinary config cascade
(itself isolated from the developer's real machine by
tests/conftest.py's `_isolate_machine_config` autouse fixture).
"""

from __future__ import annotations

import urllib.error
from pathlib import Path

import pytest
from cc.core.ecosystem.bootstrap_config import (
    DEFAULT_BOOTSTRAP_URL_TEMPLATE,
    bootstrap_url,
    fetch_org_client_id,
)


@pytest.fixture(autouse=True)
def _no_real_home(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError(
            "bootstrap_config test attempted to resolve Path.home() -- "
            "inject tmp_path/_url_template instead"
        )

    monkeypatch.setattr(Path, "home", staticmethod(_boom))


def _never_call(*_args, **_kwargs):
    raise AssertionError("this transport must never be invoked")


# ---------------------------------------------------------------------------
# bootstrap_url()
# ---------------------------------------------------------------------------


def test_bootstrap_url_default_template():
    assert bootstrap_url("acme-co") == (
        "https://raw.githubusercontent.com/acme-co/copilot-bootstrap/main/bootstrap.yml"
    )


def test_bootstrap_url_custom_template_override():
    url = bootstrap_url("acme-co", _url_template="https://example.test/{org}/boot.yml")
    assert url == "https://example.test/acme-co/boot.yml"


def test_bootstrap_url_quotes_the_org_slug():
    """An org slug can never inject an extra path segment or query string
    into the resolved URL."""
    url = bootstrap_url("acme/../evil?x=1", _url_template=DEFAULT_BOOTSTRAP_URL_TEMPLATE)
    assert "/../" not in url
    assert "?x=1" not in url.split("copilot-bootstrap")[0]


# ---------------------------------------------------------------------------
# fetch_org_client_id() -- happy path
# ---------------------------------------------------------------------------


def test_fetch_org_client_id_happy_path():
    def fake_get_text(url: str) -> str:
        assert url == bootstrap_url("acme-co")
        return "org: acme-co\ngithub_app:\n  client_id: Iv1.a1b2c3d4e5f6a7b8\n"

    assert fetch_org_client_id("acme-co", _get_text=fake_get_text) == "Iv1.a1b2c3d4e5f6a7b8"


def test_fetch_org_client_id_empty_org_never_fetches():
    assert fetch_org_client_id("", _get_text=_never_call) is None


# ---------------------------------------------------------------------------
# fetch_org_client_id() -- fail-open on every failure mode
# ---------------------------------------------------------------------------


def test_fetch_org_client_id_network_error_returns_none():
    def raising_get_text(_url: str) -> str:
        raise urllib.error.URLError("no route to host")

    assert fetch_org_client_id("acme-co", _get_text=raising_get_text) is None


def test_fetch_org_client_id_malformed_yaml_returns_none():
    def fake_get_text(_url: str) -> str:
        return "org: [unclosed"

    assert fetch_org_client_id("acme-co", _get_text=fake_get_text) is None


def test_fetch_org_client_id_non_mapping_yaml_returns_none():
    def fake_get_text(_url: str) -> str:
        return "- a\n- b\n"

    assert fetch_org_client_id("acme-co", _get_text=fake_get_text) is None


def test_fetch_org_client_id_missing_github_app_returns_none():
    def fake_get_text(_url: str) -> str:
        return "org: acme-co\n"

    assert fetch_org_client_id("acme-co", _get_text=fake_get_text) is None


def test_fetch_org_client_id_malformed_github_app_returns_none():
    def fake_get_text(_url: str) -> str:
        return "org: acme-co\ngithub_app: not-a-mapping\n"

    assert fetch_org_client_id("acme-co", _get_text=fake_get_text) is None


def test_fetch_org_client_id_empty_client_id_returns_none():
    def fake_get_text(_url: str) -> str:
        return "org: acme-co\ngithub_app:\n  client_id: ''\n"

    assert fetch_org_client_id("acme-co", _get_text=fake_get_text) is None


def test_fetch_org_client_id_mismatched_org_fails_closed():
    """A bootstrap artifact naming a DIFFERENT organization is never
    trusted, even if it parses fine and carries a client id -- this is a
    trust boundary, not just a shape check."""

    def fake_get_text(_url: str) -> str:
        return "org: someone-else\ngithub_app:\n  client_id: Iv1.not-yours\n"

    assert fetch_org_client_id("acme-co", _get_text=fake_get_text) is None


def test_fetch_org_client_id_missing_org_field_fails_closed():
    def fake_get_text(_url: str) -> str:
        return "github_app:\n  client_id: Iv1.no-org-claim\n"

    assert fetch_org_client_id("acme-co", _get_text=fake_get_text) is None


# ---------------------------------------------------------------------------
# NO-SECRET-shaped guard: this module is a pure `Optional[str]` return --
# it can never surface anything from the artifact beyond the client id
# string itself, even if the artifact carries other fields.
# ---------------------------------------------------------------------------


def test_fetch_org_client_id_ignores_everything_else_in_the_artifact():
    """A bootstrap artifact is meant to carry ONLY `org` + client id
    (invariant #6), but this reader must degrade gracefully -- never raise,
    never forward -- if a misconfigured publisher put something else in
    the file too (e.g. a secret-shaped key). The return type itself
    (`Optional[str]`) makes leaking anything beyond the client id
    structurally impossible; this test pins that no extra field changes
    the resolved value."""

    def fake_get_text(_url: str) -> str:
        return (
            "org: acme-co\n"
            "github_app:\n"
            "  client_id: Iv1.a1b2c3d4e5f6a7b8\n"
            "unexpected_secret_field: ghp_shouldneverbehere\n"
        )

    result = fetch_org_client_id("acme-co", _get_text=fake_get_text)
    assert result == "Iv1.a1b2c3d4e5f6a7b8"
    assert "ghp_" not in result
