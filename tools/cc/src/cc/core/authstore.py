"""Non-secret identity pointer for the WS-A device-flow sign-in seam.

The secret (the GitHub device-flow token) lives ONLY in the OS keychain
(see core/keychain.py) -- never on disk, never in this file. What DOES
belong on disk is a small, non-secret "who is currently signed in" pointer
so `cc doctor`/`cc auth status`-style callers can answer "who" without
touching the keychain at all: `{login, scopes, obtained_at}`. This module
NEVER accepts or persists a token -- `write_identity()` defensively strips
any `token`/`access_token`/`secret` key a caller might mistakenly pass, so
a bug upstream can never turn this file into a second, unencrypted
credential store.

Location: `<auth root>/active.json`, where the auth root resolves the same
injectable-root way every other `cc` filesystem root does (mirrors
core/ecosystem/mirror.py's `mirror_root()` `_root` convention): `_root`
overrides directly when supplied (tests point this at `tmp_path`, never a
real `Path.home()`); with no injection it defaults to `~/.copilot/auth`
(inheritance-and-publish.md §2.2's `~/.copilot/` tree -- the same root
`paths.mirrors_root` already lives under).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

# Keys this store will never persist, even if a caller passes them in --
# defense in depth against an upstream bug accidentally handing this
# module a token (see module docstring).
_FORBIDDEN_KEYS = frozenset({"token", "access_token", "refresh_token", "secret"})


def auth_root(*, _root: Optional[Path | str] = None) -> Path:
    """
    Resolve the auth root directory (`~/.copilot/auth` by default).

    `_root` is injectable so tests point this at `tmp_path` and NEVER
    resolve `Path.home()` -- mirrors `mirror_root()`'s `_root` convention
    (core/ecosystem/mirror.py).
    """
    if _root is not None:
        return Path(_root).expanduser()
    return Path.home() / ".copilot" / "auth"


def identity_path(*, _root: Optional[Path | str] = None) -> Path:
    """Return the path to the identity pointer file: `<auth root>/active.json`."""
    return auth_root(_root=_root) / "active.json"


def read_identity(*, _root: Optional[Path | str] = None) -> dict[str, Any]:
    """
    Read the current identity pointer.

    Fail-open `{}` on missing/malformed -- mirrors
    core/ecosystem/lockfile.py's `read_lockfile()` semantics: no identity
    on disk (signed out, or never signed in) is not an error.
    """
    path = identity_path(_root=_root)
    if not path.exists():
        return {}

    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    if not isinstance(data, dict):
        return {}

    return data


def write_identity(
    identity: dict[str, Any], *, _root: Optional[Path | str] = None
) -> Path:
    """
    Write the identity pointer (`{login, scopes, obtained_at}`).

    Defensively strips any `token`/`access_token`/`refresh_token`/`secret`
    key before writing -- see `_FORBIDDEN_KEYS` and the module docstring:
    this file is a non-secret pointer, never a credential store, even if a
    caller passes one in by mistake.

    Creates the auth root if needed. Returns the path written to.
    """
    path = identity_path(_root=_root)
    path.parent.mkdir(parents=True, exist_ok=True)

    safe_identity = {
        k: v for k, v in identity.items() if k not in _FORBIDDEN_KEYS
    }

    path.write_text(
        json.dumps(safe_identity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def clear_identity(*, _root: Optional[Path | str] = None) -> bool:
    """
    Delete the identity pointer (sign-out). Returns `True` if a file was
    present and removed, `False` if there was nothing to clear.
    """
    path = identity_path(_root=_root)
    if not path.exists():
        return False
    path.unlink()
    return True
