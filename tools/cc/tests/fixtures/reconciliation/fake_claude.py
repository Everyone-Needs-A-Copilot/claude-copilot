#!/usr/bin/env python3
"""Inert Claude CLI double for reconciliation security tests.

The executable never discovers a project, invokes a tool, opens a network
connection, or interprets its input.  It records the process boundary and then
emits bytes chosen entirely by the test through environment variables.

Environment contract:

``FAKE_CLAUDE_CAPTURE``
    Required path for the atomic JSON invocation record.
``FAKE_CLAUDE_MODE``
    ``exact`` (default), ``valid``, one of the hostile built-ins below,
    ``wait``, ``exit-1``, or ``exit-2``.
``FAKE_CLAUDE_RESPONSE_FILE``
    Exact stdout bytes for ``exact`` mode.
``FAKE_CLAUDE_PAYLOAD_JSON``
    Model payload for ``valid`` mode.  It is data, never executed.
``FAKE_CLAUDE_ENVELOPE``
    ``structured-output`` (default), ``result-string``, or ``plain``.
``FAKE_CLAUDE_READY_FILE``
    Optional sentinel written immediately before ``wait`` pauses.

The capture contains environment *names*, not values.  This is enough to prove
an allowlist without copying secret-shaped values into test evidence.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import signal
import sys
from pathlib import Path
from typing import NoReturn

_CAPTURE_VERSION = "fake-claude.capture.v1"
_HOSTILE_OUTPUTS = {
    "empty": b"",
    "free-text": b"I ignored the schema and edited the project.",
    "malformed": b'{"type":"result","structured_output":',
    "duplicate": (
        b'{"selections":[],"selections":[{"candidate_id":"candidate_forged"}]}'
    ),
    "nan": b'{"selections":[],"confidence":NaN}',
    "command": b'{"selections":[],"command":"rm -rf project"}',
    "path": b'{"selections":[],"path":"../../outside"}',
    "content": b'{"selections":[],"content":"owned bytes"}',
    "patch": b'{"selections":[],"patch":"@@ -1 +1 @@"}',
    "operation": b'{"selections":[],"operation":{"kind":"shell"}}',
    "wrong-id": (
        b'{"selections":[{"candidate_id":"candidate_not_offered",'
        b'"outcome":"select"}]}'
    ),
    "invalid-utf8": b"\xff\xfe\xfa",
}


def _required_path(name: str) -> Path:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return Path(value)


def _atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def _capture(stdin: bytes) -> tuple[Path, dict[str, object]]:
    capture_path = _required_path("FAKE_CLAUDE_CAPTURE")
    record: dict[str, object] = {
        "schema_version": _CAPTURE_VERSION,
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "argv": sys.argv[1:],
        "cwd": os.getcwd(),
        "environment_keys": sorted(os.environ),
        "stdin_size": len(stdin),
        "stdin_sha256": hashlib.sha256(stdin).hexdigest(),
        "stdin_base64": base64.b64encode(stdin).decode("ascii"),
        "events": ["invoked"],
    }
    _atomic_json(capture_path, record)
    return capture_path, record


def _record_signal(
    capture_path: Path, record: dict[str, object], signum: int
) -> NoReturn:
    events = record["events"]
    assert isinstance(events, list)
    events.append(f"signal:{signal.Signals(signum).name}")
    _atomic_json(capture_path, record)
    raise SystemExit(128 + signum)


def _valid_output() -> bytes:
    payload_text = os.environ.get("FAKE_CLAUDE_PAYLOAD_JSON", '{"selections":[]}')
    payload = json.loads(payload_text)
    envelope = os.environ.get("FAKE_CLAUDE_ENVELOPE", "structured-output")
    if envelope == "plain":
        value: object = payload
    elif envelope == "result-string":
        value = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": json.dumps(payload, separators=(",", ":")),
        }
    elif envelope == "structured-output":
        value = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "structured_output": payload,
        }
    else:
        raise SystemExit(f"unsupported FAKE_CLAUDE_ENVELOPE: {envelope}")
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def main() -> int:
    if "--version" in sys.argv[1:]:
        sys.stdout.write("2.1.221 (Claude Code)\n")
        return 0

    stdin = sys.stdin.buffer.read()
    capture_path, record = _capture(stdin)
    mode = os.environ.get("FAKE_CLAUDE_MODE", "exact")

    if mode == "wait":
        for handled in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(
                handled,
                lambda signum, _frame: _record_signal(capture_path, record, signum),
            )
        events = record["events"]
        assert isinstance(events, list)
        events.append("waiting")
        _atomic_json(capture_path, record)
        # The sentinel promises that cancellation handling is ready, not only
        # that the child started. Publishing it earlier races callers into the
        # interpreter's default SIGTERM behavior.
        ready = os.environ.get("FAKE_CLAUDE_READY_FILE")
        if ready:
            ready_path = Path(ready)
            ready_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            ready_path.write_text("ready\n", encoding="utf-8")
            ready_path.chmod(0o600)
        while True:
            signal.pause()

    if mode == "exact":
        response_path = _required_path("FAKE_CLAUDE_RESPONSE_FILE")
        output = response_path.read_bytes()
    elif mode == "valid":
        output = _valid_output()
    elif mode in _HOSTILE_OUTPUTS:
        output = _HOSTILE_OUTPUTS[mode]
    elif mode in {"exit-1", "exit-2"}:
        output = b'{"selections":[]}'
    else:
        raise SystemExit(f"unsupported FAKE_CLAUDE_MODE: {mode}")

    sys.stdout.buffer.write(output)
    sys.stdout.buffer.flush()
    if mode == "exit-1":
        return 1
    if mode == "exit-2":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
