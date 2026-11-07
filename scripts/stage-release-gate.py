#!/usr/bin/env python3
"""Verify a sanitized stage packet with this reviewed candidate's shared tc service.

Run only after existing source-signature verification. No database, native dispatch,
receipt command execution or validator-path override is accepted here.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# The caller verified this source, rather than an ambient tc on PATH.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "tc" / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--phase", required=True,
                        choices=("source-ready", "package-ready", "activate-ready", "complete"))
    args = parser.parse_args()
    try:
        from tc.services.cycle_stages import verify_packet
        result = verify_packet(file=args.file, sha256=args.sha256, root=args.root,
                               phase=args.phase, source_commit=args.source_commit)
        if not isinstance(result, dict) or result.get("approved") is not True:
            raise ValueError("stage service did not approve the candidate")
    except Exception as exc:
        print(f"Stage release refused: {exc}. Supply a current exported packet; upgrade stage-capable tooling if unavailable.", file=sys.stderr)
        return 4
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
