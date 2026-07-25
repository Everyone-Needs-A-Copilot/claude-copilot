import json
import subprocess
from pathlib import Path

import pytest

from cc.core.ecosystem.ssh_identity import ensure_machine_ssh_identity


class FakeCommands:
    def __init__(self, key_path: Path, registered: bool = False):
        self.key_path = key_path
        self.registered = registered
        self.calls = []

    def __call__(self, args):
        args = tuple(args)
        self.calls.append(args)
        if args[:3] == ("gh", "api", "user/keys"):
            keys = [{"key": "ssh-ed25519 TEST device"}] if self.registered else []
            return subprocess.CompletedProcess(args, 0, json.dumps(keys), "")
        if args[0] == "ssh-keygen":
            self.key_path.write_text("PRIVATE")
            Path(f"{self.key_path}.pub").write_text("ssh-ed25519 TEST device\n")
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[0] == "ssh-add":
            return subprocess.CompletedProcess(args, 0, "", "")
        if "POST" in args and "user/keys" in args:
            self.registered = True
            return subprocess.CompletedProcess(args, 0, "{}", "")
        return subprocess.CompletedProcess(args, 1, "", "unexpected")


@pytest.fixture(autouse=True)
def no_real_home(monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: (_ for _ in ()).throw(AssertionError("real home"))))


def test_plan_reports_changes_without_writing(tmp_path):
    key = tmp_path / "ssh" / "device"
    config = tmp_path / "ssh" / "config"
    fake = FakeCommands(key)
    report = ensure_machine_ssh_identity(run=fake, key_path=key, config_path=config)
    assert report["result"] == "changes-required"
    assert not key.exists()
    assert not config.exists()


def test_apply_generates_registers_and_writes_bounded_config(tmp_path):
    key = tmp_path / "ssh" / "device"
    config = tmp_path / "ssh" / "config"
    key.parent.mkdir()
    config.write_text("Host example\n  HostName example.com\n")
    fake = FakeCommands(key)
    report = ensure_machine_ssh_identity(apply=True, run=fake, key_path=key, config_path=config, title="test-device")
    assert report["result"] == "applied"
    assert "Host example" in config.read_text()
    assert "Host github-work github-personal" in config.read_text()
    assert any("POST" in call for call in fake.calls)


def test_second_apply_reuses_registered_key_and_managed_block(tmp_path):
    key = tmp_path / "ssh" / "device"
    config = tmp_path / "ssh" / "config"
    key.parent.mkdir()
    key.write_text("PRIVATE")
    Path(f"{key}.pub").write_text("ssh-ed25519 TEST device\n")
    fake = FakeCommands(key, registered=True)
    first = ensure_machine_ssh_identity(apply=True, run=fake, key_path=key, config_path=config)
    second = ensure_machine_ssh_identity(apply=False, run=fake, key_path=key, config_path=config)
    assert first["result"] == "applied"
    assert second["result"] == "ready"
    assert not any("POST" in call for call in fake.calls)


def test_unmanaged_alias_blocks_without_rewrite(tmp_path):
    key = tmp_path / "device"
    config = tmp_path / "config"
    original = "Host github-work\n  IdentityFile /custom/key\n"
    config.write_text(original)
    report = ensure_machine_ssh_identity(apply=True, run=FakeCommands(key), key_path=key, config_path=config)
    assert report["result"] == "blocked"
    assert config.read_text() == original


def test_partial_keypair_blocks_without_replacement(tmp_path):
    key = tmp_path / "device"
    key.write_text("PRIVATE")
    report = ensure_machine_ssh_identity(apply=True, run=FakeCommands(key), key_path=key, config_path=tmp_path / "config")
    assert report["result"] == "blocked"
    assert key.read_text() == "PRIVATE"


# ---------------------------------------------------------------------------
# Fix 2: `gh api user/keys` 403/404 (GitHub's documented answer for a token
# missing `admin:public_key`) is a fix only the person can make, and must be
# distinguishable from an unrelated, generic failure of the same call.
# ---------------------------------------------------------------------------


def _keys_call_failing(stderr: str, returncode: int = 1):
    def run(args):
        args = tuple(args)
        if args[:3] == ("gh", "api", "user/keys"):
            return subprocess.CompletedProcess(args, returncode, "", stderr)
        raise AssertionError(args)

    return run


def test_missing_admin_public_key_scope_reports_not_permitted(tmp_path):
    key = tmp_path / "ssh" / "device"
    config = tmp_path / "ssh" / "config"
    run = _keys_call_failing(
        'gh: Not Found (HTTP 404)\ngh: This API operation needs the "admin:public_key" '
        "scope. To request it, run:  gh auth refresh -h github.com -s admin:public_key\n"
    )
    report = ensure_machine_ssh_identity(run=run, key_path=key, config_path=config)
    assert report["result"] == "blocked"
    assert report["registration"] == "not-permitted"
    assert report["config"] == "planned"
    assert report["detail"] == (
        "Your GitHub sign-in doesn't include permission to add this Mac's key."
    )


def test_forbidden_key_listing_also_reports_not_permitted(tmp_path):
    key = tmp_path / "ssh" / "device"
    config = tmp_path / "ssh" / "config"
    run = _keys_call_failing("gh: Forbidden (HTTP 403)\n")
    report = ensure_machine_ssh_identity(run=run, key_path=key, config_path=config)
    assert report["registration"] == "not-permitted"


def test_unrelated_key_listing_failure_stays_generic(tmp_path):
    key = tmp_path / "ssh" / "device"
    config = tmp_path / "ssh" / "config"
    run = _keys_call_failing("gh: connection reset by peer\n")
    report = ensure_machine_ssh_identity(run=run, key_path=key, config_path=config)
    assert report["result"] == "blocked"
    assert report["registration"] == "not-checked"
    assert report["detail"] == "GitHub didn't answer when I asked about this Mac's keys."


# ---------------------------------------------------------------------------
# B1 for the SSH gate: an unmanaged alias is positively verified before it's
# trusted, never rewritten either way, and only ever unblocks the ONE alias
# that's genuinely missing. Default to held whenever adoption isn't proven.
# ---------------------------------------------------------------------------


class AdoptCommands:
    """Fake command runner covering the unmanaged-alias verification probes
    (`ssh -T`, `ssh -G`, `git ls-remote`, `gh api user`) in addition to the
    key generation/registration calls `FakeCommands` already covers."""

    def __init__(
        self,
        key_path: Path,
        *,
        registered: bool = True,
        signed_in_login: str | None = "pablitoalejo",
        alias_logins: dict | None = None,
        alias_hostnames: dict | None = None,
        reachable_repos: set | None = None,
    ):
        self.key_path = key_path
        self.registered = registered
        self.signed_in_login = signed_in_login
        self.alias_logins = alias_logins or {}
        self.alias_hostnames = alias_hostnames or {}
        self.reachable_repos = reachable_repos or set()
        self.calls = []

    def __call__(self, args):
        args = tuple(args)
        self.calls.append(args)
        if args[:3] == ("gh", "api", "user/keys"):
            keys = [{"key": "ssh-ed25519 TEST device"}] if self.registered else []
            return subprocess.CompletedProcess(args, 0, json.dumps(keys), "")
        if args[:4] == ("gh", "api", "user", "--jq"):
            if self.signed_in_login is None:
                return subprocess.CompletedProcess(args, 1, "", "not signed in")
            return subprocess.CompletedProcess(args, 0, f"{self.signed_in_login}\n", "")
        if args[0] == "ssh" and "-T" in args:
            alias = args[-1].removeprefix("git@")
            login = self.alias_logins.get(alias)
            if login is None:
                return subprocess.CompletedProcess(args, 255, "", "ssh: Could not resolve hostname\n")
            return subprocess.CompletedProcess(
                args,
                1,
                "",
                f"Hi {login}! You've successfully authenticated, but GitHub does not provide shell access.\n",
            )
        if args[0] == "ssh" and args[1] == "-G":
            alias = args[2]
            hostname = self.alias_hostnames.get(alias)
            if hostname is None:
                return subprocess.CompletedProcess(args, 1, "", "")
            return subprocess.CompletedProcess(args, 0, f"host {alias}\nhostname {hostname}\n", "")
        if args[0] == "git" and "ls-remote" in args:
            assert "-c" in args and any(
                value.startswith("core.sshCommand=") and "BatchMode=yes" in value
                for value in args
            ), "git ls-remote must fail closed on its own, not rely on ssh -T running first"
            target = args[-1]
            if target in self.reachable_repos:
                return subprocess.CompletedProcess(args, 0, "abc123\tHEAD\n", "")
            return subprocess.CompletedProcess(args, 128, "", "fatal: could not read from remote repository")
        if args[0] == "ssh-keygen":
            self.key_path.write_text("PRIVATE")
            Path(f"{self.key_path}.pub").write_text("ssh-ed25519 TEST device\n")
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[0] == "ssh-add":
            return subprocess.CompletedProcess(args, 0, "", "")
        if "POST" in args and "user/keys" in args:
            self.registered = True
            return subprocess.CompletedProcess(args, 0, "{}", "")
        return subprocess.CompletedProcess(args, 1, "", "unexpected")


_UNMANAGED_WORK_ALIAS = "Host github-work\n  HostName github.com\n  User git\n  IdentityFile /custom/key\n"


def test_adoptable_when_unmanaged_alias_verifies_and_offers_missing_alias(tmp_path):
    key = tmp_path / "device"
    config = tmp_path / "config"
    config.write_text(_UNMANAGED_WORK_ALIAS)
    fake = AdoptCommands(
        key,
        alias_logins={"github-work": "pablitoalejo"},
        alias_hostnames={"github-work": "github.com"},
        reachable_repos={"git@github-work:Acme/claude-copilot-internal.git"},
    )
    report = ensure_machine_ssh_identity(
        run=fake,
        key_path=key,
        config_path=config,
        verify_repos={"github-work": "Acme/claude-copilot-internal"},
    )
    assert report["result"] == "changes-required"
    assert report["config"] == "adoptable"
    assert report["adopted_alias"] == "github-work"
    assert report["missing_alias"] == "github-personal"
    assert report["decline_detail"]
    assert config.read_text() == _UNMANAGED_WORK_ALIAS


def test_apply_without_consent_leaves_adoptable_alias_untouched(tmp_path):
    key = tmp_path / "device"
    config = tmp_path / "config"
    config.write_text(_UNMANAGED_WORK_ALIAS)
    fake = AdoptCommands(
        key,
        alias_logins={"github-work": "pablitoalejo"},
        alias_hostnames={"github-work": "github.com"},
        reachable_repos={"git@github-work:Acme/claude-copilot-internal.git"},
    )
    report = ensure_machine_ssh_identity(
        apply=True,
        run=fake,
        key_path=key,
        config_path=config,
        verify_repos={"github-work": "Acme/claude-copilot-internal"},
    )
    assert report["result"] == "applied"
    assert report["config"] == "adoptable"
    assert config.read_text() == _UNMANAGED_WORK_ALIAS
    assert not key.exists()


def test_apply_with_consent_adds_missing_alias_additively(tmp_path):
    key = tmp_path / "device"
    config = tmp_path / "config"
    config.write_text(_UNMANAGED_WORK_ALIAS)
    fake = AdoptCommands(
        key,
        registered=False,
        alias_logins={"github-work": "pablitoalejo"},
        alias_hostnames={"github-work": "github.com"},
        reachable_repos={"git@github-work:Acme/claude-copilot-internal.git"},
    )
    report = ensure_machine_ssh_identity(
        apply=True,
        run=fake,
        key_path=key,
        config_path=config,
        adopt_existing=("ssh",),
        verify_repos={"github-work": "Acme/claude-copilot-internal"},
    )
    assert report["result"] == "applied"
    assert report["config"] == "adopted"
    written = config.read_text()
    # Additive: the pre-existing github-work block is preserved byte for byte.
    assert _UNMANAGED_WORK_ALIAS in written
    assert "Host github-personal" in written
    # Prepended, not appended, so a broad `Host *` later in the file can
    # never shadow HostName/User/IdentityFile for the new alias.
    assert written.index("Host github-personal") < written.index("Host github-work")
    assert key.exists()
    assert any("POST" in call for call in fake.calls)


def test_held_when_alias_signs_in_as_a_different_account(tmp_path):
    key = tmp_path / "device"
    config = tmp_path / "config"
    config.write_text(_UNMANAGED_WORK_ALIAS)
    fake = AdoptCommands(
        key,
        signed_in_login="pablitoalejo",
        alias_logins={"github-work": "someone-else"},
        alias_hostnames={"github-work": "github.com"},
        reachable_repos={"git@github-work:Acme/claude-copilot-internal.git"},
    )
    report = ensure_machine_ssh_identity(
        apply=True,
        run=fake,
        key_path=key,
        config_path=config,
        adopt_existing=("ssh",),
        verify_repos={"github-work": "Acme/claude-copilot-internal"},
    )
    assert report["result"] == "blocked"
    assert report["config"] == "held"
    assert "different account" in report["detail"]
    assert config.read_text() == _UNMANAGED_WORK_ALIAS
    assert not key.exists()


def test_held_when_ssh_cannot_confirm_a_login(tmp_path):
    key = tmp_path / "device"
    config = tmp_path / "config"
    config.write_text(_UNMANAGED_WORK_ALIAS)
    fake = AdoptCommands(key, alias_logins={})
    report = ensure_machine_ssh_identity(
        apply=True, run=fake, key_path=key, config_path=config, adopt_existing=("ssh",)
    )
    assert report["result"] == "blocked"
    assert report["config"] == "held"
    assert config.read_text() == _UNMANAGED_WORK_ALIAS
    assert not key.exists()


def test_held_when_alias_resolves_to_an_unexpected_host(tmp_path):
    key = tmp_path / "device"
    config = tmp_path / "config"
    config.write_text(_UNMANAGED_WORK_ALIAS)
    fake = AdoptCommands(
        key,
        alias_logins={"github-work": "pablitoalejo"},
        alias_hostnames={"github-work": "ghes.internal.example"},
    )
    report = ensure_machine_ssh_identity(
        apply=True, run=fake, key_path=key, config_path=config, adopt_existing=("ssh",)
    )
    assert report["result"] == "blocked"
    assert report["config"] == "held"
    assert config.read_text() == _UNMANAGED_WORK_ALIAS


def test_held_when_expected_repository_is_unreachable(tmp_path):
    key = tmp_path / "device"
    config = tmp_path / "config"
    config.write_text(_UNMANAGED_WORK_ALIAS)
    fake = AdoptCommands(
        key,
        alias_logins={"github-work": "pablitoalejo"},
        alias_hostnames={"github-work": "github.com"},
        reachable_repos=set(),
    )
    report = ensure_machine_ssh_identity(
        apply=True,
        run=fake,
        key_path=key,
        config_path=config,
        adopt_existing=("ssh",),
        verify_repos={"github-work": "Acme/claude-copilot-internal"},
    )
    assert report["result"] == "blocked"
    assert report["config"] == "held"
    assert config.read_text() == _UNMANAGED_WORK_ALIAS


def test_held_when_sentinel_pair_is_malformed(tmp_path):
    key = tmp_path / "device"
    config = tmp_path / "config"
    original = "# BEGIN Copilot Control Tower github-work\nHost github-work\n  HostName github.com\n"
    config.write_text(original)
    report = ensure_machine_ssh_identity(
        apply=True, run=FakeCommands(key), key_path=key, config_path=config
    )
    assert report["result"] == "blocked"
    assert report["config"] == "held"
    assert "I don't recognize how" in report["detail"]
    assert config.read_text() == original


def test_ready_when_both_aliases_already_work_unmanaged(tmp_path):
    """Nothing missing, nothing unverified: a pure no-op, not an offer."""
    key = tmp_path / "device"
    config = tmp_path / "config"
    original = (
        "Host github-work\n  HostName github.com\n  User git\n  IdentityFile /custom/key\n\n"
        "Host github-personal\n  HostName github.com\n  User git\n  IdentityFile /custom/key2\n"
    )
    config.write_text(original)
    fake = AdoptCommands(
        key,
        alias_logins={"github-work": "pablitoalejo", "github-personal": "pablitoalejo"},
        alias_hostnames={"github-work": "github.com", "github-personal": "github.com"},
        reachable_repos={
            "git@github-work:Acme/claude-copilot-internal.git",
            "git@github-personal:pablitoalejo/claude-copilot-private.git",
        },
    )
    report = ensure_machine_ssh_identity(
        run=fake,
        key_path=key,
        config_path=config,
        verify_repos={
            "github-work": "Acme/claude-copilot-internal",
            "github-personal": "pablitoalejo/claude-copilot-private",
        },
    )
    assert report["result"] == "ready"
    assert report["config"] == "ready"
    assert config.read_text() == original
