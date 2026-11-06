from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path

import pytest

from cc.core.release.codex import config, marketplace, step
from cc.core.release.engine import doctor, layout, pointer

from .conftest import default_layout, write_plugin

OWNER_CONFIG = '''model = "gpt-x"  # owner comment

[marketplaces.openai-bundled]
source_type = "local"
source = "/bundled"

[marketplaces.enac-materialized]
last_updated = "2026-08-14T21:01:02Z"
source_type = "local"
source = "/old/materialized"

[marketplaces.codex-copilot-local]
source_type = "local"
source = "/repo/codex-copilot"

[marketplaces.codex-copilot-project]
source_type = "local"
source = "/snapshots/x"

[hooks.state."codex-copilot@codex-copilot-local:hooks/hooks.json:pre_tool_use:0:0"]
trusted_hash = "sha256:aa"

[hooks.state."codex-copilot@enac-materialized:hooks/hooks.json:pre_tool_use:0:0"]
trusted_hash = "sha256:bb"

[plugins."browser@openai-bundled"]
enabled = true

[plugins."codex-copilot@codex-copilot-project"]
enabled = true

[plugins."codex-copilot@codex-copilot-local"]
enabled = true

[plugins."codex-copilot-internal@enac-materialized"]
enabled = false

[projects."/some/project"]
trust_level = "trusted"
'''


@pytest.fixture
def owner_config(codex_home):
    (codex_home / "config.toml").write_text(OWNER_CONFIG)
    return codex_home / "config.toml"


# ---- marketplace generation -------------------------------------------------

def test_release_contains_marketplace_with_all_tiers(home, make_release):
    manifest = make_release(personal=[("my-tool", "2.0.0", "P1", "")])
    root = layout.release_dir(manifest.release_id, home) / layout.MARKETPLACE_DIRNAME
    listing = json.loads((root / ".agents/plugins/marketplace.json").read_text())
    assert listing["name"] == "enac-materialized"
    assert [p["name"] for p in listing["plugins"]] == [
        "codex-copilot", "codex-copilot-internal", "codex-copilot-accounting", "my-tool"]
    receipt = marketplace.load_receipt(root.parent)
    assert {p["name"]: p["version"] for p in receipt["plugins"]} == {
        "codex-copilot": "1.0.0", "codex-copilot-internal": "1.8.3",
        "codex-copilot-accounting": "0.3.0", "my-tool": "2.0.0"}
    assert receipt["shadowed"] == [{"name": "codex-copilot", "tier": "organization",
                                    "component": "codex/organization", "version": "0.0.1",
                                    "winner": "foundation"}]
    assert not any(p.is_symlink() for p in root.rglob("*"))
    assert marketplace.tree_digest(root / "plugins/codex-copilot") == \
        next(p["digest"] for p in receipt["plugins"] if p["name"] == "codex-copilot")


def test_symlink_in_plugin_fails_build_and_leaves_no_release(home, make_release, tmp_path):
    elsewhere = tmp_path / "skill"
    elsewhere.mkdir()

    plugins = default_layout()
    manifest_hook = marketplace.make_post_build(home)

    def post(target, components):
        os.symlink(elsewhere, target / "codex-copilot/plugins/codex-copilot/skills")
        manifest_hook(target, components)

    with pytest.raises(marketplace.MarketplaceError, match="symlinks"):
        make_release(plugins=plugins, post_build=post)
    assert pointer.list_releases(home) == []


def test_missing_foundation_plugin_fails(home, make_release):
    with pytest.raises(marketplace.MarketplaceError, match="foundation"):
        make_release(plugins={"codex/organization": [("codex-copilot-internal", "1", "x", "")]})


def test_hooks_json_change_fails_unless_declared(home, publish, make_release):
    publish()
    with pytest.raises(marketplace.MarketplaceError, match="codex-copilot"):
        make_release(plugins=default_layout(hooks="CHANGED"))
    ok = make_release(plugins=default_layout(hooks="CHANGED"), retrust=["codex-copilot"])
    receipt = marketplace.load_receipt(layout.release_dir(ok.release_id, home))
    assert receipt["retrust"] == ["codex-copilot"]
    assert "codex-copilot" in receipt["trustContentChanged"]


def test_unchanged_hooks_pass_and_version_bump_is_reported(home, publish, make_release):
    publish()
    manifest = make_release(plugins=default_layout(version="1.1.0"))
    receipt = marketplace.load_receipt(layout.release_dir(manifest.release_id, home))
    assert receipt["retrust"] == []
    assert receipt["trustContentChanged"] == ["codex-copilot"]  # plugin.json differs


def test_strict_frozen_fails_on_any_plugin_dir_change(home, publish, make_release):
    publish()
    with pytest.raises(marketplace.MarketplaceError, match="content trust"):
        make_release(plugins=default_layout(version="1.1.0"), strict_frozen=True)
    identical = make_release(plugins=default_layout(), strict_frozen=True)
    assert marketplace.load_receipt(layout.release_dir(identical.release_id, home))["trustContentChanged"] == []


# ---- config edits -----------------------------------------------------------

def edit(**kw):
    return config.edit(OWNER_CONFIG, source="/h/.copilot/current/codex-marketplace",
                       plugins=["codex-copilot", "codex-copilot-internal"], **kw)


def test_edit_registers_one_marketplace_and_keeps_owner_content():
    parsed = tomllib.loads(edit())
    assert set(parsed["marketplaces"]) == {"openai-bundled", "enac-materialized"}
    assert parsed["marketplaces"]["enac-materialized"]["source"] == "/h/.copilot/current/codex-marketplace"
    assert set(parsed["plugins"]) == {
        "browser@openai-bundled", "codex-copilot@enac-materialized",
        "codex-copilot-internal@enac-materialized"}
    assert all(parsed["plugins"][k]["enabled"] for k in parsed["plugins"])
    assert parsed["projects"]["/some/project"]["trust_level"] == "trusted"
    assert 'model = "gpt-x"  # owner comment' in edit()
    # stale trust left in place by default, removed on request
    assert len(parsed["hooks"]["state"]) == 2
    pruned = tomllib.loads(edit(prune_trust=True))
    assert list(pruned["hooks"]["state"]) == [
        "codex-copilot@enac-materialized:hooks/hooks.json:pre_tool_use:0:0"]


def test_apply_backs_up_is_idempotent_and_rolls_back(home, owner_config, codex_home):
    result = config.apply(codex_home, home, source="/s", plugins=["codex-copilot"])
    assert result.changed and Path(result.backup).read_text() == OWNER_CONFIG
    assert "codex-copilot-local" in " ".join(result.removed)
    again = config.apply(codex_home, home, source="/s", plugins=["codex-copilot"])
    assert not again.changed and again.backup is None
    config.rollback(home)
    assert owner_config.read_text() == OWNER_CONFIG


def test_rollback_refuses_after_owner_edit(home, owner_config, codex_home):
    config.apply(codex_home, home, source="/s", plugins=["codex-copilot"])
    owner_config.write_text(owner_config.read_text() + "\n# owner edit\n")
    with pytest.raises(config.ConfigError, match="changed since"):
        config.rollback(home)
    config.rollback(home, force=True)
    assert owner_config.read_text() == OWNER_CONFIG


def test_apply_refuses_invalid_toml_without_writing(home, codex_home):
    path = codex_home / "config.toml"
    path.write_text("[broken\n")
    with pytest.raises(config.ConfigError):
        config.apply(codex_home, home, source="/s", plugins=["x"])
    assert path.read_text() == "[broken\n"
    assert list(codex_home.glob("config.toml.bak*")) == []


def test_apply_creates_missing_config_and_rollback_removes_it(home, codex_home):
    result = config.apply(codex_home, home, source="/s", plugins=["a"])
    assert result.backup is None and (codex_home / "config.toml").exists()
    config.rollback(home)
    assert not (codex_home / "config.toml").exists()


# ---- release step with a fake codex CLI ----------------------------------------

def run_step(home, codex_home, fake_codex, **kw):
    return step.run(home, codex_home, codex_bin=fake_codex, **kw)


def test_step_falls_back_to_plugin_add_and_cache_matches(home, codex_home, owner_config,
                                                         fake_codex, publish):
    publish()
    result = run_step(home, codex_home, fake_codex)
    assert result.refreshed_with == "plugin add"
    cache = codex_home / "plugins/cache/enac-materialized"
    assert (cache / "codex-copilot/1.0.0/hooks/hooks.json").read_text() == "H1"
    assert (cache / "codex-copilot-internal/1.8.3").is_dir()
    cfg = config.read(codex_home)
    assert set(cfg["marketplaces"]) == {"openai-bundled", "enac-materialized"}
    assert cfg["marketplaces"]["enac-materialized"]["source"] == step.marketplace_source(home)
    assert not any(k.endswith("codex-copilot-project") or k.endswith("codex-copilot-local")
                   for k in cfg["plugins"])


def test_step_uses_upgrade_when_it_works(home, codex_home, owner_config, fake_codex, publish,
                                         monkeypatch):
    publish()
    monkeypatch.setenv("FAKE_UPGRADE", "ok")
    assert run_step(home, codex_home, fake_codex).refreshed_with == "marketplace upgrade"
    assert "plugin add" not in (codex_home / "calls.log").read_text()


def test_step_fails_when_add_fails(home, codex_home, owner_config, fake_codex, publish, monkeypatch):
    publish()
    monkeypatch.setenv("FAKE_ADD", "fail")
    with pytest.raises(step.ReleaseStepError, match="boom"):
        run_step(home, codex_home, fake_codex)
    config.rollback(home)
    assert owner_config.read_text() == OWNER_CONFIG


def test_step_fails_when_cache_content_differs(home, codex_home, owner_config, publish, tmp_path):
    publish()
    liar = tmp_path / "liar"
    liar.write_text("#!/bin/sh\nexit 0\n")
    liar.chmod(0o755)
    with pytest.raises(step.ReleaseStepError, match="cache"):
        step.run(home, codex_home, codex_bin=str(liar))


def test_step_requires_a_release_with_marketplace(home, codex_home, fake_codex):
    with pytest.raises(step.ReleaseStepError, match="receipt"):
        run_step(home, codex_home, fake_codex)


# ---- doctor ---------------------------------------------------------------------

def names(checks):
    return {c.name: c for c in checks}


def test_doctor_passes_after_step(home, codex_home, owner_config, fake_codex, publish):
    publish()
    run_step(home, codex_home, fake_codex)
    checks = names(doctor.run(home, extra=[step.doctor_checks(codex_home, home)]))
    assert all(c.ok for c in checks.values()), checks


def test_doctor_fails_when_cache_version_differs_from_release(home, codex_home, owner_config,
                                                              fake_codex, publish):
    publish()
    run_step(home, codex_home, fake_codex)
    publish(plugins=default_layout(version="1.1.0"))  # flipped, cache not refreshed
    checks = names(doctor.run(home, extra=[step.doctor_checks(codex_home, home)]))
    assert not checks["codex-cache"].ok and "1.1.0" in checks["codex-cache"].detail
    run_step(home, codex_home, fake_codex)
    assert all(c.ok for c in doctor.run(home, extra=[step.doctor_checks(codex_home, home)]))


def test_doctor_fails_on_second_copilot_plugin_source(home, codex_home, owner_config,
                                                      fake_codex, publish):
    publish()
    run_step(home, codex_home, fake_codex)
    path = codex_home / "config.toml"
    path.write_text(path.read_text() + '\n[plugins."codex-copilot@codex-copilot-project"]\nenabled = true\n'
                    '\n[marketplaces.codex-copilot-local]\nsource_type = "local"\nsource = "/x"\n')
    checks = names(doctor.run(home, extra=[step.doctor_checks(codex_home, home)]))
    assert not checks["codex-single-source"].ok
    assert "codex-copilot@codex-copilot-project enabled" in checks["codex-single-source"].detail


def test_rollback_release_refreshes_back_to_old_versions(home, codex_home, owner_config,
                                                         fake_codex, publish):
    first = publish()
    run_step(home, codex_home, fake_codex)
    publish(plugins=default_layout(version="1.1.0"))
    run_step(home, codex_home, fake_codex)
    pointer.rollback(home)
    assert pointer.current_release_id(home) == first.release_id
    run_step(home, codex_home, fake_codex)
    assert all(c.ok for c in doctor.run(home, extra=[step.doctor_checks(codex_home, home)]))
