"""Tests for cc.core.ecosystem.bootstrap_config -- the org's PUBLIC
bootstrap artifact fetch (Defect-2 fix: the client id never reached a
fresh Mac) plus its D5 hardening (scheme/host pin, response size cap,
machine-config-only override) and the Bug 1/2/3 fixes (case-insensitive org
match, the `org_exists_on_github()` existence probe, and the
`network-unavailable` vs `invalid-artifact` failure-reason split).

Every network call is a fake `_get_text`/`_get_status` (never a real HTTP
request) -- mirrors test_github_device.py's transport-injection precedent.
The `_no_real_home` autouse fixture additionally asserts `Path.home()` is
never resolved anywhere in the call graph -- every input here is either an
explicit `_url_template` override or the ordinary config cascade (itself
isolated from the developer's real machine by tests/conftest.py's
`_isolate_machine_config` autouse fixture).
"""

from __future__ import annotations

import urllib.error
from pathlib import Path

import pytest
from cc.core.ecosystem.bootstrap_config import (
    DEFAULT_BOOTSTRAP_URL_TEMPLATE,
    bootstrap_url,
    fetch_org_client_id,
    org_exists_on_github,
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


def test_bootstrap_url_template_honors_machine_config_override(monkeypatch):
    """D5: `github_app.bootstrap_url_template` IS honored from MACHINE
    config when no explicit `_url_template` override is passed."""
    monkeypatch.setattr(
        "cc.core.ecosystem.bootstrap_config.resolve_key",
        lambda key, **kw: (
            "https://example.test/{org}/boot.yml"
            if key == "github_app.bootstrap_url_template" and kw.get("scope") == "machine"
            else None
        ),
    )
    assert bootstrap_url("acme-co") == "https://example.test/acme-co/boot.yml"


def test_bootstrap_url_template_never_reads_project_scope(monkeypatch):
    """D5: a checked-out repo's PROJECT-tier `.claude/cc/config.json` must
    never be able to redirect the bootstrap fetch -- only machine config is
    consulted, so `bootstrap_url()` calls `resolve_key(...,
    scope="machine")`, never the effective (project-cascading) resolution.
    This test pins the CALL SHAPE: any resolution that isn't explicitly
    machine-scoped raises, proving `bootstrap_url()` can never accidentally
    fall back to project/env resolution."""

    def scope_gated_resolve_key(key, *, scope=None, **_kw):
        if scope != "machine":
            raise AssertionError(
                f"bootstrap_url_template resolved with scope={scope!r}, "
                "not 'machine' -- a project-tier config value could redirect "
                "the pre-credential bootstrap fetch"
            )
        return None

    monkeypatch.setattr(
        "cc.core.ecosystem.bootstrap_config.resolve_key", scope_gated_resolve_key
    )
    assert bootstrap_url("acme-co") == bootstrap_url(
        "acme-co", _url_template=DEFAULT_BOOTSTRAP_URL_TEMPLATE
    )


# ---------------------------------------------------------------------------
# fetch_org_client_id() -- happy path
# ---------------------------------------------------------------------------


def test_fetch_org_client_id_happy_path():
    def fake_get_text(url: str) -> str:
        assert url == bootstrap_url("acme-co")
        return "org: acme-co\ngithub_app:\n  client_id: Iv1.a1b2c3d4e5f6a7b8\n"

    assert fetch_org_client_id("acme-co", _get_text=fake_get_text) == (
        "Iv1.a1b2c3d4e5f6a7b8",
        None,
    )


def test_fetch_org_client_id_empty_org_never_fetches():
    assert fetch_org_client_id("", _get_text=_never_call) == (None, "invalid-artifact")


def test_fetch_org_client_id_org_match_is_case_insensitive():
    """Bug 1: GitHub org names are case-insensitive and unique by fold. An
    artifact published as `Acme-Co` must still match a caller asking about
    `acme-co` (or any other casing) -- the value sent to GitHub afterward is
    still whatever the artifact published, verbatim (this test's `org`
    argument is only the comparison key, never re-cased in the result)."""

    def fake_get_text(_url: str) -> str:
        return "org: Acme-Co\ngithub_app:\n  client_id: Iv1.a1b2c3d4e5f6a7b8\n"

    assert fetch_org_client_id("acme-co", _get_text=fake_get_text) == (
        "Iv1.a1b2c3d4e5f6a7b8",
        None,
    )
    assert fetch_org_client_id("ACME-CO", _get_text=fake_get_text) == (
        "Iv1.a1b2c3d4e5f6a7b8",
        None,
    )


# ---------------------------------------------------------------------------
# fetch_org_client_id() -- fail-open on every failure mode, but distinguish
# network-unavailable (Bug 3) from every other ("invalid-artifact") case
# ---------------------------------------------------------------------------


def test_fetch_org_client_id_network_error_is_network_unavailable():
    """Bug 3: a genuine transport failure (never even reached a server) is
    its own distinct reason -- an offline Mac must not be told its
    organization hasn't finished setting up sign-in."""

    def raising_get_text(_url: str) -> str:
        raise urllib.error.URLError("no route to host")

    assert fetch_org_client_id("acme-co", _get_text=raising_get_text) == (
        None,
        "network-unavailable",
    )


def test_fetch_org_client_id_timeout_is_network_unavailable():
    def raising_get_text(_url: str) -> str:
        raise TimeoutError("timed out")

    assert fetch_org_client_id("acme-co", _get_text=raising_get_text) == (
        None,
        "network-unavailable",
    )


def test_fetch_org_client_id_http_error_is_invalid_artifact_not_network_unavailable():
    """An HTTP error response (e.g. 404 -- artifact not published yet) means
    a server WAS reached -- definitely online, so this is `invalid-artifact`,
    never `network-unavailable`."""

    def raising_get_text(_url: str) -> str:
        raise urllib.error.HTTPError(_url, 404, "Not Found", {}, None)

    assert fetch_org_client_id("acme-co", _get_text=raising_get_text) == (
        None,
        "invalid-artifact",
    )


def test_fetch_org_client_id_oversized_response_is_invalid_artifact():
    """D5: a response over the size cap is rejected by the DEFAULT
    transport (`_default_get_text`), not by `fetch_org_client_id` itself --
    exercised here through the real default transport against a fake
    `urlopen`, distinct from every other test in this file which injects
    `_get_text` directly."""
    import io
    from unittest.mock import patch

    from cc.core.ecosystem import bootstrap_config as bc

    oversized = b"x" * (bc._MAX_RESPONSE_BYTES + 1)

    class _FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    with patch.object(bc.urllib.request, "urlopen", return_value=_FakeResponse(oversized)):
        assert fetch_org_client_id("acme-co") == (None, "invalid-artifact")


def test_fetch_org_client_id_malformed_yaml_returns_invalid_artifact():
    def fake_get_text(_url: str) -> str:
        return "org: [unclosed"

    assert fetch_org_client_id("acme-co", _get_text=fake_get_text) == (
        None,
        "invalid-artifact",
    )


def test_fetch_org_client_id_non_mapping_yaml_returns_invalid_artifact():
    def fake_get_text(_url: str) -> str:
        return "- a\n- b\n"

    assert fetch_org_client_id("acme-co", _get_text=fake_get_text) == (
        None,
        "invalid-artifact",
    )


def test_fetch_org_client_id_missing_github_app_returns_invalid_artifact():
    def fake_get_text(_url: str) -> str:
        return "org: acme-co\n"

    assert fetch_org_client_id("acme-co", _get_text=fake_get_text) == (
        None,
        "invalid-artifact",
    )


def test_fetch_org_client_id_malformed_github_app_returns_invalid_artifact():
    def fake_get_text(_url: str) -> str:
        return "org: acme-co\ngithub_app: not-a-mapping\n"

    assert fetch_org_client_id("acme-co", _get_text=fake_get_text) == (
        None,
        "invalid-artifact",
    )


def test_fetch_org_client_id_empty_client_id_returns_invalid_artifact():
    def fake_get_text(_url: str) -> str:
        return "org: acme-co\ngithub_app:\n  client_id: ''\n"

    assert fetch_org_client_id("acme-co", _get_text=fake_get_text) == (
        None,
        "invalid-artifact",
    )


def test_fetch_org_client_id_mismatched_org_fails_closed():
    """A bootstrap artifact naming a DIFFERENT organization is never
    trusted, even if it parses fine and carries a client id -- this is a
    trust boundary, not just a shape check."""

    def fake_get_text(_url: str) -> str:
        return "org: someone-else\ngithub_app:\n  client_id: Iv1.not-yours\n"

    assert fetch_org_client_id("acme-co", _get_text=fake_get_text) == (
        None,
        "invalid-artifact",
    )


def test_fetch_org_client_id_missing_org_field_fails_closed():
    def fake_get_text(_url: str) -> str:
        return "github_app:\n  client_id: Iv1.no-org-claim\n"

    assert fetch_org_client_id("acme-co", _get_text=fake_get_text) == (
        None,
        "invalid-artifact",
    )


# ---------------------------------------------------------------------------
# D5: scheme + host pin -- applied to every resolved URL, default or
# overridden, BEFORE ever fetching it.
# ---------------------------------------------------------------------------


def test_fetch_org_client_id_rejects_http_scheme_override():
    url_template = "http://raw.githubusercontent.com/{org}/copilot-bootstrap/main/bootstrap.yml"
    assert fetch_org_client_id(
        "acme-co", _get_text=_never_call, _url_template=url_template
    ) == (None, "invalid-artifact")


def test_fetch_org_client_id_rejects_untrusted_host_override():
    url_template = "https://evil.example.com/{org}/bootstrap.yml"
    assert fetch_org_client_id(
        "acme-co", _get_text=_never_call, _url_template=url_template
    ) == (None, "invalid-artifact")


def test_fetch_org_client_id_rejects_userinfo_smuggling_the_real_host():
    """A URL like `https://raw.githubusercontent.com@evil.example.com/...`
    must resolve `hostname` to `evil.example.com`, not the userinfo-prefixed
    string -- `urllib.parse.urlsplit` already does this correctly, this
    test just pins that the pin actually uses `.hostname`, not raw string
    matching against `.netloc`."""
    url_template = "https://raw.githubusercontent.com@evil.example.com/{org}/bootstrap.yml"
    assert fetch_org_client_id(
        "acme-co", _get_text=_never_call, _url_template=url_template
    ) == (None, "invalid-artifact")


def test_fetch_org_client_id_accepts_trusted_host_with_different_path():
    """The scheme/host pin does not forbid every override -- only ones that
    escape the trusted host. A same-host, different-path template (e.g. a
    different branch/filename convention) is still fetched."""

    def fake_get_text(url: str) -> str:
        assert url == "https://raw.githubusercontent.com/acme-co/other-repo/main/boot.yml"
        return "org: acme-co\ngithub_app:\n  client_id: Iv1.a1b2c3d4e5f6a7b8\n"

    url_template = "https://raw.githubusercontent.com/{org}/other-repo/main/boot.yml"
    assert fetch_org_client_id(
        "acme-co", _get_text=fake_get_text, _url_template=url_template
    ) == ("Iv1.a1b2c3d4e5f6a7b8", None)


# ---------------------------------------------------------------------------
# NO-SECRET-shaped guard: this module's success value is a pure client-id
# string -- it can never surface anything from the artifact beyond that,
# even if the artifact carries other fields.
# ---------------------------------------------------------------------------


def test_fetch_org_client_id_ignores_everything_else_in_the_artifact():
    """A bootstrap artifact is meant to carry ONLY `org` + client id
    (invariant #6), but this reader must degrade gracefully -- never raise,
    never forward -- if a misconfigured publisher put something else in
    the file too (e.g. a secret-shaped key). The success value itself
    (a client-id string) makes leaking anything beyond the client id
    structurally impossible; this test pins that no extra field changes
    the resolved value."""

    def fake_get_text(_url: str) -> str:
        return (
            "org: acme-co\n"
            "github_app:\n"
            "  client_id: Iv1.a1b2c3d4e5f6a7b8\n"
            "unexpected_secret_field: ghp_shouldneverbehere\n"
        )

    client_id, failure_reason = fetch_org_client_id("acme-co", _get_text=fake_get_text)
    assert client_id == "Iv1.a1b2c3d4e5f6a7b8"
    assert failure_reason is None
    assert "ghp_" not in client_id


# ---------------------------------------------------------------------------
# org_exists_on_github() -- Bug 2's unauthenticated existence probe
# ---------------------------------------------------------------------------


def test_org_exists_on_github_true_on_200():
    assert org_exists_on_github("acme-co", _get_status=lambda _url: 200) is True


def test_org_exists_on_github_false_on_404():
    assert org_exists_on_github("typo-co", _get_status=lambda _url: 404) is False


@pytest.mark.parametrize("status", [403, 429, 500, 503])
def test_org_exists_on_github_inconclusive_on_rate_limit_or_server_error(status):
    """The fail direction is not negotiable: any ambiguous status (rate
    limit, server error, anything other than a clean 200/404) must degrade
    to `None`, never `False` -- telling someone their real organization
    doesn't exist is worse than making them wait."""
    assert org_exists_on_github("acme-co", _get_status=lambda _url: status) is None


def test_org_exists_on_github_inconclusive_on_network_error():
    def raising_get_status(_url: str) -> int:
        raise urllib.error.URLError("no route to host")

    assert org_exists_on_github("acme-co", _get_status=raising_get_status) is None


def test_org_exists_on_github_empty_org_never_fetches():
    assert org_exists_on_github("", _get_status=_never_call) is None
