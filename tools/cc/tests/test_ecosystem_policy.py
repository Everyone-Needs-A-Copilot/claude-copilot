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


def test_git_item_verifies_at_pinned_ref_not_blind_head(tmp_path):
    """G-9 (task 215 blocker fix): when `ref` resolves locally, `git log`
    is scoped to that resolved commit, not implicit HEAD -- a checkout
    whose HEAD is on an unrelated branch (`parentless-snapshot-match`)
    still verifies correctly against the commit the manifest actually
    pinned."""
    (tmp_path / ".git").mkdir()
    calls = []

    def fake(args, **kwargs):
        calls.append(list(args))
        if "rev-parse" in args:
            return subprocess.CompletedProcess(args, 0, "deadbeefcafe1234\n", "")
        return subprocess.CompletedProcess(
            args, 0, "G\nSHA256:approved\nENAC foundation\n", ""
        )

    verified, signer = verify_git_item(
        tmp_path,
        "skills/review",
        ["SHA256:approved"],
        ref="v5.13.23",
        run=fake,
        _trusted_keys={"SHA256:approved": "ssh-ed25519 AAAAAPPROVED"},
    )

    assert verified is True
    assert signer == "SHA256:approved"
    assert len(calls) == 2
    rev_parse_call, log_call = calls
    assert rev_parse_call == [
        "git", "-C", str(tmp_path), "rev-parse", "v5.13.23^{commit}",
    ]
    # The RESOLVED commit -- never the bare ref name, never nothing at all
    # (implicit HEAD) -- sits immediately before `--` in the log call.
    assert log_call[log_call.index("--") - 1] == "deadbeefcafe1234"


def test_git_item_falls_back_to_blind_head_when_ref_unresolvable(tmp_path):
    """A `ref` that fails to resolve locally (never fetched, unknown
    revision) must fall back to exactly today's blind-HEAD check -- never
    a new failure mode, and never silently treated as verified."""
    (tmp_path / ".git").mkdir()
    calls = []

    def fake(args, **kwargs):
        calls.append(list(args))
        if "rev-parse" in args:
            return subprocess.CompletedProcess(
                args, 128, "", "fatal: ambiguous argument"
            )
        return subprocess.CompletedProcess(
            args, 0, "G\nSHA256:approved\nENAC foundation\n", ""
        )

    verified, signer = verify_git_item(
        tmp_path,
        "skills/review",
        ["SHA256:approved"],
        ref="v9.9.9-never-fetched",
        run=fake,
        _trusted_keys={"SHA256:approved": "ssh-ed25519 AAAAAPPROVED"},
    )

    assert verified is True
    assert signer == "SHA256:approved"
    assert len(calls) == 2
    log_call = calls[1]
    # No revision was inserted -- the format flag sits immediately before
    # `--`, exactly the same shape as the no-`ref`-at-all call.
    assert log_call[log_call.index("--") - 1] == "--format=%G?%n%GF%n%GS"


def test_git_item_without_ref_is_unchanged_from_before_this_fix(tmp_path):
    """`ref` defaults to `None` -- omitting it entirely (every pre-existing
    caller) must produce the exact same single-call, blind-HEAD shape as
    always, with zero extra `run()` invocations."""
    (tmp_path / ".git").mkdir()
    calls = []

    def fake(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(
            args, 0, "G\nSHA256:approved\nENAC foundation\n", ""
        )

    verified, signer = verify_git_item(
        tmp_path,
        "skills/review",
        ["SHA256:approved"],
        run=fake,
        _trusted_keys={"SHA256:approved": "ssh-ed25519 AAAAAPPROVED"},
    )

    assert verified is True
    assert len(calls) == 1
    assert calls[0][calls[0].index("--") - 1] == "--format=%G?%n%GF%n%GS"


def test_git_item_verifies_repo_relative_path_from_layer_subpath(tmp_path):
    (tmp_path / ".git").mkdir()
    layer_root = tmp_path / ".claude"
    layer_root.mkdir()
    observed = {}

    def good(args, **kwargs):
        observed["repo"] = args[args.index("-C") + 1]
        observed["path"] = args[-1]
        return subprocess.CompletedProcess(
            args, 0, "G\nSHA256:approved\nENAC foundation\n", ""
        )

    assert verify_git_item(
        layer_root,
        "commands/protocol.md",
        ["SHA256:approved"],
        run=good,
        _trusted_keys={"SHA256:approved": "ssh-ed25519 AAAAAPPROVED"},
    ) == (True, "SHA256:approved")
    assert observed == {
        "repo": str(tmp_path),
        "path": ".claude/commands/protocol.md",
    }
