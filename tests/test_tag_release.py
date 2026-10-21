"""scripts/tag-release.sh: a merged version bump becomes a signed, verified tag.

Regression for 2026-10-06: 5.15.3 and 5.15.4 reached main (and project locks,
as release_tag v5.15.4) while the newest tag was v5.15.2.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "tag-release.sh"


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(("git", *args), cwd=cwd, check=check, capture_output=True, text=True)


def _write_release(repo: Path, version: str, *, package: str | None = None,
                   changelog: bool = True) -> None:
    (repo / "VERSION.json").write_text(json.dumps({"framework": version}))
    (repo / "package.json").write_text(json.dumps({"version": package or version}))
    (repo / ".claude-plugin").mkdir(exist_ok=True)
    (repo / ".claude-plugin/plugin.json").write_text(json.dumps({"version": version}))
    (repo / ".claude-plugin/marketplace.json").write_text(
        json.dumps({"plugins": [{"version": version}]})
    )
    log = (repo / "CHANGELOG.md").read_text() if (repo / "CHANGELOG.md").exists() else "# Changelog\n"
    if changelog:
        log = log.replace("# Changelog\n", f"# Changelog\n\n## [{version}] — 2026-10-06 — Title {version}\n", 1)
    (repo / "CHANGELOG.md").write_text(log)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", f"release {version}")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    key = tmp_path / "key"
    subprocess.run(("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)), check=True)
    signers = tmp_path / "allowed_signers"
    signers.write_text(f"fixture@example.invalid {(tmp_path / 'key.pub').read_text()}")
    for k, v in {
        "user.email": "fixture@example.invalid", "user.name": "Fixture",
        "gpg.format": "ssh", "user.signingkey": str(key),
        "gpg.ssh.allowedSignersFile": str(signers), "commit.gpgsign": "true",
        "tag.gpgsign": "true",
    }.items():
        _git(work, "config", k, v)
    _git(work, "checkout", "-q", "-b", "main")
    _write_release(work, "1.0.0")
    _git(work, "push", "-q", "origin", "main")
    return work


def _release_key(repo: Path) -> str:
    return Path(_git(repo, "config", "user.signingkey").stdout.strip() + ".pub").read_text().strip()


def _tag(repo: Path, *args: str, release_key: str | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1",
           "FOUNDATION_RELEASE_PUBLIC_KEY": release_key or _release_key(repo)}
    return subprocess.run(["bash", str(SCRIPT), *args], cwd=repo, env=env,
                          capture_output=True, text=True, timeout=60)


def test_tags_head_signed_and_annotated_from_changelog(repo: Path) -> None:
    result = _tag(repo, "--push")
    assert result.returncode == 0, result.stderr
    assert _git(repo, "cat-file", "-t", "v1.0.0").stdout.strip() == "tag"
    assert _git(repo, "tag", "-v", "v1.0.0").returncode == 0
    assert "Claude Copilot 1.0.0: Title 1.0.0" in _git(repo, "tag", "-n1", "v1.0.0").stdout
    assert "v1.0.0" in _git(repo, "ls-remote", "--tags", "origin").stdout
    # Idempotent: re-running against the same commit is a no-op.
    again = _tag(repo)
    assert again.returncode == 0 and "already tags" in again.stdout


def test_head_release_signed_by_a_key_the_preflight_rejects_is_never_published(
    repo: Path, tmp_path: Path
) -> None:
    other = tmp_path / "other-key"
    subprocess.run(("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(other)), check=True)
    result = _tag(repo, "--push", release_key=(tmp_path / "other-key.pub").read_text().strip())
    assert result.returncode == 1
    assert "failed the foundation release preflight; tag removed" in result.stderr
    assert _git(repo, "rev-parse", "-q", "--verify", "refs/tags/v1.0.0", check=False).returncode != 0
    assert "v1.0.0" not in _git(repo, "ls-remote", "--tags", "origin").stdout


def test_retroactive_tag_for_each_untagged_bump(repo: Path) -> None:
    first = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _write_release(repo, "1.0.1")
    _git(repo, "push", "-q", "origin", "main")
    assert _tag(repo, "--at", first).returncode == 0
    assert _tag(repo).returncode == 0
    assert _git(repo, "rev-parse", "v1.0.0^{commit}").stdout.strip() == first
    assert _git(repo, "rev-parse", "v1.0.1^{commit}").stdout.strip() == \
        _git(repo, "rev-parse", "HEAD").stdout.strip()


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"package": "1.0.0"}, "package.json says 1.0.0, VERSION.json says 1.0.1"),
        ({"changelog": False}, "CHANGELOG.md has no '## [1.0.1]' entry"),
    ],
)
def test_inconsistent_release_is_refused(repo: Path, kwargs, message) -> None:
    _write_release(repo, "1.0.1", **kwargs)
    _git(repo, "push", "-q", "origin", "main")
    result = _tag(repo)
    assert result.returncode == 1 and message in result.stderr, result.stderr
    assert _git(repo, "rev-parse", "-q", "--verify", "refs/tags/v1.0.1", check=False).returncode != 0


def test_unmerged_head_is_refused(repo: Path) -> None:
    _write_release(repo, "1.0.1")  # committed, not pushed
    result = _tag(repo)
    assert result.returncode == 1 and "HEAD is not origin/main" in result.stderr


def test_existing_tag_elsewhere_is_refused(repo: Path) -> None:
    assert _tag(repo).returncode == 0
    _git(repo, "commit", "-q", "--allow-empty", "-m", "later")
    _git(repo, "push", "-q", "origin", "main")
    result = _tag(repo)
    assert result.returncode == 1 and "v1.0.0 already exists at" in result.stderr
