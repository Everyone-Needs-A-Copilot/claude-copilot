import subprocess
from pathlib import Path

from cc.core.ecosystem.policy import (
    evaluate,
    read_git_tree_snapshot,
    verify_git_item,
    verify_git_item_provenance,
)

_TAG_OID = "a" * 40
_COMMIT_OID = "b" * 40


def test_non_executable_knowledge_does_not_require_code_signer():
    assert evaluate({"dimension": "knowledge"}) == "allow"


def test_executable_content_without_layer_signer_policy_blocks():
    assert evaluate({"dimension": "skills"}) == "block"


# ---------------------------------------------------------------------------
# Mocked-`run` unit tests -- exercise the tag-verify + tree-membership logic
# in isolation (security review blocker 2, 2026-08-10: `verify_git_item` no
# longer walks `git log -- path`; it verifies the pinned tag's signature,
# then confirms the item exists in the exact tree that tag's commit points
# at -- `git cat-file -e <commit>:<path>`).
# ---------------------------------------------------------------------------


def test_git_item_accepts_signed_tag_covering_item_in_its_tree(tmp_path):
    (tmp_path / ".git").mkdir()
    calls = []
    observed = {}

    def fake(args, **kwargs):
        calls.append(list(args))
        if args[-1].endswith("^{tag}"):
            return subprocess.CompletedProcess(args, 0, f"{_TAG_OID}\n", "")
        if "verify-tag" in args:
            trust_arg = next(v for v in args if v.startswith("gpg.ssh.allowedSignersFile="))
            observed["trust"] = Path(trust_arg.split("=", 1)[1]).read_text(encoding="utf-8")
            return subprocess.CompletedProcess(
                args, 0, "", 'Good "git" signature for enac-foundation with ED25519 key SHA256:ABC123\n'
            )
        if "rev-parse" in args:
            return subprocess.CompletedProcess(args, 0, f"{_COMMIT_OID}\n", "")
        if "cat-file" in args:
            return subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(f"unexpected git invocation: {args}")

    verified, signer = verify_git_item(
        tmp_path,
        "skills/review",
        ["sha256:ABC123"],
        ref="v5.13.23",
        run=fake,
        _trusted_keys={"SHA256:ABC123": "ssh-ed25519 AAAATESTKEY"},
    )

    assert verified is True
    assert signer == "SHA256:ABC123"
    assert len(calls) == 4
    capture_call, tag_call, rev_parse_call, cat_file_call = calls

    # Step 0: capture one immutable annotated-tag object identity from the
    # mutable name. Every later command uses this object id.
    assert capture_call == [
        "git", "-C", str(tmp_path), "rev-parse", "--verify", "v5.13.23^{tag}",
    ]

    # Step 1: the TAG itself is verified, using a trust file scoped to
    # exactly the compiled-key/manifest-signer intersection.
    assert observed["trust"] == (
        'enac-foundation namespaces="git" ssh-ed25519 AAAATESTKEY\n'
    )
    assert tag_call[-2:] == ["verify-tag", _TAG_OID]

    # Step 2: the SAME ref is resolved to the commit its signature covers.
    assert rev_parse_call == [
        "git", "-C", str(tmp_path), "rev-parse", f"{_TAG_OID}^{{commit}}",
    ]

    # Step 3: tree membership is checked at that resolved commit -- never a
    # `git log` walk.
    assert cat_file_call == [
        "git", "-C", str(tmp_path), "cat-file", "-e", f"{_COMMIT_OID}:skills/review",
    ]


def test_git_item_rejects_unsigned_or_wrongly_signed_tag(tmp_path):
    """A tag that fails `git verify-tag` (unsigned, revoked, or signed by an
    unapproved key) blocks immediately -- no commit resolution or tree
    lookup is ever attempted for it."""
    (tmp_path / ".git").mkdir()
    calls = []

    def fake(args, **kwargs):
        calls.append(list(args))
        if args[-1].endswith("^{tag}"):
            return subprocess.CompletedProcess(args, 0, f"{_TAG_OID}\n", "")
        return subprocess.CompletedProcess(args, 1, "", "No principal matched.\n")

    verified, signer = verify_git_item(
        tmp_path,
        "skills/review",
        ["SHA256:approved"],
        ref="v5.13.23",
        run=fake,
        _trusted_keys={"SHA256:approved": "ssh-ed25519 AAAAAPPROVED"},
    )

    assert (verified, signer) == (False, None)
    assert len(calls) == 2
    assert calls[1][-2:] == ["verify-tag", _TAG_OID]


def test_git_item_rejects_valid_but_unapproved_signer(tmp_path):
    """Defense in depth: even when `git verify-tag` itself reports success,
    the extracted fingerprint is independently re-checked against the
    allowlist before the tree is ever consulted."""
    (tmp_path / ".git").mkdir()
    calls = []

    def fake(args, **kwargs):
        calls.append(list(args))
        if args[-1].endswith("^{tag}"):
            return subprocess.CompletedProcess(args, 0, f"{_TAG_OID}\n", "")
        return subprocess.CompletedProcess(
            args, 0, "", 'Good "git" signature for x with ED25519 key SHA256:other\n'
        )

    assert verify_git_item(
        tmp_path,
        "plugins/org",
        ["SHA256:approved"],
        ref="v1.0.0",
        run=fake,
        _trusted_keys={"SHA256:approved": "ssh-ed25519 AAAAAPPROVED"},
    ) == (False, "SHA256:other")
    assert len(calls) == 2


def test_git_item_rejects_manifest_fingerprint_not_compiled_into_cc(tmp_path):
    (tmp_path / ".git").mkdir()

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("Git must not run for an untrusted manifest fingerprint")

    assert verify_git_item(
        tmp_path,
        "plugins/org",
        ["SHA256:manifest-only"],
        ref="v1.0.0",
        run=must_not_run,
        _trusted_keys={"SHA256:compiled": "ssh-ed25519 AAAACOMPILED"},
    ) == (
        False,
        None,
    )


def test_git_item_requires_ref_and_fails_closed_without_one(tmp_path):
    """Blocker 2 fix: there is no blind-HEAD/`git log` fallback left to run.
    Omitting `ref` (or a layer whose manifest never resolved one) blocks
    outright -- it must never silently fall back to a weaker check."""
    (tmp_path / ".git").mkdir()

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("Git must not run when there is no pinned tag to verify")

    assert verify_git_item(
        tmp_path,
        "skills/review",
        ["SHA256:approved"],
        run=must_not_run,
        _trusted_keys={"SHA256:approved": "ssh-ed25519 AAAAAPPROVED"},
    ) == (False, None)


def test_git_item_blocks_when_ref_does_not_resolve_after_signed_tag(tmp_path):
    """A tag can verify while `ref` still fails to resolve to a commit in
    THIS checkout (never fetched locally, etc.) -- fail closed rather than
    treat an unresolved commit as ok."""
    (tmp_path / ".git").mkdir()
    calls = []

    def fake(args, **kwargs):
        calls.append(list(args))
        if args[-1].endswith("^{tag}"):
            return subprocess.CompletedProcess(args, 0, f"{_TAG_OID}\n", "")
        if "verify-tag" in args:
            return subprocess.CompletedProcess(
                args, 0, "", 'Good "git" signature for x with ED25519 key SHA256:approved\n'
            )
        if "rev-parse" in args:
            return subprocess.CompletedProcess(args, 128, "", "fatal: ambiguous argument")
        raise AssertionError(f"unexpected git invocation: {args}")

    assert verify_git_item(
        tmp_path,
        "skills/review",
        ["SHA256:approved"],
        ref="v9.9.9-never-fetched",
        run=fake,
        _trusted_keys={"SHA256:approved": "ssh-ed25519 AAAAAPPROVED"},
    ) == (False, None)
    assert len(calls) == 3


def test_git_item_blocks_when_item_missing_from_signed_tags_tree(tmp_path):
    """The exact regression this fix targets: a signed tag over a real,
    non-orphan branch commit that simply never touched this path. The old
    `git log -- path` technique TREESAME-pruned past commits like this to
    an unrelated ancestor; the new technique asks the tree directly and
    correctly reports the item absent."""
    (tmp_path / ".git").mkdir()
    calls = []

    def fake(args, **kwargs):
        calls.append(list(args))
        if args[-1].endswith("^{tag}"):
            return subprocess.CompletedProcess(args, 0, f"{_TAG_OID}\n", "")
        if "verify-tag" in args:
            return subprocess.CompletedProcess(
                args, 0, "", 'Good "git" signature for x with ED25519 key SHA256:approved\n'
            )
        if "rev-parse" in args:
            return subprocess.CompletedProcess(args, 0, f"{_COMMIT_OID}\n", "")
        if "cat-file" in args:
            return subprocess.CompletedProcess(
                args, 128, "", "fatal: path 'skills/review' does not exist"
            )
        raise AssertionError(f"unexpected git invocation: {args}")

    assert verify_git_item(
        tmp_path,
        "skills/review",
        ["SHA256:approved"],
        ref="v5.13.23",
        run=fake,
        _trusted_keys={"SHA256:approved": "ssh-ed25519 AAAAAPPROVED"},
    ) == (False, None)
    assert len(calls) == 4


def test_git_item_verifies_repo_relative_path_from_layer_subpath(tmp_path):
    (tmp_path / ".git").mkdir()
    layer_root = tmp_path / ".claude"
    layer_root.mkdir()
    observed = {}

    def good(args, **kwargs):
        if args[-1].endswith("^{tag}"):
            return subprocess.CompletedProcess(args, 0, f"{_TAG_OID}\n", "")
        if "verify-tag" in args:
            observed["repo"] = args[args.index("-C") + 1]
            return subprocess.CompletedProcess(
                args, 0, "", 'Good "git" signature for x with ED25519 key SHA256:approved\n'
            )
        if "rev-parse" in args:
            return subprocess.CompletedProcess(args, 0, f"{_COMMIT_OID}\n", "")
        if "cat-file" in args:
            observed["path"] = args[-1]
            return subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(f"unexpected git invocation: {args}")

    assert verify_git_item(
        layer_root,
        "commands/protocol.md",
        ["SHA256:approved"],
        ref="v5.13.23",
        run=good,
        _trusted_keys={"SHA256:approved": "ssh-ed25519 AAAAAPPROVED"},
    ) == (True, "SHA256:approved")
    assert observed == {
        "repo": str(tmp_path),
        "path": f"{_COMMIT_OID}:.claude/commands/protocol.md",
    }


# ---------------------------------------------------------------------------
# Real-git reproduction (no mocking) -- security review blocker 2:
# "verify_git_item will mass-block the entire ecosystem on the first real
# release". Builds a throwaway repo whose signed tag points at a real,
# non-orphan branch commit that does NOT itself touch the tracked path
# (exactly `foundation-snapshot-release.py`'s post-RC-3 shape), and proves
# `verify_git_item` accepts the legitimate item while still blocking
# genuinely unsigned/untagged content.
# ---------------------------------------------------------------------------


def _init_signing_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    key = tmp_path / "release-key"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True
    )
    fingerprint = subprocess.run(
        ["ssh-keygen", "-lf", str(key) + ".pub", "-E", "sha256"],
        capture_output=True, text=True, check=True,
    ).stdout.split()[1]
    public_key = " ".join(key.with_suffix(".pub").read_text(encoding="utf-8").split()[:2])
    for command in (
        ("git", "init", "-q"),
        ("git", "config", "user.name", "Release Test"),
        ("git", "config", "user.email", "release@example.invalid"),
        ("git", "config", "gpg.format", "ssh"),
        ("git", "config", "user.signingkey", str(key)),
    ):
        subprocess.run(command, cwd=repo, check=True)
    return repo, fingerprint, public_key


def test_git_item_real_repro_blocks_before_and_accepts_after_for_non_orphan_tag(tmp_path):
    repo, fingerprint, public_key = _init_signing_repo(tmp_path)

    (repo / "skills").mkdir()
    (repo / "skills" / "review").write_text("skill body\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "skills/review"], cwd=repo, check=True
    )
    subprocess.run(
        ["git", "commit", "-q", "--no-gpg-sign", "-m", "add skill (unsigned, ordinary dev commit)"],
        cwd=repo, check=True,
    )

    # A second, real, non-orphan commit that does NOT touch the tracked
    # path -- this is the branch tip the release tag is cut from, exactly
    # `foundation-snapshot-release.py`'s post-RC-3 shape (no fabricated
    # parentless commit).
    (repo / "unrelated.txt").write_text("unrelated change\n", encoding="utf-8")
    subprocess.run(["git", "add", "unrelated.txt"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "--no-gpg-sign", "-m", "unrelated release-prep commit"],
        cwd=repo, check=True,
    )
    subprocess.run(["git", "tag", "-s", "v1.0.0", "-m", "release"], cwd=repo, check=True)

    # BEFORE: reproduce the retired technique directly -- `git log -1
    # <tag> -- <path>` TREESAME-prunes past the signed tag to the older,
    # UNSIGNED commit that actually introduced the path, so its `%G?` is
    # `N` (no signature) rather than the tag's own valid signature.
    old_technique = subprocess.run(
        ["git", "-C", str(repo), "log", "-1", "--format=%G?", "v1.0.0", "--", "skills/review"],
        capture_output=True, text=True, check=True,
    )
    assert old_technique.stdout.strip() == "N", (
        "fixture invalid: the retired git-log technique must reproduce the "
        "landmine (TREESAME-pruned to an unsigned ancestor) for this test "
        "to prove anything"
    )

    # AFTER: the fixed `verify_git_item` verifies the TAG itself (not the
    # commit it points to) and confirms tree membership directly -- it
    # accepts the legitimate item.
    verified, signer = verify_git_item(
        repo,
        "skills/review",
        [fingerprint],
        ref="v1.0.0",
        _trusted_keys={fingerprint: public_key},
    )
    assert (verified, signer) == (True, fingerprint)

    # Still fails closed for content that is genuinely absent from the
    # signed tag's tree.
    assert verify_git_item(
        repo,
        "skills/does-not-exist",
        [fingerprint],
        ref="v1.0.0",
        _trusted_keys={fingerprint: public_key},
    ) == (False, None)


def test_git_item_real_repro_still_blocks_genuinely_unsigned_tag(tmp_path):
    repo, fingerprint, public_key = _init_signing_repo(tmp_path)

    (repo / "skills").mkdir()
    (repo / "skills" / "review").write_text("skill body\n", encoding="utf-8")
    subprocess.run(["git", "add", "skills/review"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "--no-gpg-sign", "-m", "add skill"], cwd=repo, check=True
    )
    # Lightweight (unsigned) tag -- `git verify-tag` must reject it outright.
    subprocess.run(["git", "tag", "v1.0.0"], cwd=repo, check=True)

    assert verify_git_item(
        repo,
        "skills/review",
        [fingerprint],
        ref="v1.0.0",
        _trusted_keys={fingerprint: public_key},
    ) == (False, None)


def test_provenance_binds_one_tag_object_across_ref_switch(tmp_path):
    """A mutable tag name cannot lend its signature to replacement bytes."""
    repo, fingerprint, public_key = _init_signing_repo(tmp_path)
    skill = repo / "skills" / "review" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("signed bytes\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "--no-gpg-sign", "-m", "signed tree"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "tag", "-s", "v1.0.0", "-m", "signed release"],
        cwd=repo,
        check=True,
    )
    signed_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    skill.write_text("unsigned replacement bytes\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "--no-gpg-sign", "-m", "replacement"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "tag", "-a", "unsigned-replacement", "-m", "unsigned"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "checkout", "-q", "--detach", signed_commit], cwd=repo, check=True
    )

    switched = False

    def switch_after_verification(args, **kwargs):
        nonlocal switched
        result = subprocess.run(args, **kwargs)
        if not switched and "verify-tag" in args and result.returncode == 0:
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "update-ref",
                    "refs/tags/v1.0.0",
                    "refs/tags/unsigned-replacement",
                ],
                check=True,
            )
            switched = True
        return result

    proof = verify_git_item_provenance(
        repo,
        "skills/review",
        [fingerprint],
        ref="v1.0.0",
        run=switch_after_verification,
        _trusted_keys={fingerprint: public_key},
    )
    assert proof is not None
    snapshot = read_git_tree_snapshot(repo, proof.tree)
    assert snapshot is not None
    assert [item.content for item in snapshot.files] == [b"signed bytes\n"]
