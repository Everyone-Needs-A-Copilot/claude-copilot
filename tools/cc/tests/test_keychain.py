"""Tests for cc.core.keychain — a thin, Darwin-only wrapper around the
`security` CLI.

`_run` is always injected (a fake matching `subprocess.run`'s signature),
so these tests NEVER shell out to a real `security` binary or touch a
real keychain, and never run on a real non-Darwin check either --
`sys.platform` is monkeypatched explicitly wherever it matters.
"""

from __future__ import annotations

import subprocess
from typing import Any, NamedTuple

import pytest
from cc.core.keychain import (
    KeychainUnavailable,
    delete_secret,
    get_secret,
    set_secret,
    set_secret_stdin,
)

SERVICE = "com.everyoneneedsacopilot.copilot.github"
CONNECT_SERVICE = "copilot-cli"


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
        # Every kwarg (e.g. `input=`) each call was made with, argv-call-index
        # aligned with `self.calls` -- lets a test assert a value travelled
        # via `input=` (stdin) and never via `self.calls` (argv).
        self.kwargs_calls: list[dict[str, Any]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> _FakeResult:
        self.calls.append(argv)
        self.kwargs_calls.append(kwargs)
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
    result = set_secret("octocat", "s3cr3t", service=SERVICE, _run=run)

    assert result is True
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


def test_set_secret_reports_nonzero_exit_without_raising():
    run = _RecordingRun(_FakeResult(returncode=1, stderr="boom"))
    assert set_secret("octocat", "s3cr3t", service=SERVICE, _run=run) is False


def test_set_secret_returns_only_confirmation():
    run = _RecordingRun(_FakeResult(returncode=0))
    result = set_secret("octocat", "s3cr3t", service=SERVICE, _run=run)
    assert result is True
    assert result != "s3cr3t"


# ---------------------------------------------------------------------------
# set_secret_stdin() -- the `cc connect` non-leaking writer
# ---------------------------------------------------------------------------


def test_set_secret_stdin_invokes_interactive_batch_mode_only():
    run = _RecordingRun(_FakeResult(returncode=0))
    result = set_secret_stdin(
        "INFISICAL_CLIENT_ID", "s3cr3t", service=CONNECT_SERVICE, _run=run
    )

    assert result is True
    assert len(run.calls) == 1
    assert run.calls[0] == ["security", "-i"]


def test_set_secret_stdin_never_places_value_in_argv():
    run = _RecordingRun(_FakeResult(returncode=0))
    set_secret_stdin("INFISICAL_CLIENT_ID", "s3cr3t", service=CONNECT_SERVICE, _run=run)

    assert "s3cr3t" not in run.calls[0]
    assert all("s3cr3t" not in str(token) for token in run.calls[0])


def test_set_secret_stdin_passes_value_only_via_stdin_input_kwarg():
    run = _RecordingRun(_FakeResult(returncode=0))
    set_secret_stdin("INFISICAL_CLIENT_ID", "s3cr3t", service=CONNECT_SERVICE, _run=run)

    stdin_text = run.kwargs_calls[0]["input"]
    assert "s3cr3t" in stdin_text
    assert stdin_text == (
        'add-generic-password -a "INFISICAL_CLIENT_ID" -s "copilot-cli" '
        '-w "s3cr3t" -U\n'
    )


def test_set_secret_stdin_escapes_quotes_and_backslashes_round_trip_safe():
    run = _RecordingRun(_FakeResult(returncode=0))
    set_secret_stdin(
        "NAME", 'ha"s a "quote\\and\\backslash', service=CONNECT_SERVICE, _run=run
    )

    stdin_text = run.kwargs_calls[0]["input"]
    assert stdin_text == (
        'add-generic-password -a "NAME" -s "copilot-cli" '
        '-w "ha\\"s a \\"quote\\\\and\\\\backslash" -U\n'
    )


def test_set_secret_stdin_rejects_newline_value_without_calling_security():
    run = _RecordingRun(_FakeResult(returncode=0))
    with pytest.raises(ValueError):
        set_secret_stdin("NAME", "line1\nline2", service=CONNECT_SERVICE, _run=run)
    assert run.calls == []


def test_set_secret_stdin_rejects_carriage_return_value_without_calling_security():
    run = _RecordingRun(_FakeResult(returncode=0))
    with pytest.raises(ValueError):
        set_secret_stdin("NAME", "a\rb", service=CONNECT_SERVICE, _run=run)
    assert run.calls == []


def test_set_secret_stdin_reports_nonzero_exit_without_raising():
    run = _RecordingRun(_FakeResult(returncode=1, stderr="boom"))
    assert (
        set_secret_stdin("NAME", "s3cr3t", service=CONNECT_SERVICE, _run=run) is False
    )


def test_set_secret_stdin_returns_false_on_timeout_without_raising():
    def timing_out(*args: Any, **kwargs: Any):
        raise subprocess.TimeoutExpired(cmd=["security", "-i"], timeout=15)

    assert (
        set_secret_stdin("NAME", "s3cr3t", service=CONNECT_SERVICE, _run=timing_out)
        is False
    )


def test_set_secret_stdin_raises_on_non_darwin(monkeypatch):
    monkeypatch.setattr("cc.core.keychain.sys.platform", "linux")
    run = _RecordingRun(_FakeResult(returncode=0))
    with pytest.raises(KeychainUnavailable):
        set_secret_stdin("NAME", "s3cr3t", service=CONNECT_SERVICE, _run=run)
    assert run.calls == []


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
