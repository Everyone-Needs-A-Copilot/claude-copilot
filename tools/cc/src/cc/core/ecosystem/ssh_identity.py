"""Per-machine GitHub SSH identity provisioning for onboarding.

The private key never leaves the device. Only its public half is compared with
and, when needed, registered to the authenticated GitHub account. SSH config is
edited through bounded, sentinel-wrapped blocks.

An alias that already exists outside a Copilot-managed block is never
rewritten -- but it is no longer an automatic dead end either. It is
positively verified (same GitHub login, live access, a real repository it can
reach) before being trusted; only a verified alias is left alone. If it can't
be verified, or the sentinel pair itself is malformed, the gate stays held --
default to held whenever adoption isn't positively proven. When a verified
alias leaves exactly one alias still missing (the common case: a personal
`github-work` alias already works, but `github-personal` was never created),
that missing alias becomes `adoptable`: a purely additive, consent-gated write
that never touches the alias already in place.
"""

from __future__ import annotations

import json
import os
import platform
import re
import secrets
import socket
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Sequence

Run = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
GenerateKey = Callable[[Path, str, str], subprocess.CompletedProcess[str]]
AddKey = Callable[[Path, str | None], subprocess.CompletedProcess[str]]

# Both aliases share one device identity when created from scratch, but each
# is classified and, if needed, written independently so an alias that
# already works is never disturbed.
ALIASES: tuple[str, ...] = ("github-work", "github-personal")
EXPECTED_HOSTNAME = "github.com"

# The legacy combined block, written only when neither alias exists yet.
BEGIN = "# BEGIN Copilot Control Tower github-work"
END = "# END Copilot Control Tower github-work"

_SENTINEL_TAG = "Copilot Control Tower"
_BEGIN_RE = re.compile(rf"^# BEGIN {re.escape(_SENTINEL_TAG)} (.+)$")
_END_RE = re.compile(rf"^# END {re.escape(_SENTINEL_TAG)} (.+)$")
_SSH_LOGIN_RE = re.compile(r"Hi ([^!]+)!")
_HTTP_STATUS_RE = re.compile(r"\(HTTP (\d{3})\)")

_MALFORMED_DETAIL = (
    "I don't recognize how this Mac's GitHub connection is written down, "
    "so I left it exactly as it is."
)


def _run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)


def _new_key_passphrase() -> str:
    """Return a high-entropy passphrase used only for this machine's key."""
    return secrets.token_urlsafe(48)


def _generate_encrypted_keypair(
    key_path: Path, title: str, passphrase: str
) -> subprocess.CompletedProcess[str]:
    """Generate an encrypted OpenSSH key file.

    macOS Keychain does not store the private key itself:
    `ssh-add --apple-use-keychain` stores the passphrase. The durable private
    key therefore remains an encrypted, mode-0600 OpenSSH file, protected by
    bcrypt-PBKDF rounds rather than the previous empty-passphrase file.
    """
    args = (
        "ssh-keygen",
        "-q",
        "-t",
        "ed25519",
        "-a",
        "64",
        "-f",
        str(key_path),
        "-N",
        passphrase,
        "-C",
        title,
    )
    return _run(args)


def _add_private_key_to_agent(
    key_path: Path, passphrase: str | None
) -> subprocess.CompletedProcess[str]:
    """Load a key through Apple's Keychain-aware ssh-agent integration.

    A newly generated key supplies its passphrase through a short-lived
    askpass helper whose file contains no secret; the helper reads the secret
    only from this child process's environment. Existing encrypted keys use
    the passphrase already stored in Keychain. No passphrase is printed.
    """
    if platform.system() != "Darwin":
        args = ("ssh-add", str(key_path))
        return subprocess.CompletedProcess(
            args,
            1,
            "",
            "Secure persistent SSH key loading is not implemented on this platform.",
        )

    if passphrase is None:
        return _run(("ssh-add", "--apple-load-keychain", str(key_path)))

    with tempfile.TemporaryDirectory(prefix="ct-ssh-askpass-") as helper_dir:
        helper = Path(helper_dir) / "askpass"
        helper.write_text(
            "#!/bin/sh\n"
            'exec /usr/bin/printf "%s\\n" "$CT_SSH_KEY_PASSPHRASE"\n',
            encoding="utf-8",
        )
        helper.chmod(0o700)
        env = os.environ.copy()
        env.update(
            {
                "CT_SSH_KEY_PASSPHRASE": passphrase,
                "SSH_ASKPASS": str(helper),
                "SSH_ASKPASS_REQUIRE": "force",
                "DISPLAY": env.get("DISPLAY") or "ct-keychain",
            }
        )
        args = ("ssh-add", "--apple-use-keychain", str(key_path))
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )


def _key_material(value: str) -> str:
    fields = value.strip().split()
    return " ".join(fields[:2]) if len(fields) >= 2 else ""


def _managed_block(key_path: Path) -> str:
    lines = [
        BEGIN,
        "Host github-work github-personal",
        "  HostName github.com",
        "  User git",
        f"  IdentityFile {key_path}",
        "  IdentitiesOnly yes",
        "  AddKeysToAgent yes",
    ]
    if platform.system() == "Darwin":
        lines.append("  UseKeychain yes")
    lines.append(END)
    return "\n".join(lines)


def _adoptive_block(alias: str, key_path: Path) -> str:
    lines = [
        f"# BEGIN {_SENTINEL_TAG} {alias}",
        f"Host {alias}",
        "  HostName github.com",
        "  User git",
        f"  IdentityFile {key_path}",
        "  IdentitiesOnly yes",
        "  AddKeysToAgent yes",
    ]
    if platform.system() == "Darwin":
        lines.append("  UseKeychain yes")
    lines.append(f"# END {_SENTINEL_TAG} {alias}")
    return "\n".join(lines)


def _split_managed(content: str) -> tuple[str, list[list[str]], str | None]:
    """Remove every Copilot-managed sentinel region, however many there are.

    Returns ``(content-outside-any-managed-region, [region-lines, ...], error)``.
    A ``BEGIN`` with no matching ``END``, an ``END`` with no matching
    ``BEGIN``, or a region nested inside another all count as malformed --
    the original content is returned unchanged in that case so nothing is
    ever written on top of something that can't be fully accounted for.
    """
    lines = content.splitlines()
    regions: list[list[str]] = []
    outside: list[str] = []
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        begin_match = _BEGIN_RE.match(stripped)
        if begin_match is None:
            if _END_RE.match(stripped):
                return content, [], _MALFORMED_DETAIL
            outside.append(lines[index])
            index += 1
            continue
        end_marker = f"# END {_SENTINEL_TAG} {begin_match.group(1)}"
        finish = index + 1
        while finish < len(lines) and lines[finish].strip() != end_marker:
            probe = lines[finish].strip()
            if _BEGIN_RE.match(probe) or _END_RE.match(probe):
                return content, [], _MALFORMED_DETAIL
            finish += 1
        if finish >= len(lines):
            return content, [], _MALFORMED_DETAIL
        regions.append(lines[index : finish + 1])
        index = finish + 1
    return "\n".join(outside).strip("\n"), regions, None


def _host_aliases(text: str) -> set[str]:
    found: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("host "):
            found.update(stripped.split()[1:])
    return found


def _classify_aliases(content: str) -> tuple[dict[str, str], str | None]:
    """Classify each of ``ALIASES`` as ``"managed"``, ``"unmanaged"``, or
    ``"missing"``. ``"managed"`` means inside a Copilot sentinel region
    (trusted, never re-verified); ``"unmanaged"`` means declared by a
    ``Host`` line outside any sentinel region (must be verified before it
    can be trusted); ``"missing"`` means the alias appears nowhere at all.
    """
    outside, regions, error = _split_managed(content)
    if error:
        return {}, error
    managed: set[str] = set()
    for region in regions:
        managed |= _host_aliases("\n".join(region))
    unmanaged = _host_aliases(outside)
    return {
        alias: (
            "managed" if alias in managed else "unmanaged" if alias in unmanaged else "missing"
        )
        for alias in ALIASES
    }, None


def _write_managed_config(path: Path, key_path: Path) -> None:
    """Write the combined block. Only used when neither alias exists yet."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    outside, _regions, error = _split_managed(existing)
    classification, classify_error = _classify_aliases(existing)
    unmanaged = error is None and classify_error is None and any(
        state == "unmanaged" for state in classification.values()
    )
    if error or classify_error or unmanaged:
        raise ValueError(
            error or classify_error or "An unmanaged GitHub SSH alias already exists."
        )
    rendered = (outside.rstrip() + "\n\n" if outside.strip() else "") + _managed_block(key_path) + "\n"
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        handle.write(rendered)
        temp_path = Path(handle.name)
    temp_path.chmod(0o600)
    os.replace(temp_path, path)


def _write_adoptive_config(path: Path, key_path: Path, alias: str) -> None:
    """Add one new sentinel-wrapped block for ``alias`` only, touching
    nothing else -- not even a different alias's already-verified block.

    The block is inserted first, not appended. SSH resolves most keywords
    first-match-wins: a pre-existing broad ``Host`` pattern later in the
    file (for example ``Host *``) would otherwise silently shadow
    ``HostName``, ``User``, or ``IdentityFile`` for this alias if the block
    were appended after it. A block for one specific, previously-absent
    alias placed first always wins for that alias, and being alias-specific
    it cannot affect any other ``Host`` pattern already in the file.
    """
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    classification, error = _classify_aliases(existing)
    if error or classification.get(alias) != "missing":
        raise ValueError(
            error or f"The {alias} SSH alias is no longer missing; setup did not add a duplicate."
        )
    block = _adoptive_block(alias, key_path)
    rendered = block + "\n" + ("\n" + existing if existing.strip() else "\n")
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        handle.write(rendered)
        temp_path = Path(handle.name)
    temp_path.chmod(0o600)
    os.replace(temp_path, path)


def _permission_denied(result: subprocess.CompletedProcess[str]) -> bool:
    """GitHub's documented answer when the signed-in token lacks
    ``admin:public_key``: the keys endpoint answers 403 or 404 rather than
    naming the missing permission, so the HTTP status on a failed call is
    the only signal that distinguishes "you can't do this" from "something
    went wrong."
    """
    match = _HTTP_STATUS_RE.search(result.stderr)
    return match is not None and match.group(1) in {"403", "404"}


def _github_keys(*, run: Run) -> tuple[list[str] | None, str | None, bool]:
    """Returns ``(keys, detail, permission_denied)``. ``permission_denied``
    is only ever ``True`` alongside a ``detail``, and tells the caller this
    is a fix only the person themselves can make -- not a generic fault to
    address to nobody.
    """
    result = run(("gh", "api", "user/keys", "--paginate"))
    if result.returncode != 0:
        if _permission_denied(result):
            return (
                None,
                "Your GitHub sign-in doesn't include permission to add this Mac's key.",
                True,
            )
        return None, "GitHub didn't answer when I asked about this Mac's keys.", False
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, "GitHub's answer about this Mac's keys wasn't something I could read.", False
    if not isinstance(payload, list):
        return None, "GitHub's answer about this Mac's keys wasn't something I could read.", False
    return [str(item.get("key", "")) for item in payload if isinstance(item, dict)], None, False


def _signed_in_login(*, run: Run) -> str | None:
    result = run(("gh", "api", "user", "--jq", ".login"))
    login = result.stdout.strip()
    return login if result.returncode == 0 and login else None


def _alias_login(alias: str, *, run: Run) -> str | None:
    """``ssh -T`` against an alias. GitHub always exits 1 on a successful
    auth-only handshake (there is no shell to hand back), so the login is
    read from the banner text, not the exit code. ``BatchMode=yes`` is
    required so a passphrase prompt or an unknown host key fails closed
    instead of hanging; a short ``ConnectTimeout`` bounds the network round
    trip so a stalled connection fails closed too.
    """
    result = run(("ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-T", f"git@{alias}"))
    match = _SSH_LOGIN_RE.search(f"{result.stdout}\n{result.stderr}")
    return match.group(1) if match else None


def _alias_hostname(alias: str, *, run: Run) -> str | None:
    result = run(("ssh", "-G", alias))
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "hostname":
            return parts[1].strip()
    return None


def _alias_reaches_repo(alias: str, owner_repo: str, *, run: Run) -> bool:
    """`git ls-remote` over the alias -- the last of B1's four verification
    checks. Carries its own explicit `BatchMode=yes`/`ConnectTimeout`, the
    same non-interactive, fails-closed contract `_alias_login` above
    documents, via `-c core.sshCommand=...` rather than an environment
    variable (`Run` callables take no env override, and this stays a plain
    argv command). Previously safe only because `_alias_login` always runs
    first against the same alias and must itself succeed non-interactively
    -- ordering-dependent safety, not self-contained. If a future caller
    ever reaches this check on its own, it now fails closed by itself
    instead of risking a hang or an interactive prompt.
    """
    result = run(
        (
            "git",
            "-c",
            "core.sshCommand=ssh -o BatchMode=yes -o ConnectTimeout=10",
            "ls-remote",
            f"git@{alias}:{owner_repo}.git",
        )
    )
    return result.returncode == 0


def _verify_unmanaged_alias(
    alias: str, *, run: Run, expected_repo: str | None
) -> tuple[bool, str]:
    """Positively prove an unmanaged alias is safe to leave in place.

    Default to held whenever adoption isn't positively proven: every check
    below must pass, and a different GitHub login on the existing alias
    stays held rather than adopted -- that is a real security case, not a
    nuisance.
    """
    login = _alias_login(alias, run=run)
    if not login:
        return False, (
            "This Mac's existing GitHub connection didn't confirm who it "
            "signs in as, so I left it exactly as it is."
        )
    signed_in = _signed_in_login(run=run)
    if not signed_in:
        return False, (
            "GitHub didn't confirm who you're signed in as, so I left this "
            "Mac's existing connection exactly as it is."
        )
    if login != signed_in:
        return False, (
            "This Mac's existing GitHub connection signs in as a different "
            f"account ({login}), so I left it exactly as it is."
        )
    hostname = _alias_hostname(alias, run=run)
    if hostname != EXPECTED_HOSTNAME:
        return False, (
            "This Mac's existing GitHub connection points somewhere other "
            "than GitHub, so I left it exactly as it is."
        )
    if not expected_repo or not _alias_reaches_repo(alias, expected_repo, run=run):
        return False, (
            "This Mac's existing GitHub connection couldn't reach your "
            "spaces on GitHub, so I left it exactly as it is."
        )
    return True, (
        "This Mac already connects to GitHub, and I checked that it works "
        "and that it's signed in as you. I'll leave that exactly as it is "
        "and add the one connection it's still missing."
    )


def ensure_machine_ssh_identity(
    *,
    apply: bool = False,
    run: Run = _run,
    key_path: Path | str | None = None,
    config_path: Path | str | None = None,
    title: str | None = None,
    adopt_existing: Sequence[str] = (),
    verify_repos: dict[str, str] | None = None,
    generate_key: GenerateKey = _generate_encrypted_keypair,
    add_key: AddKey = _add_private_key_to_agent,
    passphrase_factory: Callable[[], str] = _new_key_passphrase,
) -> dict[str, Any]:
    """Plan or apply one resumable, device-local SSH identity transaction.

    An alias declared outside a Copilot-managed block is never rewritten. It
    is either positively verified and left alone, or -- if verification
    can't prove it's safe -- the whole gate stays held, exactly as it did
    before. Verification never grants a bypass: at most it unblocks the one
    alias that is still genuinely missing (B1: an ``adoptable`` state,
    gated the same way as the personal-packages gate's ``--adopt-existing``
    consent, using the ``ssh`` token).
    """
    key = Path(key_path).expanduser() if key_path else Path.home() / ".ssh" / "id_ed25519_copilot"
    public = Path(f"{key}.pub")
    config = Path(config_path).expanduser() if config_path else Path.home() / ".ssh" / "config"
    existing_config = config.read_text(encoding="utf-8") if config.exists() else ""
    consented = "ssh" in {value.strip().lower() for value in adopt_existing if value.strip()}
    verify_repos = verify_repos or {}

    if key.exists() != public.exists():
        return {
            "result": "blocked",
            "key": "incomplete",
            "registration": "not-checked",
            "config": "planned",
            "detail": "Part of this Mac's own GitHub key is missing, and I won't replace what's there.",
        }

    github_keys, error, permission_denied = _github_keys(run=run)
    if error:
        return {
            "result": "blocked",
            "key": "existing" if key.exists() else "missing",
            "registration": "not-permitted" if permission_denied else "not-checked",
            "config": "planned",
            "detail": error,
        }

    local_public = public.read_text(encoding="utf-8") if public.exists() else ""
    registered = bool(
        local_public
        and _key_material(local_public) in {_key_material(value) for value in github_keys or []}
    )
    key_state = "existing" if key.exists() else "missing"
    registration_state = "registered" if registered else "missing"

    classification, malformed = _classify_aliases(existing_config)
    if malformed:
        return {
            "result": "blocked",
            "key": key_state,
            "registration": registration_state,
            "config": "held",
            "detail": malformed,
        }

    unmanaged = [alias for alias in ALIASES if classification[alias] == "unmanaged"]
    missing = [alias for alias in ALIASES if classification[alias] == "missing"]

    adopted_alias: str | None = None
    adoption_detail = ""
    if unmanaged:
        for alias in unmanaged:
            verified, detail = _verify_unmanaged_alias(
                alias, run=run, expected_repo=verify_repos.get(alias)
            )
            if not verified:
                return {
                    "result": "blocked",
                    "key": key_state,
                    "registration": registration_state,
                    "config": "held",
                    "detail": detail,
                }
            if missing:
                adopted_alias = adopted_alias or alias
                adoption_detail = adoption_detail or detail

    to_create = tuple(missing)

    if unmanaged and not to_create:
        # Every alias this device needs already works, verified, none of it
        # Copilot's own -- there is nothing left to offer or to write.
        return {
            "result": "ready",
            "key": key_state,
            "registration": registration_state,
            "config": "ready",
            "detail": "This Mac's connections to GitHub already work. Nothing was changed.",
        }

    if unmanaged and to_create:
        decline_detail = (
            "Without this, this Mac keeps one of the two GitHub connections "
            "setup uses. Setup carries on, and I'll offer this again from "
            "the menu bar whenever you're ready."
        )
        if not apply or not consented:
            return {
                "result": "changes-required" if not apply else "applied",
                "key": key_state,
                "registration": registration_state,
                "config": "adoptable",
                "detail": adoption_detail,
                "decline_detail": decline_detail,
                "adopted_alias": adopted_alias,
                "missing_alias": to_create[0],
            }
        # Consented: fall through to the shared generate/register/write path
        # below, which writes only `to_create` (the missing alias) and never
        # touches the adopted one.

    desired_present = not to_create
    if not apply:
        ready = key.exists() and registered and desired_present
        return {
            "result": "ready" if ready else "changes-required",
            "key": key_state,
            "registration": registration_state,
            "config": "ready" if desired_present else "planned",
            "detail": (
                "This Mac has its own key for GitHub."
                if ready
                else "This Mac can be given its own key for GitHub, without copying anything from another Mac."
            ),
        }

    created_key = False
    generated_passphrase: str | None = None
    if not key.exists():
        key.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        generated_passphrase = passphrase_factory()
        if len(generated_passphrase) < 32:
            return {
                "result": "blocked",
                "key": "missing",
                "registration": "missing",
                "config": "planned",
                "detail": "A strong passphrase for this Mac's GitHub key could not be generated.",
            }
        generated = generate_key(
            key,
            title or f"Copilot Control Tower {socket.gethostname()}",
            generated_passphrase,
        )
        if generated.returncode != 0 or not key.exists() or not public.exists():
            key.unlink(missing_ok=True)
            public.unlink(missing_ok=True)
            return {
                "result": "blocked",
                "key": "unknown",
                "registration": "missing",
                "config": "planned",
                "detail": "The device SSH keypair could not be generated.",
            }
        created_key = True
        local_public = public.read_text(encoding="utf-8")

    added = add_key(key, generated_passphrase)
    if added.returncode != 0:
        if created_key:
            key.unlink(missing_ok=True)
            public.unlink(missing_ok=True)
        return {
            "result": "blocked",
            "key": "missing" if created_key else "existing",
            "registration": "registered" if registered else "missing",
            "config": "planned",
            "detail": (
                "The private key could not be stored safely, so the new keypair was removed."
                if created_key
                else "The private key remains on this Mac, but its secure SSH agent could not load it."
            ),
        }

    if not registered:
        registered_result = run(
            (
                "gh",
                "api",
                "-X",
                "POST",
                "user/keys",
                "-f",
                f"title={title or f'Copilot Control Tower {socket.gethostname()}'}",
                "-f",
                f"key={local_public.strip()}",
            )
        )
        if registered_result.returncode != 0:
            return {
                "result": "blocked",
                "key": "existing",
                "registration": "missing",
                "config": "planned",
                "detail": "GitHub did not confirm public-key registration. The private key never left this device.",
            }

    try:
        if to_create and len(to_create) < len(ALIASES):
            _write_adoptive_config(config, key, to_create[0])
            final_config = "adopted"
            # Product voice (adopt-and-honesty-copy-spec.md §0/D.1): first
            # person, no `alias`/`device`, and never the raw `to_create[0]`/
            # `adopted_alias` host tokens (`github-work`/`github-personal`)
            # -- those are internal names, not something a non-technical
            # reader should see. Left-alone stated first, addition second,
            # matching the ratified adoption-offer string this confirms.
            final_detail = (
                "I left this Mac's existing connection to GitHub exactly "
                "as it is, and added the one it was still missing, using "
                "a key made just for this Mac."
            )
        else:
            _write_managed_config(config, key)
            final_config = "ready"
            # Reuses the exact phrase D.1 already ratified for the
            # equivalent "ready" detail elsewhere in this module.
            final_detail = "This Mac has its own key for GitHub."
    except (OSError, ValueError):
        return {
            "result": "blocked",
            "key": "existing",
            "registration": "registered",
            "config": "held",
            "detail": "The SSH config could not be updated safely; existing content was preserved.",
        }

    return {
        "result": "applied",
        "key": "existing",
        "registration": "registered",
        "config": final_config,
        "detail": final_detail,
    }
