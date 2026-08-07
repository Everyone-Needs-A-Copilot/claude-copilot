"""Tests for cc usage — quota probe engine and CLI (TASK-120/121/122).

Coverage:
  (a) idle-gating SKIPS probe when no recent transcript change (mock clock/mtime)
  (b) header parsing extracts the right fields from a sample header set
  (c) non-macOS / missing-keychain path falls back to transcript reconstruction
      without crashing
  (d) cache write is atomic and statusline/dashboard readers parse it correctly
  (e) transcript-block reconstruction groups timestamps into correct 5h windows
  (f) cc usage CLI exits zero and produces JSON with expected keys
  (g) --no-probe reads cache only
  (h) --refresh forces probe even when idle gate would fire
"""

from __future__ import annotations

import json
import os
import platform
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from cc.usage.probe import (
    CACHE_PATH,
    IDLE_GATE_SECONDS,
    UsageCache,
    _build_cache_from_headers,
    _coerce_float,
    _coerce_int,
    _load_keychain_token,
    _parse_ratelimit_headers,
    _should_probe,
    read_cache,
    run_probe,
    write_cache,
)
from cc.usage.reconstruct import (
    FIVE_H_SECONDS,
    SEVEN_D_SECONDS,
    _bucket_into_5h_blocks,
    _count_in_window,
    _parse_ts,
    reconstruct_usage,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_cache(tmp_path) -> Path:
    return tmp_path / "session-usage.json"


@pytest.fixture
def sample_headers() -> dict:
    """Real header set captured on 2026-06-17 against claude-haiku-4-5."""
    return {
        "anthropic-ratelimit-unified-status": "allowed",
        "anthropic-ratelimit-unified-5h-status": "allowed",
        "anthropic-ratelimit-unified-5h-reset": "1781717400",
        "anthropic-ratelimit-unified-5h-utilization": "0.07",
        "anthropic-ratelimit-unified-7d-status": "allowed",
        "anthropic-ratelimit-unified-7d-reset": "1781751600",
        "anthropic-ratelimit-unified-7d-utilization": "0.13",
        "anthropic-ratelimit-unified-overage-status": "allowed",
        "anthropic-ratelimit-unified-overage-reset": "1781703600",
        "anthropic-ratelimit-unified-overage-utilization": "0.0",
        "anthropic-ratelimit-unified-representative-claim": "five_hour",
        "anthropic-ratelimit-unified-fallback-percentage": "0.5",
        "anthropic-ratelimit-unified-reset": "1781717400",
        "anthropic-organization-id": "deaefb02-28e7-4726-b8b2-eebae5258d77",
        "content-type": "application/json",
    }


# ---------------------------------------------------------------------------
# (a) Idle-gating — SKIPS probe when no recent transcript change
# ---------------------------------------------------------------------------


class TestIdleGating:
    def test_should_probe_false_when_mtime_none(self):
        """No transcripts at all → no probe."""
        result = _should_probe(now=time.time(), _mtime_fn=lambda: None)
        assert result is False

    def test_should_probe_false_when_transcript_old(self):
        """Transcript mtime > IDLE_GATE_SECONDS ago → no probe."""
        now = time.time()
        old_mtime = now - IDLE_GATE_SECONDS - 60  # 1 min past the gate
        result = _should_probe(now=now, _mtime_fn=lambda: old_mtime)
        assert result is False

    def test_should_probe_true_when_transcript_recent(self):
        """Transcript mtime within IDLE_GATE_SECONDS → probe."""
        now = time.time()
        recent_mtime = now - 60  # 1 min ago
        result = _should_probe(now=now, _mtime_fn=lambda: recent_mtime)
        assert result is True

    def test_should_probe_exactly_at_boundary(self):
        """Exactly at the boundary (== IDLE_GATE_SECONDS) → probe (inclusive)."""
        now = time.time()
        boundary_mtime = now - IDLE_GATE_SECONDS
        result = _should_probe(now=now, _mtime_fn=lambda: boundary_mtime)
        assert result is True

    def test_run_probe_skips_network_when_idle(self, tmp_cache):
        """run_probe never calls network when idle gate fires."""
        stale_mtime = lambda: time.time() - IDLE_GATE_SECONDS - 300

        # Write a known cache so the idle path returns it
        known = UsageCache(probed_at=time.time() - 60, source="probe", five_h_status="allowed")
        write_cache(known, tmp_cache)

        with patch("cc.usage.probe._load_keychain_token") as mock_token:
            result = run_probe(force=False, cache_path=tmp_cache, _mtime_fn=stale_mtime)

        # Token should never have been called (idle gate fired)
        mock_token.assert_not_called()
        assert result.idle_gated is True

    def test_run_probe_force_bypasses_idle_gate(self, tmp_cache, monkeypatch):
        """--refresh forces probe even when transcript is old."""
        stale_mtime = lambda: time.time() - IDLE_GATE_SECONDS - 300

        called = []

        def fake_probe(token):
            called.append(token)
            return UsageCache(probed_at=time.time(), source="probe", five_h_status="allowed")

        monkeypatch.setattr("cc.usage.probe._load_keychain_token", lambda: "tok")
        monkeypatch.setattr("cc.usage.probe._do_probe", fake_probe)

        result = run_probe(force=True, cache_path=tmp_cache, _mtime_fn=stale_mtime)
        assert called == ["tok"]
        assert result.idle_gated is False


# ---------------------------------------------------------------------------
# (b) Header parsing
# ---------------------------------------------------------------------------


class TestHeaderParsing:
    def test_parse_ratelimit_headers_extracts_all_unified(self, sample_headers):
        parsed = _parse_ratelimit_headers(sample_headers)
        assert "5h-status" in parsed
        assert parsed["5h-status"] == "allowed"
        assert "5h-utilization" in parsed
        assert "7d-status" in parsed
        assert "overage-status" in parsed
        assert "representative-claim" in parsed
        assert "fallback-percentage" in parsed
        # Non-ratelimit header must be absent
        assert "content-type" not in parsed
        assert "anthropic-organization-id" not in parsed

    def test_parse_is_case_insensitive_on_key(self):
        headers = {"Anthropic-Ratelimit-Unified-5H-Status": "rate_limited"}
        parsed = _parse_ratelimit_headers(headers)
        assert parsed.get("5h-status") == "rate_limited"

    def test_build_cache_from_headers_full(self, sample_headers):
        parsed = _parse_ratelimit_headers(sample_headers)
        cache = _build_cache_from_headers(parsed, sample_headers)
        assert cache.five_h_status == "allowed"
        assert cache.five_h_utilization == pytest.approx(0.07)
        assert cache.five_h_reset_epoch == 1781717400
        assert cache.seven_d_status == "allowed"
        assert cache.seven_d_utilization == pytest.approx(0.13)
        assert cache.seven_d_reset_epoch == 1781751600
        assert cache.overage_status == "allowed"
        assert cache.representative_claim == "five_hour"
        assert cache.fallback_percentage == pytest.approx(0.5)
        assert cache.source == "probe"

    def test_build_cache_partial_headers_degrades_gracefully(self):
        """Missing headers produce None fields, not crashes."""
        parsed = {"5h-status": "allowed"}  # only partial
        cache = _build_cache_from_headers(parsed, {})
        assert cache.five_h_status == "allowed"
        assert cache.five_h_utilization is None
        assert cache.seven_d_status is None
        assert cache.representative_claim is None

    def test_coerce_float_handles_bad_values(self):
        assert _coerce_float("0.07") == pytest.approx(0.07)
        assert _coerce_float(None) is None
        assert _coerce_float("bad") is None
        assert _coerce_float("") is None

    def test_coerce_int_handles_bad_values(self):
        assert _coerce_int("1781717400") == 1781717400
        assert _coerce_int(None) is None
        assert _coerce_int("nope") is None


# ---------------------------------------------------------------------------
# (c) Non-macOS / missing Keychain → graceful fallback
# ---------------------------------------------------------------------------


class TestNonMacOSFallback:
    def test_load_keychain_token_returns_none_on_non_macos(self, monkeypatch):
        monkeypatch.setattr("cc.usage.probe._is_macos", lambda: False)
        assert _load_keychain_token() is None

    def test_load_keychain_token_returns_none_when_security_fails(self, monkeypatch):
        monkeypatch.setattr("cc.usage.probe._is_macos", lambda: True)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not found")
            assert _load_keychain_token() is None

    def test_run_probe_falls_back_when_no_token(self, tmp_cache, monkeypatch):
        """When token is None, run_probe calls reconstruct and writes cache."""
        monkeypatch.setattr("cc.usage.probe._load_keychain_token", lambda: None)
        recent_mtime = lambda: time.time() - 30  # active session

        result = run_probe(force=False, cache_path=tmp_cache, _mtime_fn=recent_mtime)
        assert result.source == "fallback"
        assert tmp_cache.exists()

    def test_run_probe_falls_back_when_probe_errors(self, tmp_cache, monkeypatch):
        """Network error during probe → fallback, no crash."""
        monkeypatch.setattr("cc.usage.probe._load_keychain_token", lambda: "fake-token")
        recent_mtime = lambda: time.time() - 30

        def exploding_probe(token):
            return UsageCache(probed_at=time.time(), source="probe", probe_error="Connection refused")

        monkeypatch.setattr("cc.usage.probe._do_probe", exploding_probe)

        result = run_probe(force=False, cache_path=tmp_cache, _mtime_fn=recent_mtime)
        assert result.source == "fallback"
        assert result.probe_error == "Connection refused"

    def test_no_crash_when_transcript_root_missing(self, tmp_path):
        """reconstruct_usage with non-existent root returns zeros."""
        missing_root = tmp_path / "nonexistent"
        cache = reconstruct_usage(root=missing_root)
        assert cache.source == "fallback"
        assert cache.five_h_tokens_reconstructed == 0
        assert cache.seven_d_tokens_reconstructed == 0


# ---------------------------------------------------------------------------
# (d) Atomic cache write and read
# ---------------------------------------------------------------------------


class TestCacheAtomicity:
    def test_write_and_read_roundtrip(self, tmp_cache):
        orig = UsageCache(
            probed_at=1234567890.0,
            source="probe",
            five_h_status="allowed",
            five_h_utilization=0.07,
            five_h_reset_epoch=1781717400,
            seven_d_status="allowed",
            seven_d_utilization=0.13,
            raw_headers={"x": "y"},
        )
        write_cache(orig, tmp_cache)
        loaded = read_cache(tmp_cache)
        assert loaded is not None
        assert loaded.source == "probe"
        assert loaded.five_h_status == "allowed"
        assert loaded.five_h_utilization == pytest.approx(0.07)
        assert loaded.raw_headers == {"x": "y"}

    def test_write_is_atomic_via_rename(self, tmp_cache, monkeypatch):
        """Verify temp file is not the final cache path (rename semantics)."""
        rename_args = []
        real_replace = os.replace

        def capturing_replace(src, dst):
            rename_args.append((src, dst))
            return real_replace(src, dst)

        monkeypatch.setattr(os, "replace", capturing_replace)

        cache = UsageCache(probed_at=time.time(), source="fallback")
        write_cache(cache, tmp_cache)

        assert len(rename_args) == 1
        src, dst = rename_args[0]
        assert Path(dst) == tmp_cache
        assert Path(src) != tmp_cache         # was a temp file
        assert tmp_cache.exists()             # final file is in place

    def test_read_cache_returns_none_when_missing(self, tmp_path):
        missing = tmp_path / "no-such-file.json"
        assert read_cache(missing) is None

    def test_read_cache_tolerates_corrupt_json(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json {{{{")
        assert read_cache(bad) is None

    def test_statusline_reader_gets_correct_fields(self, tmp_cache):
        """Simulate the statusline reading only the fields it needs."""
        cache = UsageCache(
            probed_at=time.time(),
            source="probe",
            five_h_status="allowed",
            five_h_utilization=0.42,
        )
        write_cache(cache, tmp_cache)

        # Statusline reads raw JSON (it's a shell script / external consumer)
        raw = json.loads(tmp_cache.read_text())
        assert raw["five_h_status"] == "allowed"
        assert raw["five_h_utilization"] == pytest.approx(0.42)
        assert raw["source"] == "probe"


# ---------------------------------------------------------------------------
# (e) Transcript reconstruction — 5h bucketing
# ---------------------------------------------------------------------------


class TestTranscriptReconstruction:
    def test_parse_ts_iso8601_with_z(self):
        ep = _parse_ts("2026-06-17T13:36:32.000Z")
        assert ep is not None
        assert ep > 0

    def test_parse_ts_with_offset(self):
        ep = _parse_ts("2026-06-17T09:36:32-04:00")
        assert ep is not None

    def test_parse_ts_empty_returns_none(self):
        assert _parse_ts("") is None
        assert _parse_ts(None) is None

    def test_count_in_window_basic(self):
        now = time.time()
        recent = [now - 60, now - 120, now - 7200]
        assert _count_in_window(recent, now - 3600) == 2   # 60s + 120s within 1h
        assert _count_in_window(recent, now - FIVE_H_SECONDS) == 3  # all within 5h

    def test_bucket_into_5h_blocks(self):
        """Timestamps 4h30m apart should land in DIFFERENT 5h buckets."""
        base = 0.0  # epoch midnight
        t1 = base + 100             # bucket 0
        t2 = base + FIVE_H_SECONDS + 100  # bucket 1
        buckets = _bucket_into_5h_blocks([t1, t2], now=base + FIVE_H_SECONDS * 2)
        assert len(buckets) == 2    # two different buckets

    def test_bucket_same_bucket(self):
        """Timestamps within the same 5h window land in the SAME bucket."""
        base = 0.0
        t1 = base + 100
        t2 = base + FIVE_H_SECONDS - 100  # still in bucket 0
        buckets = _bucket_into_5h_blocks([t1, t2], now=base + FIVE_H_SECONDS * 2)
        assert len(buckets) == 1

    def test_reconstruct_with_fake_transcripts(self, tmp_path):
        """Write mock .jsonl files and verify reconstruct counts them correctly."""
        proj = tmp_path / "projects" / "my-project"
        proj.mkdir(parents=True)

        now = time.time()
        from datetime import datetime, timezone
        def ts(offset):
            dt = datetime.fromtimestamp(now - offset, tz=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        # 3 messages in the last 5h, 1 older (6h ago)
        lines = [
            json.dumps({"type": "user", "timestamp": ts(60)}),       # 1m ago
            json.dumps({"type": "user", "timestamp": ts(3600)}),     # 1h ago
            json.dumps({"type": "user", "timestamp": ts(4 * 3600)}), # 4h ago
            json.dumps({"type": "user", "timestamp": ts(6 * 3600)}), # 6h ago (outside 5h)
            json.dumps({"type": "mode"}),                             # no timestamp
        ]
        (proj / "session.jsonl").write_text("\n".join(lines))

        result = reconstruct_usage(root=tmp_path / "projects", _now=now)
        assert result.source == "fallback"
        assert result.five_h_tokens_reconstructed == 3   # 3 within 5h
        assert result.seven_d_tokens_reconstructed == 4  # all 4 with timestamps

    def test_reconstruct_empty_root(self, tmp_path):
        result = reconstruct_usage(root=tmp_path / "empty")
        assert result.five_h_tokens_reconstructed == 0
        assert result.seven_d_tokens_reconstructed == 0

    def test_reconstruct_multi_project(self, tmp_path):
        """Cross-project chaining: timestamps from multiple project dirs are summed."""
        now = time.time()
        from datetime import datetime, timezone
        def ts(offset):
            dt = datetime.fromtimestamp(now - offset, tz=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        for proj_name in ["proj-a", "proj-b", "proj-c"]:
            p = tmp_path / "projects" / proj_name
            p.mkdir(parents=True)
            (p / "session.jsonl").write_text(
                json.dumps({"type": "user", "timestamp": ts(30)}) + "\n"
            )

        result = reconstruct_usage(root=tmp_path / "projects", _now=now)
        assert result.five_h_tokens_reconstructed == 3  # one per project


# ---------------------------------------------------------------------------
# (f) CLI — exit 0, JSON output with expected keys
# ---------------------------------------------------------------------------


class TestUsageCLI:
    def test_usage_json_exit_zero(self, runner, monkeypatch, tmp_path):
        """cc usage --json exits 0 and returns valid JSON with required keys."""
        from cc.main import app

        cache_file = tmp_path / "test-cache.json"
        cache = UsageCache(
            probed_at=time.time(),
            source="fallback",
            five_h_tokens_reconstructed=5,
        )
        write_cache(cache, cache_file)

        result = runner.invoke(
            app,
            ["usage", "--json", "--no-probe", "--cache", str(cache_file)],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "source" in data
        assert "probed_at" in data
        assert "five_h_status" in data or "five_h_tokens_reconstructed" in data

    def test_usage_human_readable_exits_zero(self, runner, monkeypatch, tmp_path):
        """cc usage (human-readable) exits 0."""
        from cc.main import app

        cache_file = tmp_path / "test-cache.json"
        cache = UsageCache(probed_at=time.time(), source="probe", five_h_status="allowed")
        write_cache(cache, cache_file)

        result = runner.invoke(app, ["usage", "--no-probe", "--cache", str(cache_file)])
        assert result.exit_code == 0, result.output

    def test_usage_no_probe_reads_cache(self, runner, tmp_path):
        """--no-probe uses cache, never fires probe."""
        from cc.main import app

        cache_file = tmp_path / "test-cache.json"
        cache = UsageCache(probed_at=time.time() - 10, source="probe", five_h_status="rate_limited")
        write_cache(cache, cache_file)

        with patch("cc.usage.probe._load_keychain_token") as mock_tok:
            result = runner.invoke(
                app,
                ["usage", "--json", "--no-probe", "--cache", str(cache_file)],
            )

        mock_tok.assert_not_called()
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["five_h_status"] == "rate_limited"

    def test_usage_refresh_flag_forces_probe(self, runner, tmp_path, monkeypatch):
        """--refresh bypasses idle gate."""
        from cc.main import app

        cache_file = tmp_path / "test-cache.json"
        probe_called = []

        monkeypatch.setattr("cc.usage.probe._load_keychain_token", lambda: "tok")
        monkeypatch.setattr(
            "cc.usage.probe._do_probe",
            lambda token: (
                probe_called.append(token),
                UsageCache(probed_at=time.time(), source="probe", five_h_status="allowed"),
            )[1],
        )

        result = runner.invoke(
            app,
            ["usage", "--json", "--refresh", "--cache", str(cache_file)],
        )
        assert result.exit_code == 0
        assert probe_called  # probe was invoked

    def test_usage_shows_in_cc_help(self, runner):
        """'usage' appears in cc --help output."""
        from cc.main import app
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "usage" in result.output.lower()
