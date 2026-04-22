#!/usr/bin/env bash
# Smoke tests for .claude/claude-launcher
# Tests: status line output, env var override, missing .model fallback.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LAUNCHER="$PROJECT_ROOT/.claude/claude-launcher"
MODEL_FILE="$PROJECT_ROOT/.claude/.model"

PASS=0
FAIL=0

ok() {
  echo "  PASS: $1"
  PASS=$((PASS + 1))
}

fail() {
  echo "  FAIL: $1"
  FAIL=$((FAIL + 1))
}

run_test() {
  local label="$1"; shift
  echo "--- $label"
  if "$@"; then
    :
  else
    return 1
  fi
}

# ---------------------------------------------------------------------------
# Test 1: Launcher exits 0 and emits status line for --version
# ---------------------------------------------------------------------------
test_version_exit_and_status_line() {
  local stderr_out
  stderr_out="$("$LAUNCHER" --version 2>&1 >/dev/null)" || {
    fail "launcher exited non-zero on --version"
    return
  }
  if echo "$stderr_out" | grep -q '^\[claude-launcher\] model='; then
    ok "status line emitted to stderr"
  else
    fail "status line not found in stderr: $stderr_out"
  fi
}

# ---------------------------------------------------------------------------
# Test 2: CLAUDE_MODEL env var overrides .model file
# ---------------------------------------------------------------------------
test_env_var_override() {
  local stderr_out
  stderr_out="$(CLAUDE_MODEL=test-model-override "$LAUNCHER" --version 2>&1 >/dev/null)" || {
    fail "launcher exited non-zero with CLAUDE_MODEL set"
    return
  }
  if echo "$stderr_out" | grep -q 'source=env'; then
    ok "CLAUDE_MODEL env var reported as source=env"
  else
    fail "source=env not found in stderr: $stderr_out"
  fi
  if echo "$stderr_out" | grep -q 'model=test-model-override'; then
    ok "CLAUDE_MODEL value reflected in status line"
  else
    fail "model value not reflected in stderr: $stderr_out"
  fi
}

# ---------------------------------------------------------------------------
# Test 3: Missing/empty .model file falls back to source=default
# ---------------------------------------------------------------------------
test_missing_model_file_fallback() {
  local tmp_model
  tmp_model="$(mktemp)"
  # Temporarily move the .model file aside
  cp "$MODEL_FILE" "$tmp_model"
  rm "$MODEL_FILE"

  local stderr_out exit_code
  exit_code=0
  stderr_out="$("$LAUNCHER" --version 2>&1 >/dev/null)" || exit_code=$?

  # Restore
  cp "$tmp_model" "$MODEL_FILE"
  rm "$tmp_model"

  if [[ "$exit_code" -ne 0 ]]; then
    fail "launcher exited non-zero when .model file missing (exit=$exit_code)"
    return
  fi
  if echo "$stderr_out" | grep -q 'source=default'; then
    ok "falls back to source=default when .model missing"
  else
    fail "source=default not found in stderr: $stderr_out"
  fi
}

# ---------------------------------------------------------------------------
# Test 4: .model file value is used as source=file
# ---------------------------------------------------------------------------
test_model_file_is_used() {
  local stderr_out
  stderr_out="$("$LAUNCHER" --version 2>&1 >/dev/null)" || {
    fail "launcher exited non-zero when using .model file"
    return
  }
  if echo "$stderr_out" | grep -q 'source=file'; then
    ok ".model file reported as source=file"
  else
    fail "source=file not found in stderr: $stderr_out"
  fi
}

# ---------------------------------------------------------------------------
# Test 5: Multi-line .model file — only first line is used as model ID
# ---------------------------------------------------------------------------
test_multiline_model_file() {
  local tmp_model
  tmp_model="$(mktemp)"
  # Preserve original .model
  cp "$MODEL_FILE" "$tmp_model"

  # Write two model IDs to .model; only the first should be used
  printf 'claude-sonnet-4-6[1m]\nclaude-opus-4-5\n' > "$MODEL_FILE"

  local stderr_out exit_code
  exit_code=0
  stderr_out="$("$LAUNCHER" --version 2>&1 >/dev/null)" || exit_code=$?

  # Restore
  cp "$tmp_model" "$MODEL_FILE"
  rm "$tmp_model"

  if [[ "$exit_code" -ne 0 ]]; then
    fail "launcher exited non-zero with multi-line .model (exit=$exit_code)"
    return
  fi
  # Must contain exactly the first-line model, not a concatenation
  if echo "$stderr_out" | grep -q 'model=claude-sonnet-4-6\[1m\]'; then
    ok "multi-line .model: first line used as model ID"
  else
    fail "multi-line .model: expected first-line model in stderr: $stderr_out"
  fi
  # Must NOT contain the second model ID (which would indicate concatenation)
  if echo "$stderr_out" | grep -q 'claude-opus-4-5'; then
    fail "multi-line .model: second line leaked into model ID (concatenation bug)"
  else
    ok "multi-line .model: second line not present in model ID"
  fi
}

# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------
echo "=== claude-launcher smoke tests ==="
test_version_exit_and_status_line
test_env_var_override
test_missing_model_file_fallback
test_model_file_is_used
test_multiline_model_file

echo ""
echo "Results: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
