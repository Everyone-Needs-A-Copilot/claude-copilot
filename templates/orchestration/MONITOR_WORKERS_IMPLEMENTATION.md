# Monitor Workers Implementation

**Task:** TASK-006 - Port monitor-workers.py
**Date:** 2026-01-13
**Status:** COMPLETE

## Overview

Created a standalone worker monitoring daemon for the Claude Copilot orchestration system that detects dead/crashed workers and automatically restarts them with configurable retry limits.

## Implementation Details

### File Created
- **Location:** `templates/orchestration/monitor-workers.py`
- **Size:** ~550 lines
- **Executable:** Requires `chmod +x` (see Post-Installation below)

### Core Features

1. **Zombie Detection**
   - Uses `ps -p` verification (same pattern as check-streams)
   - Catches zombie processes that pass `kill -0` but fail `ps -p`
   - Double-verification ensures accurate dead worker detection

2. **Auto-Restart Capability**
   - Configurable max restart count (default: 2)
   - Uses existing `worker-wrapper.sh` for spawning
   - Respects stream dependencies (only restarts if dependencies complete)
   - Tracks restart attempts per worker to prevent infinite loops

3. **Operating Modes**
   - **One-shot check:** Reports dead workers without restarting
   - **Daemon mode:** Continuous monitoring with periodic checks
   - **Auto-restart:** Enables automatic worker restart on detection

4. **Logging**
   - All activity logged to `logs/monitor.log` with timestamps
   - Console output with color-coded severity levels
   - Restart attempts tracked with counts

5. **Integration**
   - Uses Task Copilot client for stream and status queries
   - Reads initiative context from Memory Copilot
   - Integrates with existing PID file management
   - Works with per-initiative log file naming

### Architecture

```python
class WorkerMonitor:
    def __init__(max_restarts, auto_restart):
        # Initialize Task Copilot client
        # Query streams and dependencies
        # Set up restart tracking

    def _is_running(stream_id):
        # Check PID file existence
        # Verify with kill -0
        # Double-check with ps -p (catches zombies)

    def _detect_dead_workers():
        # Find workers that:
        #   - Were previously running (log exists)
        #   - Are now dead
        #   - Have incomplete tasks
        #   - Have dependencies satisfied

    def restart_worker(stream_id):
        # Check restart limit
        # Spawn via worker-wrapper.sh
        # Track restart count

    def check_once():
        # Single check for dead workers
        # Optionally restart if auto_restart enabled

    def run_daemon(interval):
        # Continuous monitoring loop
        # Graceful shutdown on signals
```

### Usage Examples

```bash
# One-shot check (no restart)
python monitor-workers.py

# Background daemon with auto-restart
python monitor-workers.py --auto-restart

# Custom max restarts
python monitor-workers.py --auto-restart --max-restarts 3

# Daemon mode with custom interval
python monitor-workers.py --daemon --auto-restart --interval 60

# Check only (daemon without restart)
python monitor-workers.py --daemon --interval 30
```

### Command-Line Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--auto-restart` | Enable automatic restart of dead workers | False |
| `--max-restarts N` | Maximum restart attempts per worker | 2 |
| `--daemon` | Run as background daemon | False |
| `--interval N` | Check interval in seconds (daemon mode) | 30 |

### Exit Codes

- **0:** All workers healthy
- **1:** Dead workers detected (one-shot mode only)

### Log Output

Monitor logs are written to:
- **Location:** `.claude/orchestrator/logs/monitor.log`
- **Format:** `[ISO-timestamp] [LEVEL] message`
- **Levels:** INFO, SUCCESS, WARNING, ERROR

Example log entries:
```
[2026-01-13T10:30:00.123456] [INFO] Starting monitor daemon (interval: 30s, max_restarts: 2)
[2026-01-13T10:30:30.456789] [WARNING] Found 1 dead worker(s): Stream-B
[2026-01-13T10:30:30.567890] [INFO] Restarting worker Stream-B (attempt 1/2)
[2026-01-13T10:30:31.123456] [SUCCESS] Worker Stream-B restarted (PID: 12345)
```

## Integration with Existing System

### Dependencies
- `task_copilot_client.py` - Stream and status queries
- `worker-wrapper.sh` - Worker process spawning
- Memory Copilot DB - Initiative context
- Task Copilot DB - Stream metadata and task status

### File Structure
```
.claude/orchestrator/
├── monitor-workers.py       # This script
├── worker-wrapper.sh        # Used for spawning
├── task_copilot_client.py  # Data access layer
├── orchestrate.py           # Main orchestrator
├── check-streams            # Status display
├── pids/                    # PID files
│   └── *.pid
└── logs/                    # Log files
    ├── monitor.log          # Monitor daemon log
    └── Stream-*_*.log       # Worker logs
```

### Integration Points

1. **Dead Worker Detection:**
   - Same logic as `orchestrate.py._get_dead_workers()`
   - Uses `_is_running()` with ps -p verification
   - Checks log file size and task completion status

2. **Worker Restart:**
   - Identical prompt building as `orchestrate.py._build_prompt()`
   - Uses same worker-wrapper.sh spawning mechanism
   - Respects per-initiative log file naming

3. **Dependency Management:**
   - Queries stream dependencies from Task Copilot
   - Only restarts workers with satisfied dependencies
   - Prevents premature restart of blocked streams

## Testing Recommendations

1. **One-Shot Check:**
   ```bash
   python monitor-workers.py
   ```
   - Verify dead worker detection
   - Check log file output

2. **Manual Restart Test:**
   ```bash
   # Kill a worker
   kill -9 $(cat .claude/orchestrator/pids/Stream-A.pid)

   # Run monitor with auto-restart
   python monitor-workers.py --auto-restart

   # Verify restart in logs
   tail -20 .claude/orchestrator/logs/monitor.log
   ```

3. **Daemon Mode Test:**
   ```bash
   # Start daemon in background
   python monitor-workers.py --daemon --auto-restart &

   # Monitor log file
   tail -f .claude/orchestrator/logs/monitor.log

   # Kill a worker and observe auto-restart
   kill -9 $(cat .claude/orchestrator/pids/Stream-B.pid)

   # Stop daemon
   pkill -f monitor-workers.py
   ```

4. **Max Restart Limit Test:**
   ```bash
   # Set low limit and repeatedly kill worker
   python monitor-workers.py --daemon --auto-restart --max-restarts 1 &

   # Kill worker multiple times
   # Should stop restarting after max attempts
   ```

## Post-Installation

After deployment, run:
```bash
chmod +x templates/orchestration/monitor-workers.py
```

## Acceptance Criteria

- [x] Script exists at target location
- [x] Detects dead workers using ps -p verification
- [x] Auto-restarts with configurable limits
- [x] Logs all restart activity with timestamps
- [x] Works standalone and integrates with orchestration system
- [ ] Script is executable (requires `chmod +x` - see Post-Installation)
- [x] Supports `--auto-restart` flag
- [x] Supports `--max-restarts N` configuration
- [x] Daemon mode with `--daemon` flag
- [x] Configurable check interval with `--interval N`

## Future Enhancements

1. **Systemd Integration:**
   - Create systemd service file for production deployment
   - Auto-start on boot
   - Log rotation integration

2. **Alert System:**
   - Email/Slack notifications on repeated failures
   - Webhook support for external monitoring
   - PagerDuty integration for critical failures

3. **Metrics Collection:**
   - Track mean-time-between-failures (MTBF)
   - Monitor restart success rate
   - Export metrics to Prometheus/Grafana

4. **Smart Restart:**
   - Exponential backoff for repeated failures
   - Circuit breaker pattern for persistent issues
   - Automatic issue reporting to Memory Copilot

5. **Health Checks:**
   - Deep health verification beyond process existence
   - Detect stuck workers (no progress for N minutes)
   - Memory/CPU usage monitoring

## References

- **TASK-001:** worker-wrapper.sh implementation
- **TASK-003:** Zombie detection pattern in check-streams
- **orchestrate.py:** Dead worker detection logic (lines 284-321)
- **check-streams:** Process verification pattern (lines 43-66)
