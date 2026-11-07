"""Codex trust gate: publish asks Codex's own hooks/list and refuses a flip that would change plugin trust."""

from __future__ import annotations

import json

import pytest

from cc.core.release import publish as publisher
from cc.core.release.codex import marketplace, trust_gate
from cc.core.release.engine import build, layout, pointer

from .test_publish import _extractor, ct_app, sources  # noqa: F401  (fixtures)

PLUGIN_ID = f"codex-copilot@{marketplace.MARKETPLACE_NAME}"


def hook(content: str, status: str = "trusted", plugin: str = PLUGIN_ID) -> dict:
    return {"pluginId": plugin, "trustStatus": status, "key": f"{plugin}:hooks/hooks.json:pre_tool_use:0:0",
            "currentHash": f"sha256:aaaa/sha256:{content}"}


class Lister:
    """Stands in for `codex app-server hooks/list`: the live home reports `live`, a temp candidate home `cand`."""

    def __init__(self, live, cand):
        self.live, self.cand, self.calls = live, cand, []

    def __call__(self, codex_bin, codex_home, cwd):
        self.calls.append(str(codex_home))
        return self.cand if "trust-gate" in str(codex_home) else self.live


def run(sources, home, codex_home, fake_codex, ct_app, lister, **kw):
    return publisher.publish(
        sources, home, codex_home, venv=False, codex_bin=fake_codex, control_tower_app=ct_app,
        verifier=lambda s: build.VerifiedTag("a" * 40, "SHA256:test"), extractor=_extractor,
        hooks_lister=lister, **kw)


def test_refuses_flip_when_content_hash_would_change(home, codex_home, fake_codex, sources, ct_app, monkeypatch):
    monkeypatch.setenv("FAKE_UPGRADE", "ok")
    first = run(sources, home, codex_home, fake_codex, ct_app, Lister([hook("c1")], [hook("c1")]))
    import time; time.sleep(1.1)
    with pytest.raises(publisher.PublishError) as caught:
        run(sources, home, codex_home, fake_codex, ct_app, Lister([hook("c1")], [hook("c2")]))
    assert caught.value.step == "trust-gate" and caught.value.restored
    assert "content hash" in str(caught.value)
    assert pointer.current_release_id(home) == first.release_id  # nothing flipped


def test_stale_trust_entries_warn_but_do_not_block(home, codex_home, fake_codex, sources, ct_app, monkeypatch):
    monkeypatch.setenv("FAKE_UPGRADE", "ok")
    live = [hook("c1", "modified"), hook("c1", "untrusted")]
    report = run(sources, home, codex_home, fake_codex, ct_app, Lister(live, [hook("c1")]))
    assert report.flipped
    assert any("modified" in w and "owner" in w for w in report.trust["warnings"])


def test_never_writes_trust_entries(home, codex_home, fake_codex, sources, ct_app, monkeypatch):
    monkeypatch.setenv("FAKE_UPGRADE", "ok")
    run(sources, home, codex_home, fake_codex, ct_app, Lister([hook("c1", "modified")], [hook("c1")]))
    text = (codex_home / "config.toml").read_text()
    assert "trusted_hash" not in text and "trusted_content_hash" not in text


def test_plugin_dir_not_identical_to_frozen_core_is_refused(tmp_path):
    current = tmp_path / "cur" / "codex-marketplace"
    cand = tmp_path / "cand" / "codex-marketplace"
    for root, body in ((current, "a"), (cand, "b")):
        (root / "plugins" / "codex-copilot").mkdir(parents=True)
        (root / "plugins" / "codex-copilot" / "f").write_text(body)
    receipt = {"plugins": [{"name": "codex-copilot", "digest": marketplace.tree_digest(
        current / "plugins" / "codex-copilot")}]}
    with pytest.raises(trust_gate.TrustGateError, match="byte-identical"):
        trust_gate.assert_frozen_core(cand, receipt)


def test_listing_failure_fails_closed(home, codex_home, fake_codex, sources, ct_app, monkeypatch):
    monkeypatch.setenv("FAKE_UPGRADE", "ok")
    run(sources, home, codex_home, fake_codex, ct_app, Lister([hook("c1")], [hook("c1")]))
    import time; time.sleep(1.1)

    def broken(*_a):
        raise trust_gate.TrustGateError("codex app-server did not answer hooks/list")
    with pytest.raises(publisher.PublishError) as caught:
        run(sources, home, codex_home, fake_codex, ct_app, broken)
    assert caught.value.step == "trust-gate" and "hooks/list" in str(caught.value)
