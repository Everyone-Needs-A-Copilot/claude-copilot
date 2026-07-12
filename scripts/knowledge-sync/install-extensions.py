#!/usr/bin/env python3
"""install-extensions.py — Install knowledge-repository agent extensions into
a consuming project's .claude/agents/*.md files.

Claude Code only ever loads .claude/agents/*.md automatically — there is no
other guaranteed injection point. This script makes "extensions load
automatically" true by writing extension content directly into the matching
agent file at knowledge-sync time, inside a clearly-fenced, idempotent
marker block:

    <!-- kc-extension:begin name=<agent> source=<repo-relative-path> hash=<sha256-12> -->
    ...extension content...
    <!-- kc-extension:end -->

Behavior by manifest "type":
  - extension: the fenced block is appended below the agent's existing body.
  - override:  the fenced block REPLACES the agent's entire body below its
               YAML frontmatter (the frontmatter itself is always preserved).

Idempotence:
  - Re-running with unchanged extension content is a no-op (hash matches).
  - Re-running after an extension file changed replaces the block in place
    (never duplicates).
  - An agent whose manifest entry was removed (or whose extension file is
    gone) has its block cleanly deleted on the next run.
  - `--remove` strips every kc-extension block from every agent file in the
    project, regardless of the current manifest (uninstall).

Safety:
  - Only text inside `<!-- kc-extension:begin ... -->` / `:end -->` markers
    (or, for `override` entries, the body below frontmatter) is ever
    written. Nothing else in the agent file is touched.
  - No backups are written; git is the backup.
  - Only the single project passed via --project-root is touched.

Usage:
    install-extensions.py --knowledge-repo PATH [--project-root PATH] [--dry-run] [--remove]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

MARKER_BEGIN = "<!-- kc-extension:begin name={name} source={source} hash={hash} -->"
MARKER_END = "<!-- kc-extension:end -->"

FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)


def sha12(text: str) -> str:
    """First 12 hex chars of the sha256 of text — matches the hash= marker field."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def strip_frontmatter(text: str) -> tuple[str, str]:
    """Split a markdown file into (frontmatter incl. trailing '---\\n', body)."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return "", text
    return m.group(0), text[m.end():]


def block_pattern(name: str) -> re.Pattern:
    return re.compile(
        r"<!-- kc-extension:begin name=" + re.escape(name) +
        r" source=\S+ hash=[0-9a-f]{12} -->\n"
        r".*?"
        r"<!-- kc-extension:end -->\n?",
        re.DOTALL,
    )


def build_block(name: str, source: str, content: str) -> str:
    content = content.strip("\n")
    h = sha12(content)
    header = MARKER_BEGIN.format(name=name, source=source, hash=h)
    return f"{header}\n{content}\n{MARKER_END}\n"


def find_block(body: str, name: str) -> re.Match | None:
    return block_pattern(name).search(body)


def remove_block(body: str, name: str) -> tuple[str, bool]:
    m = find_block(body, name)
    if not m:
        return body, False
    return body[: m.start()] + body[m.end():], True


def install_extension_block(body: str, name: str, block: str) -> tuple[str, bool]:
    """extension type: append/replace the named block, preserving the rest of body."""
    m = find_block(body, name)
    if m:
        if body[m.start(): m.end()] == block:
            return body, False
        return body[: m.start()] + block + body[m.end():], True
    stripped = body.rstrip("\n")
    new_body = (stripped + "\n\n" + block) if stripped else block
    if not new_body.endswith("\n"):
        new_body += "\n"
    return new_body, True


def install_override_block(body: str, block: str) -> tuple[str, bool]:
    """override type: the fenced block IS the entire body below frontmatter."""
    desired = "\n" + block
    if body == desired:
        return body, False
    return desired, True


def load_manifest(knowledge_repo: Path) -> dict:
    with open(knowledge_repo / "knowledge-manifest.json", "r", encoding="utf-8") as f:
        return json.load(f)


def load_extension_content(knowledge_repo: Path, rel_path: str) -> str | None:
    """Read an extension .md file and return its body (frontmatter stripped).

    Returns None if the resolved path escapes the knowledge repo (defense in
    depth against a malformed/malicious manifest "file" field) or the file
    is missing.
    """
    ext_path = (knowledge_repo / rel_path).resolve()
    repo_root = knowledge_repo.resolve()
    if repo_root not in ext_path.parents and ext_path != repo_root:
        return None
    if not ext_path.is_file():
        return None
    text = ext_path.read_text(encoding="utf-8")
    _, body = strip_frontmatter(text)
    return body


def process(project_root: Path, knowledge_repo: Path, manifest: dict, dry_run: bool, remove_all: bool) -> dict:
    agents_dir = project_root / ".claude" / "agents"
    results = {
        "installed": [], "updated": [], "unchanged": [], "removed": [],
        "skipped_no_base_agent": [], "skipped_no_extension_file": [],
    }

    if not agents_dir.is_dir():
        print(f"No .claude/agents directory in {project_root}; nothing to install.")
        return results

    extensions = [] if remove_all else manifest.get("extensions", [])
    by_agent = {e["agent"]: e for e in extensions}
    agent_files = sorted(agents_dir.glob("*.md"))
    present_agents = {f.stem for f in agent_files}

    for agent_file in agent_files:
        agent_name = agent_file.stem
        text = agent_file.read_text(encoding="utf-8")
        frontmatter, body = strip_frontmatter(text)
        entry = by_agent.get(agent_name)

        if entry is None:
            new_body, changed = remove_block(body, agent_name)
            if changed:
                _apply(agent_file, frontmatter, new_body, "remove", dry_run)
                results["removed"].append(agent_name)
            continue

        rel_path = entry["file"]
        content = load_extension_content(knowledge_repo, rel_path)
        if content is None:
            print(f"WARNING: extension file missing/invalid for agent '{agent_name}': {rel_path}", file=sys.stderr)
            results["skipped_no_extension_file"].append(agent_name)
            continue

        block = build_block(agent_name, rel_path, content)
        ext_type = entry.get("type", "extension")
        was_present = find_block(body, agent_name) is not None

        if ext_type == "override":
            new_body, changed = install_override_block(body, block)
        else:
            new_body, changed = install_extension_block(body, agent_name, block)

        if changed:
            action = "update" if was_present else "install"
            _apply(agent_file, frontmatter, new_body, action, dry_run)
            results["updated" if was_present else "installed"].append(agent_name)
        else:
            results["unchanged"].append(agent_name)

    for entry in extensions:
        if entry["agent"] not in present_agents:
            results["skipped_no_base_agent"].append(entry["agent"])

    return results


def _apply(agent_file: Path, frontmatter: str, new_body: str, action: str, dry_run: bool) -> None:
    label = "[dry-run] " if dry_run else ""
    print(f"{label}{action}: {agent_file}")
    if not dry_run:
        agent_file.write_text(frontmatter + new_body, encoding="utf-8")


def print_summary(results: dict, dry_run: bool) -> None:
    prefix = "[dry-run] " if dry_run else ""
    print()
    print(f"{prefix}Extension install summary:")
    print(f"  installed: {len(results['installed'])} {results['installed']}")
    print(f"  updated:   {len(results['updated'])} {results['updated']}")
    print(f"  unchanged: {len(results['unchanged'])} {results['unchanged']}")
    print(f"  removed:   {len(results['removed'])} {results['removed']}")
    if results["skipped_no_base_agent"]:
        print(f"  skipped (no base agent in project): {results['skipped_no_base_agent']}")
    if results["skipped_no_extension_file"]:
        print(f"  skipped (extension file missing): {results['skipped_no_extension_file']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--project-root", default=".",
        help="Consuming project root containing .claude/agents/ (default: current directory)",
    )
    parser.add_argument(
        "--knowledge-repo", required=True,
        help="Path to the knowledge repository (must contain knowledge-manifest.json)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would change without writing any files",
    )
    parser.add_argument(
        "--remove", action="store_true",
        help="Strip all kc-extension blocks from the project's agent files (uninstall)",
    )
    args = parser.parse_args(argv)

    project_root = Path(args.project_root).resolve()
    knowledge_repo = Path(args.knowledge_repo).expanduser().resolve()

    manifest_path = knowledge_repo / "knowledge-manifest.json"
    if not manifest_path.is_file():
        print(f"No knowledge-manifest.json at {manifest_path}; skipping extension install.")
        return 0

    try:
        manifest = load_manifest(knowledge_repo)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"WARNING: could not read knowledge manifest ({exc}); skipping extension install.", file=sys.stderr)
        return 0

    if not args.remove and not manifest.get("extensions"):
        print("Knowledge manifest has no 'extensions' entries; nothing to install.")
        return 0

    results = process(project_root, knowledge_repo, manifest, args.dry_run, args.remove)
    print_summary(results, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
