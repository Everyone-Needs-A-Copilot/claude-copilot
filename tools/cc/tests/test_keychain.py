"""Tests for cc.core.keychain — a thin, Darwin-only wrapper around the
`security` CLI.

`_run` is always injected (a fake matching `subprocess.run`'s signature),
so these tests NEVER shell out to a real `security` binary or touch a
real keychain, and never run on a real non-Darwin check either --
`sys.platform` is monkeypatched explicitly wherever it matters.
"""

from __future__ import annotations

from typing import Any, NamedTuple

import pytest
from cc.core.keychain import KeychainUnavailable, delete_secret, get_secret, set_secret

SERVICE = "com.everyoneneedsacopilot.copilot.github"


class _FakeResult(NamedTuple):
    returncode: int
    stdout: str = ""
    stderr: str = ""


class _RecordingRun:
    """Fake `subprocess.run` that records the argv it was called with and
    returns a pre-scripted result."""

    def __init__(self, result: _FakeResult) -> None:
        self.result = result
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> _FakeResult:
        self.calls.append(argv)
        return self.result


@pytest.fixture(autouse=True)
def _force_darwin(monkeypatch):
    """Every test here exercises the "available" path by default; the
    non-Darwin tests monkeypatch `sys.platform` themselves."""
    monkeypatch.setattr("cc.core.keychain.sys.platform", "darwin")


# ---------------------------------------------------------------------------
# set_secret()
# ---------------------------------------------------------------------------


def test_set_secret_invokes_add_generic_password_with_update_flag():
    run = _RecordingRun(_FakeResult(returncode=0))
    set_secret("octocat", "s3cr3t", service=SERVICE, _run=run)

    assert len(run.calls) == 1
    assert run.calls[0] == [
        "security",
        "add-generic-password",
        "-a",
        "octocat",
        "-s",
        SERVICE,
        "-w",
        "s3cr3t",
        "-U",
    ]


def test_set_secret_never_raises_on_nonzero_exit():
    run = _RecordingRun(_FakeResult(returncode=1, stderr="boom"))
    # Must not raise -- fail-open, mirrors get/delete.
    set_secret("octocat", "s3cr3t", service=SERVICE, _run=run)


def test_set_secret_never_returns_the_secret():
    run = _RecordingRun(_FakeResult(returncode=0))
    result = set_secret("octocat", "s3cr3t", service=SERVICE, _run=run)
    assert result is None


# ---------------------------------------------------------------------------
# get_secret()
# ---------------------------------------------------------------------------


def test_get_secret_invokes_find_generic_password():
    run = _RecordingRun(_FakeResult(returncode=0, stdout="s3cr3t\n"))
    result = get_secret("octocat", service=SERVICE, _run=run)

    assert run.calls == [
        ["security", "find-generic-password", "-a", "octocat", "-s", SERVICE, "-w"]
    ]
    assert result == "s3cr3t"


def test_get_secret_nonzero_exit_returns_none():
    run = _RecordingRun(_FakeResult(returncode=44, stderr="not found"))
    assert get_secret("octocat", service=SERVICE, _run=run) is None


def test_get_secret_strips_trailing_newline_only():
    run = _RecordingRun(_FakeResult(returncode=0, stdout="s3cr3t  \n"))
    assert get_secret("octocat", service=SERVICE, _run=run) == "s3cr3t  "


# ---------------------------------------------------------------------------
# delete_secret()
# ---------------------------------------------------------------------------


def test_delete_secret_invokes_delete_generic_password():
    run = _RecordingRun(_FakeResult(returncode=0))
    result = delete_secret("octocat", service=SERVICE, _run=run)

    assert run.calls == [
        ["security", "delete-generic-password", "-a", "octocat", "-s", SERVICE]
    ]
    assert result is True


def test_delete_secret_nonzero_exit_returns_false():
    run = _RecordingRun(_FakeResult(returncode=1))
    assert delete_secret("octocat", service=SERVICE, _run=run) is False


# ---------------------------------------------------------------------------
# Non-Darwin -> KeychainUnavailable
# ---------------------------------------------------------------------------


def test_set_secret_raises_on_non_darwin(monkeypatch):
    monkeypatch.setattr("cc.core.keychain.sys.platform", "linux")
    run = _RecordingRun(_FakeResult(returncode=0))
    with pytest.raises(KeychainUnavailable):
        set_secret("octocat", "s3cr3t", service=SERVICE, _run=run)
    assert run.calls == []


def test_get_secret_raises_on_non_darwin(monkeypatch):
    monkeypatch.setattr("cc.core.keychain.sys.platform", "win32")
    run = _RecordingRun(_FakeResult(returncode=0))
    with pytest.raises(KeychainUnavailable):
        get_secret("octocat", service=SERVICE, _run=run)
    assert run.calls == []


def test_delete_secret_raises_on_non_darwin(monkeypatch):
    monkeypatch.setattr("cc.core.keychain.sys.platform", "linux")
    run = _RecordingRun(_FakeResult(returncode=0))
    with pytest.raises(KeychainUnavailable):
        delete_secret("octocat", service=SERVICE, _run=run)
    assert run.calls == []
