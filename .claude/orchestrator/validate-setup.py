#!/usr/bin/env python3
"""
Orchestration Setup Validator

Run this script to verify your environment is ready for orchestration.

Usage:
    python validate-setup.py [--verbose] [--fix]

Options:
    --verbose   Show detailed check information
    --fix       Attempt to fix issues automatically (where possible)

Exit Codes:
    0 - All checks passed, ready for orchestration
    1 - One or more checks failed
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple, Optional


class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    NC = '\033[0m'  # No Color


class SetupValidator:
    """Validates environment setup for orchestration."""

    def __init__(self, project_root: Path, verbose: bool = False, fix: bool = False):
        self.project_root = project_root
        self.verbose = verbose
        self.fix = fix
        self.checks_passed = 0
        self.checks_failed = 0
        self.failures: List[Tuple[str, str]] = []  # (check_name, error_message)
        self.fixes_attempted = 0
        self.fixes_succeeded = 0

    def print_header(self):
        """Print validation header."""
        print(f"\n{Colors.BOLD}🔧 Orchestration Setup Validation{Colors.NC}")
        print("=" * 60)
        print()

    def print_summary(self):
        """Print validation summary."""
        print()
        print("=" * 60)

        if self.checks_failed == 0:
            print(f"{Colors.GREEN}{Colors.BOLD}✓ All {self.checks_passed} checks passed. Ready for orchestration!{Colors.NC}")
            print()
            print("Next steps:")
            print("  1. Run: /orchestrate generate")
            print("  2. Review generated streams")
            print("  3. Run: /orchestrate start")
        else:
            print(f"{Colors.RED}{Colors.BOLD}✗ {self.checks_failed} check(s) failed{Colors.NC}")
            print()
            print("Failed checks:")
            for name, error in self.failures:
                print(f"  • {name}: {error}")

            if self.fix and self.fixes_attempted > 0:
                print()
                print(f"Fix attempts: {self.fixes_succeeded}/{self.fixes_attempted} succeeded")

            if not self.fix:
                print()
                print(f"Try running with --fix to attempt automatic repairs:")
                print(f"  python {Path(__file__).name} --fix")

        print()

    def check(self, name: str, passed: bool, error_msg: str = "") -> bool:
        """Record check result."""
        if passed:
            self.checks_passed += 1
            print(f"{Colors.GREEN}✓{Colors.NC} {name}")
        else:
            self.checks_failed += 1
            self.failures.append((name, error_msg))
            print(f"{Colors.RED}✗{Colors.NC} {name}")
            if error_msg:
                print(f"  {Colors.DIM}{error_msg}{Colors.NC}")

        return passed

    def attempt_fix(self, description: str, fix_func) -> bool:
        """Attempt to fix an issue."""
        if not self.fix:
            return False

        self.fixes_attempted += 1
        print(f"  {Colors.YELLOW}→ Attempting fix: {description}{Colors.NC}")

        try:
            success = fix_func()
            if success:
                self.fixes_succeeded += 1
                print(f"  {Colors.GREEN}✓ Fixed: {description}{Colors.NC}")
                return True
            else:
                print(f"  {Colors.RED}✗ Fix failed: {description}{Colors.NC}")
                return False
        except Exception as e:
            print(f"  {Colors.RED}✗ Fix failed: {str(e)}{Colors.NC}")
            return False

    def check_python_version(self) -> bool:
        """Check Python version >= 3.8."""
        version = sys.version_info
        version_str = f"{version.major}.{version.minor}.{version.micro}"

        if self.verbose:
            print(f"  Python version: {version_str}")

        passed = version.major >= 3 and version.minor >= 8

        if passed:
            return self.check("Python version", True, f"Version {version_str}")
        else:
            return self.check(
                "Python version",
                False,
                f"Version {version_str} found, need >= 3.8"
            )

    def check_claude_cli(self) -> bool:
        """Check if Claude CLI is installed and accessible."""
        claude_path = shutil.which("claude")

        if self.verbose and claude_path:
            print(f"  Claude CLI path: {claude_path}")

        if claude_path:
            return self.check("Claude CLI", True, f"Found at {claude_path}")
        else:
            return self.check(
                "Claude CLI",
                False,
                "Not found in PATH. Install from https://docs.anthropic.com/en/docs/claude-code"
            )

    def check_git_version(self) -> bool:
        """Check Git version >= 2.5 (worktree support)."""
        try:
            result = subprocess.run(
                ["git", "--version"],
                capture_output=True,
                text=True,
                check=True
            )

            # Parse version from "git version 2.43.0"
            version_str = result.stdout.strip().split()[-1]
            major, minor = map(int, version_str.split('.')[:2])

            if self.verbose:
                print(f"  Git version: {version_str}")

            # Check for worktree command support
            has_worktree = subprocess.run(
                ["git", "worktree", "--help"],
                capture_output=True,
                check=False
            ).returncode == 0

            if major >= 2 and minor >= 5 and has_worktree:
                return self.check(
                    "Git version",
                    True,
                    f"Version {version_str} with worktree support"
                )
            else:
                return self.check(
                    "Git version",
                    False,
                    f"Version {version_str} found, need >= 2.5 with worktree support"
                )

        except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
            return self.check(
                "Git version",
                False,
                "Git not found or unable to determine version"
            )

    def check_git_repository(self) -> bool:
        """Check if current directory is a git repository."""
        git_dir = self.project_root / ".git"

        if self.verbose:
            print(f"  Checking: {git_dir}")

        # Check if .git exists (regular repo or worktree file)
        if git_dir.exists():
            return self.check("Git repository", True)
        else:
            # Try git rev-parse as fallback
            try:
                subprocess.run(
                    ["git", "rev-parse", "--git-dir"],
                    cwd=self.project_root,
                    capture_output=True,
                    check=True
                )
                return self.check("Git repository", True)
            except subprocess.CalledProcessError:
                def init_repo():
                    subprocess.run(
                        ["git", "init"],
                        cwd=self.project_root,
                        capture_output=True,
                        check=True
                    )
                    return True

                passed = self.check(
                    "Git repository",
                    False,
                    "Not a git repository"
                )

                if not passed:
                    self.attempt_fix("Initialize git repository", init_repo)

                return passed

    def check_directory_permissions(self) -> bool:
        """Check write permissions in project root."""
        test_file = self.project_root / ".orchestrator_write_test"

        try:
            test_file.touch()
            test_file.unlink()
            return self.check("Directory permissions", True, "Write access OK")
        except (OSError, PermissionError) as e:
            return self.check(
                "Directory permissions",
                False,
                f"Cannot write to project root: {str(e)}"
            )

    def check_mcp_config(self) -> bool:
        """Check if .mcp.json exists."""
        mcp_config = self.project_root / ".mcp.json"

        if self.verbose:
            print(f"  Checking: {mcp_config}")

        if mcp_config.exists():
            # Verify it's valid JSON
            try:
                with open(mcp_config) as f:
                    config = json.load(f)

                # Check for task-copilot server
                servers = config.get("mcpServers", {})
                has_task_copilot = "task-copilot" in servers

                if has_task_copilot:
                    return self.check("MCP configuration", True, "task-copilot configured")
                else:
                    return self.check(
                        "MCP configuration",
                        False,
                        "task-copilot server not found in .mcp.json"
                    )

            except json.JSONDecodeError:
                return self.check(
                    "MCP configuration",
                    False,
                    ".mcp.json is not valid JSON"
                )
        else:
            return self.check(
                "MCP configuration",
                False,
                ".mcp.json not found. Run /setup-project first"
            )

    def check_mcp_servers_built(self) -> bool:
        """Check if MCP servers are built (node_modules exist)."""
        # Check task-copilot
        task_copilot_dir = self.project_root / "mcp-servers" / "task-copilot"
        task_copilot_modules = task_copilot_dir / "node_modules"

        # Check memory copilot
        memory_copilot_dir = self.project_root / "mcp-servers" / "copilot-memory"
        memory_copilot_modules = memory_copilot_dir / "node_modules"

        if self.verbose:
            print(f"  Task Copilot: {task_copilot_dir}")
            print(f"  Memory Copilot: {memory_copilot_dir}")

        task_built = task_copilot_modules.exists()
        memory_built = memory_copilot_modules.exists()

        if task_built and memory_built:
            return self.check("MCP servers built", True, "Both servers ready")
        else:
            missing = []
            if not task_built:
                missing.append("task-copilot")
            if not memory_built:
                missing.append("copilot-memory")

            def rebuild_servers():
                for server in missing:
                    server_dir = self.project_root / "mcp-servers" / server
                    if not server_dir.exists():
                        return False

                    # Run npm install
                    subprocess.run(
                        ["npm", "install"],
                        cwd=server_dir,
                        capture_output=True,
                        check=True
                    )

                    # Run npm run build
                    subprocess.run(
                        ["npm", "run", "build"],
                        cwd=server_dir,
                        capture_output=True,
                        check=True
                    )

                return True

            passed = self.check(
                "MCP servers built",
                False,
                f"Missing node_modules: {', '.join(missing)}"
            )

            if not passed:
                self.attempt_fix(f"Build {', '.join(missing)}", rebuild_servers)

            return passed

    def check_orchestrator_templates(self) -> bool:
        """Check if orchestration templates exist in Claude Copilot framework."""
        # Look for templates in ~/.claude/copilot/templates/orchestration
        home = Path.home()
        template_dir = home / ".claude" / "copilot" / "templates" / "orchestration"

        if self.verbose:
            print(f"  Template directory: {template_dir}")

        if not template_dir.exists():
            return self.check(
                "Orchestration templates",
                False,
                f"Template directory not found: {template_dir}"
            )

        required_files = [
            "orchestrate.py",
            "task_copilot_client.py",
            "check_streams_data.py",
            "check-streams",
            "watch-status"
        ]

        missing = [f for f in required_files if not (template_dir / f).exists()]

        if missing:
            return self.check(
                "Orchestration templates",
                False,
                f"Missing templates: {', '.join(missing)}"
            )
        else:
            return self.check("Orchestration templates", True, "All templates present")

    def run_all_checks(self) -> bool:
        """Run all validation checks."""
        print("Checking environment...")
        print()

        # Run checks in order
        self.check_python_version()
        self.check_claude_cli()
        self.check_git_version()
        self.check_git_repository()
        self.check_directory_permissions()
        self.check_mcp_config()
        self.check_mcp_servers_built()
        self.check_orchestrator_templates()

        return self.checks_failed == 0


def main():
    parser = argparse.ArgumentParser(
        description='Validate orchestration setup',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python validate-setup.py              # Run all checks
  python validate-setup.py --verbose    # Show detailed information
  python validate-setup.py --fix        # Attempt automatic fixes
        """
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed check information'
    )
    parser.add_argument(
        '--fix',
        action='store_true',
        help='Attempt to fix issues automatically (where possible)'
    )

    args = parser.parse_args()

    # Determine project root
    project_root = Path.cwd()

    # Create validator
    validator = SetupValidator(project_root, verbose=args.verbose, fix=args.fix)

    # Print header
    validator.print_header()

    # Run checks
    success = validator.run_all_checks()

    # Print summary
    validator.print_summary()

    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
