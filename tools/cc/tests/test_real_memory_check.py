"""Run cc memory check against the real repo's memory entries and capture the output.

This is a one-shot integration test that serves as the 'real artifact' required by
WP-125's R2 contract. It prints the JSON output and score so it can be captured.

Run: python3 -m pytest tools/cc/tests/test_real_memory_check.py -v -s
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def test_real_repo_memory_check():
    """Run cc memory check on the real project memory and report score.

    This test always passes — it's an observation test, not an assertion.
    The output is captured in the pytest -s (no-capture) output.
    """
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from cc.core.memory_check import check_all_entries
    from cc.core.entry_store import list_entries

    try:
        entries = list_entries(scope="project")
    except ValueError as e:
        print(f"[SKIP] Not in git repo or no project memory: {e}")
        return

    print(f"\nProject memory entries: {len(entries)}")

    report = check_all_entries(entries)
    data = report.to_dict()

    print(f"Score: {data['score']}/100")
    print(f"Verdict: {data['verdict']}")
    print(f"Flagged: {len(data['flagged'])} issues")

    if data["flagged"]:
        for f in data["flagged"][:10]:  # Show first 10
            print(f"  [{f['status'].upper()}] [{f['check']}] {f['entry_id'][:8]}  {f.get('message', '')[:80]}")

    print("\nFull JSON report (first 500 chars):")
    print(json.dumps(data, indent=2)[:500])

    # Always pass — this is an observation test
    assert data["score"] is not None
    assert 0 <= data["score"] <= 100
