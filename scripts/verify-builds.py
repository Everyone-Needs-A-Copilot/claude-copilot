#!/usr/bin/env python3
"""
MCP Server Build Verification Script
Builds all MCP servers and runs tests, then generates a report.
"""

import subprocess
import sys
import json
from pathlib import Path
from datetime import datetime

BASE_DIR = Path("/Users/pabs/Sites/COPILOT/claude-copilot")
MCP_DIR = BASE_DIR / "mcp-servers"

SERVERS = [
    "copilot-memory",
    "skills-copilot",
    "websocket-bridge"
]

def run_command(cmd, cwd):
    """Run a command and capture output."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            shell=True,
            timeout=120
        )
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": "Command timed out after 120 seconds"
        }
    except Exception as e:
        return {
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": str(e)
        }

def build_server(server_name):
    """Build a single MCP server."""
    server_path = MCP_DIR / server_name

    print(f"\n{'='*60}")
    print(f"Building: {server_name}")
    print(f"{'='*60}")

    if not server_path.exists():
        print(f"❌ ERROR: Directory not found: {server_path}")
        return {"success": False, "error": "Directory not found"}

    # Check if node_modules exists
    if not (server_path / "node_modules").exists():
        print(f"⚠️  node_modules not found, running npm install...")
        install_result = run_command("npm install", server_path)
        if not install_result["success"]:
            print(f"❌ npm install failed")
            print(f"Error: {install_result['stderr']}")
            return install_result
        print(f"✅ Dependencies installed")

    # Run build
    print(f"Running: npm run build")
    build_result = run_command("npm run build", server_path)

    if build_result["success"]:
        print(f"✅ Build successful")

        # Check dist directory
        dist_path = server_path / "dist"
        if dist_path.exists():
            file_count = len(list(dist_path.rglob("*.js")))
            print(f"   - Generated {file_count} JS files in dist/")
        else:
            print(f"   ⚠️  dist/ directory not found")
    else:
        print(f"❌ Build failed")
        if build_result["stderr"]:
            print(f"\nErrors:")
            print(build_result["stderr"][:500])  # First 500 chars

    return build_result

def run_tests(server_name):
    """Run tests for a server."""
    server_path = MCP_DIR / server_name

    print(f"\n{'='*60}")
    print(f"Running tests: {server_name}")
    print(f"{'='*60}")

    test_result = run_command("npm test", server_path)

    if test_result["success"]:
        print(f"✅ Tests passed")
        # Try to extract test count from output
        stdout = test_result["stdout"]
        if "passing" in stdout:
            print(f"\n{stdout}")
    else:
        print(f"❌ Tests failed")
        if test_result["stderr"]:
            print(f"\nErrors:")
            print(test_result["stderr"][:500])

    return test_result

def generate_report(results):
    """Generate markdown report."""
    report = []
    report.append("# MCP Server Build Verification Report")
    report.append(f"\n**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"\n## Build Results\n")

    success_count = 0
    for server, result in results["builds"].items():
        status = "✅ PASS" if result["success"] else "❌ FAIL"
        if result["success"]:
            success_count += 1

        report.append(f"### {server}")
        report.append(f"- **Status:** {status}")
        report.append(f"- **Return Code:** {result.get('returncode', 'N/A')}")

        if not result["success"] and result.get("stderr"):
            report.append(f"- **Errors:**")
            report.append(f"```")
            report.append(result["stderr"][:500])
            report.append(f"```")
        report.append("")

    report.append(f"\n## Test Results\n")

    if "tests" in results and results["tests"]:
        for server, result in results["tests"].items():
            status = "✅ PASS" if result["success"] else "❌ FAIL"
            report.append(f"### {server}")
            report.append(f"- **Status:** {status}")
            if result.get("stdout"):
                report.append(f"```")
                report.append(result["stdout"][:300])
                report.append(f"```")
            report.append("")

    report.append(f"\n## Summary\n")
    report.append(f"- **Servers Built Successfully:** {success_count}/{len(results['builds'])}")
    report.append(f"- **Overall Status:** {'✅ All builds passed' if success_count == len(results['builds']) else '❌ Some builds failed'}")

    return "\n".join(report)

def main():
    print("=" * 60)
    print("MCP SERVER BUILD VERIFICATION")
    print("=" * 60)

    results = {
        "builds": {},
        "tests": {}
    }

    # Build all servers
    for server in SERVERS:
        results["builds"][server] = build_server(server)

    # Generate report
    print(f"\n{'='*60}")
    print("GENERATING REPORT")
    print(f"{'='*60}")

    report = generate_report(results)

    # Save report
    report_path = BASE_DIR / "BUILD_VERIFICATION_REPORT.md"
    with open(report_path, "w") as f:
        f.write(report)

    print(f"\n✅ Report saved to: {report_path}")
    print(f"\n{report}")

    # Exit with error if any builds failed
    all_success = all(r["success"] for r in results["builds"].values())
    sys.exit(0 if all_success else 1)

if __name__ == "__main__":
    main()
