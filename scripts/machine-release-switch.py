#!/usr/bin/env python3
"""Switch one machine to a central-resolution release, with a one-command rollback.

  machine-release-switch.py switch --pins PINS.json [--layers FILE] [--home DIR] [--codex-home DIR]
  <backup dir>/rollback.py [--force]        (written by `switch`; no dependency on the release)

`switch` backs up every machine file it may touch, then: cc release publish (build, flip, links,
Codex marketplace, doctor), cc/tc/tc-limits shims, the user-level Claude hook shim (+ skill-listing
budget), the `copilot` launcher; and finally `cc doctor --release`. Nothing outside the backup
manifest is edited. Rollback restores the backed-up files (refusing any edited since the switch,
unless --force), removes the links the receipt owns, the launcher and the pointer, and keeps
~/.copilot/releases for inspection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "tools" / "cc" / "src"

ROLLBACK = r'''#!/usr/bin/env python3
"""One-command machine rollback for the central-resolution switch (stdlib only)."""
import hashlib, json, os, shutil, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
M = json.loads((HERE / "manifest.json").read_text())
force = "--force" in sys.argv
home = Path(M["home"]); chome = home / ".copilot"
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() and not p.is_symlink() else ("link:" + os.readlink(p) if p.is_symlink() else None)

def own_links():
    try: receipt = json.loads((chome / "links-receipt.json").read_text())
    except (OSError, ValueError): return []
    return [home / row["path"] for row in receipt.get("links", [])]

problems = []
for row in M["files"]:
    path = Path(row["path"])
    if sha(path) != row["after"] and not force and row["after"] != row["before"]:
        problems.append(f"{path} changed since the switch (use --force to overwrite)")
if problems:
    print("\n".join(problems), file=sys.stderr); sys.exit(1)

def adopted_rows():
    try: return json.loads((chome / "links-receipt.json").read_text()).get("adopted", [])
    except (OSError, ValueError): return []

adopted = adopted_rows()
for link in own_links():
    if link.is_symlink():
        target = os.readlink(link)
        if target.startswith(str(chome / "current")) or target.startswith(str(chome / "generated")):
            link.unlink()
shutil.rmtree(chome / "generated" / "command-skills", ignore_errors=True)
restored = 0
for row in adopted:  # framework-owned copies the switch backed up and replaced with links
    target, saved = home / row["path"], Path(row["backup"])
    if not (saved.exists() or saved.is_symlink()): continue
    if target.is_symlink(): target.unlink()
    if target.exists(): continue
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(saved), str(target)); restored += 1
for row in M["files"]:
    path = Path(row["path"]); backup = row["backup"]
    if path.is_symlink() or path.exists(): path.unlink()
    if backup is None: continue
    src = HERE / backup
    path.parent.mkdir(parents=True, exist_ok=True)
    if row["kind"] == "symlink": os.symlink(Path(row["target"]), path)
    else: shutil.copy2(src, path)
for name in M["remove"]:
    p = Path(name)
    if p.is_symlink() or p.is_file(): p.unlink()
    elif p.is_dir(): shutil.rmtree(p, ignore_errors=True)
print(f"rolled back: {len(M['files'])} files restored, links removed, {restored} adopted copies restored; releases kept in {chome / 'releases'}")
'''


def sha(path: Path) -> str | None:
    if path.is_symlink():
        return "link:" + os.readlink(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def run(argv, env=None, check=True):
    result = subprocess.run(argv, env=env, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise SystemExit(f"FAILED: {' '.join(map(str, argv))}\n{result.stdout}\n{result.stderr}")
    return result


def switch(args) -> int:
    home = Path(args.home).resolve() if args.home else Path.home()
    codex_home = Path(args.codex_home) if args.codex_home else home / ".codex"
    chome = home / ".copilot"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = chome / "rollback" / f"central-resolution-{stamp}"
    backup.mkdir(parents=True)
    tracked = [home / ".claude" / "settings.json", home / ".claude" / "CLAUDE.md",
               codex_home / "config.toml", codex_home / "AGENTS.md",
               home / ".local" / "bin" / "cc", home / ".local" / "bin" / "tc",
               home / ".local" / "bin" / "tc-limits"]
    rows = []
    for index, path in enumerate(tracked):
        row = {"path": str(path), "backup": None, "kind": "absent", "before": sha(path)}
        if path.is_symlink():
            row.update(kind="symlink", target=os.readlink(path), backup=f"f{index}.link")
            (backup / row["backup"]).write_text(os.readlink(path))
        elif path.is_file():
            row.update(kind="file", backup=f"f{index}")
            shutil.copy2(path, backup / row["backup"])
        rows.append(row)
    listing = []
    for directory in (home / ".claude" / "agents", home / ".claude" / "skills", home / ".claude" / "commands",
                      codex_home / "skills"):
        names = sorted(p.name for p in directory.iterdir()) if directory.is_dir() else []
        listing.append(f"{directory}: {len(names)} entries\n" + "\n".join(f"  {n}" for n in names))
    (backup / "existing-listing.txt").write_text("\n\n".join(listing) + "\n")

    cache_existed = (codex_home / "plugins" / "cache" / "enac-materialized").exists()
    env = {**os.environ, "HOME": str(home), "CODEX_HOME": str(codex_home), "PYTHONPATH": str(SRC)}
    cc = [args.python, "-m", "cc.main"]
    layers = args.layers or str(home / ".config" / "copilot" / "copilot.layers.yml")
    published = run(cc + ["release", "publish", "--pins", args.pins, "--layers", layers,
                          "--home", str(home), "--codex-home", str(codex_home)], env)
    report = json.loads(published.stdout[published.stdout.index('{'):])
    run(cc + ["release", "shims", "--home", str(home)], env)
    hook = run(cc + ["settings-hook", "user-add", "--home", str(home), "--json"], env)
    launcher = chome / "current" / "cli-copilot" / "scripts" / "install-cli.py"
    bin_dir = home / ".local" / "bin"
    launcher_result = run([sys.executable, str(launcher), "install", "--bin-dir", str(bin_dir),
                           "--home", str(home), "--python", args.launcher_python or args.python], env)
    remove = [str(chome / "current"), str(chome / "links-receipt.json"), str(chome / "codex-config-receipt.json"),
              str(chome / "cli-install.json"), str(chome / "cli-dev.json"), str(bin_dir / "copilot"),
              str(chome / "user-settings-receipt.json")]
    if not cache_existed:
        remove.append(str(codex_home / "plugins" / "cache" / "enac-materialized"))
    manifest = {"home": str(home), "release": report["release"], "remove": remove, "files": []}
    for row in rows:
        row["after"] = sha(Path(row["path"]))
        manifest["files"].append(row)
    (backup / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (backup / "rollback.py").write_text(ROLLBACK)
    os.chmod(backup / "rollback.py", 0o755)

    shim_env = {**env}
    shim_env.pop("PYTHONPATH")
    doctor = run([str(bin_dir / "cc"), "doctor", "--release"], shim_env, check=False)
    print(json.dumps({"release": report["release"], "backup": str(backup),
                      "rollback": f"python3 {backup / 'rollback.py'}",
                      "doctor_exit": doctor.returncode, "doctor": doctor.stdout.strip()[-1500:],
                      "links": report["links"], "launcher": launcher_result.stdout.strip()[-400:]}, indent=2))
    return doctor.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("switch")
    s.add_argument("--pins", required=True)
    s.add_argument("--layers")
    s.add_argument("--home")
    s.add_argument("--codex-home")
    s.add_argument("--python", default=sys.executable)
    s.add_argument("--launcher-python", help="Interpreter with the CLI dependencies, written into the copilot launcher (default: --python).")
    args = parser.parse_args()
    return switch(args)


if __name__ == "__main__":
    sys.exit(main())
