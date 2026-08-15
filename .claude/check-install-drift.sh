#!/usr/bin/env bash
# FF9 validates this REPOSITORY. This checks what is actually INSTALLED.
#
# Benchmarking on 2026-08-15 found the two had diverged: the v5.13.4 baseline records
# 16 agents totalling 195,975 bytes, while ~/.claude carried a materially larger corpus.
# CI was passing against a footprint nobody was running. A budget enforced on an
# artifact you do not use is not a budget.
#
# Usage:  .claude/check-install-drift.sh [--json]
# Exit 0 = installed footprint within tolerance of the baseline ceilings.
set -euo pipefail

CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOLERANCE="${CC_DRIFT_TOLERANCE:-1.10}"

baseline=$(ls -1 "$REPO_DIR"/context-budget-baseline-v*.json 2>/dev/null | sort -V | tail -1)
[ -n "$baseline" ] || { echo "no context-budget baseline found in $REPO_DIR" >&2; exit 0; }

python3 - "$baseline" "$CONFIG_DIR" "$TOLERANCE" "${1:-}" <<'PY'
import json, sys, pathlib

baseline_path, config_dir, tol, mode = sys.argv[1], pathlib.Path(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
b = json.loads(pathlib.Path(baseline_path).read_text())
th = b["thresholds"]
bpt = b.get("byte_to_token_ratio", 4.0)

def tree_bytes(p):
    if not p.exists():
        return 0, 0
    if p.is_file():
        return p.stat().st_size, 1
    files = [f for f in p.rglob("*.md") if f.is_file()]
    return sum(f.stat().st_size for f in files), len(files)

rows, failed = [], False
checks = [
    ("agent corpus", config_dir / "agents",
     th.get("agent_corpus_ceiling_bytes") or b.get("agent_corpus_total_bytes", 0)),
    ("CLAUDE.md", config_dir / "CLAUDE.md", None),
    ("commands", config_dir / "commands", None),
    ("skills", config_dir / "skills", None),
]
for label, path, ceiling in checks:
    size, n = tree_bytes(path)
    row = {"artifact": label, "installed_bytes": size, "files": n,
           "installed_tokens": round(size / bpt)}
    if ceiling:
        limit = ceiling * tol
        row.update({"ceiling_bytes": ceiling, "tolerance": tol, "limit_bytes": round(limit)})
        if size > limit:
            failed = True
            row["status"] = "DRIFT"
        else:
            row["status"] = "ok"
    else:
        row["status"] = "info"
    rows.append(row)

if mode == "--json":
    print(json.dumps({"config_dir": str(config_dir), "rows": rows, "failed": failed}, indent=2))
else:
    print(f"Installed config: {config_dir}")
    for r in rows:
        base = f"  [{r['status']:>5}] {r['artifact']:<14} {r['installed_bytes']:>9,} B"
        if r["files"]:
            base += f"  ({r['files']} files)"
        if "ceiling_bytes" in r:
            base += (f"  ceiling {r['ceiling_bytes']:,} B x{r['tolerance']} "
                     f"= {r['limit_bytes']:,} B")
        print(base)
    if failed:
        print()
        print("The installed footprint exceeds what the committed baseline validates.")
        print("Either reconcile the install, or re-baseline deliberately with a reason.")

sys.exit(1 if failed else 0)
PY
