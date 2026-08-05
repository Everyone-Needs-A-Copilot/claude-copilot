"""probe.py — idle-gated OAuth probe for Claude unified rate-limit headers.

ADR-003: Probe ONLY when a transcript changed in last ~12 min.
Producer: this module writes ~/.claude/session-usage.json (atomic).
Consumer: statusline/dashboard read that file; they NEVER call this module.

Correctness invariant
---------------------
A /v1/messages probe itself opens a fresh 5-hour window.  Naive polling
corrupts the number it reports.  We only probe when Claude Code is
actually active (transcript mtime < IDLE_GATE_SECONDS).

Real header names (verified on 2026-06-17 against claude-haiku-4-5):
  anthropic-ratelimit-unified-5h-status        allowed | rate_limited
  anthropic-ratelimit-unified-5h-reset         Unix epoch int
  anthropic-ratelimit-unified-5h-utilization   0.0 – 1.0
  anthropic-ratelimit-unified-7d-status
  anthropic-ratelimit-unified-7d-reset
  anthropic-ratelimit-unified-7d-utilization
  anthropic-ratelimit-unified-overage-status
  anthropic-ratelimit-unified-overage-reset
  anthropic-ratelimit-unified-overage-utilization
  anthropic-ratelimit-unified-representative-claim  five_hour | seven_day
  anthropic-ratelimit-unified-fallback-percentage   0.0 – 1.0
  anthropic-ratelimit-unified-reset               (master reset epoch)

R1 mitigation: header names are NEVER hardcoded with exact mandatory
presence — each field degrades gracefully to None if absent.

Platform: macOS only (Keychain); non-macOS returns a graceful fallback.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (R1: these are defaults; code degrades gracefully if wrong)
# ---------------------------------------------------------------------------

KEYCHAIN_SERVICE = "Claude Code-credentials"
PROBE_MODEL = "claude-haiku-4-5"        # cheapest model, 1-token probe
PROBE_MAX_TOKENS = 1
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

IDLE_GATE_SECONDS = 12 * 60            # 12 minutes — don't probe when idle
CACHE_PATH = Path.home() / ".claude" / "session-usage.json"
TRANSCRIPT_GLOB = "**/*.jsonl"
TRANSCRIPT_ROOT = Path.home() / ".claude" / "projects"

# Header prefix (R1: any header with this prefix is captured, not just known ones)
_RL_PREFIX = "anthropic-ratelimit-unified-"


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass
class UsageCache:
    """Serialisable record written to CACHE_PATH."""
    probed_at: float                        # epoch when probe ran
    source: str                             # "probe" | "fallback" | "stale"
    idle_gated: bool = False                # True when probe was skipped
    probe_error: Optional[str] = None       # error message if probe failed

    # 5-hour window
    five_h_status: Optional[str] = None    # allowed | rate_limited | None
    five_h_utilization: Optional[float] = None
    five_h_reset_epoch: Optional[int] = None

    # 7-day window
    seven_d_status: Optional[str] = None
    seven_d_utilization: Optional[float] = None
    seven_d_reset_epoch: Optional[int] = None

    # Overage
    overage_status: Optional[str] = None
    overage_utilization: Optional[float] = None
    overage_reset_epoch: Optional[int] = None

    # Meta
    representative_claim: Optional[str] = None   # five_hour | seven_day
    fallback_percentage: Optional[float] = None
    master_reset_epoch: Optional[int] = None

    # Transcript fallback (populated when source=="fallback")
    five_h_tokens_reconstructed: Optional[int] = None
    seven_d_tokens_reconstructed: Optional[int] = None

    # Raw headers stored verbatim for forward-compat (R1 hedge)
    raw_headers: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "UsageCache":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})


# ---------------------------------------------------------------------------
# Keychain / token extraction (macOS only)
# ---------------------------------------------------------------------------

def _is_macos() -> bool:
    return platform.system() == "Darwin"


def _load_keychain_token() -> Optional[str]:
    """Return the Claude Code OAuth access token from macOS Keychain, or None."""
    if not _is_macos():
        _log.debug("Non-macOS: skipping Keychain lookup")
        return None
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            _log.debug("Keychain lookup failed: %s", result.stderr.strip())
            return None
        raw = result.stdout.strip()
        if not raw:
            return None
        creds = json.loads(raw)
        token = (
            creds.get("claudeAiOauth", {}).get("accessToken")
            or creds.get("accessToken")
            or creds.get("token")
        )
        if not token:
            _log.debug("claudeAiOauth.accessToken not found in Keychain payload")
        return token or None
    except Exception as exc:
        _log.debug("Keychain extraction error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Transcript mtime — idle gate
# ---------------------------------------------------------------------------

def _most_recent_transcript_mtime() -> Optional[float]:
    """Return the mtime of the most recently modified transcript file, or None."""
    if not TRANSCRIPT_ROOT.exists():
        return None
    latest: Optional[float] = None
    try:
        for p in TRANSCRIPT_ROOT.glob(TRANSCRIPT_GLOB):
            try:
                mt = p.stat().st_mtime
                if latest is None or mt > latest:
                    latest = mt
            except OSError:
                continue
    except Exception as exc:
        _log.debug("Transcript glob error: %s", exc)
    return latest


def _should_probe(now: Optional[float] = None, _mtime_fn=_most_recent_transcript_mtime) -> bool:
    """Return True iff a transcript changed within IDLE_GATE_SECONDS of *now*.

    Abstracted so tests can inject both clock and mtime without touching
    the filesystem.
    """
    if now is None:
        now = time.time()
    mtime = _mtime_fn()
    if mtime is None:
        return False
    return (now - mtime) <= IDLE_GATE_SECONDS


# ---------------------------------------------------------------------------
# Header parsing (R1: capture everything with the prefix)
# ---------------------------------------------------------------------------

def _parse_ratelimit_headers(headers: dict) -> dict:
    """Extract all anthropic-ratelimit-unified-* headers into a normalised dict.

    Keys are the suffix after 'anthropic-ratelimit-unified-' (lower-cased).
    Values are returned as strings; callers coerce as needed.
    """
    out: dict = {}
    for k, v in headers.items():
        kl = k.lower()
        if kl.startswith(_RL_PREFIX):
            suffix = kl[len(_RL_PREFIX):]
            out[suffix] = v
    return out


def _coerce_float(v: Optional[str]) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _coerce_int(v: Optional[str]) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _build_cache_from_headers(parsed: dict, raw_headers: dict) -> UsageCache:
    """Populate a UsageCache from parsed rate-limit header suffixes."""
    return UsageCache(
        probed_at=time.time(),
        source="probe",
        idle_gated=False,
        five_h_status=parsed.get("5h-status"),
        five_h_utilization=_coerce_float(parsed.get("5h-utilization")),
        five_h_reset_epoch=_coerce_int(parsed.get("5h-reset")),
        seven_d_status=parsed.get("7d-status"),
        seven_d_utilization=_coerce_float(parsed.get("7d-utilization")),
        seven_d_reset_epoch=_coerce_int(parsed.get("7d-reset")),
        overage_status=parsed.get("overage-status"),
        overage_utilization=_coerce_float(parsed.get("overage-utilization")),
        overage_reset_epoch=_coerce_int(parsed.get("overage-reset")),
        representative_claim=parsed.get("representative-claim"),
        fallback_percentage=_coerce_float(parsed.get("fallback-percentage")),
        master_reset_epoch=_coerce_int(parsed.get("reset")),
        raw_headers=raw_headers,
    )


# ---------------------------------------------------------------------------
# Atomic cache writer
# ---------------------------------------------------------------------------

def write_cache(cache: UsageCache, path: Path = CACHE_PATH) -> None:
    """Atomic write: write to a tmp file, then rename into place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(cache.to_dict(), indent=2)
    # Write to a sibling tmp file, rename atomically
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".session-usage-")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(data)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def read_cache(path: Path = CACHE_PATH) -> Optional[UsageCache]:
    """Read the cache file if it exists, else return None."""
    try:
        raw = json.loads(path.read_text())
        return UsageCache.from_dict(raw)
    except Exception as exc:
        _log.debug("Cache read failed (%s): %s", path, exc)
        return None


# ---------------------------------------------------------------------------
# Network probe
# ---------------------------------------------------------------------------

def _do_probe(token: str) -> UsageCache:
    """Make a 1-token probe and parse rate-limit headers.

    On any network/auth error, returns a cache with source='probe' and
    probe_error set; does NOT raise.
    """
    body = json.dumps({
        "model": PROBE_MODEL,
        "max_tokens": PROBE_MAX_TOKENS,
        "messages": [{"role": "user", "content": "1"}],
    }).encode()
    req = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
        },
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        raw_headers = dict(resp.headers)
        parsed = _parse_ratelimit_headers(raw_headers)
        return _build_cache_from_headers(parsed, raw_headers)
    except urllib.error.HTTPError as e:
        # 4xx/5xx — headers may still carry rate-limit info
        raw_headers = dict(e.headers)
        parsed = _parse_ratelimit_headers(raw_headers)
        if parsed:
            cache = _build_cache_from_headers(parsed, raw_headers)
            cache.probe_error = f"HTTP {e.code}"
            return cache
        return UsageCache(
            probed_at=time.time(),
            source="probe",
            probe_error=f"HTTP {e.code}: {e.read()[:200].decode('utf-8', 'replace')}",
        )
    except Exception as exc:
        return UsageCache(
            probed_at=time.time(),
            source="probe",
            probe_error=str(exc),
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_probe(
    force: bool = False,
    cache_path: Path = CACHE_PATH,
    _mtime_fn=_most_recent_transcript_mtime,
    _now: Optional[float] = None,
) -> UsageCache:
    """Run the idle-gated probe workflow and write the cache.

    If *force* is True, skip the idle gate (used by ``cc usage --refresh``).

    Returns the resulting UsageCache (whether probed, gated, or fallback).
    """
    from cc.usage.reconstruct import reconstruct_usage

    now = _now if _now is not None else time.time()

    # --- Idle gate ---
    if not force and not _should_probe(now, _mtime_fn=_mtime_fn):
        _log.debug("Idle gate: no recent transcript; skipping probe")
        existing = read_cache(cache_path)
        if existing is not None:
            existing.idle_gated = True
            return existing
        # No cache and no active session: transcript fallback
        fallback = reconstruct_usage()
        fallback.idle_gated = True
        write_cache(fallback, cache_path)
        return fallback

    # --- Attempt network probe (macOS + Keychain) ---
    token = _load_keychain_token()
    if token:
        _log.debug("Probing %s with claude-haiku-4-5 (1 token)", ANTHROPIC_API_URL)
        cache = _do_probe(token)
        if cache.probe_error:
            _log.debug("Probe error: %s — falling back to transcript reconstruction", cache.probe_error)
            fallback = reconstruct_usage()
            fallback.probe_error = cache.probe_error
            write_cache(fallback, cache_path)
            return fallback
        write_cache(cache, cache_path)
        return cache
    else:
        _log.debug("No Keychain token; falling back to transcript reconstruction")
        fallback = reconstruct_usage()
        write_cache(fallback, cache_path)
        return fallback
