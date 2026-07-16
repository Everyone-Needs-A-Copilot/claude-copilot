"""Tests for cc.core.ecosystem.ecosystem_config — a READ-ONLY reader for
the org's inherited `ecosystem.yml`.

Every case is exercised against an explicit `tmp_path` file (or an
in-memory dict) — never a real ~/.claude or ~/.copilot. `load_ecosystem_config()`
/ `github_client_id()` / `departments()` never touch `Path.home()` when
given explicit input, which is all these tests ever supply.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cc.core.ecosystem.ecosystem_config import (
    departments,
    ecosystem_config_path,
    github_client_id,
    load_ecosystem_config,
)


@pytest.fixture(autouse=True)
def _no_real_home(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError(
            "ecosystem_config test attempted to resolve Path.home() -- "
            "inject tmp_path instead"
        )

    monkeypatch.setattr(Path, "home", staticmethod(_boom))


# ---------------------------------------------------------------------------
# ecosystem_config_path()
# ---------------------------------------------------------------------------


def test_ecosystem_config_path_injected_none_returns_none():
    assert ecosystem_config_path(_path=None) is None


def test_ecosystem_config_path_injected_path_is_expanded(tmp_path):
    target = tmp_path / "ecosystem.yml"
    assert ecosystem_config_path(_path=target) == target


# ---------------------------------------------------------------------------
# load_ecosystem_config()
# ---------------------------------------------------------------------------


def test_load_ecosystem_config_missing_file_returns_empty_dict(tmp_path):
    missing = tmp_path / "ecosystem.yml"
    assert load_ecosystem_config(missing) == {}


def test_load_ecosystem_config_reads_real_yaml(tmp_path):
    config_path = tmp_path / "ecosystem.yml"
    config_path.write_text(
        """
github_app:
  client_id: Iv1.abcdef1234567890
departments:
  - id: finance
    name: Finance
    repo: org/dept-finance-copilot
  - id: engineering
    name: Engineering
    repo: org/dept-engineering-copilot
""",
        encoding="utf-8",
    )

    cfg = load_ecosystem_config(config_path)
    assert cfg["github_app"]["client_id"] == "Iv1.abcdef1234567890"
    assert len(cfg["departments"]) == 2


def test_load_ecosystem_config_malformed_yaml_returns_empty_dict_not_raise(tmp_path):
    config_path = tmp_path / "ecosystem.yml"
    config_path.write_text("github_app: [unclosed", encoding="utf-8")

    assert load_ecosystem_config(config_path) == {}


def test_load_ecosystem_config_non_mapping_yaml_returns_empty_dict(tmp_path):
    config_path = tmp_path / "ecosystem.yml"
    config_path.write_text("- a\n- b\n", encoding="utf-8")

    assert load_ecosystem_config(config_path) == {}


def test_load_ecosystem_config_never_writes(tmp_path):
    missing = tmp_path / "ecosystem.yml"
    load_ecosystem_config(missing)
    assert not missing.exists()


# ---------------------------------------------------------------------------
# github_client_id()
# ---------------------------------------------------------------------------


def test_github_client_id_present():
    cfg = {"github_app": {"client_id": "Iv1.deadbeef"}}
    assert github_client_id(cfg) == "Iv1.deadbeef"


def test_github_client_id_missing_returns_none():
    assert github_client_id({}) is None


def test_github_client_id_malformed_github_app_returns_none():
    assert github_client_id({"github_app": "not-a-dict"}) is None


def test_github_client_id_empty_string_returns_none():
    assert github_client_id({"github_app": {"client_id": ""}}) is None


# ---------------------------------------------------------------------------
# departments()
# ---------------------------------------------------------------------------


def test_departments_present():
    cfg = {
        "departments": [
            {"id": "finance", "name": "Finance", "repo": "org/dept-finance-copilot"},
            {"id": "engineering", "name": "Engineering", "repo": "org/dept-eng-copilot"},
        ]
    }
    result = departments(cfg)
    assert len(result) == 2
    assert result[0]["id"] == "finance"


def test_departments_missing_returns_empty_list():
    assert departments({}) == []


def test_departments_non_list_returns_empty_list():
    assert departments({"departments": "not-a-list"}) == []


def test_departments_drops_non_dict_entries():
    cfg = {"departments": [{"id": "finance"}, "garbage", 42]}
    result = departments(cfg)
    assert result == [{"id": "finance"}]


# ---------------------------------------------------------------------------
# end-to-end: tmp ecosystem.yml -> client id + departments
# ---------------------------------------------------------------------------


def test_end_to_end_tmp_file_to_client_id_and_departments(tmp_path):
    config_path = tmp_path / "ecosystem.yml"
    config_path.write_text(
        """
github_app:
  client_id: Iv1.end2end
departments:
  - id: finance
    name: Finance
    repo: org/dept-finance-copilot
""",
        encoding="utf-8",
    )

    cfg = load_ecosystem_config(config_path)
    assert github_client_id(cfg) == "Iv1.end2end"
    assert departments(cfg) == [
        {"id": "finance", "name": "Finance", "repo": "org/dept-finance-copilot"}
    ]
