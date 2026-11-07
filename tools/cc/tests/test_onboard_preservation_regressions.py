"""Onboarding must preserve authenticated release rows and owner customization."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from cc.commands import onboard as subject
from cc.core.ecosystem import policy
from cc.core.ecosystem.manifest import validate_layers

PRODUCTS = ("knowledge", "cli", "claude", "codex")
ROLES = ("personal", "department", "organization", "foundation")


def git(path, *args):
    return subprocess.run(
        ["git", "-C", str(path), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def no_external(args):
    raise AssertionError(f"Unexpected external command: {args}")


def generated(root, *, departments=(), handoff=None):
    return subject._layer_manifest(
        "Acme", "author", PRODUCTS,
        handoff or {"foundation": {"refs": {p: "v1.2.3" for p in PRODUCTS}}},
        run=no_external, repository_root=root, department_units=departments,
    )


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("COPILOT_HOME", str(home / ".copilot"))
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    return home


@pytest.fixture
def signed_row(tmp_path, monkeypatch):
    key = tmp_path / "fixture-key"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True
    )
    public = key.with_suffix(".pub")
    fingerprint = subprocess.check_output(
        ["ssh-keygen", "-lf", str(public)], text=True
    ).split()[1]
    monkeypatch.setattr(
        policy, "FOUNDATION_SSH_SIGNING_KEYS",
        {**policy.FOUNDATION_SSH_SIGNING_KEYS, fingerprint: public.read_text().strip()},
    )

    def make(product, role, *, unit="accounting", rank=None):
        row = next(
            r for r in generated(tmp_path / "sources", departments=(unit,))["layers"]
            if r["product"] == product and r["role"] == role
        )
        repo = Path(row["source"]["path"])
        repo.mkdir(parents=True)
        git(repo, "init", "-q", "-b", "main")
        for name, value in {
            "user.name": "Fixture", "user.email": "fixture@example.invalid",
            "gpg.format": "ssh", "user.signingkey": str(key),
            "core.hooksPath": "/dev/null",
        }.items():
            git(repo, "config", name, value)
        git(repo, "remote", "add", "origin", row["source"]["repo"])
        (repo / "content").mkdir()
        (repo / "content" / "payload").write_text("authenticated fixture\n")
        if product == "claude" and role == "foundation":
            (repo / ".claude").mkdir()
            (repo / ".claude" / "payload").write_text("framework fixture\n")
        git(repo, "add", ".")
        git(repo, "commit", "-qS", "-m", "signed fixture")
        git(repo, "tag", "-s", "v1.2.3", "-m", "signed fixture release")
        if role != "personal":
            row["source"]["ref"] = "v1.2.3"
            row["policy"]["allowed_signers"] = [fingerprint]
        if rank is not None:
            row["rank"] = rank
        desired = next(
            r for r in generated(tmp_path / "sources", departments=(unit,))["layers"]
            if r["product"] == product and r["role"] == role
        )
        if rank is not None:
            desired["rank"] = rank
        return row, desired, repo

    return make


def plan(tmp_path, existing, desired):
    target = tmp_path / "manifest.yml"
    original = {"version": 1, "org": "Acme", "layers": existing}
    target.write_text(yaml.safe_dump(original))
    before = target.read_bytes()
    result = subject._manifest_adoption_plan(
        {"version": 1, "org": "Acme", "layers": desired}, target
    )
    assert target.read_bytes() == before
    return result, original


@pytest.mark.parametrize("product", PRODUCTS)
@pytest.mark.parametrize("role", ROLES)
def test_all_products_retain_complete_authenticated_or_personal_row(
    tmp_path, signed_row, product, role
):
    existing, desired, _ = signed_row(product, role)
    result, original = plan(tmp_path, [existing], [desired])
    assert result.action == "reuse", result
    assert result.payload == original


@pytest.mark.parametrize("product", ("cli", "knowledge"))
def test_new_foundation_rows_have_compiled_approved_signer(product, tmp_path):
    row = next(
        r for r in generated(tmp_path)["layers"]
        if r["product"] == product and r["role"] == "foundation"
    )
    assert "SHA256:FIfppOkzwXZUAamELQzYoSUQXiEAmTYiVewHe1ACMZo" in row["policy"]["allowed_signers"]


@pytest.mark.parametrize("product", PRODUCTS)
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("change", ("source-extra", "policy-extra", "custom-path"))
def test_nested_customization_is_held_before_replacement(tmp_path, product, role, change):
    desired = next(
        r for r in generated(tmp_path, departments=("accounting",))["layers"]
        if r["product"] == product and r["role"] == role
    )
    existing = copy.deepcopy(desired)
    if change == "source-extra":
        existing["source"]["owner_customization"] = "retain"
    elif change == "policy-extra":
        existing["policy"]["owner_customization"] = "retain"
    else:
        existing["source"]["path"] = str(tmp_path / "owner-location")
    result, _ = plan(tmp_path, [existing], [desired])
    assert result.action == "review"
    assert result.payload is None


@pytest.mark.parametrize("change", ("branch", "unsigned", "wrong-signer", "wrong-origin"))
@pytest.mark.parametrize("product", PRODUCTS)
def test_failed_foundation_authentication_cannot_be_repaired_away(
    tmp_path, signed_row, product, change
):
    existing, desired, repo = signed_row(product, "foundation")
    if change == "branch":
        existing["source"]["ref"] = "owner-branch"
    elif change == "unsigned":
        git(repo, "tag", "--no-sign", "-a", "v1.2.4", "-m", "unsigned")
        existing["source"]["ref"] = "v1.2.4"
    elif change == "wrong-signer":
        existing["policy"]["allowed_signers"] = ["SHA256:untrusted"]
    else:
        git(repo, "remote", "set-url", "origin", "git@github.com:Other/foreign.git")
    result, _ = plan(tmp_path, [existing], [desired])
    assert result.action == "review"
    assert result.payload is None


@pytest.mark.parametrize("role,alias", [("foundation", "cli-foundation"), ("organization", "cli-organization")])
def test_recognized_cli_alias_preserves_signed_row(tmp_path, signed_row, role, alias):
    existing, desired, _ = signed_row("cli", role)
    existing["id"] = alias
    result, original = plan(tmp_path, [existing], [desired])
    assert result.action == "reuse", result
    assert result.payload == original


def test_two_signed_department_units_remain_distinct(tmp_path, signed_row):
    first, expected_first, _ = signed_row("claude", "department", unit="accounting", rank=20)
    second, expected_second, _ = signed_row("claude", "department", unit="sales", rank=21)
    result, original = plan(tmp_path, [first, second], [expected_first, expected_second])
    assert result.action == "reuse", result
    assert result.payload == original


def test_department_generation_uses_declared_ranks_not_membership_order(tmp_path):
    handoff = {
        "foundation": {"refs": {p: "v1.2.3" for p in PRODUCTS}},
        "departments": [{"unit": "sales", "rank": 21}, {"unit": "accounting", "rank": 20}],
    }
    actual = generated(tmp_path, departments=("sales", "accounting"), handoff=handoff)
    validate_layers(actual["layers"])
    for product in PRODUCTS:
        assert [(r["unit"], r["rank"]) for r in actual["layers"] if r["product"] == product and r["role"] == "department"] == [("accounting", 20), ("sales", 21)]


def test_multiple_departments_without_explicit_order_hold(tmp_path):
    with pytest.raises((RuntimeError, ValueError), match="(?i)rank|order|department"):
        generated(tmp_path, departments=("sales", "accounting"))


def test_valid_linked_worktree_is_exact_but_nested_directory_is_not(tmp_path, signed_row):
    row, _, repo = signed_row("cli", "foundation")
    linked = tmp_path / "linked"
    git(repo, "worktree", "add", "--detach", str(linked), "v1.2.3")
    assert (linked / ".git").is_file()
    source = {**row["source"], "repo": str(repo)}

    def run(args):
        return subprocess.run(args, capture_output=True, text=True)

    result = subject._classify_repository_history(
        linked, owner="Everyone-Needs-A-Copilot", name="cli-copilot", source=source, run=run
    )
    assert (result.state, result.action) == ("exact", "reuse")
    nested = linked / "nested"
    nested.mkdir()
    result = subject._classify_repository_history(
        nested, owner="Everyone-Needs-A-Copilot", name="cli-copilot", source=source, run=run
    )
    assert result.action == "review"


def topology_rows(manifest, **_kwargs):
    return [
        {"id": row["id"], "product": row["product"], "role": row["role"],
         "rank": row["rank"], "unit": row.get("unit"), "repository_owner": "Acme",
         "repository_name": "fixture", "repository_visibility": "private",
         "remote_state": "ready", "author_capable": False, "repository_permission": "read", "local_path": row["source"]["path"],
         "local_state": "visible", "connection_state": "connected",
         "sync_state": "current", "action": "reuse", "detail": "fixture"}
        for row in manifest["layers"]
    ]


@pytest.fixture
def effective_plan(tmp_path, monkeypatch):
    desired = generated(tmp_path / "generated")
    effective = copy.deepcopy(desired)
    for row in effective["layers"]:
        row["source"]["path"] = str(tmp_path / "authenticated" / row["id"])
        if row["role"] != "personal":
            row["source"]["ref"] = "v1.2.2"
    target = tmp_path / "manifest.yml"
    target.write_text(yaml.safe_dump(effective))
    adoption = subject.ManifestAdoption("ready", "reuse", "fixture", target, target, effective)
    monkeypatch.setattr(subject, "_load_handoff", lambda *_a, **_k: {"components": list(PRODUCTS)})
    monkeypatch.setattr(subject, "_eligible_department_units", lambda *_a, **_k: ())
    monkeypatch.setattr(subject, "_layer_manifest", lambda *_a, **_k: copy.deepcopy(desired))
    monkeypatch.setattr(subject, "_manifest_adoption_plan", lambda *_a, **_k: adoption)

    def topology(manifest, **kwargs):
        assert manifest == effective
        return topology_rows(manifest, **kwargs)

    monkeypatch.setattr(subject, "_topology_report_layers", topology)
    return target, effective


def test_effective_adoption_drives_apply_topology_mirrors_and_pointers(effective_plan, tmp_path, monkeypatch):
    target, effective = effective_plan
    seen = []

    def consume(manifest, **_kwargs):
        assert manifest == effective
        seen.append("manifest")
        return []

    def apply(manifest, rows, **kwargs):
        consume(manifest)
        return True, None

    def pointers(path, knowledge, root):
        assert path == target
        assert knowledge == [r["source"]["path"] for r in effective["layers"] if r["product"] == "knowledge"]
        seen.append("pointers")

    monkeypatch.setattr(subject, "_apply_visible_topology", apply)
    result = subject.build_ecosystem_onboard_report(
        org="Acme", apply=True, run=no_external, manifest_path=target,
        repository_root=tmp_path / "generated",
        personal_fn=lambda **_: {"result": "ready", "owner": "author", "repositories": [], "summary": {}},
        ssh_fn=lambda **_: {"result": "ready"}, store_fn=lambda *_a, **_k: {"result": "ready"},
        codex_fn=lambda **_: {"result": "ready"}, cli_fn=lambda *_: {"result": "ready"},
        consumer_probe_fn=lambda *_: {"result": "ready"},
        update_fn=lambda **_: ({"result": "up-to-date", "blocked": [], "held_for_approval": []}, 0),
        doctor_fn=lambda **_: {"status": "healthy", "score": 100},
        resolve_fn=lambda **_: {"items": [{"id": "fixture"}]},
        mirror_seed_fn=consume, personal_mirror_cleanup_fn=consume, commit_config_fn=pointers,
    )
    assert result["result"] == "ready"
    assert seen.count("manifest") == 3
    assert "pointers" in seen


def test_shared_refresh_uses_effective_pinned_manifest(effective_plan, tmp_path, monkeypatch):
    target, _ = effective_plan
    monkeypatch.setattr(subject, "_owner", lambda **_: "author")
    monkeypatch.setattr(subject, "resolve_key", lambda key: str(target) if key == "layers.manifest" else None)
    before = target.read_bytes()
    result = subject.build_shared_repository_refresh_report(
        org="Acme", products=PRODUCTS, run=no_external, repository_root=tmp_path / "generated"
    )
    assert result["result"] == "ready"
    assert target.read_bytes() == before


@pytest.fixture
def central_marketplace(isolated_home, monkeypatch):
    from cc.core.release.codex import config, marketplace, step
    from cc.core.release.engine import layout, schema

    release = layout.release_dir("20261107T120000Z-fixture")
    release.mkdir(parents=True)
    components = []
    for name in layout.all_component_names():
        tier = name.partition("/")[2] or "foundation"
        kind = layout.KIND_LIVE if tier == "personal" else layout.KIND_SIGNED
        if name == layout.COMPONENT_CONTROL_TOWER:
            kind = layout.KIND_RECORD
        (release / name).mkdir(parents=True)
        components.append(schema.Component(name, tier, kind, "1.0.0", "v1.0.0", "a" * 40,
                                           "fixture-source", name, "fixture-signer"))
    names = ("codex-copilot", "codex-copilot-internal", "codex-copilot-accounting")
    for (component, _tier), name in zip(marketplace.PLUGIN_ROOTS, names):
        plugin = release / component / "plugins" / name
        (plugin / ".codex-plugin").mkdir(parents=True)
        (plugin / ".codex-plugin/plugin.json").write_text(json.dumps({"name": name, "version": "1.0.0"}))
        (plugin / "README.md").write_text(name)
    # Exercise the real publisher: its receipt includes declared trust metadata.
    receipt = marketplace.build_marketplace(release)
    manifest = schema.Manifest(release.name, "2026-11-07T12:00:00Z", None, tuple(components))
    manifest_path = release / layout.MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest.to_json()))
    layout.current_path().symlink_to(release)
    codex_home = isolated_home / ".codex"
    config.apply(codex_home, isolated_home, source=step.marketplace_source(), plugins=names)
    for plugin in receipt["plugins"]:
        shutil.copytree(release / layout.MARKETPLACE_DIRNAME / "plugins" / plugin["name"],
                        step.cache_dir(codex_home, plugin["name"], plugin["version"]))
    manifest_path.chmod(0o444)
    release.chmod(0o555)
    # The retired materialization root must never be touched in central mode.
    monkeypatch.setattr(subject, "resolve_key", lambda _key: str(isolated_home / "retired"))
    calls = []

    def run(args):
        calls.append(tuple(args))
        if tuple(args) == ("codex", "plugin", "marketplace", "list", "--json"):
            payload = {"marketplaces": [{"name": marketplace.MARKETPLACE_NAME,
                                         "root": str(layout.current_path() / layout.MARKETPLACE_DIRNAME)}]}
        elif tuple(args) == ("codex", "plugin", "list", "--json"):
            payload = {"installed": [{"pluginId": f"{name}@{marketplace.MARKETPLACE_NAME}",
                                      "installed": True, "enabled": True} for name in names]}
        else:
            raise AssertionError(f"Unexpected mutation command: {args}")
        return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")

    return release, names, run, calls


def file_snapshot(root):
    return {str(p.relative_to(root)): (p.stat().st_mode, p.read_bytes())
            for p in root.rglob("*") if p.is_file() and not p.is_symlink()}


@pytest.mark.parametrize("apply", (False, True))
def test_central_codex_keeps_all_three_plugins_without_writes(central_marketplace, isolated_home, apply):
    _release, names, run, calls = central_marketplace
    before = file_snapshot(isolated_home)
    result = subject._install_codex_plugin(apply=apply, run=run)
    assert result["result"] == "ready", result
    assert set(result["plugins"]) == set(names)
    assert len(calls) == 2
    assert file_snapshot(isolated_home) == before


@pytest.mark.parametrize("change", ("receipt-omission", "document-omission", "cache-drift"))
def test_incomplete_central_codex_holds_without_rewriting(central_marketplace, isolated_home, change):
    from cc.core.release.codex import marketplace, step
    from cc.core.release.engine import layout

    release, names, run, _calls = central_marketplace
    root = release / layout.MARKETPLACE_DIRNAME
    if change == "cache-drift":
        (step.cache_dir(isolated_home / ".codex", names[-1], "1.0.0") / "README.md").write_text("drift")
    else:
        target = root / (marketplace.RECEIPT_NAME if change == "receipt-omission" else marketplace.MANIFEST_RELATIVE)
        data = json.loads(target.read_text())
        data["plugins"] = data["plugins"][:-1]
        target.write_text(json.dumps(data))
    before = file_snapshot(isolated_home)
    result = subject._install_codex_plugin(apply=True, run=run)
    assert result["result"] == "blocked", result
    assert file_snapshot(isolated_home) == before


def test_missing_canonical_manifest_with_active_release_holds(central_marketplace, isolated_home):
    target = isolated_home / ".config/copilot/copilot.layers.yml"
    result = subject._manifest_adoption_plan(generated(isolated_home / "sources"), target)
    assert result.action == "review"
    assert result.payload is None
    assert not target.exists()


@pytest.fixture
def retained_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("CC_RETAIN_SCRATCH", "1")
    # Deny baseline deletion before it occurs; the fixed code must archive by rename.
    def denied_unlink(path, *_args, **_kwargs):
        raise AssertionError(f"Retention attempted deletion: {path}")
    monkeypatch.setattr(Path, "unlink", denied_unlink)
    payload = generated(tmp_path / "sources")
    return payload


def test_retained_candidate_survives_failed_consumer_probe(retained_manifest, tmp_path, monkeypatch):
    from contextlib import contextmanager

    directories = []
    @contextmanager
    def refuse_cleanup(**_kwargs):
        # Baseline uses TemporaryDirectory: preserve its evidence, then fail the contract.
        directory = tmp_path / "baseline-candidate"
        directory.mkdir()
        yield str(directory)
        raise AssertionError("Retention invoked temporary-directory cleanup")
    monkeypatch.setattr(subject.tempfile, "TemporaryDirectory", refuse_cleanup)
    adoption = subject.ManifestAdoption("changes-required", "create", "fixture", None,
                                       tmp_path / "new.yml", retained_manifest)
    def probe(candidate, source):
        directories.append(candidate)
        assert source is None
        return {"result": "blocked", "detail": "consumer rejected"}
    result = subject._validate_manifest_candidate(adoption, probe)
    assert result["result"] == "blocked"
    assert len(directories) == 1 and directories[0].is_file()
    assert yaml.safe_load(directories[0].read_text()) == retained_manifest


def test_retained_migration_and_rollback_preserve_exact_bytes(retained_manifest, tmp_path):
    source, destination = tmp_path / "legacy.yml", tmp_path / "canonical.yml"
    before = b"# original owner formatting\nversion: 1\nlayers: []\n"
    source.write_bytes(before)
    adoption = subject.ManifestAdoption("changes-required", "migrate", "fixture", source,
                                       destination, retained_manifest)
    backup = subject._apply_manifest_adoption(adoption)
    candidate = destination.read_bytes()
    assert backup.read_bytes() == before
    assert not source.exists()
    assert [p.read_bytes() for p in tmp_path.glob(".legacy.yml.retained-*/legacy.yml")] == [before]
    assert subject._rollback_manifest_adoption(adoption, backup)
    assert source.read_bytes() == before and not destination.exists()
    assert [p.read_bytes() for p in tmp_path.glob(".canonical.yml.retained-*/canonical.yml")] == [candidate]


def test_retained_rollback_refuses_concurrent_edits(retained_manifest, tmp_path):
    destination = tmp_path / "new.yml"
    adoption = subject.ManifestAdoption("changes-required", "create", "fixture", None,
                                       destination, retained_manifest)
    subject._apply_manifest_adoption(adoption)
    destination.write_text("owner concurrent edit")
    assert not subject._rollback_manifest_adoption(adoption, None)
    assert destination.read_text() == "owner concurrent edit"


def test_legacy_custom_marketplace_is_held_without_overwrite(tmp_path, monkeypatch):
    root = tmp_path / "legacy-marketplace"
    plugin = root / "plugins/codex-copilot/.codex-plugin/plugin.json"
    plugin.parent.mkdir(parents=True)
    plugin.write_text(json.dumps({"name": "codex-copilot", "version": "1.0.0"}))
    marketplace = root / ".agents/plugins/marketplace.json"
    marketplace.parent.mkdir(parents=True)
    marketplace.write_text(json.dumps({"name": "owner-custom", "plugins": []}))
    monkeypatch.setattr(subject, "resolve_key", lambda _key: str(root))
    before = file_snapshot(root)
    # Prevent the legacy baseline from discarding original bytes before failure.
    original_replace = subject.os.replace
    def deny_marketplace_replace(source, target):
        assert Path(target) != marketplace, "custom marketplace overwrite attempted"
        return original_replace(source, target)
    monkeypatch.setattr(subject.os, "replace", deny_marketplace_replace)
    result = subject._install_codex_plugin(apply=True, run=no_external)
    assert result["result"] == "blocked"
    assert file_snapshot(root) == before


@pytest.mark.parametrize("change", ("duplicate", "unknown", "non-list", "extra-key", "legitimate-subset"))
def test_central_codex_trust_provenance_is_bounded(central_marketplace, isolated_home, change):
    from cc.core.release.codex import marketplace
    from cc.core.release.engine import layout

    release, names, run, _calls = central_marketplace
    receipt = release / layout.MARKETPLACE_DIRNAME / marketplace.RECEIPT_NAME
    payload = json.loads(receipt.read_text())
    if change == "duplicate":
        payload["retrust"] = [names[0], names[0]]
    elif change == "unknown":
        payload["trustContentChanged"] = ["unknown-plugin"]
    elif change == "non-list":
        payload["retrust"] = names[0]
    elif change == "extra-key":
        payload["owner_customization"] = True
    else:
        payload["retrust"] = [names[1]]
        payload["trustContentChanged"] = [names[1]]
    receipt.write_text(json.dumps(payload))
    before = file_snapshot(isolated_home)
    result = subject._install_codex_plugin(apply=True, run=run)
    assert result["result"] == ("ready" if change == "legitimate-subset" else "blocked"), result
    assert file_snapshot(isolated_home) == before


def test_single_declared_department_without_rank_uses_default_twenty(tmp_path):
    handoff = {
        "foundation": {"refs": {product: "v1.2.3" for product in PRODUCTS}},
        "departments": [{"unit": "accounting"}],
    }
    actual = generated(tmp_path, departments=("accounting",), handoff=handoff)
    validate_layers(actual["layers"])
    departments = [row for row in actual["layers"] if row["role"] == "department"]
    assert len(departments) == len(PRODUCTS)
    assert all(row["unit"] == "accounting" and row["rank"] == 20 for row in departments)
