"""Fixtures: fake signed components with Codex plugins, fake codex CLI, temp HOME/CODEX_HOME."""

from __future__ import annotations

import json
import os
import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cc.core.release.codex import marketplace
from cc.core.release.engine import build, layout, pointer

FAKE_CODEX = '''#!{python}
import os, shutil, sys, tempfile, tomllib
from pathlib import Path
home = Path(os.environ["CODEX_HOME"])
args = sys.argv[1:]
cfg = tomllib.loads((home / "config.toml").read_text())
def source(mp): return Path(cfg["marketplaces"][mp]["source"])
def install(mp, name):
    src = source(mp) / "plugins" / name
    version = __import__("json").loads((src / ".codex-plugin/plugin.json").read_text())["version"]
    dest = home / "plugins/cache" / mp / name / version
    if dest.exists():
        if os.environ.get("COPILOT_TEST_RETAIN_SCRATCH") == "1":
            preserved = Path(tempfile.mkdtemp(prefix="codex-cache-retained-", dir=home.parent))
            original_mode = dest.stat().st_mode & 0o7777
            moved = False
            os.chmod(dest, original_mode | 0o200)
            try:
                # macOS requires a writable directory for rename. Never fall
                # back to copy/delete, and restore the exact archived mode.
                os.rename(dest, preserved / "cache")
                moved = True
            finally:
                os.chmod(preserved / "cache" if moved else dest, original_mode)
            (preserved / "origin.txt").write_text(str(dest))
        else:
            for d, _, _f in os.walk(dest):
                os.chmod(d, 0o700)
            shutil.rmtree(dest, onexc=lambda f, p, e: (os.chmod(p, 0o600), f(p)))
    shutil.copytree(src.resolve(), dest, symlinks=False)
with open(home / "calls.log", "a") as log:
    log.write(" ".join(args) + "\\n")
if args[:3] == ["plugin", "marketplace", "upgrade"]:
    if os.environ.get("FAKE_UPGRADE") != "ok":
        print("marketplace is not a Git source", file=sys.stderr); sys.exit(1)
    mp = args[3]
    for p in (source(mp) / "plugins").iterdir():
        install(mp, p.name)
elif args[:2] == ["plugin", "add"]:
    if os.environ.get("FAKE_ADD") == "fail":
        print("boom", file=sys.stderr); sys.exit(2)
    name, mp = args[2].split("@")
    install(mp, name)
else:
    sys.exit(64)
'''


@pytest.fixture
def home(tmp_path):
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.fixture
def codex_home(tmp_path):
    path = tmp_path / "codex"
    path.mkdir()
    return path


@pytest.fixture
def fake_codex(tmp_path):
    path = tmp_path / "bin" / "codex"
    path.parent.mkdir()
    path.write_text(FAKE_CODEX.format(python=sys.executable))
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def write_plugin(root: Path, name: str, version: str, hooks: str = "H1", extra: str = "") -> None:
    plugin = root / "plugins" / name
    (plugin / ".codex-plugin").mkdir(parents=True, exist_ok=True)
    (plugin / ".codex-plugin" / "plugin.json").write_text(json.dumps({"name": name, "version": version}))
    (plugin / "hooks").mkdir(exist_ok=True)
    (plugin / "hooks" / "hooks.json").write_text(hooks)
    (plugin / "README.md").write_text(extra or name)


def default_layout(version="1.0.0", hooks="H1"):
    return {
        "codex-copilot": [("codex-copilot", version, hooks, "")],
        "codex/organization": [("codex-copilot-internal", "1.8.3", "O1", ""),
                               ("codex-copilot", "0.0.1", "STALE", "")],  # shadowed duplicate
        "codex/department-accounting": [("codex-copilot-accounting", "0.3.0", "A1", "")],
    }


@pytest.fixture
def make_release(home, tmp_path):
    counter = {"n": 0}

    def _build(plugins=None, post_build=None, personal=None, **market_kwargs):
        plugins = plugins if plugins is not None else default_layout()
        # The shipped default is strict (frozen core plugin); these fixtures build non-frozen
        # plugin trees on purpose, so they opt out unless a test asks for strict explicitly.
        market_kwargs.setdefault("strict_frozen", False)
        counter["n"] += 1
        now = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=counter["n"])
        live = tmp_path / f"live-{counter['n']}"
        live.mkdir()
        for entry in personal or []:
            write_plugin(live, *entry)

        def extractor(src, _tag, destination: Path):
            destination.mkdir(parents=True)
            for entry in plugins.get(src.name, []):
                write_plugin(destination, *entry)

        sources = []
        for name in layout.all_component_names():
            if name == layout.COMPONENT_CONTROL_TOWER:
                sources.append(build.ComponentSource(name, "framework", layout.KIND_RECORD, version="1"))
            elif name == "codex/personal":
                sources.append(build.ComponentSource(name, "personal", layout.KIND_LIVE, ref="main",
                                                     source=str(live)))
            elif name.endswith("/personal"):
                other = tmp_path / f"other-{name.replace('/', '-')}"
                other.mkdir(exist_ok=True)
                sources.append(build.ComponentSource(name, "personal", layout.KIND_LIVE, ref="main",
                                                     source=str(other)))
            else:
                sources.append(build.ComponentSource(name, "x", layout.KIND_SIGNED, version="v1", ref="v1",
                                                     source="unused", allowed_signers=("SHA256:test",)))
        return build.build_release(
            sources, home, now=now,
            verifier=lambda src: build.VerifiedTag("a" * 40, "SHA256:test"),
            extractor=extractor,
            post_build=post_build or marketplace.make_post_build(home, **market_kwargs),
        )
    return _build


@pytest.fixture
def publish(home, make_release):
    def _publish(**kwargs):
        manifest = make_release(**kwargs)
        pointer.flip(manifest.release_id, home)
        return manifest
    return _publish
