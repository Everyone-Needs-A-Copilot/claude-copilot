"""Defect-level controls for the independent central-resolution audit."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from cc.core.project_migrate.rollback import rollback_migration
from cc.core.project_migrate.framework_index import FrameworkIndex
from cc.core.project_migrate.known import Known
from cc.core.project_migrate.classify import classify
from cc.core.release import publish as publisher
from cc.core.release.codex import config, marketplace, step
from cc.core.release.engine import layout, pointer, schema, doctor
from cc.core.release.links import LinkPlan, write_plan

OLD = '20261107T000000Z-aaaaaaaaaaaa'
NEW = '20261107T000001Z-bbbbbbbbbbbb'


def _backup(tmp_path, rel='scripts/helper.sh', backup_rel='original'):
    project = tmp_path / 'project'; project.mkdir()
    backup = tmp_path / 'backup'; backup.mkdir()
    data = b'original framework bytes\n'
    (backup / 'original').write_bytes(data)
    manifest = {'project': str(project), 'status': 'applied', 'entries': [
        {'path': rel, 'kind': 'deleted', 'backup': backup_rel,
         'sha_before': 'sha256:' + hashlib.sha256(data).hexdigest(), 'mode': 0o755}]}
    (backup / 'manifest.json').write_text(json.dumps(manifest))
    return project, backup, data


def test_restore_rejects_changed_ancestor(tmp_path):
    project, backup, _ = _backup(tmp_path)
    outside = tmp_path / 'outside'; outside.mkdir()
    (project / 'scripts').symlink_to(outside, target_is_directory=True)
    result = rollback_migration(backup)
    assert result['conflicts']
    assert not (outside / 'helper.sh').exists()
    assert json.loads((backup / 'manifest.json').read_text())['status'] == 'applied'


def test_restore_preserves_bytes_and_mode(tmp_path):
    project, backup, data = _backup(tmp_path)
    result = rollback_migration(backup)
    assert result['conflicts'] == []
    assert (project / 'scripts/helper.sh').read_bytes() == data
    assert (project / 'scripts/helper.sh').stat().st_mode & 0o777 == 0o755


@pytest.mark.parametrize('field,value', [('path', '../escaped'), ('path', '/tmp/absolute-escape'),
                                       ('backup', '../outside-backup'), ('backup', 'linked')])
def test_restore_rejects_uncontained_receipt(tmp_path, field, value):
    project, backup, data = _backup(tmp_path)
    (tmp_path / 'outside-backup').write_bytes(data)
    (backup / 'linked').symlink_to(tmp_path / 'outside-backup')
    record = json.loads((backup / 'manifest.json').read_text())
    record['entries'][0][field] = value
    (backup / 'manifest.json').write_text(json.dumps(record))
    assert rollback_migration(backup)['conflicts']
    assert not (project / 'scripts/helper.sh').exists()
    assert not (tmp_path / 'escaped').exists()


def test_restore_parent_swap_cannot_redirect_write(tmp_path, monkeypatch):
    project, backup, data = _backup(tmp_path)
    (project / 'scripts').mkdir()
    outside = tmp_path / 'outside'; outside.mkdir()
    replace = os.replace
    def swap(src, dst, **kw):
        if dst == 'helper.sh':
            (project / 'scripts').rename(project / 'original-scripts')
            (project / 'scripts').symlink_to(outside, target_is_directory=True)
        return replace(src, dst, **kw)
    monkeypatch.setattr(os, 'replace', swap)
    result = rollback_migration(backup)
    assert not (outside / 'helper.sh').exists()
    assert (project / 'original-scripts/helper.sh').read_bytes() == data
    assert result['conflicts']


def test_only_authenticated_release_trees_authorize_copies(tmp_path, monkeypatch):
    from cc.core.ecosystem import policy
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', '/dev/null')
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    repo = tmp_path / 'repo'; repo.mkdir()
    key = tmp_path / 'signer'
    subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)], check=True)
    public = key.with_suffix('.pub').read_text().strip()
    fingerprint = subprocess.check_output(['ssh-keygen', '-lf', str(key.with_suffix('.pub'))], text=True).split()[1]
    monkeypatch.setattr(policy, 'FOUNDATION_SSH_SIGNING_KEYS', {fingerprint: public})
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), '-c', 'core.hooksPath=/dev/null',
            '-c', 'commit.gpgsign=false', '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid',
            *args], text=True, stderr=subprocess.PIPE).strip()
    git('init', '-q', '-b', 'main')
    (repo / 'scripts').mkdir(); (repo / 'scripts/released.sh').write_text('released bytes\n')
    git('add', '.'); git('commit', '-qm', 'released')
    git('-c', 'gpg.format=ssh', '-c', f'user.signingkey={key}', 'tag', '-s', 'v1', '-m', 'release')
    # An intermediate main commit also was never a released tree.
    (repo / 'scripts/intermediate.sh').write_text('intermediate bytes\n')
    git('add', '.'); git('commit', '-qm', 'intermediate')
    git('checkout', '-b', 'experiment')
    (repo / 'scripts/experiment.sh').write_text('experimental bytes\n')
    git('add', '.'); git('commit', '-qm', 'experiment')
    git('tag', 'unsigned-experiment')
    index = FrameworkIndex(); index.add_git_history(repo)
    project = tmp_path / 'project'; (project / 'scripts').mkdir(parents=True)
    for name in ('released', 'intermediate', 'experiment'):
        shutil.copyfile(repo / f'scripts/{name}.sh', project / f'scripts/{name}.sh')
    known = Known({}, {}, {}, framework_index=index)
    assert classify(project, 'scripts/released.sh', known)[0] == 'delete'
    assert classify(project, 'scripts/intermediate.sh', known) is None
    assert classify(project, 'scripts/experiment.sh', known) is None
    # Explicit project ownership remains a separate hard veto.
    owned = project / 'scripts/owned.md'; owned.write_text('---\nowner: project\n---\nowned\n')
    from cc.core.project_migrate.framework_index import blob_id
    index.add(blob_id(owned.read_bytes()), owned.name, False)
    assert classify(project, 'scripts/owned.md', known)[0] == 'keep-owner'


def _releases(tmp_path):
    home = tmp_path / 'home'; ch = home / '.codex'; ch.mkdir(parents=True)
    before = b'# owner comment\n[plugins."old@codex-copilot-local"]\nenabled = true\n'
    (ch / 'config.toml').write_bytes(before)
    for rid in (OLD, NEW):
        root = layout.release_dir(rid, home); root.mkdir(parents=True)
        comps = tuple(schema.Component(n, 'framework', 'record', '1', 'v1', 'a'*40, 'fixture', '')
                      for n in layout.all_component_names())
        manifest = schema.Manifest(rid, '2026-11-07T00:00:00Z', None, comps)
        (root / layout.MANIFEST_NAME).write_text(json.dumps(manifest.to_json()))
        write_plan(LinkPlan(rid, agents_block='fixture framework'), root)
        mp = root / layout.MARKETPLACE_DIRNAME
        plugin = mp / 'plugins/codex-copilot'; plugin.mkdir(parents=True)
        (plugin / 'marker').write_text(rid)
        (mp / marketplace.RECEIPT_NAME).write_text(json.dumps({'schema': 1, 'plugins': [
            {'name': 'codex-copilot', 'version': rid, 'digest': marketplace.tree_digest(plugin)}]}))
    pointer.flip(OLD, home)
    return home, ch, before


@pytest.mark.parametrize('failure', ['refresh', 'cache', 'doctor'])
def test_publish_restores_owned_configuration_on_failure(tmp_path, monkeypatch, failure):
    home, ch, before = _releases(tmp_path)
    monkeypatch.setattr(publisher.build, 'build_release', lambda *a, **k: schema.load(layout.release_dir(NEW, home)))
    monkeypatch.setattr(publisher.trust_gate, 'check', lambda *a, **k: SimpleNamespace(to_json=lambda: {}))
    def runner(argv, env):
        if failure == 'refresh':
            return subprocess.CompletedProcess(argv, 7, '', 'injected failure')
        if failure == 'doctor':
            src = layout.current_path(home) / layout.MARKETPLACE_DIRNAME / 'plugins/codex-copilot'
            dest = step.cache_dir(ch, 'codex-copilot', NEW)
            shutil.copytree(src, dest, dirs_exist_ok=True)
        return subprocess.CompletedProcess(argv, 0, '', '')
    monkeypatch.setattr(publisher, 'run_doctor', lambda *a, **k: [doctor.Check('injected', False, 'failure')])
    with pytest.raises(publisher.PublishError) as caught:
        publisher.publish([], home, ch, codex_runner=runner)
    assert caught.value.restored
    assert pointer.current_release_id(home) == OLD
    assert (ch / 'config.toml').read_bytes() == before


def test_config_receipt_failure_leaves_configuration_unchanged(tmp_path, monkeypatch):
    home, ch, before = _releases(tmp_path)
    write = config._atomic_write
    def fail_receipt(path, data):
        if path == config.receipt_path(home):
            raise OSError('receipt storage unavailable')
        write(path, data)
    monkeypatch.setattr(config, '_atomic_write', fail_receipt)
    with pytest.raises(OSError):
        config.apply(ch, home, source='fixture', plugins=['codex-copilot'])
    assert (ch / 'config.toml').read_bytes() == before


@pytest.mark.parametrize('fail', [True, False])
def test_explicit_rollback_refreshes_validates_and_recovers(tmp_path, monkeypatch, fail):
    home, ch, before = _releases(tmp_path)
    pointer.flip(NEW, home)
    original_history = pointer.read_history(home)
    calls = []; checks = []
    def runner(argv, env):
        rid = pointer.current_release_id(home); calls.append(rid)
        if fail and rid == OLD:
            return subprocess.CompletedProcess(argv, 7, '', 'refresh failed')
        src = layout.current_path(home) / layout.MARKETPLACE_DIRNAME / 'plugins/codex-copilot'
        shutil.copytree(src, step.cache_dir(ch, 'codex-copilot', rid), dirs_exist_ok=True)
        return subprocess.CompletedProcess(argv, 0, '', '')
    def check(*args, **kwargs):
        rid = pointer.current_release_id(home); checks.append(rid)
        return step.doctor_checks(ch, home)(layout.release_dir(rid, home))
    monkeypatch.setattr(publisher, 'run_doctor', check)
    if fail:
        with pytest.raises(pointer.PointerError):
            publisher.rollback(home, ch, to=OLD, codex_runner=runner)
        assert pointer.current_release_id(home) == NEW
        assert pointer.read_history(home) == original_history
        assert (ch / 'config.toml').read_bytes() == before
        assert NEW in checks
    else:
        result = publisher.rollback(home, ch, to=OLD, codex_runner=runner)
        assert result['release'] == OLD
        assert pointer.current_release_id(home) == OLD
        assert checks == [OLD]
        assert not step.verify_cache(ch, marketplace.load_receipt(layout.release_dir(OLD, home)))
    assert OLD in calls


def test_signed_tree_verifier_preserves_subtree_and_root_binding(tmp_path, monkeypatch):
    """Use the real signed fixture from the classification control for both APIs."""
    test_only_authenticated_release_trees_authorize_copies(tmp_path, monkeypatch)
    from cc.core.ecosystem import policy
    repo = tmp_path / 'repo'
    root = policy.verify_git_tree_release(repo, '.', tuple(policy.FOUNDATION_SSH_SIGNING_KEYS), ref='refs/tags/v1')
    subtree = policy.verify_git_tree_release(repo, 'scripts', tuple(policy.FOUNDATION_SSH_SIGNING_KEYS), ref='refs/tags/v1')
    assert root and subtree
    assert root.release.commit == subtree.release.commit
    assert root.tree == root.release.tree
    assert root.tree != subtree.tree
    assert policy.verify_git_tree_release(repo, '../scripts', tuple(policy.FOUNDATION_SSH_SIGNING_KEYS), ref='refs/tags/v1') is None
