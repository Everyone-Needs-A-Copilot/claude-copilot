#!/usr/bin/env python3
"""
check-manifest.py — Fitness check for .claude-plugin/ manifests.

Validates:
1. plugin.json and marketplace.json are valid JSON.
2. Every agent/command referenced in plugin.json exists on disk.
3. Hook scripts referenced in plugin.json exist on disk.
4. Skill categories referenced in plugin.json exist on disk.
5. marketplace.json references a valid manifest path.
6. plugin.json version matches VERSION.json framework version.

Run from repo root:
    python3 .claude-plugin/check-manifest.py

Exit 0 = all checks pass.
Exit 1 = one or more checks failed (details printed to stderr).
"""

import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_DIR = os.path.join(REPO_ROOT, ".claude-plugin")
CLAUDE_DIR = os.path.join(REPO_ROOT, ".claude")

errors = []
warnings = []


def fail(msg: str) -> None:
    errors.append(msg)
    print(f"  FAIL  {msg}", file=sys.stderr)


def warn(msg: str) -> None:
    warnings.append(msg)
    print(f"  WARN  {msg}", file=sys.stderr)


def ok(msg: str) -> None:
    print(f"  OK    {msg}")


def load_json(path: str, label: str):
    try:
        with open(path) as f:
            data = json.load(f)
        ok(f"{label} is valid JSON")
        return data
    except FileNotFoundError:
        fail(f"{label} not found at {path}")
        return None
    except json.JSONDecodeError as e:
        fail(f"{label} is not valid JSON: {e}")
        return None


def check_path_exists(base: str, rel: str, label: str) -> bool:
    """Resolve rel relative to base, check existence."""
    # Strip ${CLAUDE_PLUGIN_ROOT}/ prefix for manifest hook paths — resolve
    # relative to PLUGIN_DIR instead.
    if rel.startswith("${CLAUDE_PLUGIN_ROOT}"):
        rel_stripped = rel.replace("${CLAUDE_PLUGIN_ROOT}/", "")
        full = os.path.normpath(os.path.join(PLUGIN_DIR, rel_stripped))
    else:
        full = os.path.normpath(os.path.join(base, rel))
    if os.path.exists(full):
        ok(f"{label} exists → {os.path.relpath(full, REPO_ROOT)}")
        return True
    else:
        fail(f"{label} NOT FOUND → {os.path.relpath(full, REPO_ROOT)}")
        return False


print("\n=== Claude Copilot Manifest Fitness Check ===\n")

# ── 1. Load files ─────────────────────────────────────────────────────────────
plugin_path = os.path.join(PLUGIN_DIR, "plugin.json")
market_path = os.path.join(PLUGIN_DIR, "marketplace.json")
version_path = os.path.join(REPO_ROOT, "VERSION.json")

plugin = load_json(plugin_path, "plugin.json")
market = load_json(market_path, "marketplace.json")
version_data = load_json(version_path, "VERSION.json")

print()

# ── 2. Version sync ───────────────────────────────────────────────────────────
if plugin and version_data:
    fw_version = version_data.get("framework")
    plugin_version = plugin.get("version")
    if fw_version and plugin_version:
        if fw_version == plugin_version:
            ok(
                f"Version in sync: plugin.json={plugin_version} == VERSION.json.framework={fw_version}"
            )
        else:
            fail(
                f"Version drift: plugin.json={plugin_version} != VERSION.json.framework={fw_version}"
                " — update plugin.json version field"
            )
    else:
        warn("Could not read version from plugin.json or VERSION.json for comparison")
print()

# ── 3. Agents directory ───────────────────────────────────────────────────────
if plugin:
    agents_rel = plugin.get("agents", "")
    agents_base = PLUGIN_DIR
    agents_full = os.path.normpath(os.path.join(agents_base, agents_rel))
    if os.path.isdir(agents_full):
        ok(f"agents dir exists → {os.path.relpath(agents_full, REPO_ROOT)}")
        # Verify each base agent
        expected_agents = [
            "design.md",
            "do.md",
            "doc.md",
            "kc.md",
            "me.md",
            "qa.md",
            "sd.md",
            "ta.md",
        ]
        for agent_file in expected_agents:
            agent_path = os.path.join(agents_full, agent_file)
            if os.path.exists(agent_path):
                ok(f"  agent {agent_file} exists")
            else:
                fail(
                    f"  agent {agent_file} MISSING in {os.path.relpath(agents_full, REPO_ROOT)}"
                )
    else:
        fail(f"agents dir NOT FOUND → {os.path.relpath(agents_full, REPO_ROOT)}")
    print()

# ── 4. Skills directory ───────────────────────────────────────────────────────
if plugin:
    skills_rel = plugin.get("skills", "")
    skills_full = os.path.normpath(os.path.join(PLUGIN_DIR, skills_rel))
    if os.path.isdir(skills_full):
        ok(f"skills dir exists → {os.path.relpath(skills_full, REPO_ROOT)}")
        # Verify categories match VERSION.json
        if version_data:
            expected_cats = (
                version_data.get("components", {})
                .get("skills", {})
                .get("categories", [])
            )
            for cat in expected_cats:
                cat_path = os.path.join(skills_full, cat)
                if os.path.isdir(cat_path):
                    ok(f"  skill category '{cat}' exists")
                else:
                    fail(f"  skill category '{cat}' MISSING")
    else:
        fail(f"skills dir NOT FOUND → {os.path.relpath(skills_full, REPO_ROOT)}")
    print()

# ── 5. Commands directory ─────────────────────────────────────────────────────
if plugin:
    commands_rel = plugin.get("commands", "")
    commands_full = os.path.normpath(os.path.join(PLUGIN_DIR, commands_rel))
    if os.path.isdir(commands_full):
        ok(f"commands dir exists → {os.path.relpath(commands_full, REPO_ROOT)}")
        # Verify key commands
        if version_data:
            all_commands = version_data.get("components", {}).get("commands", {}).get(
                "projectCommands", []
            ) + version_data.get("components", {}).get("commands", {}).get(
                "machineCommands", []
            )
            for cmd in all_commands:
                cmd_path = os.path.join(commands_full, cmd)
                if os.path.exists(cmd_path):
                    ok(f"  command {cmd} exists")
                else:
                    fail(f"  command {cmd} MISSING")
    else:
        fail(f"commands dir NOT FOUND → {os.path.relpath(commands_full, REPO_ROOT)}")
    print()

# ── 6. Hooks ──────────────────────────────────────────────────────────────────
if plugin:
    hooks_block = plugin.get("hooks", {})
    hook_scripts = set()
    for event, entries in hooks_block.items():
        for entry in entries:
            for hook in entry.get("hooks", []):
                cmd = hook.get("command", "")
                if cmd:
                    hook_scripts.add(cmd)

    for script_ref in sorted(hook_scripts):
        check_path_exists(
            PLUGIN_DIR, script_ref, f"hook script ({script_ref.split('/')[-1]})"
        )
    print()

# ── 7. Marketplace references plugin manifest ─────────────────────────────────
if market and plugin:
    plugins_list = market.get("plugins", [])
    for entry in plugins_list:
        manifest_rel = entry.get("manifest", "")
        if manifest_rel:
            manifest_full = os.path.normpath(os.path.join(REPO_ROOT, manifest_rel))
            if os.path.exists(manifest_full):
                ok(f"marketplace plugin manifest reference exists → {manifest_rel}")
            else:
                fail(f"marketplace plugin manifest NOT FOUND → {manifest_rel}")
        # Version in marketplace matches plugin.json
        mkt_ver = entry.get("version")
        plugin_ver = plugin.get("version") if plugin else None
        if mkt_ver and plugin_ver:
            if mkt_ver == plugin_ver:
                ok(f"marketplace version matches plugin.json: {mkt_ver}")
            else:
                fail(
                    f"marketplace version {mkt_ver} != plugin.json version {plugin_ver}"
                )
    print()

# ── 8. clone-user files untouched guard ──────────────────────────────────────
# .claude/settings.json must still exist (clone wiring is intact)
settings_path = os.path.join(CLAUDE_DIR, "settings.json")
if os.path.exists(settings_path):
    ok(".claude/settings.json exists (clone-user hook wiring intact)")
    # Verify it still uses absolute paths (not ${CLAUDE_PLUGIN_ROOT})
    try:
        with open(settings_path) as f:
            settings_text = f.read()
        if "${CLAUDE_PLUGIN_ROOT}" in settings_text:
            fail(
                ".claude/settings.json contains ${CLAUDE_PLUGIN_ROOT} — this would break clone users"
            )
        else:
            ok(
                ".claude/settings.json does not reference ${CLAUDE_PLUGIN_ROOT} (correct for clone users)"
            )
    except Exception as e:
        warn(f"Could not read .claude/settings.json: {e}")
else:
    fail(".claude/settings.json MISSING — clone-user hook wiring is broken")
print()

# ── Summary ───────────────────────────────────────────────────────────────────
print("=== Summary ===")
print(f"  Errors:   {len(errors)}")
print(f"  Warnings: {len(warnings)}")
print()

if errors:
    print("RESULT: FAILED — fix the above errors before merging.", file=sys.stderr)
    sys.exit(1)
else:
    print("RESULT: PASSED — manifest is consistent with the .claude/ asset tree.")
    sys.exit(0)
