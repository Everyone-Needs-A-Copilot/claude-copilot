#!/usr/bin/env bash
set -euo pipefail

project=""
framework_root=""
project_name=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) project="${2:-}"; shift 2 ;;
    --framework-root) framework_root="${2:-}"; shift 2 ;;
    --name) project_name="${2:-}"; shift 2 ;;
    --description|--stack) shift 2 ;;
    --no-tc-init) shift ;;
    *) echo "unsupported fixture option: $1" >&2; exit 2 ;;
  esac
done

[[ -d "$project" ]] || { echo "missing project" >&2; exit 2; }
[[ -d "$framework_root/plugins/codex-copilot/skills" ]] || {
  echo "missing fixture plugin" >&2
  exit 2
}
[[ -x "$framework_root/scripts/copilot-gate.sh" ]] || {
  echo "missing fixture gate" >&2
  exit 2
}

mkdir -p \
  "$project/plugins" \
  "$project/.claude/skills" \
  "$project/.claude/cc" \
  "$project/.claude/memory/entries" \
  "$project/.agents/plugins" \
  "$project/docs/01-architecture" \
  "$project/docs/40-initiatives/_template/phases" \
  "$project/docs/40-initiatives/_template/decisions" \
  "$project/docs/40-initiatives/_template/retrospectives" \
  "$project/scripts"
cp -R "$framework_root/plugins/codex-copilot" "$project/plugins/codex-copilot"
ln -s ../../plugins/codex-copilot/skills "$project/.claude/skills/codex-copilot"
cp "$framework_root/scripts/copilot-gate.sh" "$project/scripts/copilot-gate.sh"
chmod +x "$project/scripts/copilot-gate.sh"

printf '# Project\n\n## Codex Copilot\n\nUse ./plugins/codex-copilot.\n' > "$project/AGENTS.md"
printf '# Product purpose\n' > "$project/SOUL.md"
printf '# Architecture guiding principles\n' > "$project/docs/01-architecture/12-architecture-guiding-principles.md"
printf '# Initiatives\n' > "$project/docs/40-initiatives/README.md"
printf '# Initiative template\n' > "$project/docs/40-initiatives/_template/README.md"
printf '%s\n' '{"name":"codex-copilot-project","plugins":[{"name":"codex-copilot","source":{"source":"local","path":"./plugins/codex-copilot"}}]}' > "$project/.agents/plugins/marketplace.json"
printf '{"installType":"copy","pluginPath":"./plugins/codex-copilot","projectName":"%s"}\n' "${project_name:-fixture}" > "$project/.codex-copilot.json"
printf '%s\n' '{"$schema":"cc-config-v1","version":1,"paths":{"knowledge_repo":"@machine"}}' > "$project/.claude/cc/config.json"
printf 'memory.db\nmemory.db-shm\nmemory.db-wal\n' > "$project/.claude/memory/.gitignore"
touch "$project/.claude/memory/entries/.gitkeep"
