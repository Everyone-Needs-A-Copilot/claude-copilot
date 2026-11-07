from __future__ import annotations

import json
import os
import subprocess
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from cc.commands.release import release_app
from cc.core.release import publish as publisher
from cc.core.release.engine import build, doctor, layout, pointer, prune, schema, shims

from .conftest import git


def test_build_writes_complete_manifest(home, make_release):
    manifest = make_release()
    root = layout.release_dir(manifest.release_id, home)
    loaded = schema.load(root)
    assert {c.name for c in loaded.components} == set(layout.all_component_names())
    claude = loaded.component("claude-copilot")
    assert claude.commit and claude.signer == "SHA256:test" and claude.version == "v1"
    assert (root / "claude-copilot" / "VERSION").read_text() == "1\n"
    assert loaded.component("control-tower").path == ""
    assert not os.access(root / "claude-copilot" / "VERSION", os.W_OK)  # immutable


def test_bad_signature_fails_build_and_leaves_current(home, make_release):
    first = make_release()
    pointer.flip(first.release_id, home)

    def reject(src):
        if src.name == "knowledge/organization":
            raise build.ReleaseBuildError("bad signature")
        return build.VerifiedTag("a" * 40, "SHA256:test")

    with pytest.raises(build.ReleaseBuildError):
        make_release(verifier=reject)
    assert pointer.current_release_id(home) == first.release_id
    assert pointer.list_releases(home) == [first.release_id]
    assert [p.name for p in layout.releases_dir(home).iterdir()] == [first.release_id]


def test_default_verifier_rejects_unsigned_tag(repo):
    src = build.ComponentSource("claude-copilot", "x", layout.KIND_SIGNED, ref="v1",
                                source=str(repo), allowed_signers=("SHA256:test",))
    with pytest.raises(build.ReleaseBuildError):
        build.default_verifier(src)


def test_personal_tier_is_live_link(home, make_release, live):
    manifest = make_release()
    link = layout.release_dir(manifest.release_id, home) / "claude" / "personal"
    assert link.is_symlink()
    (live["claude"] / "new.txt").write_text("fresh")
    assert (link / "new.txt").read_text() == "fresh"  # no new release needed


def test_live_link_into_worktrees_refused(home, make_sources, tmp_path):
    sources = make_sources()
    bad = tmp_path / ".worktrees" / "wt"
    bad.mkdir(parents=True)
    sources = [s if s.name != "cli/personal" else build.ComponentSource(
        s.name, s.tier, s.kind, ref="main", source=str(bad)) for s in sources]
    with pytest.raises(build.ReleaseBuildError):
        build.build_release(sources, home, verifier=lambda s: build.VerifiedTag("b" * 40, "SHA256:test"))


def test_flip_is_atomic_and_logged(home, make_release):
    a, b = make_release("v1"), make_release("v2")
    assert pointer.current_release_id(home) is None
    pointer.flip(a.release_id, home)
    pointer.flip(b.release_id, home, reason="ship")
    current = layout.current_path(home)
    assert current.is_symlink() and current.resolve().name == b.release_id
    assert not [p for p in layout.copilot_home(home).iterdir() if p.name.endswith(".tmp")]
    history = pointer.read_history(home)
    assert [r["release"] for r in history] == [a.release_id, b.release_id]
    assert history[1]["previous"] == a.release_id and history[1]["reason"] == "ship"
    assert b.previous is None  # nothing was current when it was built


def test_flip_unknown_release_leaves_current(home, make_release):
    a = make_release()
    pointer.flip(a.release_id, home)
    with pytest.raises(schema.ReleaseSchemaError):
        pointer.flip("20260101T000000Z-nothing", home)
    assert pointer.current_release_id(home) == a.release_id


def test_rollback_previous_and_named(home, make_release):
    a, b, c = make_release("v1"), make_release("v2"), make_release("v1")
    for item in (a, b, c):
        pointer.flip(item.release_id, home)
    pointer.rollback(home)
    assert pointer.current_release_id(home) == b.release_id
    pointer.rollback(home, to=a.release_id, reason="named")
    assert pointer.current_release_id(home) == a.release_id
    actions = [r["action"] for r in pointer.read_history(home)]
    assert actions[-2:] == ["rollback", "rollback"]
    with pytest.raises(pointer.PointerError):
        pointer.rollback(home, to=a.release_id)


def test_rollback_without_history_errors(home, make_release):
    pointer.flip(make_release().release_id, home)
    with pytest.raises(pointer.PointerError):
        pointer.rollback(home)


def test_prune_plans_exact_paths_and_needs_approval(home, make_release):
    releases = [make_release() for _ in range(5)]
    for item in releases:
        pointer.flip(item.release_id, home)
    receipt = prune.plan(home, keep=2)
    expected = [str(layout.release_dir(r.release_id, home)) for r in releases[:3]]
    assert receipt["paths"] == expected
    assert prune.execute(receipt["receipt"], home) == []  # no approval, nothing deleted
    assert all(os.path.isdir(p) for p in expected)
    removed = prune.execute(receipt["receipt"], home, approved=True)
    assert removed == expected
    assert pointer.list_releases(home) == sorted(r.release_id for r in releases[3:])


def test_prune_never_removes_current_even_if_listed(home, make_release):
    a, b = make_release(), make_release()
    pointer.flip(a.release_id, home)
    pointer.flip(b.release_id, home)
    receipt = prune.plan(home, keep=1)
    assert str(layout.release_dir(a.release_id, home)) not in receipt["paths"]  # previous kept
    path = layout.copilot_home(home) / "prune-receipts" / f"{receipt['receipt']}.json"
    forged = json.loads(path.read_text())
    forged["paths"] = [str(layout.release_dir(b.release_id, home))]
    path.write_text(json.dumps(forged))
    assert prune.execute(receipt["receipt"], home, approved=True) == []
    assert layout.release_dir(b.release_id, home).is_dir()


def _run(shim, home):
    result = subprocess.run([str(shim)], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    return result


def test_shims_follow_flip(home, make_release):
    a, b = make_release("v1"), make_release("v2")
    shims.install(home)
    cc = layout.bin_dir(home) / "cc"
    missing = _run(cc, home)
    assert missing.returncode == 0 and "cc release status" in missing.stderr
    pointer.flip(a.release_id, home)
    assert f"cc-from-{a.release_id}" in _run(cc, home).stdout
    pointer.flip(b.release_id, home)
    assert f"cc-from-{b.release_id}" in _run(cc, home).stdout
    assert f"cc-from-{b.release_id}" in _run(layout.bin_dir(home) / "tc", home).stdout
    assert "tc-limits-ran" in _run(layout.bin_dir(home) / "tc-limits", home).stdout


def test_doctor_passes_healthy_and_fails_dangling(home, make_release):
    a = make_release()
    pointer.flip(a.release_id, home)
    assert all(c.ok for c in doctor.run(home))
    build._remove(layout.release_dir(a.release_id, home))
    checks = doctor.run(home)
    assert not all(c.ok for c in checks)


def test_doctor_fails_invalid_manifest(home, make_release):
    a = make_release()
    pointer.flip(a.release_id, home)
    root = layout.release_dir(a.release_id, home)
    os.chmod(root, 0o700)
    os.chmod(root / "release.json", 0o600)
    (root / "release.json").write_text(json.dumps({"schema": 2}))
    assert not all(c.ok for c in doctor.run(home))


def test_doctor_fails_worktree_link(home, make_release, tmp_path):
    a = make_release()
    pointer.flip(a.release_id, home)
    root = layout.release_dir(a.release_id, home)
    bad = tmp_path / ".worktrees" / "x"
    bad.mkdir(parents=True)
    os.chmod(root, 0o700)
    os.symlink(bad, root / "sneaky")
    failed = [c for c in doctor.run(home) if not c.ok]
    assert [c.name for c in failed] == ["no-worktree-links"]


def test_doctor_fails_when_missing(home):
    assert not all(c.ok for c in doctor.run(home))


def test_default_extractor_archives_subpath(home, repo, tmp_path):
    git(repo, "tag", "-f", "-a", "v3", "-m", "v3")
    src = build.ComponentSource("x", "t", layout.KIND_SIGNED, ref="v3", source=str(repo), subpath="tools")
    tag = build.VerifiedTag(git(repo, "rev-parse", "v3^{commit}"), "s")
    build.default_extractor(src, tag, tmp_path / "out")
    assert (tmp_path / "out" / "tc" / "tc-limits").is_file()


def test_cli_status_flip_history_rollback_prune(home, make_release, monkeypatch):
    a, b = make_release(), make_release()
    runner = CliRunner()
    base = ["--home", str(home)]
    assert runner.invoke(release_app, ["flip", a.release_id, *base]).exit_code == 0
    assert runner.invoke(release_app, ["flip", b.release_id, *base]).exit_code == 0
    status = json.loads(runner.invoke(release_app, ["status", *base]).stdout)
    assert status["release"] == b.release_id and status["valid"]
    # These engine-only releases omit Codex/app consumer fixtures. The full
    # publisher recovery contract has separate behavioral tests; retain real
    # pointer movement and engine doctor checks for this CLI dispatch test.
    refresh = Mock()
    with monkeypatch.context() as patch:
        patch.setattr(publisher.codex_step, "run", refresh)
        patch.setattr(publisher, "run_doctor", lambda home, codex_home, **kw: doctor.run(home))
        assert runner.invoke(release_app, ["rollback", *base]).exit_code == 0
    refresh.assert_called_once()
    assert refresh.call_args.args == (home, None)
    history = json.loads(runner.invoke(release_app, ["history", *base]).stdout)
    assert [r["action"] for r in history] == ["flip", "flip", "rollback"]
    plan = json.loads(runner.invoke(release_app, ["prune", "--keep", "1", *base]).stdout)
    assert plan["approved"] is False
    assert runner.invoke(release_app, ["prune", "--approve", *base]).exit_code == 1
    # `release doctor` is the full release check: engine checks pass on this bare release, while the
    # Codex marketplace, links receipt and Control Tower record (absent here) fail it (was: exit 0).
    doctor_run = runner.invoke(release_app, ["doctor", *base, "--codex-home", str(home / ".codex")])
    assert doctor_run.exit_code == 1
    failed = {row["name"] for row in json.loads(doctor_run.stdout) if not row["ok"]}
    assert failed <= {"codex-marketplace", "links", "control-tower"} and "codex-marketplace" in failed
    assert runner.invoke(release_app, ["flip", "bogus", *base]).exit_code == 1


def test_sources_from_layers_maps_tiers():
    layers = {"layers": [
        {"role": "foundation", "product": "knowledge", "source": {"ref": "v1", "path": "/k"}, "policy": {"allowed_signers": ["S"]}},
        {"role": "department", "unit": "accounting", "product": "cli", "source": {"ref": "v2", "path": "/c"}, "policy": {"allowed_signers": ["S"]}},
    ]}
    with pytest.raises(build.ReleaseBuildError, match="knowledge/organization"):
        build.sources_from_layers(layers, {})


def test_history_failure_restores_pointer(home, make_release, monkeypatch):
    a, b = make_release("v1"), make_release("v2")
    pointer.flip(a.release_id, home)

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(pointer, "append_history", boom)
    with pytest.raises(pointer.PointerError):
        pointer.flip(b.release_id, home)
    assert pointer.current_release_id(home) == a.release_id


def test_history_failure_on_first_flip_removes_pointer(home, make_release, monkeypatch):
    a = make_release()
    monkeypatch.setattr(pointer, "append_history", lambda *_a, **_k: (_ for _ in ()).throw(OSError("x")))
    with pytest.raises(pointer.PointerError):
        pointer.flip(a.release_id, home)
    assert pointer.current_release_id(home) is None


def test_repeated_rollback_walks_back_through_history(home, make_release):
    a, b, c = make_release("v1"), make_release("v2"), make_release("v1")
    for item in (a, b, c):
        pointer.flip(item.release_id, home)
    pointer.rollback(home)
    assert pointer.current_release_id(home) == b.release_id
    pointer.rollback(home)
    assert pointer.current_release_id(home) == a.release_id
    with pytest.raises(pointer.PointerError, match="no earlier release"):
        pointer.rollback(home)


def test_rollback_multiple_steps(home, make_release):
    a, b, c = make_release("v1"), make_release("v2"), make_release("v1")
    for item in (a, b, c):
        pointer.flip(item.release_id, home)
    pointer.rollback(home, steps=2)
    assert pointer.current_release_id(home) == a.release_id
    with pytest.raises(pointer.PointerError, match="no earlier release"):
        pointer.rollback(home, steps=1)


def test_shim_warns_on_stderr_and_exits_zero_when_current_missing(home):
    import subprocess

    shims.install(home)
    shim = layout.bin_dir(home) / "cc"
    result = subprocess.run([str(shim)], capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stderr.count("\n") == 1 and "no current release" in result.stderr


def test_extractor_leaves_out_escaping_symlinks_but_keeps_inner_ones(tmp_path):
    import io, tarfile
    from pathlib import Path
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, target in ((".mcp.json", "../outside/mcp.json"), ("inner", "real")):
            info = tarfile.TarInfo(name); info.type = tarfile.SYMTYPE; info.linkname = target
            tar.addfile(info)
        data = b"x"; info = tarfile.TarInfo("real"); info.size = 1; tar.addfile(info, io.BytesIO(data))
    buf.seek(0)
    dest = tmp_path / "out"; dest.mkdir()
    with tarfile.open(fileobj=buf) as tar:
        tar.extractall(dest, filter=build._release_filter)
    assert not (dest / ".mcp.json").is_symlink() and not (dest / ".mcp.json").exists()
    assert (dest / "inner").is_symlink()
