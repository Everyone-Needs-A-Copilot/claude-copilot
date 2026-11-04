#!/usr/bin/env python3
"""Codex native adapter to the shared, provider-free cycle lifecycle smoke."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def role_ids(include_optional: bool = False) -> list[str]:
    catalog = json.loads((ROOT / 'agent-catalog.json').read_text())
    roles = [agent['id'] for agent in catalog['agents']]
    if include_optional:
        roles.extend(agent['id'] for agent in catalog['optionalAgents'])
    return list(dict.fromkeys(roles))

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['smoke'])
    parser.add_argument('--include-optional', action='store_true', help='Check optional role labels without activating their packs')
    parser.add_argument('--tc', default=shutil.which('tc'), help='Exact shared tc executable; no provider CLI is invoked')
    parser.add_argument('--out', help='Shared smoke evidence destination')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    if not args.tc:
        parser.error('shared tc is missing; restore tooling before dispatch')
    command = [args.tc, 'cycle', 'smoke', '--roles', ','.join(role_ids(args.include_optional))]
    if args.out:
        command.extend(['--out', args.out])
    if args.json:
        command.append('--json')
    try:
        return subprocess.run(command, check=False).returncode
    except OSError as exc:
        print(f'Cannot run shared cycle smoke: {exc}', file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
