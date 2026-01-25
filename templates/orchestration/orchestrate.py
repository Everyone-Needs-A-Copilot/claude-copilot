#!/usr/bin/env python3
"""
Claude Copilot Orchestrator - Fully Dynamic Version

Spawns and manages multiple headless Claude Code sessions for parallel stream execution.
All stream information and dependencies are queried from Task Copilot SQLite database.

NO HARDCODED PHASES - Streams define their own dependencies, execution is fully dynamic.

Usage:
    python orchestrate.py preflight      # Validate environment before orchestration
    python orchestrate.py start          # Start all streams (respects dependencies)
    python orchestrate.py start Stream-C # Start specific stream
    python orchestrate.py status         # Check status of all streams
    python orchestrate.py stop           # Stop all running streams
    python orchestrate.py logs Stream-A  # Tail logs for a stream
    python orchestrate.py test-routing   # Show routing plan without executing (dry run)

Routing Logs:
    All agent routing decisions are logged to: .claude/orchestrator/logs/routing.log
"""

import json
import subprocess
import os
import sys
import time
import signal
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from collections import defaultdict

# Import Task Copilot client
from task_copilot_client import TaskCopilotClient

# Configuration
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # Go up from .claude/orchestrator to project root
PROJECT_NAME = PROJECT_ROOT.name  # Auto-detect from directory name
LOG_DIR = SCRIPT_DIR / "logs"
PID_DIR = SCRIPT_DIR / "pids"
ROUTING_LOG = LOG_DIR / "routing.log"
POLL_INTERVAL = 30  # seconds

# Task Copilot workspace ID - auto-detect from project name
WORKSPACE_ID = PROJECT_NAME


class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    MAGENTA = '\033[0;35m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    NC = '\033[0m'  # No Color


def log(msg: str, color: str = Colors.BLUE):
    print(f"{color}[ORCHESTRATOR]{Colors.NC} {msg}")


def success(msg: str):
    print(f"{Colors.GREEN}[SUCCESS]{Colors.NC} {msg}")


def warn(msg: str):
    print(f"{Colors.YELLOW}[WARNING]{Colors.NC} {msg}")


def error(msg: str):
    print(f"{Colors.RED}[ERROR]{Colors.NC} {msg}")


def log_routing(msg: str, to_file: bool = True, to_console: bool = True):
    """Log routing decision to file and/or console."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"[{timestamp}] {msg}"

    if to_console:
        print(f"{Colors.CYAN}[ROUTING]{Colors.NC} {msg}")

    if to_file:
        try:
            with open(ROUTING_LOG, "a") as f:
                f.write(log_msg + "\n")
        except Exception as e:
            warn(f"Failed to write to routing log: {e}")


class PreflightValidator:
    """Validates environment before orchestration to catch issues early."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.errors: List[Tuple[str, str]] = []  # (check_name, error_message)
        self.warnings: List[Tuple[str, str]] = []  # (check_name, warning_message)

    def validate_all(self) -> bool:
        """Run all validations. Returns True if environment is healthy."""
        self.errors = []
        self.warnings = []

        # Run all validation checks
        self.validate_claude_cli()
        self.validate_git_worktree_support()
        self.validate_directory_permissions()
        self.validate_task_copilot()

        # Return True only if no errors (warnings are acceptable)
        return len(self.errors) == 0

    def validate_claude_cli(self) -> bool:
        """Check Claude CLI is in PATH and executable."""
        # First check with shutil.which
        claude_path = shutil.which('claude')

        # If not found, check common installation locations
        if not claude_path:
            common_paths = [
                '/opt/homebrew/bin/claude',
                '/usr/local/bin/claude',
                os.path.expanduser('~/.local/bin/claude')
            ]
            for path in common_paths:
                if os.path.exists(path) and os.access(path, os.X_OK):
                    claude_path = path
                    break

        if not claude_path:
            self.errors.append((
                "Claude CLI",
                "NOT FOUND\n   → Install with: brew install anthropics/tap/claude\n   → Or add claude to PATH"
            ))
            return False

        # Verify it's executable
        if not os.access(claude_path, os.X_OK):
            self.errors.append((
                "Claude CLI",
                f"Found at {claude_path} but NOT EXECUTABLE\n   → Run: chmod +x {claude_path}"
            ))
            return False

        return True

    def validate_git_worktree_support(self) -> bool:
        """Check git supports worktrees and project is a git repo."""
        # Check if project is a git repository
        if not (self.project_root / '.git').exists():
            self.errors.append((
                "Git Repository",
                f"NOT A GIT REPO: {self.project_root}\n   → Initialize with: git init"
            ))
            return False

        # Check git version supports worktrees (requires git >= 2.5)
        try:
            result = subprocess.run(
                ['git', '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                self.errors.append((
                    "Git Version",
                    "Could not determine git version"
                ))
                return False

            # Parse version (output format: "git version 2.43.0")
            version_str = result.stdout.strip()
            # Extract version number
            import re
            match = re.search(r'git version (\d+)\.(\d+)', version_str)
            if match:
                major, minor = int(match.group(1)), int(match.group(2))
                if major < 2 or (major == 2 and minor < 5):
                    self.errors.append((
                        "Git Version",
                        f"Git {major}.{minor} found - worktrees require >= 2.5\n   → Update git: brew upgrade git"
                    ))
                    return False
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            self.errors.append((
                "Git Check",
                f"Failed to check git version: {e}"
            ))
            return False

        # Test worktree support by running 'git worktree list'
        try:
            result = subprocess.run(
                ['git', 'worktree', 'list'],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                self.errors.append((
                    "Git Worktree",
                    f"Git worktree command failed\n   → {result.stderr.strip()}"
                ))
                return False
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            self.errors.append((
                "Git Worktree",
                f"Failed to test worktree support: {e}"
            ))
            return False

        return True

    def validate_directory_permissions(self) -> bool:
        """Check write permissions for worktree directory."""
        worktree_base = self.project_root / '.claude' / 'worktrees'

        # If it doesn't exist, check parent directory
        if not worktree_base.exists():
            check_dir = self.project_root / '.claude'
            if not check_dir.exists():
                check_dir = self.project_root
        else:
            check_dir = worktree_base

        if not os.access(check_dir, os.W_OK):
            self.errors.append((
                "Directory Permissions",
                f"Cannot write to {check_dir}\n   → Check permissions: ls -la {check_dir.parent}"
            ))
            return False

        # Also check PID and log directories
        orchestrator_dir = self.project_root / '.claude' / 'orchestrator'
        if orchestrator_dir.exists():
            for subdir in ['pids', 'logs']:
                subdir_path = orchestrator_dir / subdir
                if subdir_path.exists() and not os.access(subdir_path, os.W_OK):
                    self.warnings.append((
                        f"{subdir.title()} Directory",
                        f"Warning - Cannot write to {subdir_path}"
                    ))

        return True

    def validate_task_copilot(self) -> bool:
        """Check Task Copilot MCP server is accessible."""
        mcp_json_path = self.project_root / '.mcp.json'

        if not mcp_json_path.exists():
            self.errors.append((
                "Task Copilot",
                "NOT CONFIGURED - .mcp.json not found\n   → Run: /setup-project"
            ))
            return False

        # Read and parse .mcp.json
        try:
            with open(mcp_json_path, 'r') as f:
                mcp_config = json.load(f)
        except json.JSONDecodeError as e:
            self.errors.append((
                "Task Copilot",
                f".mcp.json is invalid JSON: {e}"
            ))
            return False
        except Exception as e:
            self.errors.append((
                "Task Copilot",
                f"Could not read .mcp.json: {e}"
            ))
            return False

        # Check for task-copilot server configuration
        if 'mcpServers' not in mcp_config:
            self.errors.append((
                "Task Copilot",
                "NOT CONFIGURED - mcpServers missing in .mcp.json\n   → Run: /setup-project"
            ))
            return False

        if 'task-copilot' not in mcp_config['mcpServers']:
            self.errors.append((
                "Task Copilot",
                "NOT CONFIGURED - task-copilot server missing\n   → Run: /setup-project"
            ))
            return False

        # Verify the server path exists
        tc_config = mcp_config['mcpServers']['task-copilot']
        if 'args' in tc_config and len(tc_config['args']) > 0:
            server_path = Path(tc_config['args'][0])
            if not server_path.exists():
                self.warnings.append((
                    "Task Copilot",
                    f"Warning - Server path not found: {server_path}\n   → May need to rebuild: cd mcp-servers/task-copilot && npm run build"
                ))

        return True

    def validate_worktree(self, worktree_path: Path, main_project_path: Path) -> bool:
        """
        Validate a worktree was created correctly.

        Checks:
        1. Directory exists and is a git worktree (not just mkdir)
        2. File count is reasonable (within 50% of main project)
        3. Git recognizes it as a worktree

        Args:
            worktree_path: Path to the worktree directory
            main_project_path: Path to the main project root

        Returns:
            True if worktree is valid, False otherwise
        """
        # Clear errors/warnings for this validation
        worktree_errors = []

        # Check 1: Directory exists
        if not worktree_path.exists():
            self.errors.append((
                "Worktree Validation",
                f"Directory does not exist: {worktree_path}"
            ))
            return False

        # Check 2: .git file exists (worktrees have a .git file, not directory)
        git_file = worktree_path / '.git'
        if not git_file.exists():
            worktree_errors.append(f"Missing .git file in worktree")
        elif git_file.is_dir():
            worktree_errors.append(f".git is a directory (should be a file in worktrees)")

        # Check 3: Git recognizes it as a worktree
        try:
            result = subprocess.run(
                ['git', 'worktree', 'list'],
                cwd=main_project_path,
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                # Check if worktree_path is in the output
                worktree_listed = False
                for line in result.stdout.strip().split('\n'):
                    # Lines are like: "/path/to/worktree <hash> [branch]"
                    if str(worktree_path.resolve()) in line:
                        worktree_listed = True
                        break

                if not worktree_listed:
                    worktree_errors.append(f"Not listed in 'git worktree list'")
            else:
                worktree_errors.append(f"Failed to run 'git worktree list'")

        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            worktree_errors.append(f"Git command failed: {e}")

        # Check 4: File count comparison (within 50% of main project)
        try:
            # Count files in main project (excluding .git and common ignore patterns)
            main_files = []
            for root, dirs, files in os.walk(main_project_path):
                # Skip .git and common directories
                dirs[:] = [d for d in dirs if d not in ['.git', 'node_modules', '__pycache__', '.venv', 'venv']]
                main_files.extend(files)

            main_file_count = len(main_files)

            # Count files in worktree
            worktree_files = []
            for root, dirs, files in os.walk(worktree_path):
                dirs[:] = [d for d in dirs if d not in ['.git', 'node_modules', '__pycache__', '.venv', 'venv']]
                worktree_files.extend(files)

            worktree_file_count = len(worktree_files)

            # Expect at least 50% of main project files
            min_expected = int(main_file_count * 0.5)

            if worktree_file_count < min_expected:
                worktree_errors.append(
                    f"Directory has {worktree_file_count} files, expected ~{main_file_count} (main project has {main_file_count})"
                )

        except Exception as e:
            # File count check is best-effort, don't fail validation on exceptions
            pass

        # If there are errors, compile them into a single error message
        if worktree_errors:
            error_msg = f"INVALID WORKTREE: {worktree_path}\n"
            for err in worktree_errors:
                error_msg += f"   → {err}\n"
            error_msg += "   → This usually means 'mkdir' was used instead of 'git worktree add'\n"
            error_msg += f"   → Fix: Remove directory and re-create with 'git worktree add'"

            self.errors.append((
                "Worktree Validation",
                error_msg
            ))
            return False

        return True

    def print_report(self) -> None:
        """Print validation results with actionable messages."""
        print(f"\n{Colors.BOLD}🔍 Pre-flight Validation{Colors.NC}")
        print("=" * 60)

        # Track all checks performed
        all_checks = {
            "Claude CLI": True,
            "Git Worktree": True,
            "Permissions": True,
            "Task Copilot": True
        }

        # Mark failed checks
        for check_name, _ in self.errors:
            all_checks[check_name] = False

        # Print status for each check
        for check_name, passed in all_checks.items():
            if passed:
                # Check if there's a warning for this check
                warning = next((msg for name, msg in self.warnings if name == check_name), None)
                if warning:
                    print(f"⚠️  {Colors.YELLOW}{check_name}{Colors.NC}: {warning}")
                else:
                    # Need to show details for passing checks
                    if check_name == "Claude CLI":
                        claude_path = shutil.which('claude') or '/opt/homebrew/bin/claude'
                        print(f"✅ {Colors.GREEN}{check_name}{Colors.NC}: Found at {claude_path}")
                    elif check_name == "Git Worktree":
                        try:
                            result = subprocess.run(['git', '--version'], capture_output=True, text=True, timeout=5)
                            version = result.stdout.strip()
                            print(f"✅ {Colors.GREEN}{check_name}{Colors.NC}: Supported ({version})")
                        except:
                            print(f"✅ {Colors.GREEN}{check_name}{Colors.NC}: Supported")
                    elif check_name == "Permissions":
                        print(f"✅ {Colors.GREEN}{check_name}{Colors.NC}: Write access confirmed")
                    elif check_name == "Task Copilot":
                        print(f"✅ {Colors.GREEN}{check_name}{Colors.NC}: Configured in .mcp.json")
            else:
                # Print error details
                error_msg = next((msg for name, msg in self.errors if name == check_name), "FAILED")
                print(f"❌ {Colors.RED}{check_name}{Colors.NC}: {error_msg}")

        print()

        # Print summary
        if len(self.errors) == 0:
            if len(self.warnings) > 0:
                print(f"{Colors.YELLOW}All checks passed with {len(self.warnings)} warning(s). Orchestration should work.{Colors.NC}\n")
            else:
                print(f"{Colors.GREEN}All checks passed. Ready to orchestrate.{Colors.NC}\n")
        else:
            print(f"{Colors.RED}Pre-flight failed with {len(self.errors)} error(s). Fix issues above before running orchestration.{Colors.NC}\n")


class Orchestrator:
    def __init__(self):
        # Initialize Task Copilot client
        self.tc_client = TaskCopilotClient(WORKSPACE_ID)

        # Require active initiative
        self.initiative_id = self.tc_client.get_active_initiative_id()
        if not self.initiative_id:
            error("No active initiative found. Start an initiative with /protocol first.")
            sys.exit(1)

        # Get initiative details for display
        self.initiative_details = self.tc_client.get_initiative_details(self.initiative_id)
        if self.initiative_details:
            log(f"Initiative: {self.initiative_details.name}")
            if self.initiative_details.goal:
                log(f"Goal: {self.initiative_details.goal[:100]}")

        self.streams = self._query_streams()
        self.stream_dependencies = self._build_dependency_graph()
        self.dependency_depth = self._calculate_dependency_depth()
        self.running_processes: Dict[str, subprocess.Popen] = {}

        # Ensure directories exist
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        PID_DIR.mkdir(parents=True, exist_ok=True)

        # Clean up stale PID files from previous runs
        self._cleanup_stale_pids()

    def _query_streams(self) -> Dict[str, dict]:
        """Query streams dynamically using Task Copilot client."""
        try:
            # Filter streams by initiative
            stream_infos = self.tc_client.stream_list(initiative_id=self.initiative_id)

            if not stream_infos:
                error(f"No streams found for initiative {self.initiative_id}")
                sys.exit(1)

            streams = {}
            for stream_info in stream_infos:
                # All parallel streams use worktrees, main stream uses project root
                worktree = "." if stream_info.stream_id == "main" else f".claude/worktrees/{stream_info.stream_id}"

                streams[stream_info.stream_id] = {
                    "id": stream_info.stream_id,
                    "name": stream_info.stream_name,
                    "dependencies": stream_info.dependencies,
                    "worktree": worktree,
                }

            log(f"Found {len(streams)} streams")
            return streams

        except FileNotFoundError as e:
            error(str(e))
            sys.exit(1)
        except Exception as e:
            error(f"Failed to query streams: {e}")
            sys.exit(1)

    def _build_dependency_graph(self) -> Dict[str, Set[str]]:
        """Build stream dependency graph from task metadata.

        Returns a dict mapping stream_id -> set of stream_ids it depends on.
        """
        dependency_graph: Dict[str, Set[str]] = defaultdict(set)

        for stream_id, stream in self.streams.items():
            dependencies = stream.get("dependencies", [])

            for dep in dependencies:
                # Dependencies can be streamIds or task titles
                # If it matches a stream ID, use it directly
                if dep in self.streams:
                    dependency_graph[stream_id].add(dep)
                else:
                    # Try to extract stream ID from task title format
                    # Common formats: "Stream-A: Task", "[Stream-A] Task", etc.
                    for sid in self.streams.keys():
                        if dep.startswith(f"{sid}:") or dep.startswith(f"[{sid}]"):
                            dependency_graph[stream_id].add(sid)
                            break

        return dependency_graph

    def _calculate_dependency_depth(self) -> Dict[str, int]:
        """Calculate the dependency depth for each stream.

        Depth 0: No dependencies
        Depth 1: Depends only on depth-0 streams
        Depth N: Depends on at least one depth-(N-1) stream
        """
        depths: Dict[str, int] = {}
        remaining = set(self.streams.keys())
        current_depth = 0

        while remaining:
            # Find streams where all dependencies are satisfied
            ready = set()
            for stream_id in remaining:
                deps = self.stream_dependencies.get(stream_id, set())
                if all(dep in depths for dep in deps):
                    ready.add(stream_id)

            if not ready:
                # Circular dependency detected
                warn(f"Circular dependency detected in streams: {remaining}")
                # Assign remaining to current depth to break the cycle
                for stream_id in remaining:
                    depths[stream_id] = current_depth
                break

            # Assign depth to ready streams
            for stream_id in ready:
                deps = self.stream_dependencies.get(stream_id, set())
                if deps:
                    max_dep_depth = max(depths[dep] for dep in deps)
                    depths[stream_id] = max_dep_depth + 1
                else:
                    depths[stream_id] = 0
                remaining.remove(stream_id)

            current_depth += 1

        return depths

    def _get_stream_status(self, stream_id: str) -> Optional[dict]:
        """Get stream status using Task Copilot client."""
        try:
            # Filter by initiative
            progress = self.tc_client.stream_get(stream_id, initiative_id=self.initiative_id)
            if not progress:
                return None

            return {
                "total_tasks": progress.total_tasks,
                "completed_tasks": progress.completed_tasks,
                "in_progress_tasks": progress.in_progress_tasks,
                "is_complete": progress.is_complete
            }
        except Exception as e:
            warn(f"Failed to get status for {stream_id}: {e}")
            return None

    def _are_dependencies_complete(self, stream_id: str) -> bool:
        """Check if all dependencies for a stream are complete.

        A stream is ready when ALL streams it depends on have 100% tasks completed.
        """
        dependencies = self.stream_dependencies.get(stream_id, set())

        if not dependencies:
            # No dependencies, always ready
            return True

        # Check each dependency
        for dep_stream_id in dependencies:
            status = self._get_stream_status(dep_stream_id)
            if not status or not status["is_complete"]:
                return False

        return True

    def _get_ready_streams(self) -> List[str]:
        """Get list of streams that are ready to start (dependencies complete, not running, not complete)."""
        ready = []
        for stream_id in self.streams.keys():
            # Skip if already running
            if self._is_running(stream_id):
                continue

            # Skip if already complete
            status = self._get_stream_status(stream_id)
            if status and status["is_complete"]:
                continue

            # Check if dependencies are complete
            if self._are_dependencies_complete(stream_id):
                ready.append(stream_id)

        return ready

    def _get_blocked_streams(self) -> Dict[str, List[str]]:
        """Get streams that are blocked and what they're blocked by.

        Returns dict mapping stream_id -> list of incomplete dependency stream_ids
        """
        blocked = {}
        for stream_id in self.streams.keys():
            # Skip if already running or complete
            if self._is_running(stream_id):
                continue

            status = self._get_stream_status(stream_id)
            if status and status["is_complete"]:
                continue

            # Check dependencies
            dependencies = self.stream_dependencies.get(stream_id, set())
            incomplete_deps = []
            for dep_stream_id in dependencies:
                dep_status = self._get_stream_status(dep_stream_id)
                if not dep_status or not dep_status["is_complete"]:
                    incomplete_deps.append(dep_stream_id)

            if incomplete_deps:
                blocked[stream_id] = incomplete_deps

        return blocked

    def _get_dead_workers(self) -> List[str]:
        """Detect workers that died with incomplete tasks.

        Returns list of stream_ids where:
        - Worker was previously running (PID file exists or existed)
        - Process is now dead
        - Tasks are not complete
        - Dependencies are satisfied (was ready to run)
        """
        dead_workers = []

        for stream_id in self.streams.keys():
            # Skip if currently running
            if self._is_running(stream_id):
                continue

            # Skip if complete
            status = self._get_stream_status(stream_id)
            if status and status["is_complete"]:
                continue

            # Skip if dependencies not met (wasn't ready yet)
            if not self._are_dependencies_complete(stream_id):
                continue

            # Check if there's evidence of prior execution
            # (log file exists with content, indicating worker started)
            log_file = self._get_log_file(stream_id)
            if log_file.exists() and log_file.stat().st_size > 100:
                # Worker ran but died - has incomplete tasks
                # Check if there's at least one in_progress or we had progress
                if status and (status["completed_tasks"] > 0 or status["in_progress_tasks"] > 0):
                    dead_workers.append(stream_id)
                elif status and status["total_tasks"] > 0:
                    # Had tasks but no progress - likely died early
                    dead_workers.append(stream_id)

        return dead_workers

    def _preflight_check_agent_assignments(self) -> bool:
        """Pre-flight check for non-'me' agent assignments.

        NOTE: This check is now INFORMATIONAL only - workers route tasks to specialized agents.
        Keeping the method for backwards compatibility but it always returns True.

        Returns:
            True (always passes now that routing is enabled)
        """
        # Specialized agent routing is now enabled - no need to check/reassign
        non_me_tasks = self.tc_client.get_non_me_agent_tasks(initiative_id=self.initiative_id)

        if non_me_tasks:
            # Group by agent for informational display
            by_agent: Dict[str, int] = defaultdict(int)
            for task in non_me_tasks:
                by_agent[task['assigned_agent']] += 1

            log(f"Found {len(non_me_tasks)} task(s) assigned to specialized agents:")
            for agent, count in sorted(by_agent.items()):
                log(f"  • @agent-{agent}: {count} tasks")
            log("Workers will route these tasks to their assigned agents.")
            print()

        return True

    def _get_pid_file(self, stream_id: str) -> Path:
        return PID_DIR / f"{stream_id}.pid"

    def _get_log_file(self, stream_id: str) -> Path:
        """Get log file path using per-initiative naming."""
        return LOG_DIR / f"{stream_id}_{self.initiative_id[:8]}.log"

    def _is_running(self, stream_id: str) -> bool:
        """Check if a stream worker is currently running."""
        pid_file = self._get_pid_file(stream_id)
        if not pid_file.exists():
            return False

        try:
            pid = int(pid_file.read_text().strip())
            # Check if process exists with kill -0
            os.kill(pid, 0)
            # Double-check with ps to catch zombies (kill -0 succeeds for zombies)
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "pid="],
                capture_output=True,
                timeout=5
            )
            if result.returncode != 0:
                # Process is zombie or doesn't exist
                pid_file.unlink(missing_ok=True)
                return False
            return True
        except (ProcessLookupError, ValueError, subprocess.TimeoutExpired):
            pid_file.unlink(missing_ok=True)
            return False

    def _cleanup_stale_pids(self):
        """Clean up stale PID files from workers that exited without cleanup."""
        cleaned = 0
        for pid_file in PID_DIR.glob("*.pid"):
            stream_id = pid_file.stem
            if not self._is_running(stream_id):
                # _is_running already cleaned up the file if stale
                cleaned += 1
        if cleaned > 0:
            log(f"Cleaned up {cleaned} stale PID file(s)")

    def _merge_all_worktrees(self) -> Tuple[int, List[str]]:
        """Merge all worktree branches to main branch.

        Returns:
            Tuple of (success_count, list_of_failed_stream_ids)
        """
        worktree_base = PROJECT_ROOT / '.claude' / 'worktrees'
        success_count = 0
        failures = []

        if not worktree_base.exists():
            log("No worktrees directory found")
            return 0, []

        # Get current branch name
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=10
            )
            main_branch = result.stdout.strip() or "main"
        except Exception:
            main_branch = "main"

        for stream_id in self.streams.keys():
            worktree_path = worktree_base / stream_id
            if not worktree_path.exists():
                continue

            try:
                # Check if worktree has commits ahead of main
                result = subprocess.run(
                    ["git", "log", f"{main_branch}..HEAD", "--oneline"],
                    cwd=worktree_path,
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                if not result.stdout.strip():
                    # No new commits in worktree
                    log(f"  {stream_id}: No new commits to merge")
                    continue

                commits = result.stdout.strip().split('\n')
                log(f"  {stream_id}: {len(commits)} commit(s) to merge")

                # Get the worktree's branch name (usually same as stream_id)
                branch_result = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=worktree_path,
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                worktree_branch = branch_result.stdout.strip()

                # Merge the worktree branch into main from the main project root
                merge_result = subprocess.run(
                    ["git", "merge", worktree_branch, "--no-edit", "-m",
                     f"Merge {stream_id} into {main_branch}"],
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    text=True,
                    timeout=60
                )

                if merge_result.returncode == 0:
                    success_count += 1
                    log(f"  {stream_id}: Merged successfully")
                else:
                    # Check if it's a conflict
                    if "CONFLICT" in merge_result.stdout or "CONFLICT" in merge_result.stderr:
                        warn(f"  {stream_id}: Merge conflict - manual resolution required")
                        # Abort the merge
                        subprocess.run(["git", "merge", "--abort"], cwd=PROJECT_ROOT, capture_output=True)
                    else:
                        warn(f"  {stream_id}: Merge failed - {merge_result.stderr[:100]}")
                    failures.append(stream_id)

            except subprocess.TimeoutExpired:
                warn(f"  {stream_id}: Merge timed out")
                failures.append(stream_id)
            except Exception as e:
                warn(f"  {stream_id}: Merge error - {e}")
                failures.append(stream_id)

        return success_count, failures

    def _cleanup_worktrees(self):
        """Remove all worktrees after successful merge."""
        worktree_base = PROJECT_ROOT / '.claude' / 'worktrees'

        if not worktree_base.exists():
            return

        cleaned = 0
        for stream_id in self.streams.keys():
            worktree_path = worktree_base / stream_id
            if not worktree_path.exists():
                continue

            try:
                # Remove the git worktree properly
                result = subprocess.run(
                    ["git", "worktree", "remove", str(worktree_path), "--force"],
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode == 0:
                    cleaned += 1
                else:
                    # Fallback: just delete the directory
                    shutil.rmtree(worktree_path, ignore_errors=True)
                    cleaned += 1
            except Exception as e:
                warn(f"Failed to cleanup {stream_id} worktree: {e}")
                # Try force delete
                shutil.rmtree(worktree_path, ignore_errors=True)

        # Prune worktree metadata
        subprocess.run(["git", "worktree", "prune"], cwd=PROJECT_ROOT, capture_output=True)

        if cleaned > 0:
            log(f"Cleaned up {cleaned} worktree(s)")

        # Remove worktrees directory if empty
        if worktree_base.exists() and not any(worktree_base.iterdir()):
            worktree_base.rmdir()

    def _get_all_tasks(self) -> List[Dict]:
        """Get all tasks for the current initiative."""
        conn = self.tc_client._connect()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    t.id,
                    t.title,
                    t.status,
                    t.assigned_agent,
                    json_extract(t.metadata, '$.streamId') as stream_id,
                    json_extract(t.metadata, '$.files') as files
                FROM tasks t
                LEFT JOIN prds p ON t.prd_id = p.id
                WHERE json_extract(t.metadata, '$.streamId') IS NOT NULL
                  AND t.archived = 0
                  AND p.initiative_id = ?
                ORDER BY json_extract(t.metadata, '$.streamId'), t.created_at
            """, (self.initiative_id,))

            tasks = []
            for row in cursor.fetchall():
                task_id, title, status, agent, stream_id, files = row
                tasks.append({
                    'id': task_id,
                    'title': title,
                    'status': status,
                    'assigned_agent': agent or 'me',
                    'stream_id': stream_id,
                    'files': files
                })

            return tasks
        finally:
            conn.close()

    def _generate_routing_plan(self) -> Dict:
        """Generate routing plan for all tasks."""
        tasks = self._get_all_tasks()

        # Group by stream
        streams_tasks = defaultdict(list)
        agent_counts = defaultdict(int)

        for task in tasks:
            stream_id = task['stream_id']
            agent = task['assigned_agent']

            streams_tasks[stream_id].append(task)
            agent_counts[agent] += 1

        return {
            'streams': streams_tasks,
            'agent_counts': agent_counts,
            'total_tasks': len(tasks)
        }

    def _build_prompt(self, stream: dict) -> str:
        """Build the prompt for a Claude Code worker."""
        dependencies = self.stream_dependencies.get(stream['id'], set())
        deps_str = ", ".join(dependencies) if dependencies else "None"

        return f"""You are a worker agent in the Claude Copilot orchestration system.

## Your Assignment
- Stream: {stream['id']}
- Stream Name: {stream['name']}
- Dependencies: {deps_str}

## MANDATORY PROTOCOL - YOU MUST FOLLOW THIS EXACTLY

### Step 1: Query Your Tasks
Call `task_list` with streamId filter to get your assigned tasks:
```
task_list(metadata.streamId="{stream['id']}")
```

### Step 2: Route Each Task to Its Assigned Agent

**For EACH task in order:**

1. **Get task details:**
   ```
   task_get(id="TASK-xxx")
   ```

2. **Check the assignedAgent field:**
   - If `assignedAgent` is "me", execute the task yourself
   - If `assignedAgent` is anything else (uid, qa, sec, uxd, etc.), invoke that agent

3. **Route to specialized agent:**
   ```
   # Use Task tool to invoke the specialized agent
   Task: Execute task TASK-xxx
   Subagent: @agent-{{assignedAgent}}
   Context: [Brief task context from task.title and task.description]
   ```

4. **Wait for agent to complete:**
   - The specialized agent will call skill_evaluate() to load domain skills
   - The specialized agent will execute the task
   - The specialized agent will call task_update() when complete

5. **Move to next task:**
   - Do NOT mark tasks as complete yourself (agents do this)
   - Simply move to the next task in your stream

### Step 3: Verify Before Exiting

**Before outputting any completion summary:**
1. Call `task_list(metadata.streamId="{stream['id']}")` again
2. Check that ALL tasks have `status: "completed"`
3. If ANY task is still `pending` or `in_progress`, investigate and retry
4. Only after verification passes, output your summary

### Step 4: Output Summary
Only after ALL tasks are verified complete in Task Copilot, output:
- List of tasks routed to which agents
- Which agents completed their work
- Any commits made
- Any issues encountered

## CRITICAL RULES
- DO NOT execute tasks assigned to specialized agents yourself
- Each specialized agent loads their own domain skills via skill_evaluate()
- DO NOT claim "complete" without verifying in Task Copilot first
- Stay focused on {stream['id']} tasks only
- If an agent is blocked, check task status and coordinate

## Specialized Agent Examples

**Example 1: UI Implementation Task**
```
Task Details:
- id: TASK-123
- title: "Implement topic card component"
- assignedAgent: "uid"

Action: Invoke @agent-uid via Task tool
→ @agent-uid will call skill_evaluate() with files/context
→ @agent-uid will load design-patterns or ux-patterns skills
→ @agent-uid will implement component with accessibility
→ @agent-uid will call work_product_store(taskId, type="implementation", ...)
→ @agent-uid will call task_update(id="TASK-123", status="completed")
```

**Example 2: Testing Task**
```
Task Details:
- id: TASK-456
- title: "Add tests for evidence selector"
- assignedAgent: "qa"

Action: Invoke @agent-qa via Task tool
→ @agent-qa will call skill_evaluate() with test file context
→ @agent-qa will load pytest-patterns or jest-patterns skills
→ @agent-qa will write comprehensive tests
→ @agent-qa will call work_product_store(taskId, type="test_plan", ...)
→ @agent-qa will call task_update(id="TASK-456", status="completed")
```

**Example 3: Generic Implementation Task**
```
Task Details:
- id: TASK-789
- title: "Fix evidence migration bug"
- assignedAgent: "me"

Action: Execute yourself (you are 'me')
→ Call task_update(id="TASK-789", status="in_progress")
→ Execute the fix
→ Store work product (REQUIRED before completion)
→ Call task_update(id="TASK-789", status="completed")
```

## MANDATORY: Work Product Before Completion

**CRITICAL: You MUST store a work product before marking ANY task as completed.**

Tasks have `verificationRequired=true` which enforces:
1. Task must have `acceptanceCriteria` in metadata (set by @agent-ta)
2. Task must have proof of completion (work product OR detailed notes)

**Before calling `task_update(status="completed")`, ALWAYS call:**

```
work_product_store({{
  taskId: "TASK-xxx",
  type: "implementation",  // or "test_plan", "documentation", etc.
  title: "Brief title of what was done",
  content: "Summary of changes:\\n- File1: description\\n- File2: description\\nTest results: PASSED"
}})
```

**Work product content should include:**
- Files modified with brief descriptions
- Key changes made
- Test results or verification steps
- Any issues encountered and how they were resolved

**If you skip this step, task_update will FAIL with verification error.**

## Anti-Patterns (NEVER DO THESE)
- Executing uid/qa/sec tasks yourself instead of routing
- Outputting "All tasks complete" without verifying Task Copilot
- Skipping agent routing for specialized tasks
- Marking other agents' tasks as complete yourself
- Calling task_update(status="completed") WITHOUT first calling work_product_store()
- Providing minimal/empty work product content (must be substantive)

Begin by querying your task list with task_list.
"""

    def spawn_worker(self, stream_id: str, wait_for_deps: bool = True, skip_preflight: bool = False) -> bool:
        """Spawn a Claude Code worker for a stream.

        Args:
            stream_id: The stream to spawn
            wait_for_deps: Whether to check dependencies before spawning
            skip_preflight: Skip preflight validation (used when called from start_all which already validated)
        """
        if stream_id not in self.streams:
            error(f"Stream '{stream_id}' not found")
            return False

        # Run preflight check if not skipped
        if not skip_preflight:
            validator = PreflightValidator(PROJECT_ROOT)
            if not validator.validate_all():
                validator.print_report()
                return False
            validator.print_report()

        stream = self.streams[stream_id]

        # Check if already running
        if self._is_running(stream_id):
            warn(f"Worker {stream_id} already running")
            return True

        # Check dependencies
        if wait_for_deps and not self._are_dependencies_complete(stream_id):
            dependencies = self.stream_dependencies.get(stream_id, set())
            warn(f"Dependencies not complete for {stream_id}: {', '.join(dependencies)}")
            return False

        # Determine working directory
        if stream["worktree"] == ".":
            work_dir = PROJECT_ROOT
        else:
            work_dir = PROJECT_ROOT / stream["worktree"]

        if not work_dir.exists():
            # Create proper git worktree (not just a directory!)
            log(f"Creating git worktree for {stream_id}...")

            # Ensure branch exists (create from current HEAD if not)
            branch_result = subprocess.run(
                ["git", "branch", stream_id],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True
            )
            # Ignore error if branch already exists

            # Create the worktree linked to the branch
            worktree_result = subprocess.run(
                ["git", "worktree", "add", str(work_dir), stream_id],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True
            )

            if worktree_result.returncode != 0:
                # Check if worktree already exists but directory was deleted
                if "already checked out" in worktree_result.stderr or "already exists" in worktree_result.stderr:
                    warn(f"Worktree issue for {stream_id}: {worktree_result.stderr.strip()}")
                    warn(f"Attempting to repair by removing and recreating...")
                    subprocess.run(["git", "worktree", "remove", str(work_dir), "--force"], cwd=PROJECT_ROOT, capture_output=True)
                    subprocess.run(["git", "worktree", "prune"], cwd=PROJECT_ROOT, capture_output=True)
                    worktree_result = subprocess.run(
                        ["git", "worktree", "add", str(work_dir), stream_id],
                        cwd=PROJECT_ROOT,
                        capture_output=True,
                        text=True
                    )

                if worktree_result.returncode != 0:
                    error(f"Failed to create worktree for {stream_id}: {worktree_result.stderr}")
                    return False

            success(f"Created git worktree at {work_dir}")

            # Validate the worktree was created correctly
            validator = PreflightValidator(PROJECT_ROOT)
            if not validator.validate_worktree(work_dir, PROJECT_ROOT):
                validator.print_report()
                # Clean up the failed worktree
                log(f"Cleaning up invalid worktree at {work_dir}...")
                try:
                    shutil.rmtree(work_dir, ignore_errors=True)
                    subprocess.run(
                        ["git", "worktree", "remove", str(work_dir), "--force"],
                        cwd=PROJECT_ROOT,
                        capture_output=True
                    )
                    subprocess.run(["git", "worktree", "prune"], cwd=PROJECT_ROOT, capture_output=True)
                except Exception as cleanup_err:
                    warn(f"Cleanup warning: {cleanup_err}")

                error(f"Worktree validation failed for {stream_id}")
                error(f"Please remove the directory manually and re-run orchestrate generate")
                return False

            success(f"Worktree validated successfully")

        dependencies = self.stream_dependencies.get(stream_id, set())
        deps_str = f" (depends on: {', '.join(dependencies)})" if dependencies else " (no dependencies)"

        log(f"Spawning worker for {stream_id}")
        log(f"  Name: {stream['name']}")
        log(f"  Dependencies: {deps_str}")
        log(f"  Working dir: {work_dir}")

        prompt = self._build_prompt(stream)
        pid_file = self._get_pid_file(stream_id)
        wrapper_script = SCRIPT_DIR / "worker-wrapper.sh"

        # Spawn via wrapper script (handles PID cleanup, log archiving, per-initiative logs)
        proc = subprocess.Popen(
            [
                str(wrapper_script),
                stream_id,
                str(pid_file),
                str(LOG_DIR),  # Wrapper constructs per-initiative log filename
                str(work_dir),
                self.initiative_id,  # For per-initiative log naming
                prompt
            ],
            start_new_session=True,  # Detach from parent
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Give wrapper a moment to write PID file
        time.sleep(0.5)

        # Read actual PID from file (wrapper's PID, not subprocess PID)
        if pid_file.exists():
            actual_pid = pid_file.read_text().strip()
        else:
            actual_pid = str(proc.pid)

        self.running_processes[stream_id] = proc

        # Log file uses per-initiative naming
        log_file = LOG_DIR / f"{stream_id}_{self.initiative_id[:8]}.log"
        success(f"Worker {stream_id} started (PID: {actual_pid})")
        success(f"Logs: {log_file}")
        success(f"Logs: {log_file}")
        return True

    def start_all(self):
        """Start all streams respecting dependencies dynamically.

        This method continuously polls for ready streams and spawns workers.
        No hardcoded phases - everything is determined by dependency graph.
        """
        log(f"Starting dynamic orchestration for {PROJECT_NAME}")
        print()

        # Pre-flight validation: check environment before spawning workers
        validator = PreflightValidator(PROJECT_ROOT)
        if not validator.validate_all():
            validator.print_report()
            sys.exit(1)

        # Print report even on success to show what was validated
        validator.print_report()

        # Pre-flight check: warn about non-'me' agent assignments
        if not self._preflight_check_agent_assignments():
            sys.exit(1)

        # Display dependency structure
        self._display_dependency_structure()
        print()

        # Track which streams we've attempted to start
        attempted = set()

        # Track restart counts to prevent infinite loops
        restart_counts: Dict[str, int] = defaultdict(int)
        MAX_RESTARTS = 2

        # Main execution loop
        while True:
            # Find streams that are ready to start
            ready_streams = self._get_ready_streams()

            # Filter out streams we've already attempted
            new_ready = [s for s in ready_streams if s not in attempted]

            if new_ready:
                log(f"Found {len(new_ready)} ready streams: {', '.join(new_ready)}")
                for stream_id in new_ready:
                    self.spawn_worker(stream_id, wait_for_deps=False, skip_preflight=True)
                    attempted.add(stream_id)
                    print()

            # Check for dead workers that need restarting
            dead_workers = self._get_dead_workers()
            for stream_id in dead_workers:
                if restart_counts[stream_id] < MAX_RESTARTS:
                    restart_counts[stream_id] += 1
                    warn(f"Worker {stream_id} died with incomplete tasks - restarting (attempt {restart_counts[stream_id]}/{MAX_RESTARTS})")
                    self.spawn_worker(stream_id, wait_for_deps=False, skip_preflight=True)
                    print()
                else:
                    error(f"Worker {stream_id} failed {MAX_RESTARTS} times - marking as stuck")

            # Check if all streams are complete
            all_complete = True
            for stream_id in self.streams.keys():
                status = self._get_stream_status(stream_id)
                if not status or not status["is_complete"]:
                    all_complete = False
                    break

            if all_complete:
                success("All streams complete!")
                print()

                # CRITICAL: Merge all worktree branches to main BEFORE archiving
                log("Merging worktree branches to main...")
                merge_success, merge_failures = self._merge_all_worktrees()
                if merge_success:
                    success(f"Merged {merge_success} stream(s) to main")
                if merge_failures:
                    warn(f"Failed to merge {len(merge_failures)} stream(s): {', '.join(merge_failures)}")
                print()

                # Archive streams for this initiative
                log(f"Archiving streams for initiative {self.initiative_id}")
                archived_count = self.tc_client.archive_initiative_streams(self.initiative_id)
                success(f"Archived {archived_count} tasks")

                # Clean up worktrees after successful merge
                log("Cleaning up worktrees...")
                self._cleanup_worktrees()

                # Mark initiative as complete
                log("Marking initiative as complete")
                if self.tc_client.complete_initiative(self.initiative_id):
                    success("Initiative marked as COMPLETE")
                else:
                    warn("Failed to mark initiative as complete (Memory Copilot database may not be accessible)")

                print()
                success("Initiative complete - all streams merged and archived")
                break

            # Check if we're stuck (nothing ready, nothing running, not all complete)
            running_count = sum(1 for s in self.streams.keys() if self._is_running(s))
            if not new_ready and running_count == 0 and not all_complete:
                error("Orchestration stuck - no streams ready and none running")
                blocked = self._get_blocked_streams()
                if blocked:
                    error("Blocked streams:")
                    for stream_id, deps in blocked.items():
                        error(f"  {stream_id} waiting for: {', '.join(deps)}")
                break

            # Wait before next poll
            if not all_complete:
                time.sleep(POLL_INTERVAL)

        print()
        log("Orchestration complete")
        log("Use 'python orchestrate.py status' to check final status")

    def _display_dependency_structure(self):
        """Display stream dependency structure grouped by depth."""
        print(f"{Colors.BOLD}Stream Dependency Structure:{Colors.NC}")
        print()

        # Group by depth
        depths = defaultdict(list)
        for stream_id, depth in self.dependency_depth.items():
            depths[depth].append(stream_id)

        # Display each depth level
        for depth in sorted(depths.keys()):
            stream_ids = sorted(depths[depth])

            if depth == 0:
                print(f"  {Colors.GREEN}Depth {depth} (Independent):{Colors.NC}")
            else:
                print(f"  {Colors.CYAN}Depth {depth}:{Colors.NC}")

            for stream_id in stream_ids:
                stream = self.streams[stream_id]
                deps = self.stream_dependencies.get(stream_id, set())

                if deps:
                    deps_str = f" → depends on: {', '.join(sorted(deps))}"
                else:
                    deps_str = ""

                print(f"    • {Colors.BOLD}{stream_id}{Colors.NC} ({stream['name']}){deps_str}")

            print()

    def check_status(self):
        """Display status of all workers grouped by dependency depth."""
        print(f"\n{Colors.BOLD}{'='*75}{Colors.NC}")
        print(f"{Colors.BOLD}              {PROJECT_NAME.upper()} - WORKER STATUS{Colors.NC}")
        print(f"{Colors.BOLD}{'='*75}{Colors.NC}\n")

        # Group streams by dependency depth
        depths = defaultdict(list)
        for stream_id, depth in self.dependency_depth.items():
            depths[depth].append(stream_id)

        # Display overall progress
        total_streams = len(self.streams)
        completed_streams = 0
        running_streams = 0

        for stream_id in self.streams.keys():
            status = self._get_stream_status(stream_id)
            if status and status["is_complete"]:
                completed_streams += 1
            if self._is_running(stream_id):
                running_streams += 1

        print(f"  {Colors.BOLD}Overall:{Colors.NC} {completed_streams}/{total_streams} complete, {running_streams} running")
        print()

        # Display each depth level
        for depth in sorted(depths.keys()):
            stream_ids = sorted(depths[depth])

            if depth == 0:
                depth_label = f"Depth {depth} (Independent)"
            else:
                depth_label = f"Depth {depth}"

            print(f"  {Colors.MAGENTA}{depth_label}{Colors.NC}")

            for stream_id in stream_ids:
                stream = self.streams[stream_id]
                running = self._is_running(stream_id)
                status = self._get_stream_status(stream_id)

                # Determine status icon
                if status and status["is_complete"]:
                    icon = f"{Colors.GREEN}[DONE]{Colors.NC}"
                    status_text = "Complete"
                elif running:
                    icon = f"{Colors.YELLOW}[RUN]{Colors.NC}"
                    status_text = "Running"
                else:
                    # Check if blocked by dependencies
                    if not self._are_dependencies_complete(stream_id):
                        icon = f"{Colors.CYAN}[WAIT]{Colors.NC}"
                        deps = self.stream_dependencies.get(stream_id, set())
                        status_text = f"Waiting for: {', '.join(sorted(deps))}"
                    else:
                        pid_file = self._get_pid_file(stream_id)
                        if pid_file.exists():
                            icon = f"{Colors.RED}[STOP]{Colors.NC}"
                            status_text = "Stopped"
                        else:
                            icon = f"{Colors.DIM}[---]{Colors.NC}"
                            status_text = "Not started"

                # Progress bar
                if status and status["total_tasks"] > 0:
                    pct = int(status["completed_tasks"] / status["total_tasks"] * 100)
                    bar_filled = pct // 7
                    bar = "=" * bar_filled + "-" * (15 - bar_filled)
                    progress = f"[{bar}] {status['completed_tasks']}/{status['total_tasks']}"
                else:
                    progress = "[---------------] ?/?"

                # Get PID if running
                pid_str = ""
                if running:
                    pid_file = self._get_pid_file(stream_id)
                    if pid_file.exists():
                        pid_str = f" (PID: {pid_file.read_text().strip()})"

                print(f"    {icon} {Colors.BOLD}{stream_id}{Colors.NC} | {stream['name']}")
                print(f"      {progress} | {status_text}{pid_str}")
            print()

        # Show blocked streams summary
        blocked = self._get_blocked_streams()
        if blocked:
            print(f"  {Colors.YELLOW}Blocked Streams:{Colors.NC}")
            for stream_id, deps in blocked.items():
                print(f"    • {stream_id} waiting for: {', '.join(sorted(deps))}")
            print()

    def stop_all(self):
        """Stop all running workers."""
        log("Stopping all workers...")

        for pid_file in PID_DIR.glob("*.pid"):
            stream_id = pid_file.stem
            try:
                pid = int(pid_file.read_text().strip())
                os.kill(pid, signal.SIGTERM)
                log(f"Stopped {stream_id} (PID: {pid})")
            except (ProcessLookupError, ValueError):
                pass
            pid_file.unlink(missing_ok=True)

        success("All workers stopped")

    def stop_one(self, stream_id: str):
        """Stop a specific worker."""
        pid_file = self._get_pid_file(stream_id)
        if not pid_file.exists():
            warn(f"No PID file for {stream_id}")
            return

        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            log(f"Stopped {stream_id} (PID: {pid})")
        except (ProcessLookupError, ValueError):
            warn(f"Process not found for {stream_id}")

        pid_file.unlink(missing_ok=True)

    def tail_logs(self, stream_id: str):
        """Tail logs for a stream."""
        log_file = self._get_log_file(stream_id)
        if not log_file.exists():
            error(f"No logs found for {stream_id}")
            return

        subprocess.run(["tail", "-f", str(log_file)])

    def test_routing(self):
        """Display routing plan without executing tasks."""
        print(f"\n{Colors.BOLD}{'='*75}{Colors.NC}")
        print(f"{Colors.BOLD}           ROUTING PLAN - TEST MODE (DRY RUN){Colors.NC}")
        print(f"{Colors.BOLD}{'='*75}{Colors.NC}\n")

        log(f"Initiative: {self.initiative_details.name if self.initiative_details else self.initiative_id}")
        print()

        # Generate routing plan
        plan = self._generate_routing_plan()

        # Display tasks grouped by stream
        print(f"{Colors.BOLD}Task Routing by Stream:{Colors.NC}\n")

        # Sort streams by dependency depth
        depths = defaultdict(list)
        for stream_id, depth in self.dependency_depth.items():
            depths[depth].append(stream_id)

        for depth in sorted(depths.keys()):
            stream_ids = sorted(depths[depth])

            for stream_id in stream_ids:
                if stream_id not in plan['streams']:
                    continue

                stream = self.streams[stream_id]
                tasks = plan['streams'][stream_id]

                # Display stream header
                deps = self.stream_dependencies.get(stream_id, set())
                deps_str = f" (depends on: {', '.join(sorted(deps))})" if deps else ""

                print(f"  {Colors.MAGENTA}{stream_id}{Colors.NC}: {stream['name']}{deps_str}")

                # Display tasks with agent assignments
                agent_colors = {
                    'me': Colors.GREEN,
                    'uid': Colors.CYAN,
                    'uxd': Colors.CYAN,
                    'qa': Colors.YELLOW,
                    'sec': Colors.RED,
                    'ta': Colors.BLUE,
                    'sd': Colors.BLUE,
                    'doc': Colors.DIM,
                }

                for task in tasks:
                    agent = task['assigned_agent']
                    color = agent_colors.get(agent, Colors.NC)
                    status_icon = {
                        'completed': f"{Colors.GREEN}✓{Colors.NC}",
                        'in_progress': f"{Colors.YELLOW}◐{Colors.NC}",
                        'pending': f"{Colors.DIM}○{Colors.NC}",
                        'blocked': f"{Colors.RED}✗{Colors.NC}",
                    }.get(task['status'], "?")

                    # Truncate title if too long
                    title = task['title']
                    if len(title) > 60:
                        title = title[:57] + "..."

                    print(f"    {status_icon} {task['id']} → {color}@agent-{agent}{Colors.NC}")
                    print(f"      {Colors.DIM}{title}{Colors.NC}")

                print()

        # Display routing summary
        print(f"{Colors.BOLD}Routing Summary:{Colors.NC}\n")

        # Sort agents by count
        sorted_agents = sorted(plan['agent_counts'].items(), key=lambda x: x[1], reverse=True)

        total_tasks = plan['total_tasks']
        for agent, count in sorted_agents:
            color = agent_colors.get(agent, Colors.NC)
            pct = int(count / total_tasks * 100) if total_tasks > 0 else 0
            bar_filled = pct // 5
            bar = "█" * bar_filled + "░" * (20 - bar_filled)
            print(f"  {color}@agent-{agent:6}{Colors.NC} {bar} {count:3} tasks ({pct:3}%)")

        print()
        print(f"  {Colors.BOLD}Total:{Colors.NC} {total_tasks} tasks across {len(plan['streams'])} streams")
        print()

        # Display execution order
        print(f"{Colors.BOLD}Execution Order (by dependency depth):{Colors.NC}\n")

        for depth in sorted(depths.keys()):
            stream_ids = sorted(depths[depth])
            stream_ids_with_tasks = [s for s in stream_ids if s in plan['streams']]

            if not stream_ids_with_tasks:
                continue

            if depth == 0:
                print(f"  {Colors.GREEN}Depth {depth} (Independent - can run in parallel):{Colors.NC}")
            else:
                print(f"  {Colors.CYAN}Depth {depth} (will start after depth {depth-1} completes):{Colors.NC}")

            for stream_id in stream_ids_with_tasks:
                task_count = len(plan['streams'][stream_id])
                print(f"    • {stream_id} ({task_count} tasks)")

            print()

        print(f"{Colors.YELLOW}[DRY RUN] No workers will be spawned. Use 'orchestrate.py start' to execute.{Colors.NC}\n")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Claude Copilot Orchestrator")
    parser.add_argument("command", choices=["start", "status", "stop", "logs", "test-routing", "preflight"],
                       help="Command to run")
    parser.add_argument("stream_id", nargs="?", help="Stream ID (for start/stop/logs)")

    args = parser.parse_args()

    # Handle preflight command separately (doesn't need Orchestrator initialization)
    if args.command == "preflight":
        validator = PreflightValidator(PROJECT_ROOT)
        validator.validate_all()
        validator.print_report()
        sys.exit(0 if len(validator.errors) == 0 else 1)

    orchestrator = Orchestrator()

    if args.command == "start":
        if args.stream_id:
            orchestrator.spawn_worker(args.stream_id)
        else:
            orchestrator.start_all()
    elif args.command == "status":
        orchestrator.check_status()
    elif args.command == "stop":
        if args.stream_id:
            orchestrator.stop_one(args.stream_id)
        else:
            orchestrator.stop_all()
    elif args.command == "logs":
        if not args.stream_id:
            error("Usage: orchestrate.py logs <stream-id>")
            sys.exit(1)
        orchestrator.tail_logs(args.stream_id)
    elif args.command == "test-routing":
        orchestrator.test_routing()


if __name__ == "__main__":
    main()
