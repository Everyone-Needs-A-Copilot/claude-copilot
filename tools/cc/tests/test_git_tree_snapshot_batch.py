"""Exact byte and fail-closed framing contracts for batched Git snapshots."""

import hashlib
import subprocess

import pytest
from cc.core.ecosystem import policy


def _oid(content, algorithm="sha1"):
    return hashlib.new(
        algorithm, b"blob " + str(len(content)).encode() + b"\0" + content
    ).hexdigest()


def _frame(content, algorithm="sha1"):
    return f"{_oid(content, algorithm)} blob {len(content)}\n".encode() + content + b"\n"


@pytest.mark.parametrize("algorithm", ["sha1", "sha256"])
def test_real_git_snapshot_preserves_bytes_modes_identity_and_uses_one_batch(
    tmp_path, monkeypatch, algorithm
):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-q", f"--object-format={algorithm}", str(repo)], check=True
    )
    expected = {
        "empty": (b"", 0o644),
        "nested/caf\u00e9.bin": (b"\0\xff\nblob 4\n\x80", 0o644),
        "run": (b"#!/bin/sh\nexit 0\n", 0o755),
        "duplicate": (b"#!/bin/sh\nexit 0\n", 0o644),
    }
    for path, (content, mode) in expected.items():
        file = repo / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content)
        file.chmod(mode)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    tree = subprocess.check_output(["git", "-C", str(repo), "write-tree"]).decode().strip()
    # Working-tree drift must never affect reads through the captured tree.
    (repo / "run").write_bytes(b"unsigned working bytes")
    original_run = subprocess.run
    calls = []

    def capture(args, **kwargs):
        calls.append((args, kwargs))
        return original_run(args, **kwargs)

    monkeypatch.setattr(policy.subprocess, "run", capture)
    snapshot = policy.read_git_tree_snapshot(repo, tree)
    assert snapshot is not None
    expected_files = tuple(
        policy.GitTreeFile(path, mode, _oid(content, algorithm), content)
        for path, (content, mode) in sorted(expected.items())
    )
    reference = policy.GitTreeSnapshot(tree=tree, files=expected_files)
    assert snapshot == reference
    assert snapshot.manifest() == reference.manifest()
    assert snapshot.fingerprint() == reference.fingerprint()
    assert len(calls) == 2
    assert calls[1][0][-2:] == ["cat-file", "--batch"]
    requested = calls[1][1]["input"].splitlines()
    assert len(requested) == 3
    assert set(requested) == {item.oid.encode() for item in expected_files}
    assert calls[1][1]["timeout"] == 8.0


@pytest.mark.parametrize(
    "response",
    [
        b"",
        b"missing\n",
        f"{_oid(b'abc')} missing\n".encode(),
        f"{_oid(b'abc')} tree 3\nabc\n".encode(),
        f"{'0' * 40} blob 3\nabc\n".encode(),
        f"{_oid(b'abc')} blob -1\nabc\n".encode(),
        f"{_oid(b'abc')} blob +3\nabc\n".encode(),
        f"{_oid(b'abc')} blob 03\nabc\n".encode(),
        f"{_oid(b'abc')} blob nope\nabc\n".encode(),
        f"{_oid(b'abc')} blob 3 extra\nabc\n".encode(),
        f"{_oid(b'abc')}  blob 3\nabc\n".encode(),
        f"{_oid(b'abc')} blob 3\nabc".encode(),
        f"{_oid(b'abc')} blob 3\nab\n".encode(),
        f"{_oid(b'abc')} blob 3\nabcX\n".encode(),
        f"{_oid(b'abc')} blob 2\nabc\n".encode(),
        f"{_oid(b'abc')} blob 4\nabc\n".encode(),
        f"{_oid(b'abc')} blob 3\nxyz\n".encode(),
        _frame(b"abc") + b"unexpected",
        _frame(b"abc") + _frame(b"abc"),
        f"{_oid(b'abc')} blob ".encode() + b"9" * 5000 + b"\nabc\n",
    ],
)
def test_rejects_invalid_batch_response(response):
    assert policy._parse_git_blob_batch(response, [_oid(b"abc")]) is None


def test_multiple_frames_are_bound_to_request_order_and_complete():
    first, second = b"\x00\xff\n", b""
    expected = [_oid(first), _oid(second)]
    assert policy._parse_git_blob_batch(_frame(first) + _frame(second), expected) == {
        expected[0]: first,
        expected[1]: second,
    }
    assert policy._parse_git_blob_batch(_frame(second) + _frame(first), expected) is None
    assert policy._parse_git_blob_batch(_frame(first), expected) is None


@pytest.mark.parametrize("failure", ["exit", "timeout", "oserror", "malformed"])
def test_snapshot_fails_closed_when_batch_read_fails(tmp_path, monkeypatch, failure):
    oid = _oid(b"abc")

    def run(args, **kwargs):
        if "ls-tree" in args:
            return subprocess.CompletedProcess(args, 0, f"100644 blob {oid}\tfile\0".encode())
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args, 8)
        if failure == "oserror":
            raise OSError("unavailable")
        return subprocess.CompletedProcess(
            args, 1 if failure == "exit" else 0, b"invalid\n"
        )

    monkeypatch.setattr(policy.subprocess, "run", run)
    assert policy.read_git_tree_snapshot(tmp_path, "a" * 40) is None


@pytest.mark.parametrize(
    "listing",
    [
        b"",
        f"120000 blob {_oid(b'abc')}\tlink\0".encode(),
        f"160000 commit {'a' * 40}\tsubmodule\0".encode(),
        f"100644 blob {_oid(b'abc')}\t../escape\0".encode(),
        f"100644 blob {_oid(b'abc')}\t/absolute\0".encode(),
        f"100644 blob {_oid(b'abc')}\tbad\npath\0".encode(),
        f"100644 blob {_oid(b'abc')}\tfile\0".encode() * 2,
    ],
)
def test_listing_shape_rejections_remain_before_batch_read(tmp_path, monkeypatch, listing):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, listing)

    monkeypatch.setattr(policy.subprocess, "run", run)
    assert policy.read_git_tree_snapshot(tmp_path, "a" * 40) is None
    assert len(calls) == 1
