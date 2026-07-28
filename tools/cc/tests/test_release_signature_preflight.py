from __future__ import annotations

import os
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).parents[3] / "scripts" / "verify-foundation-release.sh"


def _run(*args: str, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _repo_and_key(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    repo = tmp_path / "repo"
    repo.mkdir()
    key = tmp_path / "release-key"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
        check=True,
    )
    public_key = key.with_suffix(".pub").read_text(encoding="utf-8").split(" test@", 1)[0].strip()
    env = os.environ.copy()
    env.update(
        {
            "FOUNDATION_RELEASE_PRINCIPAL": "test-foundation",
            "FOUNDATION_RELEASE_PUBLIC_KEY": public_key,
        }
    )
    for command in (
        ("git", "init", "-q"),
        ("git", "config", "user.name", "Release Test"),
        ("git", "config", "user.email", "release@example.invalid"),
        ("git", "config", "gpg.format", "ssh"),
        ("git", "config", "user.signingkey", str(key)),
    ):
        subprocess.run(command, cwd=repo, check=True)
    (repo / "content.txt").write_text("release\n", encoding="utf-8")
    subprocess.run(["git", "add", "content.txt"], cwd=repo, check=True)
    return repo, key, env


def test_release_preflight_accepts_signed_tag_over_signed_root_snapshot(tmp_path: Path) -> None:
    repo, _key, env = _repo_and_key(tmp_path)
    subprocess.run(["git", "commit", "-qS", "-m", "snapshot"], cwd=repo, check=True)
    commit = _run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    subprocess.run(["git", "tag", "-s", "v1.2.3", "-m", "release"], cwd=repo, check=True)

    result = _run(str(SCRIPT), str(repo), "v1.2.3", commit, cwd=repo, env=env)

    assert result.returncode == 0, result.stderr
    assert "foundation release signatures: verified" in result.stdout


def test_release_preflight_rejects_signed_tag_over_unsigned_snapshot(tmp_path: Path) -> None:
    repo, _key, env = _repo_and_key(tmp_path)
    subprocess.run(["git", "commit", "-q", "--no-gpg-sign", "-m", "snapshot"], cwd=repo, check=True)
    commit = _run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    subprocess.run(["git", "tag", "-s", "v1.2.3", "-m", "release"], cwd=repo, check=True)

    result = _run(str(SCRIPT), str(repo), "v1.2.3", commit, cwd=repo, env=env)

    assert result.returncode != 0
    assert "commit" in result.stderr
    assert "valid foundation release signature" in result.stderr
