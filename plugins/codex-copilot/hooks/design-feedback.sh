#!/bin/bash
# Optional native edit feedback; project/runtime opt-in is enforced by cc.
# Explicit tc QA remains authoritative even when this reminder is unavailable.
[ "${CC_DESIGN_FEEDBACK:-}" = "off" ] && exit 0
CC_DESIGN_BIN="$HOME/.local/bin/cc"
[ -x "$CC_DESIGN_BIN" ] || exit 0
exec "$CC_DESIGN_BIN" design feedback --runtime codex
