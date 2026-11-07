#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

pattern="/Users/[^/[:space:]\"]+|/home/[^/[:space:]\"]+|/Volumes/[^/[:space:]\"]+"
placeholder='/Users/(yourname|you|username|yourusername|your-username|example|user)\b'
violations=""

intentional_fixture() {
  case "$1" in
    tools/cc/src/cc/core/evaluation/safety.py | \
    tools/cc/tests/conformance/baselines/2026-08-12-reviewed-current.json | \
    tools/cc/tests/release_codex/fixtures/hooks_list_live_codex_0.167.0.json)
      return 0
      ;;
  esac
  return 1
}

while IFS= read -r -d '' file; do
  case "$file" in
    docs/* | */docs/* | templates/* | src/*.egg-info/* | node_modules/* | \
    .mcp.json | .claude/settings.local.json | coverage.xml | \
    scripts/pre-commit-no-hardcoded-paths | scripts/check-no-hardcoded-paths.sh | \
    .github/workflows/no-hardcoded-paths.yml)
      continue
      ;;
  esac
  if intentional_fixture "$file"; then
    continue
  fi
  matches="$(grep -nE "$pattern" "$file" 2>/dev/null | grep -vE "$placeholder" || true)"
  if [[ -n "$matches" ]]; then
    violations+="${file}:${matches}"$'\n'
  fi
done < <(git ls-files -z)

if [[ -n "$violations" ]]; then
  printf 'ERROR: hardcoded machine paths found\n\n%s' "$violations" >&2
  exit 1
fi

echo "No hardcoded machine paths found in portable tracked files."
