"""Native event shape and feedback boundaries; scoped tests authorized by owner."""
import importlib
import json

import pytest

module = importlib.import_module("cc.core.design.feedback")
PATCH = "*** Begin Patch\n*** Add File: surface.html\n+<button>Continue</button>\n*** End Patch"


@pytest.mark.parametrize("field", ["command", "input", "patch"])
def test_codex_patch_event_fields(field):
    assert module._event_targets({"tool_name": "apply_patch", "tool_input": {field: PATCH}}, "codex") == ["surface.html"]


def test_feedback_native_command_deduplication_and_failure_boundary(tmp_path, monkeypatch):
    state = tmp_path / ".copilot"
    state.mkdir()
    (state / "design-feedback.json").write_text(json.dumps({"runtimes": {"codex": True}}))
    surface = tmp_path / "surface.html"
    surface.write_text("<button>Continue</button>")
    calls = []
    pin = {"sha256": "first-pin"}
    def audit(root, targets, timeout):
        calls.append((targets, timeout))
        return {"status": "completed", "findings": []}
    monkeypatch.setattr(module, "tool_status", lambda: pin)
    monkeypatch.setattr(module, "audit", audit)
    event = {"hook_event_name": "PostToolUse", "session_id": "native-1", "tool_name": "apply_patch", "tool_input": {"command": PATCH}}
    assert module.feedback(tmp_path, event, "codex") is None
    assert len(calls) == 1
    assert module.feedback(tmp_path, event, "codex") is None
    assert len(calls) == 1
    surface.write_text("<button>Changed</button>")
    module.feedback(tmp_path, event, "codex")
    assert len(calls) == 2
    pin["sha256"] = "second-pin"
    module.feedback(tmp_path, event, "codex")
    assert len(calls) == 3
    module.feedback(tmp_path, {**event, "session_id": "native-2"}, "codex")
    assert len(calls) == 4
    assert all(timeout == 2 for _, timeout in calls)
    monkeypatch.setattr(module, "audit", lambda *args, **kwargs: {"status": "timeout"})
    failed = module.feedback(tmp_path, {**event, "session_id": "native-failure"}, "codex")
    assert set(failed) == {"hookSpecificOutput"}
    assert set(failed["hookSpecificOutput"]) == {"hookEventName", "additionalContext"}
    assert "No approval granted" in failed["hookSpecificOutput"]["additionalContext"]
    assert len(list((state / "design-feedback").glob("*.json"))) == 2
    assert not (state / "tasks.db").exists()
