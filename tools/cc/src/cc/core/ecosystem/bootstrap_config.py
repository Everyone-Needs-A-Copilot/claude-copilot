"""The org's PUBLIC bootstrap artifact -- breaks the sign-in chicken-and-egg.

`cc auth login` needs the org's GitHub App client id (`core/config.py`'s
`github_app.client_id`) to even construct a device-flow request. Before this
module existed, the only place that id lived was the org's PRIVATE
`<org>-copilot-internal/ecosystem.yml` (docs/01-architecture/
admin-standup-contract.md §4, in the copilot-control-tower repo) -- and
reading a private repo requires authenticating first. Circular: sign-in
needs the client id, and the client id lived only somewhere sign-in was
needed to read.

This module reads a second, deliberately tiny, PUBLIC artifact the org
publishes once (an outward, admin-owned action -- this module only ever
reads it, never writes it): a file carrying ONLY `org` and
`github_app.client_id`, both non-secret by design
(admin-standup-contract.md §1.6/§4: "the Client ID is public"). Being
public, it is fetchable over plain HTTPS with NO GitHub authentication and
NO `gh` CLI dependency -- consistent with `core/ecosystem/github_device.py`'s
own device-flow transport, which is also a bare `urllib.request` call, so a
completely fresh Mac with nothing installed but a network connection can
still sign in.

Default location: a NEW, minimal, public-by-construction repo the org
creates once, distinct from its existing private `<org>-copilot-internal`
triplet --

    https://raw.githubusercontent.com/<org>/copilot-bootstrap/main/bootstrap.yml

carrying exactly:

    org: acme-co
    github_app:
      client_id: Iv1.a1b2c3d4e5f6a7b8

Overridable via the `github_app.bootstrap_url_template` config key (a
`{org}`-format template) for an org that hosts this artifact somewhere else.

Fail-open on every network/parse/shape problem -- mirrors
`ecosystem_config.py`'s own fail-open posture: a missing, unreachable,
malformed, or mismatched-org artifact degrades to `None` (the caller,
`commands/auth.py`'s `_resolve_client_id()`, turns that into the
`no-company-app` error envelope), never raises.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

import yaml

from cc.core.config import resolve_key

DEFAULT_BOOTSTRAP_URL_TEMPLATE = (
    "https://raw.githubusercontent.com/{org}/copilot-bootstrap/main/bootstrap.yml"
)

# Injectable transport signature, mirroring github_device.py's
# `PostJsonFn`/`GetJsonFn` convention: tests substitute a fake and this
# module never makes a real network call in the test suite.
GetTextFn = Callable[[str], str]

_REQUEST_TIMEOUT_SECONDS = 10


def _default_get_text(url: str) -> str:
    """Stdlib `urllib.request`-based default GET transport (plain-text
    response) -- only ever exercised outside the test suite."""
    request = urllib.request.Request(url, headers={"Accept": "text/plain"}, method="GET")
    with urllib.request.urlopen(  # noqa: S310 -- fixed https URL, built from a validated org slug
        request, timeout=_REQUEST_TIMEOUT_SECONDS
    ) as response:
        return response.read().decode("utf-8")


def bootstrap_url(org: str, *, _url_template: Optional[str] = None) -> str:
    """Return the resolved bootstrap URL for `org`.

    `_url_template` overrides directly when supplied (tests); with no
    override, resolves the `github_app.bootstrap_url_template` config key,
    falling back to `DEFAULT_BOOTSTRAP_URL_TEMPLATE`. The org slug is
    URL-quoted before formatting so it can never inject an extra path
    segment or query string into the template.
    """
    template: str = _url_template or resolve_key("github_app.bootstrap_url_template") or (
        DEFAULT_BOOTSTRAP_URL_TEMPLATE
    )
    return template.format(org=urllib.parse.quote(org, safe=""))


def fetch_org_client_id(
    org: str,
    *,
    _get_text: GetTextFn = _default_get_text,
    _url_template: Optional[str] = None,
) -> Optional[str]:
    """
    Fetch `org`'s public bootstrap artifact and return its
    `github_app.client_id`, or `None` on any failure.

    Fail-open, never raises: a network error, a non-YAML/non-mapping body,
    or a body that doesn't even claim to belong to `org` (fail CLOSED on
    trust, never honor a client id from an artifact naming a different
    organization) all degrade to `None` identically to "the org has no
    company app yet" -- this module deliberately does not distinguish those
    cases from each other, since none of them are actionable by the person
    signing in.
    """
    if not org:
        return None

    url = bootstrap_url(org, _url_template=_url_template)
    try:
        raw = _get_text(url)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None

    try:
        data: Any = yaml.safe_load(raw)
    except yaml.YAMLError:
        return None

    if not isinstance(data, dict) or data.get("org") != org:
        return None

    github_app = data.get("github_app")
    if not isinstance(github_app, dict):
        return None

    client_id = github_app.get("client_id")
    return client_id if isinstance(client_id, str) and client_id else None


__all__ = [
    "DEFAULT_BOOTSTRAP_URL_TEMPLATE",
    "GetTextFn",
    "bootstrap_url",
    "fetch_org_client_id",
]
