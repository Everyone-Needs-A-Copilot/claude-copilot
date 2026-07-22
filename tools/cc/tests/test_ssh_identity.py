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
