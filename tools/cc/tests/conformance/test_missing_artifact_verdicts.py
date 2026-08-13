"""Missing required repo artifacts are failures, not harness uncertainty."""

from __future__ import annotations

import json
import subprocess

from cc.core.conformance.dimensions import d01_claude, d02_codex
from cc.core.conformance.types import Verdict


def test_d01_missing_fitness_check_is_fail(tmp_path):
    result = d01_claude.check_d01_fitness_check_passes(tmp_path)

    assert result.verdict is Verdict.FAIL
    assert result.evidence[0].kind == "fitness-check-unavailable"


def test_d01_execution_error_remains_could_not_run(tmp_path, monkeypatch):
    script = tmp_path / d01_claude.FITNESS_CHECK_RELATIVE_PATH
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)

    def unavailable(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr(d01_claude.subprocess, "run", unavailable)
    result = d01_claude.check_d01_fitness_check_passes(tmp_path)

    assert result.verdict is Verdict.COULD_NOT_RUN
    assert result.evidence[0].kind == "fitness-check-execution-error"


def test_d02_missing_declared_version_is_fail(tmp_path):
    result = d02_codex.check_d02_declared_version_matches_lock(tmp_path)

    assert result.verdict is Verdict.FAIL
    assert result.evidence[0].kind == "declared-version-missing"


def test_d02_missing_lock_version_is_fail(tmp_path):
    (tmp_path / d02_codex.CODEX_CONFIG_RELATIVE_PATH).write_text(
        json.dumps({"frameworkVersion": "0.6.1"}), encoding="utf-8"
    )

    result = d02_codex.check_d02_declared_version_matches_lock(tmp_path)

    assert result.verdict is Verdict.FAIL
    assert result.evidence[0].kind == "lock-version-missing"
