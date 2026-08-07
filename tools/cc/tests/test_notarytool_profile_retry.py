from __future__ import annotations

import os
from pathlib import Path
import subprocess


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "notarytool-profile-retry.sh"


def _fake_xcrun(tmp_path: Path) -> Path:
    executable = tmp_path / "xcrun"
    executable.write_text(
        """#!/usr/bin/env bash
set -eu
count_file="$FAKE_COUNT_FILE"
count=0
if [[ -f "$count_file" ]]; then count="$(<"$count_file")"; fi
count=$((count + 1))
printf '%s\n' "$count" > "$count_file"
case "$FAKE_MODE" in
  transient)
    if [[ "$count" -eq 1 ]]; then
      echo 'Error: No Keychain password item found for profile: ct-notary' >&2
      exit 69
    fi
    echo '{"ok":true}'
    ;;
  permanent-keychain)
    echo 'Error: The specified item could not be found in the keychain.' >&2
    exit 69
    ;;
  remote)
    echo 'Error: HTTP status code: 401. Invalid credentials.' >&2
    exit 65
    ;;
esac
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def _run(tmp_path: Path, mode: str, attempts: int = 3) -> subprocess.CompletedProcess[str]:
    _fake_xcrun(tmp_path)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{tmp_path}:{env['PATH']}",
            "FAKE_MODE": mode,
            "FAKE_COUNT_FILE": str(tmp_path / "count"),
            "CT_NOTARY_PROFILE_ATTEMPTS": str(attempts),
            "CT_NOTARY_PROFILE_RETRY_DELAY": "0",
        }
    )
    return subprocess.run(
        [str(SCRIPT), "--profile", "ct-notary", "--", "history"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_retries_transient_data_protection_keychain_lookup(tmp_path: Path) -> None:
    result = _run(tmp_path, "transient")

    assert result.returncode == 0
    assert result.stdout.strip() == '{"ok":true}'
    assert "temporarily unavailable to this process" in result.stderr
    assert (tmp_path / "count").read_text(encoding="utf-8").strip() == "2"


def test_does_not_retry_remote_authentication_rejection(tmp_path: Path) -> None:
    result = _run(tmp_path, "remote")

    assert result.returncode == 65
    assert "Invalid credentials" in result.stderr
    assert "temporarily unavailable" not in result.stderr
    assert (tmp_path / "count").read_text(encoding="utf-8").strip() == "1"


def test_exhaustion_does_not_claim_the_profile_was_deleted(tmp_path: Path) -> None:
    result = _run(tmp_path, "permanent-keychain", attempts=2)

    assert result.returncode == 69
    assert "does not prove the Data Protection Keychain item was deleted" in result.stderr
    assert "if it succeeds, continue without recreating credentials" in result.stderr
    assert (tmp_path / "count").read_text(encoding="utf-8").strip() == "2"
