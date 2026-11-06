"""Trust gate against real `hooks/list` payloads captured from Codex 0.167.0 (read-only, 2026-11-06)."""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from cc.core.release.codex import trust_gate

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> list:
    return json.loads((FIXTURES / name).read_text())


def lister_for(live: list, candidate: list):
    def lister(_bin, codex_home, _cwd):
        return candidate if "trust-gate" in str(codex_home) else live
    return lister


def ok_runner(cmd, env):
    return subprocess.CompletedProcess(cmd, 0, "", "")


def gate(tmp_path, live, candidate, **kw):
    release = tmp_path / "rel"
    release.mkdir(exist_ok=True)
    return trust_gate.check(release, None, tmp_path / "codex", runner=ok_runner,
                            lister=lister_for(live, candidate), **kw)


def per_hook_content(hooks: list) -> list:
    """The shape the sandbox reported in round 6: a distinct content value per hook."""
    out = copy.deepcopy(hooks)
    for h in out:
        per_hook, _, _ = h["currentHash"].partition("/")
        h["currentHash"] = f"{per_hook}/sha256:{per_hook.removeprefix('sha256:')}"
    return out


def test_fixtures_carry_six_distinct_per_hook_hashes():
    live = load("hooks_list_live_codex_0.167.0.json")
    assert len(live) == 6 and len({h["currentHash"] for h in live}) == 6


def test_real_payload_unchanged_plugin_passes_with_accurate_warning(tmp_path):
    live = load("hooks_list_live_codex_0.167.0.json")
    live[0]["trustStatus"] = "trusted"  # WP-319: the guard is trusted, the other 5 are modified
    result = gate(tmp_path, live, load("hooks_list_candidate_codex_0.167.0.json"))
    (warning,) = result.warnings
    assert "5 of 6" in warning and "1 trusted" in warning
    assert "pre_tool_use:1:0 modified" in warning and "subagent_start:0:0 modified" in warning
    assert "pre_tool_use:0:0 modified" not in warning


def test_distinct_per_hook_content_values_compare_by_key(tmp_path):
    live = per_hook_content(load("hooks_list_live_codex_0.167.0.json"))
    candidate = per_hook_content(load("hooks_list_candidate_codex_0.167.0.json"))
    assert gate(tmp_path, live, candidate).candidate_hash  # six distinct values, none changed: no refusal


@pytest.mark.parametrize("shape", [lambda x: x, per_hook_content])
def test_one_changed_hook_refuses_and_names_it(tmp_path, shape):
    live = shape(load("hooks_list_live_codex_0.167.0.json"))
    candidate = shape(load("hooks_list_candidate_codex_0.167.0.json"))
    candidate[2]["currentHash"] = "sha256:aaaa/sha256:" + "f" * 64
    with pytest.raises(trust_gate.TrustGateError, match=r"post_tool_use:0:0"):
        gate(tmp_path, live, candidate)


def test_dropped_hook_refuses(tmp_path):
    live = load("hooks_list_live_codex_0.167.0.json")
    with pytest.raises(trust_gate.TrustGateError, match="subagent_start:0:0"):
        gate(tmp_path, live, load("hooks_list_candidate_codex_0.167.0.json")[:-1])


def test_non_strict_change_is_a_warning(tmp_path):
    live = load("hooks_list_live_codex_0.167.0.json")
    candidate = load("hooks_list_candidate_codex_0.167.0.json")
    candidate[0]["currentHash"] = "sha256:aaaa/sha256:" + "f" * 64
    result = gate(tmp_path, live, candidate, strict=False)
    assert any("pre_tool_use:0:0" in w and "non-strict" in w for w in result.warnings)
