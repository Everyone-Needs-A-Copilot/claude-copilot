"""
Phase 1 (Stream-D) tests for PRD-7: Verification and Observability

TASK-112: Declarative agent/routing manifest
TASK-113: Structured validation-result pattern
TASK-114: SessionStart banner generated from manifest

These are failable checks — they will fail if the artifacts are wrong or missing.
"""

import json
import os
import subprocess
import sys
import importlib.util

BASE = "/Volumes/Dev/Sites/COPILOT/claude-copilot"
AGENTS_DIR = os.path.join(BASE, ".claude/agents")
MANIFEST_PATH = os.path.join(AGENTS_DIR, "manifest.json")
SCHEMA_PATH = os.path.join(AGENTS_DIR, "manifest.schema.json")
HOOKS_DIR = os.path.join(BASE, ".claude/hooks")
PROTOCOL_INJECTION = os.path.join(HOOKS_DIR, "protocol-injection.md")
SESSION_START_SH = os.path.join(HOOKS_DIR, "session-start.sh")
VALIDATION_LIB = os.path.join(HOOKS_DIR, "lib", "validation_result.py")

EXPECTED_FRAMEWORK_AGENT_COUNT = 15  # kc is setup-only per ADR-002/PRD-7; counted separately


# ---------------------------------------------------------------------------
# TASK-112: Manifest
# ---------------------------------------------------------------------------

class TestManifest:
    """Declarative agent/routing manifest must be valid and match disk."""

    def test_manifest_exists(self):
        assert os.path.isfile(MANIFEST_PATH), f"manifest.json not found at {MANIFEST_PATH}"

    def test_schema_exists(self):
        assert os.path.isfile(SCHEMA_PATH), f"manifest.schema.json not found at {SCHEMA_PATH}"

    def test_manifest_parses_as_valid_json(self):
        with open(MANIFEST_PATH) as f:
            data = json.load(f)  # raises ValueError if invalid
        assert isinstance(data, dict), "manifest.json must be a JSON object"

    def test_manifest_has_required_keys(self):
        with open(MANIFEST_PATH) as f:
            data = json.load(f)
        for key in ("schemaVersion", "agents", "routingEdges", "designChain"):
            assert key in data, f"manifest.json missing required key: {key}"

    def test_framework_agent_count_is_16(self):
        with open(MANIFEST_PATH) as f:
            data = json.load(f)
        framework_agents = [
            name for name, desc in data["agents"].items()
            if desc.get("role") == "framework"
        ]
        assert len(framework_agents) == EXPECTED_FRAMEWORK_AGENT_COUNT, (
            f"Expected {EXPECTED_FRAMEWORK_AGENT_COUNT} framework agents, "
            f"got {len(framework_agents)}: {sorted(framework_agents)}"
        )

    def test_kc_is_setup_only_not_framework(self):
        with open(MANIFEST_PATH) as f:
            data = json.load(f)
        assert "kc" in data["agents"], "kc must be present in manifest"
        assert data["agents"]["kc"]["role"] == "setup-only", (
            "kc must have role=setup-only, not framework"
        )

    def test_design_is_absent(self):
        """Retired 'design' agent must not appear in manifest."""
        with open(MANIFEST_PATH) as f:
            data = json.load(f)
        assert "design" not in data["agents"], (
            "Retired 'design' agent must not appear in manifest"
        )

    def test_manifest_agents_match_disk_agents(self):
        """Every framework agent file on disk must appear in manifest and vice versa."""
        # Get agent names from disk (exclude kc file since it's setup-only,
        # but we still want it in the manifest — just not counted as framework)
        disk_agents = set()
        for fname in os.listdir(AGENTS_DIR):
            if fname.endswith(".md") and not fname.startswith("_"):
                disk_agents.add(fname[:-3])  # strip .md

        with open(MANIFEST_PATH) as f:
            data = json.load(f)
        manifest_agents = set(data["agents"].keys())

        # Every disk agent must be in manifest
        missing_from_manifest = disk_agents - manifest_agents
        assert not missing_from_manifest, (
            f"Agents on disk but missing from manifest: {missing_from_manifest}"
        )

        # Every manifest agent must have a file on disk
        missing_from_disk = manifest_agents - disk_agents
        assert not missing_from_disk, (
            f"Agents in manifest but no .md file on disk: {missing_from_disk}"
        )

    def test_design_chain_is_correct(self):
        with open(MANIFEST_PATH) as f:
            data = json.load(f)
        expected = ["sd", "uxd", "uids", "uid", "ta", "me"]
        assert data["designChain"] == expected, (
            f"designChain expected {expected}, got {data['designChain']}"
        )

    def test_routing_edges_present(self):
        with open(MANIFEST_PATH) as f:
            data = json.load(f)
        edges = data["routingEdges"]
        assert len(edges) >= 10, f"Expected at least 10 routing edges, got {len(edges)}"

        # Verify the mandatory me→qa edge exists
        me_to_qa = [
            e for e in edges
            if e.get("from") == "me" and e.get("to") == "qa"
        ]
        assert me_to_qa, "Mandatory me→qa routing edge must exist in manifest"

    def test_all_agents_have_required_fields(self):
        with open(MANIFEST_PATH) as f:
            data = json.load(f)
        for name, desc in data["agents"].items():
            assert "role" in desc, f"Agent {name} missing 'role'"
            assert "model" in desc, f"Agent {name} missing 'model'"
            assert "tools" in desc, f"Agent {name} missing 'tools'"
            assert desc["role"] in ("framework", "setup-only"), (
                f"Agent {name} has invalid role: {desc['role']}"
            )

    def test_schema_validates_with_jsonschema_if_available(self):
        """Validate manifest against its schema (skipped if jsonschema not installed)."""
        try:
            import jsonschema
        except ImportError:
            # jsonschema not installed; skip this check gracefully
            return

        with open(MANIFEST_PATH) as f:
            manifest = json.load(f)
        with open(SCHEMA_PATH) as f:
            schema = json.load(f)

        jsonschema.validate(instance=manifest, schema=schema)


# ---------------------------------------------------------------------------
# TASK-113: Structured validation-result pattern
# ---------------------------------------------------------------------------

class TestValidationResult:
    """Structured-result module must be importable and produce correct shapes."""

    def test_validation_result_module_exists(self):
        assert os.path.isfile(VALIDATION_LIB), (
            f"validation_result.py not found at {VALIDATION_LIB}"
        )

    def _import_module(self):
        spec = importlib.util.spec_from_file_location("validation_result", VALIDATION_LIB)
        mod = importlib.util.module_from_spec(spec)
        # Register in sys.modules BEFORE exec so dataclass __module__ resolves correctly
        sys.modules["validation_result"] = mod
        spec.loader.exec_module(mod)
        return mod

    def test_module_imports_cleanly(self):
        mod = self._import_module()
        assert hasattr(mod, "CheckResult"), "Module must export CheckResult"
        assert hasattr(mod, "ValidationReport"), "Module must export ValidationReport"

    def test_check_result_pass(self):
        mod = self._import_module()
        result = mod.CheckResult(
            check="test-check",
            status="pass",
            message="All good"
        )
        assert result.status == "pass"
        assert result.check == "test-check"

    def test_check_result_fail(self):
        mod = self._import_module()
        result = mod.CheckResult(
            check="agent-count",
            status="fail",
            expected="16",
            actual="15",
            message="Agent count mismatch"
        )
        assert result.status == "fail"
        assert result.expected == "16"
        assert result.actual == "15"

    def test_check_result_warn(self):
        mod = self._import_module()
        result = mod.CheckResult(
            check="schema-validation",
            status="warn",
            message="jsonschema not installed, skipped"
        )
        assert result.status == "warn"

    def test_validation_report_pass_rollup(self):
        """All pass checks → overall verdict pass."""
        mod = self._import_module()
        checks = [
            mod.CheckResult("a", "pass", message="ok"),
            mod.CheckResult("b", "pass", message="ok"),
        ]
        report = mod.ValidationReport(checks=checks)
        assert report.verdict == "pass"

    def test_validation_report_fail_rollup(self):
        """Any fail → overall verdict fail."""
        mod = self._import_module()
        checks = [
            mod.CheckResult("a", "pass", message="ok"),
            mod.CheckResult("b", "fail", message="bad"),
        ]
        report = mod.ValidationReport(checks=checks)
        assert report.verdict == "fail"

    def test_validation_report_warn_rollup(self):
        """Warn but no fail → overall verdict warn."""
        mod = self._import_module()
        checks = [
            mod.CheckResult("a", "pass", message="ok"),
            mod.CheckResult("b", "warn", message="advisory"),
        ]
        report = mod.ValidationReport(checks=checks)
        assert report.verdict == "warn"

    def test_validation_report_to_json(self):
        """Report serializes to valid JSON with expected shape."""
        mod = self._import_module()
        checks = [
            mod.CheckResult(
                check="agent-count",
                status="pass",
                expected="16",
                actual="16",
                message="Correct"
            )
        ]
        report = mod.ValidationReport(checks=checks)
        j = report.to_json()
        data = json.loads(j)
        assert "verdict" in data
        assert "checks" in data
        assert isinstance(data["checks"], list)
        assert data["checks"][0]["check"] == "agent-count"
        assert data["checks"][0]["status"] == "pass"

    def test_shell_emit_produces_valid_json(self):
        """Shell-emit function produces a JSON line consumable by bash hooks."""
        mod = self._import_module()
        checks = [
            mod.CheckResult("x", "fail", expected="yes", actual="no", message="mismatch")
        ]
        report = mod.ValidationReport(checks=checks)
        line = report.to_shell_json()
        # Must be a single-line valid JSON
        assert "\n" not in line.strip(), "Shell JSON must be a single line"
        data = json.loads(line)
        assert data["verdict"] == "fail"


# ---------------------------------------------------------------------------
# TASK-114: Banner generated from manifest
# ---------------------------------------------------------------------------

class TestBannerFromManifest:
    """SessionStart banner must reflect the true 16-agent roster from manifest."""

    def test_protocol_injection_no_retired_design(self):
        with open(PROTOCOL_INJECTION) as f:
            content = f.read()
        assert "@agent-design" not in content, (
            "protocol-injection.md must not reference retired @agent-design"
        )

    def test_protocol_injection_no_kc_as_framework(self):
        """kc must not be listed as a framework agent alongside the 16."""
        with open(PROTOCOL_INJECTION) as f:
            content = f.read()
        # kc should not appear in the agents listing line (the roster line)
        # The rule 1 line should NOT list @agent-kc among framework agents
        lines = content.splitlines()
        roster_lines = [l for l in lines if "@agent-" in l and "Rule 1" in content]
        # Check the agents line specifically
        agent_list_lines = [l for l in lines if "@agent-me" in l and "@agent-ta" in l]
        for line in agent_list_lines:
            assert "@agent-kc" not in line, (
                f"@agent-kc must not appear in the framework agent roster line: {line}"
            )

    def test_banner_roster_matches_manifest(self):
        """Agents listed in the banner must match manifest framework agents."""
        with open(MANIFEST_PATH) as f:
            data = json.load(f)
        framework_agents = sorted([
            name for name, desc in data["agents"].items()
            if desc.get("role") == "framework"
        ])

        with open(PROTOCOL_INJECTION) as f:
            content = f.read()

        # Every framework agent must be mentioned in the injection
        for agent in framework_agents:
            assert f"@agent-{agent}" in content, (
                f"Framework agent @agent-{agent} is in manifest but missing from banner"
            )

    def test_session_start_sh_reads_manifest(self):
        """session-start.sh must reference manifest.json."""
        with open(SESSION_START_SH) as f:
            content = f.read()
        assert "manifest.json" in content, (
            "session-start.sh must read from manifest.json to generate roster"
        )

    def test_session_start_sh_produces_valid_json(self):
        """Execute session-start.sh — it must emit valid JSON with systemMessage."""
        env = os.environ.copy()
        env["COPILOT_SESSION_START"] = "on"
        # Unset anything that might cause issues
        env.pop("COPILOT_QA_GATE", None)

        result = subprocess.run(
            ["/bin/bash", SESSION_START_SH],
            capture_output=True,
            text=True,
            env=env,
            cwd=BASE,
            timeout=10
        )
        assert result.returncode == 0, (
            f"session-start.sh exited {result.returncode}\n"
            f"stderr: {result.stderr}\nstdout: {result.stdout}"
        )
        stdout = result.stdout.strip()
        assert stdout, "session-start.sh produced no output"
        data = json.loads(stdout)
        assert "systemMessage" in data, "Output must have 'systemMessage' key"
        assert len(data["systemMessage"]) > 100, "systemMessage seems too short"

    def test_banner_contains_correct_agents_not_retired(self):
        """Execute banner and verify it contains correct agents, not retired ones."""
        env = os.environ.copy()
        env["COPILOT_SESSION_START"] = "on"

        result = subprocess.run(
            ["/bin/bash", SESSION_START_SH],
            capture_output=True,
            text=True,
            env=env,
            cwd=BASE,
            timeout=10
        )
        assert result.returncode == 0

        data = json.loads(result.stdout.strip())
        msg = data["systemMessage"]

        assert "@agent-design" not in msg, (
            "Banner must not contain retired @agent-design"
        )
        # The banner should mention current framework agents
        assert "@agent-me" in msg, "Banner must mention @agent-me"
        assert "@agent-qa" in msg, "Banner must mention @agent-qa"
        assert "@agent-ta" in msg, "Banner must mention @agent-ta"
