"""Tests for cc.core.skill_cache -- the parsed-frontmatter cache (WP-372
P2.2), mirroring test_docs_cache.py's conventions: every test injects
`cache_dir=tmp_path`, never the real machine default.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cc.core.skill_cache import (
    _DB_NAME,
    cache_clear,
    cache_get_frontmatter,
    cache_put_frontmatter,
    skill_cache_dir,
    skill_cache_ttl_hours,
)


@pytest.fixture(autouse=True)
def _no_real_home(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError(
            "skill cache test attempted to resolve Path.home() -- inject tmp_path instead"
        )

    monkeypatch.setattr(Path, "home", staticmethod(_boom))


@pytest.fixture
def cache(tmp_path: Path) -> Path:
    return tmp_path / "skill-cache"


# ---------------------------------------------------------------------------
# cache_get_frontmatter / cache_put_frontmatter
# ---------------------------------------------------------------------------


def test_get_miss_on_absent_db(cache: Path, tmp_path: Path):
    result = cache_get_frontmatter(
        tmp_path / "SKILL.md", mtime=1.0, size=10, cache_dir=cache
    )
    assert result is None
    # A miss on a not-yet-created cache must never create the DB file
    # itself (no db, no directory pollution just from checking).
    assert not (cache / _DB_NAME).exists()


def test_put_then_get_roundtrip(cache: Path, tmp_path: Path):
    skill_path = tmp_path / "alpha" / "SKILL.md"
    fm = {"name": "alpha", "description": "test", "triggers": {"keywords": ["a"]}}

    cache_put_frontmatter(skill_path, mtime=100.0, size=42, frontmatter=fm, cache_dir=cache)
    got = cache_get_frontmatter(skill_path, mtime=100.0, size=42, cache_dir=cache)

    assert got == fm


def test_get_misses_on_mtime_mismatch(cache: Path, tmp_path: Path):
    skill_path = tmp_path / "alpha" / "SKILL.md"
    cache_put_frontmatter(
        skill_path, mtime=100.0, size=42, frontmatter={"name": "alpha"}, cache_dir=cache
    )
    got = cache_get_frontmatter(skill_path, mtime=200.0, size=42, cache_dir=cache)
    assert got is None


def test_get_misses_on_size_mismatch(cache: Path, tmp_path: Path):
    skill_path = tmp_path / "alpha" / "SKILL.md"
    cache_put_frontmatter(
        skill_path, mtime=100.0, size=42, frontmatter={"name": "alpha"}, cache_dir=cache
    )
    got = cache_get_frontmatter(skill_path, mtime=100.0, size=99, cache_dir=cache)
    assert got is None


def test_get_expires_after_ttl(cache: Path, tmp_path: Path):
    skill_path = tmp_path / "alpha" / "SKILL.md"
    cache_put_frontmatter(
        skill_path, mtime=100.0, size=42, frontmatter={"name": "alpha"}, cache_dir=cache
    )
    # ttl_hours=0 -- any stored entry is immediately "too old"
    got = cache_get_frontmatter(
        skill_path, mtime=100.0, size=42, cache_dir=cache, ttl_hours=0
    )
    assert got is None


def test_put_overwrites_previous_entry_for_same_path(cache: Path, tmp_path: Path):
    skill_path = tmp_path / "alpha" / "SKILL.md"
    cache_put_frontmatter(
        skill_path, mtime=100.0, size=42, frontmatter={"name": "v1"}, cache_dir=cache
    )
    cache_put_frontmatter(
        skill_path, mtime=200.0, size=50, frontmatter={"name": "v2"}, cache_dir=cache
    )
    got = cache_get_frontmatter(skill_path, mtime=200.0, size=50, cache_dir=cache)
    assert got == {"name": "v2"}
    # The stale (mtime=100) entry no longer matches -- confirms one row per
    # path (INSERT OR REPLACE), not an accumulating history.
    stale = cache_get_frontmatter(skill_path, mtime=100.0, size=42, cache_dir=cache)
    assert stale is None


def test_different_paths_do_not_collide(cache: Path, tmp_path: Path):
    a = tmp_path / "alpha" / "SKILL.md"
    b = tmp_path / "beta" / "SKILL.md"
    cache_put_frontmatter(a, mtime=1.0, size=1, frontmatter={"name": "alpha"}, cache_dir=cache)
    cache_put_frontmatter(b, mtime=1.0, size=1, frontmatter={"name": "beta"}, cache_dir=cache)

    assert cache_get_frontmatter(a, mtime=1.0, size=1, cache_dir=cache) == {"name": "alpha"}
    assert cache_get_frontmatter(b, mtime=1.0, size=1, cache_dir=cache) == {"name": "beta"}


def test_cache_never_raises_on_corrupt_db(cache: Path, tmp_path: Path):
    cache.mkdir(parents=True)
    (cache / _DB_NAME).write_bytes(b"not a sqlite database")

    # Neither read nor write should raise -- best-effort, never blocks.
    result = cache_get_frontmatter(tmp_path / "SKILL.md", mtime=1.0, size=1, cache_dir=cache)
    assert result is None
    cache_put_frontmatter(
        tmp_path / "SKILL.md", mtime=1.0, size=1, frontmatter={"name": "x"}, cache_dir=cache
    )


# ---------------------------------------------------------------------------
# cache_clear
# ---------------------------------------------------------------------------


def test_cache_clear_removes_all_entries(cache: Path, tmp_path: Path):
    skill_path = tmp_path / "alpha" / "SKILL.md"
    cache_put_frontmatter(
        skill_path, mtime=1.0, size=1, frontmatter={"name": "alpha"}, cache_dir=cache
    )
    removed = cache_clear(cache_dir=cache)
    assert removed == 1
    assert cache_get_frontmatter(skill_path, mtime=1.0, size=1, cache_dir=cache) is None


def test_cache_clear_on_absent_db_returns_zero(cache: Path):
    assert cache_clear(cache_dir=cache) == 0


# ---------------------------------------------------------------------------
# skill_cache_dir() / skill_cache_ttl_hours()
# ---------------------------------------------------------------------------


def test_skill_cache_dir_override_creates_directory(tmp_path: Path):
    target = tmp_path / "override-cache"
    result = skill_cache_dir(_override=target)
    assert result == target
    assert target.is_dir()


def test_skill_cache_dir_writes_gitignore(tmp_path: Path):
    target = tmp_path / "override-cache"
    skill_cache_dir(_override=target)
    assert (target / ".gitignore").exists()


def test_skill_cache_ttl_hours_default(monkeypatch):
    monkeypatch.setattr("cc.core.skill_cache.resolve_key", lambda key: None)
    assert skill_cache_ttl_hours() == 24


def test_skill_cache_ttl_hours_reads_config(monkeypatch):
    monkeypatch.setattr(
        "cc.core.skill_cache.resolve_key",
        lambda key: 48 if key == "skills.cache_ttl_hours" else None,
    )
    assert skill_cache_ttl_hours() == 48
