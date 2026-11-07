#!/usr/bin/env python3
"""Release gate: the bundled Codex plugin is exactly the codex-copilot release it pins.

WHY THIS EXISTS. The framework installer (scripts/install-framework-snapshot.py
via scripts/codex_plugin_snapshot.py) makes `plugins/codex-copilot` from THIS
repository the only Codex plugin a machine runs. Through 5.34.8 every release
still bundled codex-copilot 0.16.0 while codex-copilot itself had reached
0.16.8, so Codex sessions never received the 0.16.1+ coordinator guard. No check
compared the two: codex-copilot's parity check hashes only this repository's
`.claude/` agents, commands and skills (the Claude-to-Codex direction), and cc's
lock and status code resolves a Claude snapshot to the pinned codex-copilot
checkout, so it reported the pinned version, not the bytes Codex actually loads.

THE PIN. VERSION.json `components.codexPlugin` records the paired release:
`version`, `sourceRepo`, `sourceTag`, `sourceCommit` and `pluginTree` (the git
tree id of `plugins/codex-copilot` at that tag; a git tree id covers every
path, byte and file mode, so equal ids mean a byte-for-byte copy).

CHECKS (all must hold):
  1. The pin is complete and `sourceTag` is `v<version>`.
  2. The bundled `.codex-plugin/plugin.json` names `version`.
  3. The bundled tree hashes to `pluginTree` (working tree, or `--at <commit>`).
  4. With `--upstream PATH` or `--fetch-upstream`: `sourceTag` in codex-copilot
     resolves to `sourceCommit` and its `plugins/codex-copilot` tree is
     `pluginTree`.
  5. With `--layers-manifest PATH` (when the file exists): the manifest's
     codex foundation layer pins `sourceTag`, so a machine never runs a Codex
     foundation that differs from the plugin this release delivers.

Usage:
  scripts/check-codex-plugin-pin.py [--repo-root DIR] [--at COMMIT]
      [--upstream PATH | --fetch-upstream] [--layers-manifest PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

PLUGIN_PATH = "plugins/codex-copilot"
MANIFEST_PATH = f"{PLUGIN_PATH}/.codex-plugin/plugin.json"
PIN_FIELDS = ("version", "sourceRepo", "sourceTag", "sourceCommit", "pluginTree")


class PinError(Exception):
    """The bundled plugin and its pin disagree."""


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ("git", *args), cwd=cwd, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise PinError(
            f"git {' '.join(args)} failed in {cwd}: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout


def _is_git_worktree(root: Path) -> bool:
    return (
        subprocess.run(
            ("git", "rev-parse", "--show-toplevel"),
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        ).returncode
        == 0
    )


# --- git tree id of a working directory -------------------------------------


def _object_id(kind: bytes, payload: bytes) -> bytes:
    return hashlib.sha1(kind + b" %d\0" % len(payload) + payload).digest()


def _tree_id(root: Path, relative_files: list[str]) -> str:
    """Compute the git tree id git would record for these files under root."""
    tree: dict = {}
    for relative in relative_files:
        node = tree
        parts = relative.split("/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = root / relative

    def build(node: dict) -> bytes:
        entries = []
        for name, value in node.items():
            if isinstance(value, dict):
                entries.append((name + "/", b"40000", name, build(value)))
                continue
            metadata = value.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                mode, payload = b"120000", os.readlink(value).encode()
            elif stat.S_ISREG(metadata.st_mode):
                mode = b"100755" if metadata.st_mode & 0o100 else b"100644"
                payload = value.read_bytes()
            else:
                raise PinError(f"unsupported entry in bundled plugin: {value}")
            entries.append((name, mode, name, _object_id(b"blob", payload)))
        body = b"".join(
            mode + b" " + name.encode() + b"\0" + digest
            for _key, mode, name, digest in sorted(entries, key=lambda e: e[0])
        )
        return _object_id(b"tree", body)

    return build(tree).hex()


def _bundled_files(repo_root: Path) -> list[str]:
    plugin = repo_root / PLUGIN_PATH
    if not plugin.is_dir():
        raise PinError(f"bundled plugin is missing: {plugin}")
    if _is_git_worktree(repo_root):
        # Exactly what a commit of this tree would contain: tracked files that
        # still exist plus untracked files git would not ignore.
        listed = _git(
            repo_root,
            "ls-files", "-z", "--cached", "--others", "--exclude-standard",
            "--", PLUGIN_PATH,
        ).split("\0")
        files = sorted(
            {p for p in listed if p and os.path.lexists(repo_root / p)}
        )
    else:
        files = sorted(
            p.relative_to(repo_root).as_posix()
            for p in plugin.rglob("*")
            if p.is_symlink() or p.is_file()
        )
    return [p[len(PLUGIN_PATH) + 1 :] for p in files]


# --- inputs -----------------------------------------------------------------


def _read_text(repo_root: Path, relative: str, at: str | None) -> str:
    if at:
        return _git(repo_root, "show", f"{at}:{relative}")
    return (repo_root / relative).read_text(encoding="utf-8")


def load_pin(repo_root: Path, at: str | None = None) -> dict:
    try:
        version = json.loads(_read_text(repo_root, "VERSION.json", at))
    except (OSError, json.JSONDecodeError) as exc:
        raise PinError(f"VERSION.json is unreadable: {exc}") from exc
    pin = version.get("components", {}).get("codexPlugin")
    if not isinstance(pin, dict):
        raise PinError("VERSION.json has no components.codexPlugin pin")
    missing = [f for f in PIN_FIELDS if not isinstance(pin.get(f), str) or not pin[f]]
    if missing:
        raise PinError(f"components.codexPlugin is missing: {', '.join(missing)}")
    if pin["sourceTag"] != f"v{pin['version']}":
        raise PinError(
            f"components.codexPlugin sourceTag {pin['sourceTag']} is not v{pin['version']}"
        )
    for field, length in (("sourceCommit", 40), ("pluginTree", 40)):
        if not re.fullmatch(r"[0-9a-f]{%d}" % length, pin[field]):
            raise PinError(f"components.codexPlugin {field} is not a full git object id")
    return pin


def layers_codex_foundation_ref(manifest: Path) -> str | None:
    """Return the codex foundation layer's ref from a copilot.layers.yml."""
    text = manifest.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        layers = (yaml.safe_load(text) or {}).get("layers") or []
        for layer in layers:
            if layer.get("product") == "codex" and layer.get("role") == "foundation":
                return str((layer.get("source") or {}).get("ref"))
        return None
    except ImportError:
        pass
    # Minimal fallback: split on list items and read product/role/ref.
    for block in re.split(r"\n- ", "\n" + text):
        product = re.search(r"^\s*product:\s*(\S+)", block, re.M)
        role = re.search(r"^\s*role:\s*(\S+)", block, re.M)
        ref = re.search(r"^\s*ref:\s*(\S+)", block, re.M)
        if product and role and ref and (product[1], role[1]) == ("codex", "foundation"):
            return ref[1]
    return None


# --- checks -----------------------------------------------------------------


def check_bundle(repo_root: Path, pin: dict, at: str | None = None) -> list[str]:
    problems: list[str] = []
    try:
        manifest = json.loads(_read_text(repo_root, MANIFEST_PATH, at))
        bundled_version = manifest.get("version")
    except (OSError, json.JSONDecodeError, PinError) as exc:
        return [f"bundled plugin manifest is unreadable: {exc}"]
    if bundled_version != pin["version"]:
        problems.append(
            f"bundled codex-copilot is {bundled_version} but the release pins "
            f"{pin['version']} ({pin['sourceTag']})"
        )
    if at:
        actual = _git(repo_root, "rev-parse", f"{at}:{PLUGIN_PATH}").strip()
    else:
        actual = _tree_id(repo_root / PLUGIN_PATH, _bundled_files(repo_root))
    if actual != pin["pluginTree"]:
        problems.append(
            f"bundled {PLUGIN_PATH} tree is {actual} but {pin['sourceTag']} is "
            f"{pin['pluginTree']}: the content is not a byte-for-byte copy. Re-sync with: "
            f"git -C <codex-copilot> archive {pin['sourceTag']} {PLUGIN_PATH} | tar -x"
        )
    return problems


def check_upstream(upstream: Path, pin: dict) -> list[str]:
    tag = pin["sourceTag"]
    problems: list[str] = []
    commit = _git(upstream, "rev-parse", f"refs/tags/{tag}^{{commit}}").strip()
    if commit != pin["sourceCommit"]:
        problems.append(
            f"codex-copilot {tag} resolves to {commit}, but the pin records {pin['sourceCommit']}"
        )
    tree = _git(upstream, "rev-parse", f"refs/tags/{tag}:{PLUGIN_PATH}").strip()
    if tree != pin["pluginTree"]:
        problems.append(
            f"codex-copilot {tag} {PLUGIN_PATH} tree is {tree}, but the pin records {pin['pluginTree']}"
        )
    return problems


def check_fetched_upstream(pin: dict) -> list[str]:
    tag = pin["sourceTag"]
    with tempfile.TemporaryDirectory(prefix="codex-plugin-pin-") as tmp:
        bare = Path(tmp)
        _git(bare, "init", "-q", "--bare")
        _git(
            bare, "fetch", "-q", "--depth", "1", "--no-tags",
            pin["sourceRepo"], f"+refs/tags/{tag}:refs/tags/{tag}",
        )
        return check_upstream(bare, pin)


def check_layers(manifest: Path, pin: dict) -> list[str]:
    ref = layers_codex_foundation_ref(manifest)
    if ref is None:
        return []
    if ref != pin["sourceTag"]:
        return [
            f"{manifest} pins the codex foundation at {ref}, but this release bundles "
            f"{pin['sourceTag']}: re-sync {PLUGIN_PATH} and the pin, or fix the layer pin"
        ]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--at", help="check the bundle and pin as committed at this commit")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--upstream", type=Path, help="a codex-copilot git repository")
    source.add_argument(
        "--fetch-upstream", action="store_true",
        help="fetch the pinned tag from the pin's sourceRepo and verify it",
    )
    parser.add_argument(
        "--layers-manifest", type=Path,
        help="a copilot.layers.yml whose codex foundation ref must equal the pin (skipped when absent)",
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    try:
        pin = load_pin(repo_root, args.at)
        problems = check_bundle(repo_root, pin, args.at)
        if args.upstream:
            problems += check_upstream(args.upstream.resolve(), pin)
        elif args.fetch_upstream:
            problems += check_fetched_upstream(pin)
        if args.layers_manifest and args.layers_manifest.is_file():
            problems += check_layers(args.layers_manifest, pin)
    except PinError as exc:
        problems = [str(exc)]
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1
    print(
        f"bundled codex-copilot {pin['version']} matches {pin['sourceTag']} "
        f"({pin['sourceCommit'][:12]}, tree {pin['pluginTree'][:12]})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
