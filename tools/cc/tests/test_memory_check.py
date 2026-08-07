"""Tests for cc memory check — drift detection (TASK-118/119).

Coverage:
  (a) deleted referenced path → flagged fail
  (b) valid path → NOT flagged
  (c) <placeholder> / URL route / negated-section path → NOT flagged
  (d) cross-entry version conflict → flagged warn
  (e) score math is correct
  (f) cc memory check CLI subcommand wires up and exits zero with --json
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from cc.core.memory_check import (
    PathClaim,
    CommandClaim,
    VersionClaim,
    CheckResult,
    EntryReport,
    MemoryCheckReport,
    _extract_path_claims,
    _extract_version_claims,
    _extract_command_claims,
    check_path_exists,
    check_command_resolves,
    check_version_conflicts,
    check_staleness,
    check_entry,
    check_all_entries,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_file(tmp_path):
    """A real file on disk that claim checkers can find."""
    f = tmp_path / "real_file.py"
    f.write_text("# real")
    return f


@pytest.fixture
def memory_root(tmp_path, monkeypatch):
    """Patch resolve_memory_root for CLI tests."""
    import cc.core.entry_store as es
    monkeypatch.setattr(es, "_git_root", lambda: tmp_path)
    return tmp_path / ".claude" / "memory"


@pytest.fixture
def cli_runner():
    from typer.testing import CliRunner
    return CliRunner()


@pytest.fixture
def cli_app():
    from cc.main import app
    return app


# ---------------------------------------------------------------------------
# (a) Deleted / missing path → flagged error
# ---------------------------------------------------------------------------


class TestPathExistsChecker:
    def test_missing_absolute_path_is_fail(self, tmp_path):
        """A non-existent absolute path gets status=fail."""
        missing = tmp_path / "does_not_exist.py"
        claim = PathClaim(raw=str(missing), source_entry_id="entry-001")
        result = check_path_exists(claim)
        assert result.status == "fail"
        assert "does_not_exist" in result.message

    def test_missing_relative_path_is_warn(self):
        """A non-existent relative path gets status=warn (not fail — could be repo-relative)."""
        claim = PathClaim(raw="src/missing_module.py", source_entry_id="entry-002")
        result = check_path_exists(claim)
        assert result.status == "warn"

    # (b) Valid path → NOT flagged
    def test_existing_path_is_pass(self, tmp_file):
        """An existing path gets status=pass."""
        claim = PathClaim(raw=str(tmp_file), source_entry_id="entry-003")
        result = check_path_exists(claim)
        assert result.status == "pass"

    # (c) Negated section → NOT flagged
    def test_negated_claim_is_pass(self):
        """A negated claim is unconditionally pass."""
        claim = PathClaim(raw="/nonexistent/path", source_entry_id="entry-004", negated=True)
        result = check_path_exists(claim)
        assert result.status == "pass"
        assert "negated" in result.message.lower()

    def test_negated_context_skips_missing_path(self):
        """Paths in 'not yet built' paragraph are not flagged."""
        body = """
## Planned features

These are not yet built and will be added later:
- `/Volumes/NonExistent/future_module.py`
"""
        claims = _extract_path_claims("entry-005", body)
        # Either no claims extracted from negated section, or all are negated
        for claim in claims:
            if "NonExistent" in claim.raw or "future_module" in claim.raw:
                assert claim.negated, f"Expected negated=True for {claim.raw}"


# ---------------------------------------------------------------------------
# (c) Placeholder and URL route filtering
# ---------------------------------------------------------------------------


class TestNegationAwareness:
    def test_placeholder_not_extracted_as_claim(self):
        """<placeholder> tokens must not be extracted as path claims."""
        body = "Run `cc docs get <pkg>` to fetch docs."
        claims = _extract_path_claims("entry-010", body)
        # <pkg> should NOT be in claims
        raw_vals = [c.raw for c in claims]
        assert "<pkg>" not in raw_vals, f"Placeholder was extracted: {raw_vals}"

    def test_url_route_not_extracted_as_path(self):
        """API routes like /api/x should NOT be treated as filesystem paths."""
        body = "Call GET /api/memory/entries to retrieve entries."
        claims = _extract_path_claims("entry-011", body)
        raw_vals = [c.raw for c in claims]
        # URL routes starting with /api should not be flagged
        api_routes = [r for r in raw_vals if r.startswith("/api")]
        assert api_routes == [], f"URL route was extracted as path: {api_routes}"

    def test_http_verb_path_not_extracted(self):
        """POST /api/v1/store should not be extracted as a filesystem path."""
        body = "The endpoint accepts POST /api/v1/store requests."
        claims = _extract_path_claims("entry-012", body)
        raw_vals = [c.raw for c in claims]
        api_routes = [r for r in raw_vals if "/api/v1" in r]
        assert api_routes == [], f"HTTP verb path was extracted: {api_routes}"

    def test_negated_paragraph_heading(self):
        """Paths under a 'Removed' or 'Deprecated' heading are negated."""
        body = """
## Removed

The old path `/Volumes/OldProject/legacy.py` was deleted.
"""
        claims = _extract_path_claims("entry-013", body)
        for c in claims:
            if "legacy.py" in c.raw:
                assert c.negated, f"Expected negated claim for {c.raw}"

    def test_not_yet_built_marker_negates(self):
        """'not yet built' inline marker should negate the path on that line."""
        body = "The `src/future_feature.py` module is not yet built."
        claims = _extract_path_claims("entry-014", body)
        for c in claims:
            if "future_feature" in c.raw:
                assert c.negated, f"Expected negated claim for {c.raw}"

    def test_double_braces_placeholder_not_extracted(self):
        """{{value}} template tokens are not path claims."""
        body = "Set the path to {{config_dir}}/settings.yaml."
        claims = _extract_path_claims("entry-015", body)
        raw_vals = [c.raw for c in claims]
        assert "{{config_dir}}" not in raw_vals


# ---------------------------------------------------------------------------
# (d) Cross-entry version conflict → flagged warn
# ---------------------------------------------------------------------------


class TestVersionConflictChecker:
    def test_same_package_different_versions_is_warn(self):
        """Two entries claiming different versions of the same package → warn."""
        claims = [
            VersionClaim(package="typer", version="0.9.0", source_entry_id="entry-A"),
            VersionClaim(package="typer", version="0.12.0", source_entry_id="entry-B"),
        ]
        results = check_version_conflicts(claims)
        assert len(results) == 1
        assert results[0].status == "warn"
        assert "typer" in results[0].message
        assert "0.9.0" in results[0].message
        assert "0.12.0" in results[0].message

    def test_same_package_same_version_no_conflict(self):
        """Two entries claiming the same version → no conflict."""
        claims = [
            VersionClaim(package="pydantic", version="2.0.0", source_entry_id="entry-A"),
            VersionClaim(package="pydantic", version="2.0.0", source_entry_id="entry-B"),
        ]
        results = check_version_conflicts(claims)
        assert results == []

    def test_different_packages_no_conflict(self):
        """Different packages with different versions → no conflict between them."""
        claims = [
            VersionClaim(package="requests", version="2.31.0", source_entry_id="entry-A"),
            VersionClaim(package="httpx", version="0.27.0", source_entry_id="entry-B"),
        ]
        results = check_version_conflicts(claims)
        assert results == []

    def test_version_extraction_from_prose(self):
        """Version claims are extracted from prose-style 'typer version 0.9.0'."""
        body = "We use typer version 0.9.0 for CLI construction."
        claims = _extract_version_claims("entry-X", body)
        pkgs = [c.package for c in claims]
        assert "typer" in pkgs

    def test_version_extraction_npm_style(self):
        """npm-style foo@^1.2.3 is extracted."""
        body = "Install with `npm install react@18.2.0`."
        claims = _extract_version_claims("entry-Y", body)
        pkgs = [c.package for c in claims]
        assert "react" in pkgs


# ---------------------------------------------------------------------------
# (e) Score math
# ---------------------------------------------------------------------------


class TestScoreMath:
    def _make_report(self, statuses: list[str]) -> MemoryCheckReport:
        """Build a MemoryCheckReport with one entry containing given statuses."""
        report = MemoryCheckReport()
        er = EntryReport(entry_id="test", entry_type="context", path="test.md")
        for i, s in enumerate(statuses):
            er.checks.append(CheckResult(check=f"check-{i}", status=s, message="test"))
        report.entries.append(er)
        return report

    def test_all_pass_is_100(self):
        report = self._make_report(["pass", "pass", "pass"])
        assert report.score == 100

    def test_one_fail_deducts_10(self):
        report = self._make_report(["fail"])
        assert report.score == 90

    def test_one_warn_deducts_3(self):
        report = self._make_report(["warn"])
        assert report.score == 97

    def test_one_info_deducts_1(self):
        report = self._make_report(["info"])
        assert report.score == 99

    def test_mixed_deduction(self):
        # 1 fail (−10) + 2 warn (−6) + 1 info (−1) = −17 → 83
        report = self._make_report(["fail", "warn", "warn", "info"])
        assert report.score == 83

    def test_score_floors_at_zero(self):
        """Score never goes below 0 even with many failures."""
        report = self._make_report(["fail"] * 20)
        assert report.score == 0

    def test_empty_report_is_100(self):
        report = MemoryCheckReport()
        assert report.score == 100

    def test_verdict_fail_when_any_fail(self):
        report = self._make_report(["pass", "fail", "warn"])
        assert report.verdict == "fail"

    def test_verdict_warn_when_no_fail(self):
        report = self._make_report(["pass", "warn"])
        assert report.verdict == "warn"

    def test_verdict_pass_when_all_pass(self):
        report = self._make_report(["pass", "pass"])
        assert report.verdict == "pass"

    def test_cross_entry_check_deducts_from_score(self):
        """Cross-entry version conflict warns deduct from total score."""
        report = MemoryCheckReport()
        report.cross_entry_checks.append(
            CheckResult(check="version-conflict", status="warn", message="conflict")
        )
        assert report.score == 97

    def test_flagged_excludes_pass(self):
        """flagged() only returns non-pass items."""
        report = self._make_report(["pass", "fail", "warn"])
        flagged = report.flagged()
        assert len(flagged) == 2
        statuses = {f["status"] for f in flagged}
        assert "pass" not in statuses


# ---------------------------------------------------------------------------
# Staleness checker
# ---------------------------------------------------------------------------


class TestStalenessChecker:
    def test_old_entry_is_warn(self):
        entry = {"id": "x", "updated": "2020-01-01T00:00:00Z"}
        result = check_staleness(entry, max_days=30)
        assert result is not None
        assert result.status == "warn"

    def test_recent_entry_is_none(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        entry = {"id": "x", "updated": now}
        result = check_staleness(entry, max_days=30)
        assert result is None

    def test_missing_updated_is_none(self):
        entry = {"id": "x"}
        result = check_staleness(entry, max_days=30)
        assert result is None


# ---------------------------------------------------------------------------
# check_all_entries integration
# ---------------------------------------------------------------------------


class TestCheckAllEntries:
    def test_valid_path_not_flagged(self, tmp_file):
        """An entry referencing an existing path produces no failures."""
        entry = {
            "id": "entry-valid",
            "type": "context",
            "path": "test.md",
            "content": f"See `{tmp_file}` for implementation.",
            "updated": "2099-01-01T00:00:00Z",
        }
        report = check_all_entries([entry], check_commands=False)
        fails = [c for er in report.entries for c in er.checks if c.status == "fail"]
        # No failures for the existing path
        path_fails = [f for f in fails if f.check == "path-exists" and str(tmp_file) in (f.artifact or "")]
        assert path_fails == []

    def test_deleted_path_flagged(self, tmp_path):
        """An entry referencing a non-existent absolute path gets flagged (fail or warn)."""
        gone = tmp_path / "gone.py"
        entry = {
            "id": "entry-gone",
            "type": "context",
            "path": "test.md",
            "content": f"The file `{gone}` was the implementation.",
            "updated": "2099-01-01T00:00:00Z",
        }
        report = check_all_entries([entry], check_commands=False, check_stale=False)
        # Check extraction works first
        claims = _extract_path_claims("entry-gone", entry["content"])
        assert any(str(gone) == c.raw or str(gone) in c.raw for c in claims), \
            f"Path claim not extracted for {gone}. Claims found: {[c.raw for c in claims]}"
        # Check that non-pass checks exist for the missing path
        nonfails = [c for er in report.entries for c in er.checks if c.status in ("fail", "warn")]
        assert any(str(gone) in (f.artifact or "") or str(gone) in f.message for f in nonfails), \
            f"Expected fail/warn for {gone}, got checks: {[c.to_dict() for c in [c for er in report.entries for c in er.checks]]}"

    def test_version_conflict_across_entries(self):
        """Two entries claiming different versions of the same package → cross-entry warn."""
        entry_a = {
            "id": "entry-a",
            "type": "context",
            "path": "a.md",
            "content": "We use typer version 0.9.0 for CLI.",
            "updated": "2099-01-01T00:00:00Z",
        }
        entry_b = {
            "id": "entry-b",
            "type": "context",
            "path": "b.md",
            "content": "The project uses typer version 0.12.0.",
            "updated": "2099-01-01T00:00:00Z",
        }
        report = check_all_entries([entry_a, entry_b], check_paths=False, check_commands=False, check_stale=False)
        conflict_checks = [c for c in report.cross_entry_checks if c.check == "version-conflict"]
        assert len(conflict_checks) >= 1
        assert conflict_checks[0].status == "warn"

    def test_empty_entries_returns_100(self):
        report = check_all_entries([])
        assert report.score == 100
        assert report.verdict == "pass"


# ---------------------------------------------------------------------------
# CLI integration: cc memory check --json
# ---------------------------------------------------------------------------


class TestMemoryCheckCLI:
    def _make_entry(self, root: Path, content: str) -> None:
        """Write a minimal memory entry to the entries dir."""
        import uuid
        from cc.core.entry_format import build_frontmatter, render_entry
        from cc.core.entry_store import _atomic_write

        e_dir = root / ".claude" / "memory" / "entries"
        e_dir.mkdir(parents=True, exist_ok=True)
        uid = str(uuid.uuid4())
        fm = build_frontmatter(
            entry_id=uid, entry_type="context", tags=[], scope="project"
        )
        _atomic_write(e_dir / f"{uid}.md", render_entry(fm, content))

    def test_check_exits_zero_json(self, cli_runner, cli_app, monkeypatch, tmp_path):
        """cc memory check --json exits 0 with valid JSON output."""
        import cc.core.entry_store as es
        monkeypatch.setattr(es, "_git_root", lambda: tmp_path)

        self._make_entry(
            tmp_path,
            "No file references here — just prose about the architecture.",
        )

        result = cli_runner.invoke(cli_app, ["memory", "check", "--json", "--no-paths", "--no-commands", "--no-stale"])
        assert result.exit_code == 0, f"stderr: {result.output}"
        data = json.loads(result.output)
        assert "score" in data
        assert "verdict" in data
        assert "entries" in data
        assert "flagged" in data

    def test_check_empty_memory_exits_zero(self, cli_runner, cli_app, monkeypatch, tmp_path):
        """cc memory check with no entries exits 0."""
        import cc.core.entry_store as es
        monkeypatch.setattr(es, "_git_root", lambda: tmp_path)

        result = cli_runner.invoke(cli_app, ["memory", "check", "--json"])
        assert result.exit_code == 0

    def test_check_score_100_when_clean(self, cli_runner, cli_app, monkeypatch, tmp_path):
        """Clean entry with no references scores 100."""
        import cc.core.entry_store as es
        monkeypatch.setattr(es, "_git_root", lambda: tmp_path)

        self._make_entry(
            tmp_path,
            "Pure prose: the architecture uses a layered design pattern.",
        )
        result = cli_runner.invoke(
            cli_app,
            ["memory", "check", "--json", "--no-paths", "--no-commands", "--no-stale"],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["score"] == 100

    def test_check_human_output_no_crash(self, cli_runner, cli_app, monkeypatch, tmp_path):
        """cc memory check (human readable) does not crash."""
        import cc.core.entry_store as es
        monkeypatch.setattr(es, "_git_root", lambda: tmp_path)

        self._make_entry(tmp_path, "Just prose.")
        result = cli_runner.invoke(cli_app, ["memory", "check", "--no-paths", "--no-commands", "--no-stale"])
        assert result.exit_code == 0
