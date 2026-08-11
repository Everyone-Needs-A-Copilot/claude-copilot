"""Parity test between tc's and cc's content_guard modules (item 3).

`cc` and `tc` are separate installables with no shared package (see the
module docstring in `tc.services.content_guard` / `cc.core.content_guard`
for why the module is duplicated rather than factored into a new shared
dependency). The duplication is only safe as long as the two copies never
drift, so this test is the mechanism that checks the mechanism: it compares
the two files byte-for-byte, not just the pattern tuples, because the
redaction/neutralization logic and the rationale comments are exactly as
load-bearing as the regex strings themselves -- a "the patterns match but
the redaction logic diverged" drift would be just as real a bug.
"""

from __future__ import annotations

from pathlib import Path

from tc.services.content_guard import INJECTION_PATTERNS, SECRET_PATTERNS

_TC_MODULE = Path(__file__).resolve().parents[1] / "src" / "tc" / "services" / "content_guard.py"
_CC_MODULE = (
    Path(__file__).resolve().parents[3] / "tools" / "cc" / "src" / "cc" / "core" / "content_guard.py"
)


def test_cc_sibling_module_exists():
    assert _CC_MODULE.is_file(), f"expected cc's copy at {_CC_MODULE}"


def test_modules_are_byte_identical():
    tc_text = _TC_MODULE.read_text(encoding="utf-8")
    cc_text = _CC_MODULE.read_text(encoding="utf-8")
    assert tc_text == cc_text, (
        "tc.services.content_guard and cc.core.content_guard have drifted -- "
        "the two files must be kept byte-identical (see this test's module "
        "docstring). Diff the two files and reconcile them."
    )


def test_pattern_id_order_is_stable_and_non_empty():
    # Cheap sanity check independent of the byte-identity test above: the
    # tuples this process actually loaded aren't empty and have unique ids.
    injection_ids = [spec.id for spec in INJECTION_PATTERNS]
    secret_ids = [spec.id for spec in SECRET_PATTERNS]
    assert len(injection_ids) >= 10
    assert len(secret_ids) >= 8
    assert len(injection_ids) == len(set(injection_ids))
    assert len(secret_ids) == len(set(secret_ids))
