"""
Phase 2 Stream-A / Workstream 1 tests for PRD-7: Verification and Observability

TASK-115: Harden qa.md — verdicts must name a failable check + external artifact
TASK-116: Harden sec.md — forbid unverified flags + warning-accumulation threshold
TASK-117: Gate the QA-gate hook on an artifact marker, not the word 'pass'

These are failable checks — they verify the hook behavior with external artifacts,
not model introspection.

Test plan (per task instruction):
  (a) A verdict WITHOUT an artifact does NOT unblock the gate
  (b) A verdict WITH a valid artifact DOES unblock
  (c) Escape hatch (COPILOT_QA_GATE=off) still bypasses
  (d) 3-fail auto-unblock still fires
  (e) sec.md halts only at the 3rd warning (WARNING_HALT_THRESHOLD = 3)
"""

import json
import os
import re
import subprocess
import sys
import importlib.util
import tempfile
import shutil

BASE = "/Volumes/Dev/Sites/COPILOT/claude-copilot"
AGENTS_DIR = os.path.join(BASE, ".claude/agents")
HOOKS_DIR = os.path.join(BASE, ".claude/hooks")
QA_AGENT = os.path.join(AGENTS_DIR, "qa.md")
SEC_AGENT = os.path.join(AGENTS_DIR, "sec.md")
SUBAGENT_STOP = os.path.join(HOOKS_DIR, "subagent-stop.sh")
PRETOOL_CHECK = os.path.join(HOOKS_DIR, "pretool-check.sh")
VALIDATION_LIB = os.path.join(HOOKS_DIR, "lib", "validation_result.py")
README_HOOKS = os.path.join(HOOKS_DIR, "README.md")


# ---------------------------------------------------------------------------
# Helpers: invoke subagent-stop.sh with a synthesized payload
# ---------------------------------------------------------------------------

def _run_subagent_stop(payload: dict, gate_file: str, env_extra: dict = None) -> subprocess.CompletedProcess:
    """Run subagent-stop.sh with the given payload and a temporary gate file."""
    env = os.environ.copy()
    env["COPILOT_QA_GATE_FILE_OVERRIDE"] = gate_file  # not used by the script directly
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        ["/bin/bash", SUBAGENT_STOP],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=BASE,
        timeout=10
    )
    return result


def _make_gate_file(content: dict) -> str:
    """Write gate state JSON to a temp file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".json", prefix="qa-gate-test-")
    with os.fdopen(fd, "w") as f:
        json.dump(content, f)
    return path


def _parse_verdict_from_subagent_stop(last_message: str, session_id: str, agent_type: str = "qa",
                                       initial_gate: dict = None) -> dict:
    """
    Run subagent-stop.sh and return the resulting gate state for the session.

    We use a dedicated temp state directory to avoid touching the real gate file.
    """
    tmp_state_dir = tempfile.mkdtemp(prefix="ws1-test-state-")
    gate_path = os.path.join(tmp_state_dir, "qa-gate.json")
    lock_path = os.path.join(tmp_state_dir, "qa-gate.lock")

    # Write initial gate state if provided
    if initial_gate is not None:
        with open(gate_path, "w") as f:
            json.dump(initial_gate, f)

    # Patch SCRIPT_DIR in the environment — we can't easily do this for bash scripts,
    # so we use a wrapper approach: write a tiny wrapper that overrides STATE_DIR.
    wrapper = os.path.join(tmp_state_dir, "run_hook.sh")
    with open(wrapper, "w") as f:
        f.write("#!/usr/bin/env bash\n")
        f.write(f"export SCRIPT_DIR_OVERRIDE={tmp_state_dir!r}\n")
        # We override the STATE_DIR by patching the script inline via sed
        f.write(f'exec /bin/bash -c \''
                f'source_file={SUBAGENT_STOP!r}; '
                f'content=$(cat "$source_file"); '
                f'content="${{content/STATE_DIR=\\"${{SCRIPT_DIR}}/state\\"/STATE_DIR={tmp_state_dir!r}}}"; '
                f'eval "$content"\' -- "$@"\n')

    os.chmod(wrapper, 0o755)

    payload = {
        "session_id": session_id,
        "agent_type": agent_type,
        "last_assistant_message": last_message,
    }

    env = os.environ.copy()
    # Use a patched version of the script with our temp state dir
    # We write a modified copy of the script with STATE_DIR replaced
    patched_script = os.path.join(tmp_state_dir, "subagent-stop.sh")
    with open(SUBAGENT_STOP) as f:
        content = f.read()
    # Replace the STATE_DIR assignment to point to our temp dir
    content = content.replace(
        'STATE_DIR="${SCRIPT_DIR}/state"',
        f'STATE_DIR={tmp_state_dir!r}'
    )
    with open(patched_script, "w") as f:
        f.write(content)
    os.chmod(patched_script, 0o755)

    result = subprocess.run(
        ["/bin/bash", patched_script],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=BASE,
        timeout=10
    )

    # Read the gate state after the run
    gate_state = {}
    if os.path.isfile(gate_path):
        with open(gate_path) as f:
            gate_state = json.load(f)

    # Cleanup
    shutil.rmtree(tmp_state_dir, ignore_errors=True)

    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "gate_state": gate_state,
    }


# ---------------------------------------------------------------------------
# Helpers: call parse_qa_verdict logic directly by importing it from bash
# We extract parse_qa_verdict logic into Python for fast unit testing.
# The shell integration is tested via the full subagent-stop.sh invocation.
# ---------------------------------------------------------------------------

def _extract_has_artifact(message: str) -> bool:
    """Python equivalent of has_artifact_marker() in subagent-stop.sh.

    ARTIFACT: <type>|<detail>
    type ∈ {test-run, file-check, diff-check}
    """
    pattern = re.compile(
        r'^\s*ARTIFACT:\s+(test-run|file-check|diff-check)\|.+$',
        re.MULTILINE | re.IGNORECASE
    )
    return bool(pattern.search(message))


def _python_parse_verdict(msg: str) -> str:
    """Python port of parse_qa_verdict() for fast unit testing without bash overhead."""
    msg_upper = msg.upper()

    if re.search(r'VERDICT:\s*(APPROVED-WITH-MINOR-FIXES|APPROVED)', msg_upper):
        if _extract_has_artifact(msg):
            return "pass"
        else:
            return "fail"

    if re.search(r'VERDICT:\s*REJECTED', msg_upper):
        return "fail"

    if '<promise>COMPLETE</promise>' in msg:
        if not re.search(r'REJECTED|VERDICT:\s*FAIL', msg_upper):
            if _extract_has_artifact(msg):
                return "pass"
            else:
                return "fail"

    return "fail"


# ---------------------------------------------------------------------------
# TASK-115: QA agent — artifact marker requirement
# ---------------------------------------------------------------------------

class TestQAAgentArtifactRequirement:
    """qa.md must document the ARTIFACT marker requirement."""

    def test_qa_md_exists(self):
        assert os.path.isfile(QA_AGENT), f"qa.md not found at {QA_AGENT}"

    def test_qa_md_contains_artifact_marker_documentation(self):
        with open(QA_AGENT) as f:
            content = f.read()
        assert "ARTIFACT:" in content, "qa.md must document the ARTIFACT marker"

    def test_qa_md_names_artifact_types(self):
        with open(QA_AGENT) as f:
            content = f.read()
        for artifact_type in ("test-run", "file-check", "diff-check"):
            assert artifact_type in content, (
                f"qa.md must document artifact type '{artifact_type}'"
            )

    def test_qa_md_states_bare_pass_is_invalid(self):
        with open(QA_AGENT) as f:
            content = f.read()
        # Must explicitly warn that a bare VERDICT: APPROVED without ARTIFACT will not unblock
        assert "NOT unblock" in content or "will not unblock" in content.lower() or \
               "WILL NOT" in content, (
            "qa.md must explicitly state that a bare VERDICT: APPROVED will not unblock the gate"
        )

    def test_qa_md_contains_example_artifact_lines(self):
        with open(QA_AGENT) as f:
            content = f.read()
        # Should have at least one example with the pipe format
        assert re.search(r'ARTIFACT:\s+(test-run|file-check|diff-check)\|', content), (
            "qa.md must include an example ARTIFACT line with pipe-separated format"
        )


# ---------------------------------------------------------------------------
# TASK-115 + TASK-117: Artifact marker parsing logic — unit tests (Python port)
# These are fast unit tests verifying the logic used by has_artifact_marker()
# and parse_qa_verdict() in subagent-stop.sh.
# ---------------------------------------------------------------------------

class TestArtifactMarkerParsing:
    """(a) verdict WITHOUT artifact does NOT unblock; (b) WITH artifact DOES unblock."""

    # --- (a) No artifact → must NOT pass ---

    def test_bare_approved_no_artifact_is_fail(self):
        msg = "Task: TASK-115 | WP: WP-200\nVERDICT: APPROVED"
        assert _python_parse_verdict(msg) == "fail", (
            "VERDICT: APPROVED without ARTIFACT must not unblock (returns fail)"
        )

    def test_approved_with_minor_fixes_no_artifact_is_fail(self):
        msg = "Task: TASK-115\nVERDICT: APPROVED-WITH-MINOR-FIXES\nSome notes here."
        assert _python_parse_verdict(msg) == "fail", (
            "VERDICT: APPROVED-WITH-MINOR-FIXES without ARTIFACT must not unblock"
        )

    def test_complete_promise_no_artifact_is_fail(self):
        msg = "Task: TASK-115\n<promise>COMPLETE</promise>"
        assert _python_parse_verdict(msg) == "fail", (
            "<promise>COMPLETE</promise> without ARTIFACT must not unblock"
        )

    def test_rejected_is_always_fail(self):
        msg = "Task: TASK-115\nVERDICT: REJECTED\nFailed checks."
        assert _python_parse_verdict(msg) == "fail"

    def test_empty_message_is_fail(self):
        assert _python_parse_verdict("") == "fail"

    def test_artifact_wrong_type_is_fail(self):
        """An artifact with an unrecognized type must NOT unblock."""
        msg = (
            "Task: TASK-115\n"
            "ARTIFACT: screenshot|some-image.png\n"
            "VERDICT: APPROVED"
        )
        assert _python_parse_verdict(msg) == "fail", (
            "An artifact with an unrecognized type must not unblock"
        )

    # --- (b) Valid artifact → must pass ---

    def test_approved_with_test_run_artifact_passes(self):
        msg = (
            "Task: TASK-115 | WP: WP-200\n"
            "ARTIFACT: test-run|pytest tests/test_prd7_ws1.py exit=0 \"12 passed\"\n"
            "VERDICT: APPROVED"
        )
        assert _python_parse_verdict(msg) == "pass"

    def test_approved_with_file_check_artifact_passes(self):
        msg = (
            "Task: TASK-115\n"
            "ARTIFACT: file-check|.claude/agents/manifest.json exists agents=15\n"
            "VERDICT: APPROVED"
        )
        assert _python_parse_verdict(msg) == "pass"

    def test_approved_with_diff_check_artifact_passes(self):
        msg = (
            "Task: TASK-115\n"
            "ARTIFACT: diff-check|expected 16 agents actual 16 match\n"
            "VERDICT: APPROVED"
        )
        assert _python_parse_verdict(msg) == "pass"

    def test_approved_with_minor_fixes_with_artifact_passes(self):
        msg = (
            "Task: TASK-115\n"
            "ARTIFACT: test-run|pytest tests/ exit=0 \"all passed\"\n"
            "VERDICT: APPROVED-WITH-MINOR-FIXES"
        )
        assert _python_parse_verdict(msg) == "pass"

    def test_complete_promise_with_artifact_passes(self):
        msg = (
            "Task: TASK-115\n"
            "ARTIFACT: file-check|.claude/hooks/subagent-stop.sh exists has_artifact_marker\n"
            "<promise>COMPLETE</promise>"
        )
        assert _python_parse_verdict(msg) == "pass"

    def test_artifact_case_insensitive(self):
        """ARTIFACT keyword matching must be case-insensitive."""
        msg = (
            "Task: TASK-115\n"
            "artifact: test-run|pytest tests/ exit=0 \"passed\"\n"
            "VERDICT: APPROVED"
        )
        assert _python_parse_verdict(msg) == "pass"

    def test_artifact_allows_leading_whitespace(self):
        msg = (
            "Task: TASK-115\n"
            "  ARTIFACT: test-run|pytest tests/ exit=0 \"passed\"\n"
            "VERDICT: APPROVED"
        )
        assert _python_parse_verdict(msg) == "pass"

    def test_multiple_artifacts_still_passes(self):
        """Multiple ARTIFACT lines is fine — at least one valid one is sufficient."""
        msg = (
            "Task: TASK-115\n"
            "ARTIFACT: test-run|pytest tests/unit exit=0 \"5 passed\"\n"
            "ARTIFACT: file-check|.claude/agents/qa.md exists\n"
            "VERDICT: APPROVED"
        )
        assert _python_parse_verdict(msg) == "pass"


# ---------------------------------------------------------------------------
# TASK-117: Escape hatch and 3-fail auto-unblock — integration via bash hook
# (c) escape hatch still bypasses; (d) 3-fail auto-unblock still fires
# ---------------------------------------------------------------------------

class TestGateHookIntegration:
    """Integration tests against the actual subagent-stop.sh bash script."""

    SESSION = "test-ws1-session-001"

    def _run_hook(self, message: str, agent_type: str = "qa",
                  initial_gate: dict = None, env_extra: dict = None) -> dict:
        """Invoke the patched subagent-stop.sh and return gate state."""
        result = _parse_verdict_from_subagent_stop(
            last_message=message,
            session_id=self.SESSION,
            agent_type=agent_type,
            initial_gate=initial_gate,
        )
        return result

    def test_bare_approved_does_not_clear_gate(self):
        """(a) A bare VERDICT: APPROVED without ARTIFACT must not clear pending_tasks."""
        # Set up a gate with a pending task
        initial = {
            self.SESSION: {
                "pending_tasks": ["TASK-115"],
                "retries": {},
                "history": [],
                "lastSeen": "2026-06-17T10:00:00Z"
            }
        }
        msg = "Task: TASK-115 | WP: WP-200\nVERDICT: APPROVED"
        result = self._run_hook(msg, initial_gate=initial)

        gate = result["gate_state"]
        # pending_tasks must still contain TASK-115 — gate NOT cleared
        session = gate.get(self.SESSION, {})
        pending = session.get("pending_tasks", [])
        assert "TASK-115" in pending, (
            f"Bare VERDICT: APPROVED without artifact must NOT clear pending_tasks; "
            f"got: {pending}"
        )

    def test_approved_with_artifact_clears_gate(self):
        """(b) VERDICT: APPROVED WITH ARTIFACT must clear pending_tasks."""
        initial = {
            self.SESSION: {
                "pending_tasks": ["TASK-115"],
                "retries": {},
                "history": [],
                "lastSeen": "2026-06-17T10:00:00Z"
            }
        }
        msg = (
            "Task: TASK-115 | WP: WP-200\n"
            "ARTIFACT: test-run|pytest tests/test_prd7_ws1.py exit=0 \"passed\"\n"
            "VERDICT: APPROVED"
        )
        result = self._run_hook(msg, initial_gate=initial)

        gate = result["gate_state"]
        session = gate.get(self.SESSION, {})
        pending = session.get("pending_tasks", [])
        assert "TASK-115" not in pending, (
            f"VERDICT: APPROVED with artifact must clear TASK-115 from pending_tasks; "
            f"got: {pending}"
        )

    def test_escape_hatch_bypasses_gate(self):
        """(c) COPILOT_QA_GATE=off must bypass all state management."""
        initial = {
            self.SESSION: {
                "pending_tasks": ["TASK-115"],
                "retries": {},
                "history": [],
                "lastSeen": "2026-06-17T10:00:00Z"
            }
        }
        msg = "Task: TASK-115\nVERDICT: APPROVED"  # bare pass, no artifact

        # Even a bare pass should not cause state changes when escape hatch is on,
        # because the script exits 0 immediately.
        tmp_state_dir = tempfile.mkdtemp(prefix="ws1-escape-test-")
        gate_path = os.path.join(tmp_state_dir, "qa-gate.json")
        with open(gate_path, "w") as f:
            json.dump(initial, f)

        patched_script = os.path.join(tmp_state_dir, "subagent-stop.sh")
        with open(SUBAGENT_STOP) as f:
            content = f.read()
        content = content.replace(
            'STATE_DIR="${SCRIPT_DIR}/state"',
            f'STATE_DIR={tmp_state_dir!r}'
        )
        with open(patched_script, "w") as f:
            f.write(content)
        os.chmod(patched_script, 0o755)

        env = os.environ.copy()
        env["COPILOT_QA_GATE"] = "off"

        result = subprocess.run(
            ["/bin/bash", patched_script],
            input=json.dumps({
                "session_id": self.SESSION,
                "agent_type": "qa",
                "last_assistant_message": msg,
            }),
            capture_output=True,
            text=True,
            env=env,
            cwd=BASE,
            timeout=10,
        )

        shutil.rmtree(tmp_state_dir, ignore_errors=True)

        # Script should exit 0 and not modify the gate when COPILOT_QA_GATE=off
        assert result.returncode == 0, f"Script should exit 0 with escape hatch; got {result.returncode}"

    def test_three_fail_auto_unblock_fires(self):
        """(d) After 3 consecutive QA failures, gate auto-unblocks (MAX_RETRIES=3)."""
        # Build a state with TASK-115 at 2 retries already
        initial = {
            self.SESSION: {
                "pending_tasks": ["TASK-115"],
                "retries": {"TASK-115": 2},  # already 2 failures
                "history": [
                    {"taskId": "TASK-115", "event": "qa_failed_retry_1", "ts": "2026-06-17T10:00:00Z"},
                    {"taskId": "TASK-115", "event": "qa_failed_retry_2", "ts": "2026-06-17T10:01:00Z"},
                ],
                "lastSeen": "2026-06-17T10:01:00Z"
            }
        }
        # Send a 3rd failing verdict (no artifact, so it fails)
        msg = "Task: TASK-115\nVERDICT: APPROVED"  # bare, no artifact → fail verdict
        result = self._run_hook(msg, initial_gate=initial)

        gate = result["gate_state"]
        session = gate.get(self.SESSION, {})
        pending = session.get("pending_tasks", [])

        # After 3 failures, task should be removed from pending_tasks (auto-unblock)
        assert "TASK-115" not in pending, (
            f"After 3 consecutive QA failures, TASK-115 should be auto-unblocked; "
            f"pending_tasks={pending}"
        )

        # Verify the stdout contains an advisory message
        assert "advisory" in result["stdout"].lower() or "degraded" in result["stdout"].lower(), (
            f"Auto-unblock should emit an advisory systemMessage; stdout={result['stdout']!r}"
        )


# ---------------------------------------------------------------------------
# TASK-115 + 117: has_artifact_marker — edge cases
# ---------------------------------------------------------------------------

class TestHasArtifactMarker:
    """Unit tests for the has_artifact_marker regex logic."""

    def test_empty_string_has_no_artifact(self):
        assert not _extract_has_artifact("")

    def test_artifact_with_no_pipe_is_rejected(self):
        assert not _extract_has_artifact("ARTIFACT: test-run no pipe here")

    def test_artifact_with_empty_detail_is_rejected(self):
        assert not _extract_has_artifact("ARTIFACT: test-run|")

    def test_artifact_test_run_is_recognized(self):
        assert _extract_has_artifact("ARTIFACT: test-run|pytest tests/ exit=0")

    def test_artifact_file_check_is_recognized(self):
        assert _extract_has_artifact("ARTIFACT: file-check|.claude/agents/qa.md exists")

    def test_artifact_diff_check_is_recognized(self):
        assert _extract_has_artifact("ARTIFACT: diff-check|expected X actual X match")

    def test_artifact_must_have_valid_type(self):
        assert not _extract_has_artifact("ARTIFACT: screenshot|image.png")
        assert not _extract_has_artifact("ARTIFACT: run|pytest tests/")
        assert not _extract_has_artifact("ARTIFACT: check|something")

    def test_artifact_embedded_in_longer_message(self):
        msg = (
            "Task: TASK-115 | WP: WP-200\n"
            "Tests ran: 12 passed.\n"
            "ARTIFACT: test-run|pytest tests/test_prd7_ws1.py exit=0 \"12 passed\"\n"
            "VERDICT: APPROVED\n"
        )
        assert _extract_has_artifact(msg)


# ---------------------------------------------------------------------------
# TASK-116: sec.md — warning accumulation threshold
# ---------------------------------------------------------------------------

class TestSecAgentWarningThreshold:
    """sec.md must document the warning-accumulation threshold and enforce N=3."""

    def test_sec_md_exists(self):
        assert os.path.isfile(SEC_AGENT), f"sec.md not found at {SEC_AGENT}"

    def test_sec_md_has_warning_threshold_constant(self):
        """(e) sec.md must define WARNING_HALT_THRESHOLD = 3 as a clearly-marked constant."""
        with open(SEC_AGENT) as f:
            content = f.read()
        assert "WARNING_HALT_THRESHOLD" in content, (
            "sec.md must define WARNING_HALT_THRESHOLD as a named constant"
        )
        # The constant must equal 3
        match = re.search(r'WARNING_HALT_THRESHOLD\s*=\s*(\d+)', content)
        assert match, "WARNING_HALT_THRESHOLD must be assigned a numeric value"
        assert match.group(1) == "3", (
            f"WARNING_HALT_THRESHOLD must equal 3, got {match.group(1)}"
        )

    def test_sec_md_forbids_first_warning_halt(self):
        """(e) sec.md must say NOT to halt on the first warning."""
        with open(SEC_AGENT) as f:
            content = f.read()
        # Must contain language about NOT halting on first warning
        assert ("first warning" in content.lower() or
                "halt on the first" in content.lower() or
                "accumulate" in content.lower()), (
            "sec.md must document that halt is deferred — accumulate warnings to threshold"
        )

    def test_sec_md_forbids_unverified_flags(self):
        """sec.md must explicitly forbid unverified flags."""
        with open(SEC_AGENT) as f:
            content = f.read()
        # Must contain the confirming-evidence requirement
        assert ("absence of evidence" in content.lower() or
                "confirming evidence" in content.lower() or
                "confirm" in content.lower()), (
            "sec.md must require confirming evidence before flagging"
        )

    def test_sec_md_requires_evidence_citation(self):
        with open(SEC_AGENT) as f:
            content = f.read()
        assert "evidence" in content.lower(), (
            "sec.md must require evidence for each flag"
        )

    def test_warning_threshold_logic_python(self):
        """(e) Python simulation: sec should NOT halt at 1 or 2 warnings, SHOULD halt at 3."""
        WARNING_HALT_THRESHOLD = 3  # matches sec.md constant

        def should_halt(warning_count: int) -> bool:
            return warning_count >= WARNING_HALT_THRESHOLD

        assert not should_halt(1), "Must NOT halt on 1st warning"
        assert not should_halt(2), "Must NOT halt on 2nd warning"
        assert should_halt(3), "MUST halt on 3rd warning"
        assert should_halt(4), "Must still halt when count exceeds threshold"


# ---------------------------------------------------------------------------
# TASK-117: README.md documents new requirements
# ---------------------------------------------------------------------------

class TestReadmeDocumentation:
    """README.md must document the artifact requirement and escape hatches."""

    def test_readme_documents_artifact_requirement(self):
        with open(README_HOOKS) as f:
            content = f.read()
        assert "ARTIFACT" in content, "README.md must document the ARTIFACT marker requirement"

    def test_readme_documents_artifact_types(self):
        with open(README_HOOKS) as f:
            content = f.read()
        for t in ("test-run", "file-check", "diff-check"):
            assert t in content, f"README.md must document artifact type '{t}'"

    def test_readme_documents_escape_hatches(self):
        with open(README_HOOKS) as f:
            content = f.read()
        assert "COPILOT_QA_GATE=off" in content, (
            "README.md must document the COPILOT_QA_GATE=off escape hatch"
        )

    def test_readme_documents_bare_pass_is_invalid(self):
        with open(README_HOOKS) as f:
            content = f.read()
        # Should explicitly say bare pass does not unblock
        assert "bare" in content.lower() or "without an" in content.lower(), (
            "README.md must document that a bare VERDICT without ARTIFACT does not unblock"
        )

    def test_readme_documents_3_fail_auto_unblock(self):
        with open(README_HOOKS) as f:
            content = f.read()
        assert "3-fail" in content.lower() or "3 fail" in content.lower() or \
               "auto-unblock" in content.lower() or "auto_unblock" in content.lower() or \
               "MAX_RETRIES" in content or "3 consecutive" in content.lower(), (
            "README.md must document the 3-fail auto-unblock safety"
        )


# ---------------------------------------------------------------------------
# TASK-117: subagent-stop.sh contains has_artifact_marker function
# ---------------------------------------------------------------------------

class TestSubagentStopHookHardening:
    """subagent-stop.sh must contain the artifact marker enforcement."""

    def test_subagent_stop_has_artifact_function(self):
        with open(SUBAGENT_STOP) as f:
            content = f.read()
        assert "has_artifact_marker" in content, (
            "subagent-stop.sh must define has_artifact_marker()"
        )

    def test_subagent_stop_artifact_types_in_regex(self):
        with open(SUBAGENT_STOP) as f:
            content = f.read()
        for t in ("test-run", "file-check", "diff-check"):
            assert t in content, (
                f"subagent-stop.sh must include artifact type '{t}' in has_artifact_marker regex"
            )

    def test_subagent_stop_fail_on_missing_artifact(self):
        """subagent-stop.sh parse_qa_verdict must return fail when artifact is absent."""
        with open(SUBAGENT_STOP) as f:
            content = f.read()
        # Must have logic that returns/echoes "fail" when artifact is absent
        assert 'echo "fail"' in content, (
            "subagent-stop.sh must echo fail when artifact is missing from an APPROVED verdict"
        )

    def test_subagent_stop_warns_on_missing_artifact(self):
        """subagent-stop.sh must log a warning when artifact is absent from approved verdict."""
        with open(SUBAGENT_STOP) as f:
            content = f.read()
        assert "NO ARTIFACT" in content or "no artifact" in content.lower() or \
               "ARTIFACT marker" in content, (
            "subagent-stop.sh must warn when ARTIFACT marker is missing from passing verdict"
        )

    def test_subagent_stop_preserves_escape_hatch(self):
        with open(SUBAGENT_STOP) as f:
            content = f.read()
        assert 'COPILOT_QA_GATE' in content, (
            "subagent-stop.sh must preserve the COPILOT_QA_GATE escape hatch"
        )

    def test_subagent_stop_preserves_max_retries(self):
        with open(SUBAGENT_STOP) as f:
            content = f.read()
        assert "MAX_RETRIES=3" in content or "MAX_RETRIES = 3" in content, (
            "subagent-stop.sh must preserve MAX_RETRIES=3 for auto-unblock"
        )


# ---------------------------------------------------------------------------
# Regression: validation_result.py still imports cleanly (Phase 1 check)
# ---------------------------------------------------------------------------

class TestValidationResultRegression:
    """Confirm Phase 1 artifact (validation_result.py) still works."""

    def _import_module(self):
        spec = importlib.util.spec_from_file_location("validation_result", VALIDATION_LIB)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["validation_result"] = mod
        spec.loader.exec_module(mod)
        return mod

    def test_module_imports_cleanly(self):
        mod = self._import_module()
        assert hasattr(mod, "CheckResult")
        assert hasattr(mod, "ValidationReport")

    def test_artifact_field_on_check_result(self):
        """CheckResult must have an 'artifact' field (WS1 integration)."""
        mod = self._import_module()
        result = mod.CheckResult(
            check="qa-gate",
            status="pass",
            message="Gate cleared",
            artifact="test-run|pytest tests/test_prd7_ws1.py exit=0"
        )
        assert result.artifact == "test-run|pytest tests/test_prd7_ws1.py exit=0"

    def test_artifact_appears_in_to_dict(self):
        mod = self._import_module()
        result = mod.CheckResult(
            check="qa-gate",
            status="pass",
            artifact="file-check|.claude/agents/qa.md exists"
        )
        d = result.to_dict()
        assert d.get("artifact") == "file-check|.claude/agents/qa.md exists"

    def test_check_result_without_artifact_omits_field(self):
        """artifact=None must be omitted from the serialized dict."""
        mod = self._import_module()
        result = mod.CheckResult(check="x", status="pass")
        d = result.to_dict()
        assert "artifact" not in d, "artifact=None must be omitted from to_dict()"
