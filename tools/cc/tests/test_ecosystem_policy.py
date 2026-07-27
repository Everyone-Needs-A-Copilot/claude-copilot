import subprocess
from pathlib import Path

from cc.core.ecosystem.policy import evaluate, verify_git_item


def test_non_executable_knowledge_does_not_require_code_signer():
    assert evaluate({"dimension": "knowledge"}) == "allow"


def test_executable_content_without_layer_signer_policy_blocks():
    assert evaluate({"dimension": "skills"}) == "block"


def test_git_item_requires_valid_allowlisted_fingerprint(tmp_path):
    (tmp_path / ".git").mkdir()
    observed = {}

    def good(args, **kwargs):
        trust_arg = next(
            value
            for value in args
            if value.startswith("gpg.ssh.allowedSignersFile=")
        )
        trust_path = trust_arg.split("=", 1)[1]
        observed["trust"] = Path(trust_path).read_text(encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, "G\nSHA256:abc123\nOrg signer\n", "")

    verified, signer = verify_git_item(
        tmp_path,
        "skills/review",
        ["sha256:ABC123"],
        run=good,
        _trusted_keys={
            "SHA256:ABC123": "ssh-ed25519 AAAATESTKEY"
        },
    )
    assert verified is True
    assert signer == "SHA256:abc123"
    assert observed["trust"] == (
        'enac-foundation namespaces="git" ssh-ed25519 AAAATESTKEY\n'
    )


def test_git_item_rejects_valid_but_unapproved_signer(tmp_path):
    (tmp_path / ".git").mkdir()

    def unknown(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, "G\nSHA256:other\nOther signer\n", "")

    assert verify_git_item(
        tmp_path,
        "plugins/org",
        ["SHA256:approved"],
        run=unknown,
        _trusted_keys={"SHA256:approved": "ssh-ed25519 AAAAAPPROVED"},
    ) == (
        False,
        "SHA256:other",
    )


def test_git_item_rejects_manifest_fingerprint_not_compiled_into_cc(tmp_path):
    (tmp_path / ".git").mkdir()

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("Git must not run for an untrusted manifest fingerprint")

    assert verify_git_item(
        tmp_path,
        "plugins/org",
        ["SHA256:manifest-only"],
        run=must_not_run,
        _trusted_keys={"SHA256:compiled": "ssh-ed25519 AAAACOMPILED"},
    ) == (
        False,
        None,
    )
