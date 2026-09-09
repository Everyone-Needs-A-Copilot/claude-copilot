import json
from pathlib import Path

import pytest

from cc.core.enforcement import evaluate

RULES = Path(__file__).resolve().parents[3] / ".claude/hooks/security-rules.json"


@pytest.mark.parametrize("command,decision", [("git status", "allow"), ("rm -rf /fixture", "deny"),
                                               ("git push origin --force", "deny"), ("DROP TABLE fixture", "deny")])
def test_shared_rules(command, decision):
    result = evaluate({"schema_version": 1, "operation": "shell", "command": command}, RULES)
    assert result["decision"] == decision
    assert len(result["policy_sha256"]) == 64


def test_warning_mode_is_explicit():
    assert evaluate({"schema_version": 1, "operation": "shell", "command": "rm -rf /fixture"},
                    RULES, destructive_action="warn")["decision"] == "warn"


@pytest.mark.parametrize("payload", [None, {}, {"schema_version": 2},
                                     {"schema_version": 1, "operation": "patch", "command": "x"},
                                     {"schema_version": 1, "operation": "shell", "command": None}])
def test_invalid_requests_never_allow(payload):
    with pytest.raises(ValueError):
        evaluate(payload, RULES)


def test_missing_policy_errors(tmp_path):
    with pytest.raises(OSError):
        evaluate({"schema_version": 1, "operation": "shell", "command": "git status"}, tmp_path / "missing")


def test_cli_errors_do_not_echo_payload(runner):
    from cc.main import app
    result = runner.invoke(app, ["enforcement", "evaluate", "--rules", "/missing-policy", "--json"],
                           input=json.dumps({"schema_version": 1, "operation": "shell", "command": "SECRET-CANARY"}))
    assert result.exit_code == 2
    assert json.loads(result.stdout)["decision"] == "error"
    assert "SECRET-CANARY" not in result.stdout
