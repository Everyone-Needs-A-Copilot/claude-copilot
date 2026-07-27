import subprocess

from cc.core.ecosystem.policy import evaluate, verify_git_item


def test_non_executable_knowledge_does_not_require_code_signer():
    assert evaluate({"dimension": "knowledge"}) == "allow"


def test_executable_content_without_layer_signer_policy_blocks():
    assert evaluate({"dimension": "skills"}) == "block"


def test_git_item_requires_valid_allowlisted_fingerprint(tmp_path):
    (tmp_path / ".git").mkdir()

    def good(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, "G\nSHA256:abc123\nOrg signer\n", "")

    verified, signer = verify_git_item(
        tmp_path,
        "skills/review",
        ["sha256:ABC123"],
        run=good,
    )
    assert verified is True
    assert signer == "SHA256:abc123"


def test_git_item_rejects_valid_but_unapproved_signer(tmp_path):
    (tmp_path / ".git").mkdir()

    def unknown(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, "G\nSHA256:other\nOther signer\n", "")

    assert verify_git_item(tmp_path, "plugins/org", ["SHA256:approved"], run=unknown) == (
        False,
        "SHA256:other",
    )
