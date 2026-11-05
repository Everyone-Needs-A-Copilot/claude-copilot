#!/usr/bin/env python3
"""Install a private local feature snapshot, preserving executables for rollback.

Run with an existing owner-enabled ~/.config/copilot/docker-resources.json policy.
Does not edit release-pinned repositories, install dependencies, or publish code.
"""

import argparse
import datetime
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli-source", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    home = Path.home()
    policy = json.loads((home / ".config/copilot/docker-resources.json").read_text())
    if policy.get("automatic_synthetic_cleanup") is not True or not policy.get(
        "approval"
    ):
        parser.error("Owner-enabled synthetic cleanup policy is required.")
    framework_source = Path(__file__).resolve().parents[1] / "src"
    cli_source = args.cli_source.resolve() / "copilot_cli"
    docker_executable = shutil.which("docker")
    if not docker_executable:
        parser.error("Docker CLI is required before installing the scheduled check.")
    docker_bin = str(Path(docker_executable).parent)
    cc_executable = Path(shutil.which("cc") or "")
    cli_executable = Path(shutil.which("copilot") or "")
    agent = home / "Library/LaunchAgents/com.copilot.docker-resources.plist"
    if agent.exists():
        parser.error(
            "Scheduled job already exists; inspect it instead of replacing it."
        )
    interpreters = {}
    for executable in (cc_executable, cli_executable):
        line = executable.read_text().splitlines()[0]
        if not line.startswith("#!/") or not Path(line[2:]).is_file():
            parser.error(f"Expected a Python console script at {executable}")
        interpreters[executable] = line[2:]
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot = home / ".local/share/copilot/docker-resources" / stamp
    snapshot.mkdir(parents=True, mode=0o700, exist_ok=False)
    shutil.copytree(
        framework_source / "cc",
        snapshot / "framework/cc",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copytree(
        cli_source,
        snapshot / "cli/copilot_cli",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    for executable in (cc_executable, cli_executable):
        shutil.copy2(executable, snapshot / (executable.name + ".original"))
    files = {
        str(p.relative_to(snapshot)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in snapshot.rglob("*")
        if p.is_file()
    }
    receipt = {
        "snapshot": str(snapshot),
        "framework_source": str(framework_source),
        "cli_source": str(cli_source),
        "files": files,
        "executables": {str(p): interpreters[p] for p in interpreters},
        "launch_agent": str(agent),
        "evidence": str(args.evidence.resolve()),
    }
    for executable, relative, module in (
        (cc_executable, "framework", "cc.main"),
        (cli_executable, "cli", "copilot_cli.main"),
    ):
        executable.write_text(
            f"#!{interpreters[executable]}\n"
            "import sys\n"
            f"sys.path.insert(0, {str(snapshot / relative)!r})\n"
            f"from {module} import app\n"
            "app()\n"
        )
    job = {
        "Label": "com.copilot.docker-resources",
        "ProgramArguments": [str(cc_executable), "resources", "maintain"],
        "EnvironmentVariables": {
            "PATH": f"{docker_bin}:/opt/homebrew/bin:{home}/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        },
        "RunAtLoad": True,
        "StartInterval": 3600,
        "ProcessType": "Background",
    }
    agent.parent.mkdir(parents=True, exist_ok=True)
    agent.write_bytes(plistlib.dumps(job))
    receipt_path = snapshot / "install.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    args.evidence.mkdir(parents=True, exist_ok=True)
    shutil.copy2(receipt_path, args.evidence / "install.json")
    subprocess.run(
        ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(agent)], check=True
    )
    print(receipt_path)


if __name__ == "__main__":
    main()
