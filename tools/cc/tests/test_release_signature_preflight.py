from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[3] / "scripts" / "verify-foundation-release.sh"
PACKAGER = Path(__file__).parents[3] / "scripts" / "package-cc-macos-release.sh"


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
        ("git", "init", "-q", "-b", "main"),
        ("git", "config", "user.name", "Release Test"),
        ("git", "config", "user.email", "release@example.invalid"),
        ("git", "config", "gpg.format", "ssh"),
        ("git", "config", "user.signingkey", str(key)),
    ):
        subprocess.run(command, cwd=repo, check=True)
    (repo / "content.txt").write_text("release\n", encoding="utf-8")
    subprocess.run(["git", "add", "content.txt"], cwd=repo, check=True)
    return repo, key, env


def _publish_and_clone_tag(
    tmp_path: Path,
    repo: Path,
    tag: str,
) -> Path:
    remote = tmp_path / "remote.git"
    checkout = tmp_path / "tag-checkout"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", str(remote)], cwd=repo, check=True
    )
    subprocess.run(["git", "push", "-q", "origin", "main", tag], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "clone",
            "-q",
            "--branch",
            tag,
            "--no-single-branch",
            str(remote),
            str(checkout),
        ],
        check=True,
    )
    return checkout


def test_release_preflight_accepts_signed_tag_over_signed_root_snapshot(tmp_path: Path) -> None:
    repo, _key, env = _repo_and_key(tmp_path)
    subprocess.run(["git", "commit", "-qS", "-m", "snapshot"], cwd=repo, check=True)
    commit = _run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    subprocess.run(["git", "tag", "-s", "v1.2.3", "-m", "release"], cwd=repo, check=True)

    result = _run(str(SCRIPT), str(repo), "v1.2.3", commit, "main", cwd=repo, env=env)

    assert result.returncode == 0, result.stderr
    assert "foundation release signatures: verified" in result.stdout


def test_release_preflight_rejects_signed_tag_over_unsigned_snapshot(tmp_path: Path) -> None:
    repo, _key, env = _repo_and_key(tmp_path)
    subprocess.run(["git", "commit", "-q", "--no-gpg-sign", "-m", "snapshot"], cwd=repo, check=True)
    commit = _run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    subprocess.run(["git", "tag", "-s", "v1.2.3", "-m", "release"], cwd=repo, check=True)

    result = _run(str(SCRIPT), str(repo), "v1.2.3", commit, "main", cwd=repo, env=env)

    assert result.returncode != 0
    assert "commit" in result.stderr
    assert "valid foundation release signature" in result.stderr


def test_release_preflight_accepts_signed_tag_over_signed_non_root_commit(tmp_path: Path) -> None:
    """The inverse proof at the realistic RC-3 shape: a signed tag placed
    on a real, NON-root branch commit (not a fabricated snapshot) whose
    commit is itself also properly signed must still be accepted -- this
    fix must not have simply made the script reject everything."""
    repo, _key, env = _repo_and_key(tmp_path)
    subprocess.run(["git", "commit", "-qS", "-m", "initial"], cwd=repo, check=True)
    (repo / "content.txt").write_text("release v2\n", encoding="utf-8")
    subprocess.run(["git", "add", "content.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qS", "-m", "second, real branch commit"], cwd=repo, check=True)
    commit = _run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    subprocess.run(["git", "tag", "-s", "v1.2.4", "-m", "release"], cwd=repo, check=True)

    result = _run(str(SCRIPT), str(repo), "v1.2.4", commit, "main", cwd=repo, env=env)

    assert result.returncode == 0, result.stderr
    assert "foundation release signatures: verified" in result.stdout


def test_packager_preserves_remote_branch_context_for_tag_checkout() -> None:
    script = PACKAGER.read_text(encoding="utf-8")

    assert '--branch "${SOURCE_REF}" --no-single-branch' in script
    assert '--branch "${SOURCE_REF}" --single-branch' not in script


def test_release_preflight_accepts_packager_shaped_tag_checkout(tmp_path: Path) -> None:
    repo, _key, env = _repo_and_key(tmp_path)
    subprocess.run(["git", "commit", "-qS", "-m", "initial"], cwd=repo, check=True)
    (repo / "content.txt").write_text("release v2\n", encoding="utf-8")
    subprocess.run(["git", "add", "content.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qS", "-m", "release"], cwd=repo, check=True)
    commit = _run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    subprocess.run(
        ["git", "tag", "-s", "v1.2.5", "-m", "release"], cwd=repo, check=True
    )
    checkout = _publish_and_clone_tag(tmp_path, repo, "v1.2.5")

    branch_ref = _run(
        "git", "rev-parse", "--verify", "origin/main^{commit}", cwd=checkout
    )
    result = _run(
        str(SCRIPT), str(checkout), "v1.2.5", commit, "main", cwd=checkout, env=env
    )

    assert branch_ref.returncode == 0, branch_ref.stderr
    assert result.returncode == 0, result.stderr
    assert "ancestor of origin/main" in result.stdout


def test_release_preflight_rejects_signed_tag_outside_remote_main(
    tmp_path: Path,
) -> None:
    repo, _key, env = _repo_and_key(tmp_path)
    subprocess.run(["git", "commit", "-qS", "-m", "main"], cwd=repo, check=True)
    subprocess.run(["git", "switch", "-q", "-c", "release-side"], cwd=repo, check=True)
    (repo / "content.txt").write_text("unmerged release\n", encoding="utf-8")
    subprocess.run(["git", "add", "content.txt"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-qS", "-m", "unmerged release"], cwd=repo, check=True
    )
    commit = _run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    subprocess.run(
        ["git", "tag", "-s", "v1.2.6", "-m", "release"], cwd=repo, check=True
    )
    subprocess.run(["git", "switch", "-q", "main"], cwd=repo, check=True)
    checkout = _publish_and_clone_tag(tmp_path, repo, "v1.2.6")

    result = _run(
        str(SCRIPT), str(checkout), "v1.2.6", commit, "main", cwd=checkout, env=env
    )

    assert result.returncode != 0
    assert "is not an ancestor of origin/main" in result.stderr
