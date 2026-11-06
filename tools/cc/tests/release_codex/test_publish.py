"""`cc release publish`: one command builds, flips, links, refreshes Codex, checks and restores on failure."""

from __future__ import annotations

import json
import plistlib
from pathlib import Path

import pytest

from cc.core.release import publish as publisher
from cc.core.release.engine import build, layout, pointer

from .conftest import default_layout, write_plugin


@pytest.fixture
def ct_app(tmp_path):
    app = tmp_path / "CT.app"
    (app / "Contents").mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps({"CFBundleShortVersionString": "0.6.11"}))
    return app


@pytest.fixture
def sources(tmp_path, ct_app):
    out = []
    for name in layout.all_component_names():
        if name == layout.COMPONENT_CONTROL_TOWER:
            out.append(build.ComponentSource(name, "framework", layout.KIND_RECORD, version="0.6.11",
                                             ref="refs/tags/v0.6.11", source=str(ct_app), commit="86b405b"))
        elif name.endswith("/personal"):
            live = tmp_path / f"live-{name.replace('/', '-')}"
            live.mkdir(exist_ok=True)
            out.append(build.ComponentSource(name, "personal", layout.KIND_LIVE, ref="main", source=str(live)))
        else:
            out.append(build.ComponentSource(name, "x", layout.KIND_SIGNED, version="v1", ref="v1",
                                             source="unused", allowed_signers=("SHA256:test",)))
    return out


def _extractor(src, _tag, destination: Path):
    destination.mkdir(parents=True)
    for entry in default_layout().get(src.name, []):
        write_plugin(destination, *entry)
    if src.name == layout.COMPONENT_CODEX:
        (destination / "skills" / "me").mkdir(parents=True)
        (destination / "skills" / "me" / "SKILL.md").write_text("---\nname: me\ndescription: d\n---\n")


def _run(sources, home, codex_home, fake_codex, **kw):
    return publisher.publish(
        sources, home, codex_home, venv=False, codex_bin=fake_codex, control_tower_app=kw.pop("app"),
        verifier=lambda s: build.VerifiedTag("a" * 40, "SHA256:test"), extractor=_extractor, **kw)


def test_publish_runs_every_step_and_passes_doctor(home, codex_home, fake_codex, sources, ct_app, monkeypatch):
    monkeypatch.setenv("FAKE_UPGRADE", "ok")
    report = _run(sources, home, codex_home, fake_codex, app=ct_app)
    assert report.flipped and pointer.current_release_id(home) == report.release_id
    assert all(c["ok"] for c in report.checks), report.checks
    assert (home / ".claude" / "skills").exists() or report.links["errors"] == []
    record = json.loads((layout.current_path(home) / layout.MANIFEST_NAME).read_text())
    ct = [c for c in record["components"] if c["name"] == layout.COMPONENT_CONTROL_TOWER][0]
    assert (ct["version"], ct["commit"]) == ("0.6.11", "86b405b")
    assert pointer.read_history(home)[-1]["reason"] == "publish"


def test_publish_fails_closed_and_restores_previous_release(home, codex_home, fake_codex, sources, ct_app, monkeypatch):
    monkeypatch.setenv("FAKE_UPGRADE", "ok")
    first = _run(sources, home, codex_home, fake_codex, app=ct_app)
    import time; time.sleep(1.1)  # release ids have one-second resolution
    monkeypatch.setenv("FAKE_UPGRADE", "no")
    monkeypatch.setenv("FAKE_ADD", "fail")
    with pytest.raises(publisher.PublishError) as caught:
        _run(sources, home, codex_home, fake_codex, app=ct_app)
    assert caught.value.step == "codex" and caught.value.restored
    assert f"--to {first.release_id}" in caught.value.rollback_hint
    assert pointer.current_release_id(home) == first.release_id


def test_doctor_flags_control_tower_drift(home, codex_home, fake_codex, sources, ct_app, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_UPGRADE", "ok")
    _run(sources, home, codex_home, fake_codex, app=ct_app)
    (ct_app / "Contents" / "Info.plist").write_bytes(plistlib.dumps({"CFBundleShortVersionString": "0.7.0"}))
    failed = [c.name for c in publisher.run_doctor(home, codex_home, control_tower_app=ct_app) if not c.ok]
    assert failed == ["control-tower"]
