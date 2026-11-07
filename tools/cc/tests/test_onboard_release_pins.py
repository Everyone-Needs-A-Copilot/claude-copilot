"""Signed central tier pins survive onboarding; unfamiliar setups still stop."""
from __future__ import annotations

import copy
import subprocess

import pytest
import yaml

from cc.commands.onboard import _manifest_adoption_plan
from cc.core.ecosystem import policy


@pytest.fixture
def pinned_manifest(tmp_path, monkeypatch):
    key = tmp_path / "release-key"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
    public = key.with_suffix(".pub")
    fingerprint = subprocess.check_output(["ssh-keygen", "-lf", str(public)], text=True).split()[1]
    monkeypatch.setattr(policy, "FOUNDATION_SSH_SIGNING_KEYS", {fingerprint: public.read_text().strip()})
    repo = tmp_path / "layer"
    repo.mkdir()
    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    git("init", "-q", "-b", "main")
    for name, value in [("user.name", "Fixture"), ("user.email", "fixture@example.invalid"),
                        ("gpg.format", "ssh"), ("user.signingkey", str(key)),
                        ("core.hooksPath", "/dev/null")]:
        git("config", name, value)
    origin = "git@github-work:Acme/claude-copilot-internal.git"
    git("remote", "add", "origin", origin)
    (repo / "skills").mkdir()
    (repo / "skills" / "example.md").write_text("release payload\n")
    git("add", ".")
    git("commit", "-qS", "-m", "signed source")
    git("tag", "-s", "v1.2.3", "-m", "signed release")
    row = {"id": "claude-organization", "role": "organization", "rank": 30,
           "product": "claude", "source": {"repo": origin, "ref": "v1.2.3", "path": str(repo)},
           "auth": "work", "activation": "always", "policy": {"allowed_signers": [fingerprint]}}
    existing = {"version": 1, "org": "Acme", "layers": [row]}
    desired = copy.deepcopy(existing)
    desired["layers"][0]["source"]["ref"] = "main"
    desired["layers"][0]["policy"]["allowed_signers"] = []
    return tmp_path / "layers.yml", existing, desired, git


@pytest.mark.parametrize("role", ["organization", "department"])
def test_verified_central_pin_and_policy_are_preserved(pinned_manifest, role):
    target, existing, desired, _ = pinned_manifest
    for payload in (existing, desired):
        row = payload["layers"][0]
        row["role"] = role
        if role == "department":
            row.update(id="claude-department-accounting", rank=20, unit="accounting")
    target.write_text(yaml.safe_dump(existing))
    before = target.read_bytes()
    original_desired = copy.deepcopy(desired)
    plan = _manifest_adoption_plan(desired, target)
    assert plan.action == "reuse"
    assert plan.payload == existing
    assert desired == original_desired
    assert target.read_bytes() == before


@pytest.mark.parametrize("change", ["branch", "unsigned", "wrong-repo", "wrong-origin", "wrong-org",
                                     "extra-field", "subpath", "signer-policy", "rank", "activation"])
def test_unverified_or_customized_pin_stays_review_only(pinned_manifest, change):
    target, existing, desired, git = pinned_manifest
    row = existing["layers"][0]
    if change == "branch": row["source"]["ref"] = "custom"
    elif change == "unsigned":
        git("-c", "tag.gpgsign=false", "tag", "-a", "v1.2.4", "-m", "unsigned")
        row["source"]["ref"] = "v1.2.4"
    elif change == "wrong-repo": row["source"]["repo"] = "git@github-work:Other/custom.git"
    elif change == "wrong-origin": git("remote", "set-url", "origin", "git@github-work:Other/custom.git")
    elif change == "wrong-org": existing["org"] = "Other"
    elif change == "extra-field": row["owner_customization"] = True
    elif change == "subpath": row["source"]["subpath"] = "custom"
    elif change == "signer-policy": row["policy"]["allowed_signers"] = ["SHA256:untrusted"]
    elif change == "rank": row["rank"] = 99
    elif change == "activation": row["activation"] = "manual"
    target.write_text(yaml.safe_dump(existing))
    before = target.read_bytes()
    plan = _manifest_adoption_plan(desired, target)
    assert plan.action == "review"
    assert plan.payload is None
    assert target.read_bytes() == before
