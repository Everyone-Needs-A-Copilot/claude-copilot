from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[3]
PACKAGER = ROOT / "scripts/package-cc-macos-release.sh"
VERIFIER = ROOT / "scripts/verify-foundation-release.sh"
WORKFLOW = ROOT / ".github/workflows/cc-macos-release.yml"


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


@pytest.mark.parametrize("integrated", [True, False])
def test_packager_verifies_real_tag_main_ancestry_before_building(
    tmp_path: Path, integrated: bool
) -> None:
    """Exercise the actual packager through source verification, without Apple or downloads."""
    origin = tmp_path / "origin"
    origin.mkdir()
    key = tmp_path / "test-release-key"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
    _git(origin, "init", "-q", "-b", "main")
    for name, value in (
        ("user.name", "Release fixture"),
        ("user.email", "release@example.invalid"),
        ("gpg.format", "ssh"),
        ("user.signingkey", str(key)),
    ):
        _git(origin, "config", name, value)
    (origin / "scripts").mkdir()
    shutil.copy2(VERIFIER, origin / "scripts/verify-foundation-release.sh")
    _git(origin, "add", ".")
    _git(origin, "commit", "-qS", "-m", "signed base")
    if not integrated:
        _git(origin, "switch", "-qc", "unmerged")
    _git(origin, "commit", "-qS", "--allow-empty", "-m", "signed release")
    commit = _git(origin, "rev-parse", "HEAD")
    _git(origin, "tag", "-s", "v1.2.3", "-m", "signed final fixture")
    _git(origin, "switch", "-q", "main")
    if integrated:
        _git(origin, "commit", "-qS", "--allow-empty", "-m", "later main commit")

    tools = tmp_path / "tools"
    tools.mkdir()
    real_git = shutil.which("git")
    assert real_git is not None
    git_wrapper = tools / "git"
    git_wrapper.write_text(
        f'#!{sys.executable}\n'
        'import os, sys\n'
        'args=sys.argv[1:]\n'
        'if args[-3:]==["remote", "get-url", "origin"]:\n'
        ' print(os.environ["PACKAGING_TEST_ORIGIN"])\n'
        ' raise SystemExit(0)\n'
        'os.execv(os.environ["PACKAGING_TEST_GIT"], [os.environ["PACKAGING_TEST_GIT"], *args])\n'
    )
    git_wrapper.chmod(0o755)
    curl = tools / "curl"
    curl.write_text('#!/bin/sh\necho REACHED_VERIFIED_SOURCE >&2\nexit 91\n')
    curl.chmod(0o755)
    # These commands are presence-checked before source verification. A fixture
    # must fail if the packager calls one before its source has been verified.
    for name in ("arch", "codesign", "ditto", "file", "install_name_tool", "lipo", "otool", "pkgutil", "shasum", "unzip", "uv", "xcrun"):
        stub = tools / name
        stub.write_text(f'#!/bin/sh\necho "Unexpected pre-verification call: {name}" >&2\nexit 92\n')
        stub.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{tools}{os.pathsep}{env['PATH']}",
            "PACKAGING_TEST_ORIGIN": str(origin),
            "PACKAGING_TEST_GIT": real_git,
            "CT_SIGN_IDENTITY": "fixture identity",
            "CT_NOTARY_KEYCHAIN_PROFILE": "",
            "CT_NOTARY_KEY_ID": "fixture key id",
            "CT_NOTARY_KEY_ISSUER": "fixture issuer",
            "CT_NOTARY_KEY_PATH": str(tmp_path / "unused-fixture-key.p8"),
            "FOUNDATION_RELEASE_PRINCIPAL": "fixture-foundation",
            "FOUNDATION_RELEASE_PUBLIC_KEY": key.with_suffix(".pub").read_text().strip(),
        }
    )
    result = subprocess.run(
        [str(PACKAGER), "--source-ref", "v1.2.3", "--source-commit", commit,
         "--output-dir", str(tmp_path / "unused-build-output")],
        env=env, capture_output=True, text=True, check=False,
    )
    output = result.stdout + result.stderr
    if integrated:
        assert result.returncode == 91, output
        assert "foundation release signatures: verified" in output
        assert "ancestor of origin/main" in output
        assert "REACHED_VERIFIED_SOURCE" in output
    else:
        assert result.returncode != 0, output
        assert "not an ancestor of origin/main" in output
        assert "REACHED_VERIFIED_SOURCE" not in output


def test_ci_fails_closed_when_apple_inputs_are_absent() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    step = next(
        step for step in workflow["jobs"]["package"]["steps"]
        if step.get("name") == "Validate release credentials"
    )
    env = os.environ.copy()
    for name in step["env"]:
        env.pop(name, None)
    result = subprocess.run(
        ["bash", "-c", step["run"]], env=env,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "Required release secret is not configured: APPLE_CERTIFICATE" in result.stderr
