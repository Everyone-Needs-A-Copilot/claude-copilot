"""Per-machine GitHub SSH identity provisioning for onboarding.

The private key never leaves the device. Only its public half is compared with
and, when needed, registered to the authenticated GitHub account. SSH config is
edited through one bounded managed block; an unmanaged ``github-work`` alias is
treated as user-owned and blocks rather than being rewritten.
"""

from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Sequence

Run = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
BEGIN = "# BEGIN Copilot Control Tower github-work"
END = "# END Copilot Control Tower github-work"


def _run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)


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


def _split_managed(content: str) -> tuple[str, str | None]:
    start = content.find(BEGIN)
    finish = content.find(END)
    if start < 0 and finish < 0:
        return content, None
    if start < 0 or finish < start:
        return content, "Malformed Copilot-managed SSH config block."
    finish += len(END)
    outside = (content[:start] + content[finish:]).strip("\n")
    return outside, None


def _has_unmanaged_alias(content: str) -> bool:
    outside, error = _split_managed(content)
    if error:
        return True
    for line in outside.splitlines():
        stripped = line.strip()
        if not stripped.lower().startswith("host "):
            continue
        aliases = stripped.split()[1:]
        if "github-work" in aliases or "github-personal" in aliases:
            return True
    return False


def _write_managed_config(path: Path, key_path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    outside, error = _split_managed(existing)
    if error or _has_unmanaged_alias(existing):
        raise ValueError(error or "An unmanaged GitHub SSH alias already exists.")
    rendered = (outside.rstrip() + "\n\n" if outside.strip() else "") + _managed_block(key_path) + "\n"
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        handle.write(rendered)
        temp_path = Path(handle.name)
    temp_path.chmod(0o600)
    os.replace(temp_path, path)


def _github_keys(*, run: Run) -> tuple[list[str] | None, str | None]:
    result = run(("gh", "api", "user/keys", "--paginate"))
    if result.returncode != 0:
        return None, "GitHub could not list SSH keys for the authenticated account."
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, "GitHub returned an unreadable SSH key response."
    if not isinstance(payload, list):
        return None, "GitHub returned an unreadable SSH key response."
    return [str(item.get("key", "")) for item in payload if isinstance(item, dict)], None


def ensure_machine_ssh_identity(
    *,
    apply: bool = False,
    run: Run = _run,
    key_path: Path | str | None = None,
    config_path: Path | str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """Plan or apply one resumable, device-local SSH identity transaction."""
    key = Path(key_path).expanduser() if key_path else Path.home() / ".ssh" / "id_ed25519_copilot"
    public = Path(f"{key}.pub")
    config = Path(config_path).expanduser() if config_path else Path.home() / ".ssh" / "config"
    existing_config = config.read_text(encoding="utf-8") if config.exists() else ""

    if _has_unmanaged_alias(existing_config):
        return {"result": "blocked", "key": "unknown", "registration": "unknown", "config": "held", "detail": "An existing GitHub SSH alias is user-managed; setup did not replace it."}
    if key.exists() != public.exists():
        return {"result": "blocked", "key": "incomplete", "registration": "unknown", "config": "planned", "detail": "Only one half of the device SSH keypair exists; setup did not replace it."}

    github_keys, error = _github_keys(run=run)
    if error:
        return {"result": "blocked", "key": "existing" if key.exists() else "missing", "registration": "unknown", "config": "planned", "detail": error}

    local_public = public.read_text(encoding="utf-8") if public.exists() else ""
    registered = bool(local_public and _key_material(local_public) in {_key_material(value) for value in github_keys or []})
    desired_block = _managed_block(key)
    config_ready = desired_block in existing_config
    if not apply:
        ready = key.exists() and registered and config_ready
        return {
            "result": "ready" if ready else "changes-required",
            "key": "existing" if key.exists() else "missing",
            "registration": "registered" if registered else "missing",
            "config": "ready" if config_ready else "planned",
            "detail": "The device SSH identity is ready." if ready else "The device SSH identity can be completed without copying a private key.",
        }

    if not key.exists():
        key.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        generated = run(("ssh-keygen", "-t", "ed25519", "-f", str(key), "-N", "", "-C", title or f"Copilot Control Tower {socket.gethostname()}"))
        if generated.returncode != 0 or not key.exists() or not public.exists():
            return {"result": "blocked", "key": "unknown", "registration": "missing", "config": "planned", "detail": "The device SSH keypair could not be generated."}
        local_public = public.read_text(encoding="utf-8")

    add_args = ("ssh-add", "--apple-use-keychain", str(key)) if platform.system() == "Darwin" else ("ssh-add", str(key))
    added = run(add_args)
    if added.returncode != 0:
        return {"result": "blocked", "key": "existing", "registration": "registered" if registered else "missing", "config": "planned", "detail": "The private key remains on this device, but the SSH agent could not load it."}

    if not registered:
        registered_result = run(("gh", "api", "-X", "POST", "user/keys", "-f", f"title={title or f'Copilot Control Tower {socket.gethostname()}'}", "-f", f"key={local_public.strip()}"))
        if registered_result.returncode != 0:
            return {"result": "blocked", "key": "existing", "registration": "missing", "config": "planned", "detail": "GitHub did not confirm public-key registration. The private key never left this device."}

    try:
        _write_managed_config(config, key)
    except (OSError, ValueError):
        return {"result": "blocked", "key": "existing", "registration": "registered", "config": "held", "detail": "The SSH config could not be updated safely; existing content was preserved."}

    return {"result": "applied", "key": "existing", "registration": "registered", "config": "ready", "detail": "This device has its own registered SSH identity."}
