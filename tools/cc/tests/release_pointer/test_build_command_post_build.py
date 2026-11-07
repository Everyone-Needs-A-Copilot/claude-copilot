"""`cc release build` runs the same post-build as publish: source markers precede the cc venv.

The venv step runs `tc provenance --record`, which needs `.source-commit` and
`.source-tree` in the extracted release (it has no `.git`). Only the publish
post-build wrote them, so the bare build command failed on the venv step.
"""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from cc.commands import release as release_cmd
from cc.core.release import publish


def test_build_command_uses_publish_post_build(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def fake_make_post_build(home=None, **kwargs):
        captured["home"] = home
        return "POST_BUILD"

    def fake_build_release(sources, home, post_build=None, **_):
        captured["post_build"] = post_build
        raise release_cmd.build.ReleaseBuildError("stop")

    monkeypatch.setattr(publish, "make_post_build", fake_make_post_build)
    monkeypatch.setattr(release_cmd.build, "sources_from_layers", lambda *_: [])
    monkeypatch.setattr(release_cmd.build, "build_release", fake_build_release)
    pins, layers = tmp_path / "pins.json", tmp_path / "layers.yml"
    pins.write_text("{}")
    layers.write_text("{}")
    result = CliRunner().invoke(release_cmd.release_app, ["build", "--pins", str(pins), "--layers", str(layers), "--home", str(tmp_path)])
    assert captured["post_build"] == "POST_BUILD"
    assert "release build failed" in result.output
