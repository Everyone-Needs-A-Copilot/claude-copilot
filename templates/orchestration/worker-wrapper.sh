#!/bin/bash
# Worker wrapper script - ensures PID file cleanup on exit
#
# Usage: worker-wrapper.sh <stream-id> <pid-file> <log-dir> <work-dir> <initiative-id> <prompt>
#
# This wrapper:
# 1. Archives any existing log file for this stream
# 2. Creates new per-initiative log file
# 3. Writes PID file
# 4. Sets up EXIT trap to clean up PID file
# 5. Runs Claude with the prompt
# 6. Cleans up on exit (success, failure, or signal)

# Ensure common paths are in PATH (homebrew, local bin, etc.)
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"

STREAM_ID="$1"
PID_FILE="$2"
LOG_DIR="$3"
WORK_DIR="$4"
INITIATIVE_ID="$5"
PROMPT="$6"

# Short initiative ID for filename (first 8 chars)
SHORT_INIT_ID="${INITIATIVE_ID:0:8}"

# Log file uses per-initiative naming
LOG_FILE="$LOG_DIR/${STREAM_ID}_${SHORT_INIT_ID}.log"

# Archive directory
ARCHIVE_DIR="$LOG_DIR/archive"

# Archive old logs for this stream (from previous initiatives)
archive_old_logs() {
    mkdir -p "$ARCHIVE_DIR"

    # Find any existing logs for this stream (both old format and other initiative IDs)
    for old_log in "$LOG_DIR/${STREAM_ID}"*.log "$LOG_DIR/${STREAM_ID}.log"; do
        [ -f "$old_log" ] 2>/dev/null || continue

        # Skip if it's our current log file
        [ "$old_log" = "$LOG_FILE" ] && continue

        # Get timestamp from file modification time
        if [[ "$OSTYPE" == "darwin"* ]]; then
            timestamp=$(stat -f "%Sm" -t "%Y%m%d_%H%M%S" "$old_log" 2>/dev/null)
        else
            timestamp=$(stat -c "%y" "$old_log" 2>/dev/null | cut -d'.' -f1 | tr ' ' '_' | tr ':' '-')
        fi

        # Archive with timestamp
        base_name=$(basename "$old_log" .log)
        archive_name="${base_name}_${timestamp}.log"
        mv "$old_log" "$ARCHIVE_DIR/$archive_name" 2>/dev/null
    done
}

# Cleanup function - runs on ANY exit
cleanup() {
    local exit_code=$?
    echo "" >> "$LOG_FILE"
    echo "============================================================" >> "$LOG_FILE"
    echo "Worker exited: $(date -Iseconds)" >> "$LOG_FILE"
    echo "Exit code: $exit_code" >> "$LOG_FILE"
    echo "============================================================" >> "$LOG_FILE"

    # Remove PID file
    rm -f "$PID_FILE"

    exit $exit_code
}

# Set up trap for all exit scenarios
trap cleanup EXIT INT TERM HUP

# Archive old logs before starting
archive_old_logs

# Write our PID
echo $$ > "$PID_FILE"

# Log start with initiative context
{
    echo ""
    echo "============================================================"
    echo "Started: $(date -Iseconds)"
    echo "Stream: $STREAM_ID"
    echo "Initiative: $INITIATIVE_ID"
    echo "PID: $$"
    echo "Working dir: $WORK_DIR"
    echo "Log file: $LOG_FILE"
    echo "============================================================"
    echo ""
} >> "$LOG_FILE"

# Change to work directory
cd "$WORK_DIR" || exit 1

# Debug: Log prompt length and claude path
{
    echo "Prompt length: ${#PROMPT} chars"
    echo "Claude path: $(which claude 2>/dev/null || echo 'NOT FOUND')"
    echo "PATH: $PATH"
    echo "Starting claude..."
} >> "$LOG_FILE"

# Run Claude - output goes to log file
claude --print --dangerously-skip-permissions -p "$PROMPT" >> "$LOG_FILE" 2>&1
CLAUDE_EXIT=$?
echo "Claude exited with code: $CLAUDE_EXIT" >> "$LOG_FILE"

# Exit code will be captured by trap
