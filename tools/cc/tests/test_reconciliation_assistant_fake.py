"""Self-tests for the inert Claude executable used by proposal security QA."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Pytest imports this suite from the repository root in CI.  Keep the reusable
# harness test-only while making its import independent of that working dir.
sys.path.insert(0, str(Path(__file__).parent))

from reconciliation_assistant_harness import (
    capture_record,
    decoded_stdin,
    snapshot_tree,
)


FAKE_CLAUDE = (
    Path(__file__).parent / "fixtures" / "reconciliation" / "fake_claude.py"
)


def _environment(tmp_path: Path, **updates: str) -> dict[str, str]:
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "FAKE_CLAUDE_CAPTURE": str(tmp_path / "capture.json"),
        **updates,
    }
    return environment


def test_fake_emits_exact_bytes_and_records_process_boundary(tmp_path: Path) -> None:
    response = tmp_path / "hostile.response"
    response.write_bytes(b'{"candidate_id":"candidate_offered"}\n')
    environment = _environment(
        tmp_path,
        FAKE_CLAUDE_MODE="exact",
        FAKE_CLAUDE_RESPONSE_FILE=str(response),
    )
    private_cwd = tmp_path / "private-cwd"
    private_cwd.mkdir(mode=0o700)

    invocation = subprocess.run(
        [str(FAKE_CLAUDE), "--print", "--tools", ""],
        input=b'{"bounded":"packet"}',
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=private_cwd,
        env=environment,
        check=False,
    )

    assert invocation.returncode == 0
    assert invocation.stdout == response.read_bytes()
    assert invocation.stderr == b""
    captured = capture_record(tmp_path / "capture.json")
    assert captured["argv"] == ["--print", "--tools", ""]
    assert captured["cwd"] == str(private_cwd)
    assert decoded_stdin(captured) == b'{"bounded":"packet"}'
    assert "FAKE_SECRET_CANARY" not in captured["environment_keys"]


@pytest.mark.parametrize(
    "mode",
    [
        "empty",
        "free-text",
        "malformed",
        "duplicate",
        "nan",
        "command",
        "path",
        "content",
        "patch",
        "operation",
        "wrong-id",
        "invalid-utf8",
        "exit-1",
        "exit-2",
    ],
)
def test_fake_has_deterministic_adversarial_modes(
    tmp_path: Path, mode: str
) -> None:
    invocation = subprocess.run(
        [str(FAKE_CLAUDE), "--print"],
        input=b"packet",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_environment(tmp_path, FAKE_CLAUDE_MODE=mode),
        check=False,
    )

    assert (tmp_path / "capture.json").is_file()
    assert decoded_stdin(capture_record(tmp_path / "capture.json")) == b"packet"
    assert invocation.returncode == {"exit-1": 1, "exit-2": 2}.get(mode, 0)


@pytest.mark.parametrize("envelope", ["plain", "result-string", "structured-output"])
def test_fake_wraps_valid_payload_in_supported_test_envelopes(
    tmp_path: Path, envelope: str
) -> None:
    payload = {"selections": [{"candidate_id": "candidate_offered"}]}
    invocation = subprocess.run(
        [str(FAKE_CLAUDE), "--print"],
        input=b"packet",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_environment(
            tmp_path,
            FAKE_CLAUDE_MODE="valid",
            FAKE_CLAUDE_ENVELOPE=envelope,
            FAKE_CLAUDE_PAYLOAD_JSON=json.dumps(payload),
        ),
        check=True,
    )

    emitted = json.loads(invocation.stdout)
    if envelope == "plain":
        assert emitted == payload
    elif envelope == "result-string":
        assert json.loads(emitted["result"]) == payload
    else:
        assert emitted["structured_output"] == payload


def test_fake_wait_mode_records_process_group_cancellation(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    process = subprocess.Popen(
        [str(FAKE_CLAUDE), "--print"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_environment(
            tmp_path,
            FAKE_CLAUDE_MODE="wait",
            FAKE_CLAUDE_READY_FILE=str(ready),
        ),
        start_new_session=True,
    )
    assert process.stdin is not None
    process.stdin.write(b"packet")
    process.stdin.close()
    deadline = time.monotonic() + 5
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ready.exists()

    os.killpg(process.pid, signal.SIGTERM)
    assert process.wait(timeout=5) == 128 + signal.SIGTERM
    captured = capture_record(tmp_path / "capture.json")
    assert captured["events"] == ["invoked", "waiting", "signal:SIGTERM"]


def test_tree_snapshot_detects_bytes_modes_and_symlink_target_changes(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    tracked = project / "tracked"
    tracked.write_bytes(b"before")
    linked = project / "linked"
    linked.symlink_to("tracked")
    before = snapshot_tree(project)

    tracked.write_bytes(b"after")
    tracked.chmod(0o600)
    linked.unlink()
    linked.symlink_to("elsewhere")

    assert snapshot_tree(project) != before


def test_fake_version_probe_does_not_require_capture(tmp_path: Path) -> None:
    invocation = subprocess.run(
        [str(FAKE_CLAUDE), "--version"],
        cwd=tmp_path,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    assert invocation.stdout == b"2.1.221 (Claude Code)\n"
    assert invocation.stderr == b""
