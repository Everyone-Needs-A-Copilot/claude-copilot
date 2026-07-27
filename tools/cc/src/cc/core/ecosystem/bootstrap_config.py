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
`{org}`-format template) for an org that hosts this artifact somewhere else
-- MACHINE config only (`resolve_key(..., scope="machine")`), never project
config. This runs before any credential exists and picks which GitHub App a
device-flow sign-in binds to, so it is security-sensitive: invariant #4
(copilot-control-tower/CLAUDE.md) is "nothing security-critical comes from
user-editable local config," and project config (`<repo>/.claude/cc/
config.json`) arrives with nothing more than a `git clone`/checkout -- zero
prior trust. Machine config requires the person (or an admin they already
trust) to have run `cc config set` on their OWN machine first, a materially
different trust posture. This is the smallest real lever `resolve_key()`
already exposes (`scope=`) -- not a rearchitecture; a fuller fix would route
this key through this codebase's signed-inherited-config path once one
exists, which it does not yet.

Even a machine-config override is not trusted to name an arbitrary host,
though: `_is_trusted_bootstrap_url()` pins every resolved URL (default or
overridden) to `https://raw.githubusercontent.com/...` before ever fetching
it. A per-host ALLOWLIST was the other option; a single fixed host was
chosen instead because every legitimate publisher already uses this exact
convention (it's the one this module's own docstring/default advertises),
and a user-editable allowlist would just relocate the same "trusted from
local config" problem invariant #4 flags rather than remove it. A org that
needs a genuinely different host is a case for this codebase's (not yet
built) signed-config path, not a wider allowlist here.

Fail-open on failure modes that are indistinguishable from "the org hasn't
published this yet" (unreachable-but-not-a-real-org-signal, malformed body,
wrong shape, org-name mismatch, untrusted URL) -- mirrors
`ecosystem_config.py`'s own fail-open posture. Distinguishes exactly one
other case: a genuine transport/connectivity failure (DNS, connection
refused, timeout) is reachable-vs-not information the caller CAN act on
(`commands/auth.py`'s `_resolve_client_id()` surfaces it as
`network-unavailable`, not `no-company-app` -- an offline Mac deserves an
offline message, not "your organization hasn't finished setting up
sign-in"). Never raises.
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

# Scheme + host pin (D5 hardening) -- see the module docstring for why a
# single fixed host was chosen over a configurable allowlist.
_TRUSTED_SCHEME = "https"
_TRUSTED_HOST = "raw.githubusercontent.com"

# Injectable transport signature, mirroring github_device.py's
# `PostJsonFn`/`GetJsonFn` convention: tests substitute a fake and this
# module never makes a real network call in the test suite.
GetTextFn = Callable[[str], str]

_REQUEST_TIMEOUT_SECONDS = 10

# This artifact is documented (see module docstring) to carry exactly two
# scalar fields. A legitimate publisher's file is a few dozen bytes; this
# cap is generous well beyond any plausible legitimate size, so a
# compromised/malicious host cannot exhaust memory or hang this
# pre-credential fetch by streaming an unbounded body.
_MAX_RESPONSE_BYTES = 64 * 1024


class _BootstrapResponseTooLarge(ValueError):
    """Raised by `_default_get_text` when a response exceeds
    `_MAX_RESPONSE_BYTES`. A `ValueError` subclass so it is still caught by
    any pre-existing broad `except ValueError` -- but `fetch_org_client_id`
    catches it BY NAME first so an oversized-but-reachable response is
    classified as `invalid-artifact`, never `network-unavailable` (the
    server responded at all, so the machine is definitely online)."""


def _default_get_text(url: str) -> str:
    """Stdlib `urllib.request`-based default GET transport (plain-text
    response) -- only ever exercised outside the test suite."""
    request = urllib.request.Request(url, headers={"Accept": "text/plain"}, method="GET")
    with urllib.request.urlopen(  # noqa: S310 -- scheme+host pinned by the caller
        request, timeout=_REQUEST_TIMEOUT_SECONDS
    ) as response:
        body = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(body) > _MAX_RESPONSE_BYTES:
        raise _BootstrapResponseTooLarge(
            f"bootstrap artifact response exceeded {_MAX_RESPONSE_BYTES} bytes"
        )
    return body.decode("utf-8")


def bootstrap_url(org: str, *, _url_template: Optional[str] = None) -> str:
    """Return the resolved bootstrap URL for `org`.

    `_url_template` overrides directly when supplied (tests); with no
    override, resolves the `github_app.bootstrap_url_template` config key
    from MACHINE config ONLY (see module docstring), falling back to
    `DEFAULT_BOOTSTRAP_URL_TEMPLATE`. The org slug is URL-quoted before
    formatting so it can never inject an extra path segment or query string
    into the template. Does NOT itself enforce the scheme/host pin --
    `fetch_org_client_id()` does that, immediately before fetching, so this
    function stays a pure "resolve the template" helper.
    """
    template: str = (
        _url_template
        or resolve_key("github_app.bootstrap_url_template", scope="machine")
        or DEFAULT_BOOTSTRAP_URL_TEMPLATE
    )
    return template.format(org=urllib.parse.quote(org, safe=""))


def _is_trusted_bootstrap_url(url: str) -> bool:
    """Scheme + host pin -- see module docstring. Applied to EVERY resolved
    URL, default or overridden, immediately before it is ever fetched."""
    parsed = urllib.parse.urlsplit(url)
    return parsed.scheme == _TRUSTED_SCHEME and parsed.hostname == _TRUSTED_HOST


def fetch_org_client_id(
    org: str,
    *,
    _get_text: GetTextFn = _default_get_text,
    _url_template: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """
    Fetch `org`'s public bootstrap artifact and return `(client_id,
    failure_reason)`.

    `failure_reason` is `None` on success, and one of:
      - `"network-unavailable"` -- the fetch could not reach a server at
        all (DNS failure, connection refused, timeout) -- distinguishable
        from getting an HTTP response, which means the network is fine and
        SOME server answered.
      - `"invalid-artifact"` -- every other failure mode: an untrusted URL
        (scheme/host pin), an HTTP error response (e.g. a 404 -- the
        artifact isn't published yet), a response over the size cap, a
        non-YAML/non-mapping body, or a body that doesn't even claim to
        belong to `org` (case-folded compare -- GitHub org names are
        case-insensitive and unique by fold, so "Acme-Co" vs "acme-co" must
        match; this is a trust boundary, not a shape check, so it still
        fails CLOSED on a genuine name mismatch, never honoring a client id
        from an artifact naming a different organization).

    Never raises.
    """
    if not org:
        return None, "invalid-artifact"

    url = bootstrap_url(org, _url_template=_url_template)
    if not _is_trusted_bootstrap_url(url):
        return None, "invalid-artifact"

    try:
        raw = _get_text(url)
    except _BootstrapResponseTooLarge:
        return None, "invalid-artifact"
    except urllib.error.HTTPError:
        return None, "invalid-artifact"
    except (urllib.error.URLError, TimeoutError, OSError):
        return None, "network-unavailable"
    except ValueError:
        return None, "invalid-artifact"

    try:
        data: Any = yaml.safe_load(raw)
    except yaml.YAMLError:
        return None, "invalid-artifact"

    if not isinstance(data, dict):
        return None, "invalid-artifact"

    artifact_org = data.get("org")
    if not isinstance(artifact_org, str) or artifact_org.casefold() != org.casefold():
        return None, "invalid-artifact"

    github_app = data.get("github_app")
    if not isinstance(github_app, dict):
        return None, "invalid-artifact"

    client_id = github_app.get("client_id")
    if not (isinstance(client_id, str) and client_id):
        return None, "invalid-artifact"

    return client_id, None


def _default_get_status(url: str) -> int:
    """Stdlib `urllib.request`-based default transport for
    `org_exists_on_github()` -- returns only the HTTP status code, never
    the response body (this probe only needs existence, not content)."""
    request = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json"}, method="GET"
    )
    try:
        with urllib.request.urlopen(  # noqa: S310 -- fixed api.github.com URL
            request, timeout=_REQUEST_TIMEOUT_SECONDS
        ) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


GetStatusFn = Callable[[str], int]


def org_exists_on_github(
    org: str, *, _get_status: GetStatusFn = _default_get_status
) -> Optional[bool]:
    """
    Unauthenticated existence probe against GitHub's public org endpoint
    (`GET api.github.com/orgs/<org>`) -- distinguishes "this org slug is a
    typo / doesn't exist" from "this org exists but hasn't published a
    bootstrap artifact yet", so `commands/auth.py`'s `_resolve_client_id()`
    can surface a distinct `org-not-found` instead of collapsing both into
    `no-company-app`.

    Returns:
      - `True`  -- the org slug resolves on GitHub (200).
      - `False` -- GitHub affirmatively says no such org (404).
      - `None`  -- inconclusive: rate-limited, network error, or any other
        status. NEVER treated as "does not exist" -- `api.github.com`'s
        unauthenticated rate limit (60/hour) is shared by every caller
        behind one IP, so a busy corporate network will trip this often,
        and telling someone their real organization doesn't exist is worse
        than making them wait. Every ambiguous signal fails toward `None`,
        never `False`.

    Never raises.
    """
    if not org:
        return None

    url = f"https://api.github.com/orgs/{urllib.parse.quote(org, safe='')}"
    try:
        status = _get_status(url)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None

    if status == 200:
        return True
    if status == 404:
        return False
    return None


__all__ = [
    "DEFAULT_BOOTSTRAP_URL_TEMPLATE",
    "GetStatusFn",
    "GetTextFn",
    "bootstrap_url",
    "fetch_org_client_id",
    "org_exists_on_github",
]
