"""
Tests for k8s_lint.py — bundled alongside the linter.

Run with:  python3 -m pytest .claude/skills/devops/kubernetes/scripts/test_k8s_lint.py -v
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent / "k8s_lint.py"

spec = importlib.util.spec_from_file_location("k8s_lint", SCRIPT)
k8s_lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(k8s_lint)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_script(args=(), stdin_text=None):
    cmd = [sys.executable, str(SCRIPT)] + list(args)
    result = subprocess.run(cmd, input=stdin_text, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def parse_output(stdout: str):
    return json.loads(stdout.split("\n\n")[0])


def finding_ids(findings):
    return [f["id"] for f in findings]


# ---------------------------------------------------------------------------
# Minimal compliant Deployment (passes all checks)
# ---------------------------------------------------------------------------

GOOD_DEPLOYMENT = {
    "apiVersion": "apps/v1",
    "kind": "Deployment",
    "metadata": {"name": "api"},
    "spec": {
        "replicas": 2,
        "template": {
            "spec": {
                "containers": [{
                    "name": "api",
                    "image": "api:v1.2.3",
                    "resources": {
                        "requests": {"cpu": "250m", "memory": "256Mi"},
                        "limits": {"cpu": "500m", "memory": "512Mi"},
                    },
                    "livenessProbe": {"httpGet": {"path": "/health", "port": 8080}},
                    "readinessProbe": {"httpGet": {"path": "/ready", "port": 8080}},
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 1000,
                        "readOnlyRootFilesystem": True,
                        "capabilities": {"drop": ["ALL"]},
                    },
                }]
            }
        }
    }
}


# ---------------------------------------------------------------------------
# K8S-001: Missing resource requests
# ---------------------------------------------------------------------------

class TestResourceRequests:
    def _make_deployment(self, resources=None):
        d = json.loads(json.dumps(GOOD_DEPLOYMENT))
        c = d["spec"]["template"]["spec"]["containers"][0]
        if resources is None:
            del c["resources"]
        else:
            c["resources"] = resources
        return d

    def test_no_resources_raises_k8s001(self):
        findings = k8s_lint.check_resource_requests(self._make_deployment({}))
        assert "K8S-001" in finding_ids(findings)

    def test_no_requests_key_raises_k8s001(self):
        findings = k8s_lint.check_resource_requests(
            self._make_deployment({"limits": {"cpu": "500m"}})
        )
        assert "K8S-001" in finding_ids(findings)

    def test_with_requests_no_finding(self):
        findings = k8s_lint.check_resource_requests(GOOD_DEPLOYMENT)
        assert findings == []

    def test_severity_is_medium(self):
        findings = k8s_lint.check_resource_requests(self._make_deployment({}))
        assert findings[0]["severity"] == "MEDIUM"


# ---------------------------------------------------------------------------
# K8S-002: Missing resource limits
# ---------------------------------------------------------------------------

class TestResourceLimits:
    def _make_deployment(self, resources=None):
        d = json.loads(json.dumps(GOOD_DEPLOYMENT))
        c = d["spec"]["template"]["spec"]["containers"][0]
        if resources is None:
            del c["resources"]
        else:
            c["resources"] = resources
        return d

    def test_no_limits_raises_k8s002(self):
        findings = k8s_lint.check_resource_limits(
            self._make_deployment({"requests": {"cpu": "250m"}})
        )
        assert "K8S-002" in finding_ids(findings)

    def test_with_limits_no_finding(self):
        findings = k8s_lint.check_resource_limits(GOOD_DEPLOYMENT)
        assert findings == []

    def test_severity_is_high(self):
        findings = k8s_lint.check_resource_limits(self._make_deployment({}))
        assert findings[0]["severity"] == "HIGH"


# ---------------------------------------------------------------------------
# K8S-003: Missing liveness probe
# ---------------------------------------------------------------------------

class TestLivenessProbe:
    def test_no_liveness_probe_raises_k8s003(self):
        d = json.loads(json.dumps(GOOD_DEPLOYMENT))
        del d["spec"]["template"]["spec"]["containers"][0]["livenessProbe"]
        findings = k8s_lint.check_liveness_probe(d)
        assert "K8S-003" in finding_ids(findings)

    def test_with_liveness_probe_no_finding(self):
        findings = k8s_lint.check_liveness_probe(GOOD_DEPLOYMENT)
        assert findings == []

    def test_severity_is_high(self):
        d = json.loads(json.dumps(GOOD_DEPLOYMENT))
        del d["spec"]["template"]["spec"]["containers"][0]["livenessProbe"]
        findings = k8s_lint.check_liveness_probe(d)
        assert findings[0]["severity"] == "HIGH"

    def test_non_workload_kind_skipped(self):
        # ConfigMap has no pod spec, should return no findings
        manifest = {"kind": "ConfigMap", "metadata": {"name": "cfg"}, "data": {}}
        findings = k8s_lint.check_liveness_probe(manifest)
        assert findings == []


# ---------------------------------------------------------------------------
# K8S-004: Missing readiness probe
# ---------------------------------------------------------------------------

class TestReadinessProbe:
    def test_no_readiness_probe_raises_k8s004(self):
        d = json.loads(json.dumps(GOOD_DEPLOYMENT))
        del d["spec"]["template"]["spec"]["containers"][0]["readinessProbe"]
        findings = k8s_lint.check_readiness_probe(d)
        assert "K8S-004" in finding_ids(findings)

    def test_with_readiness_probe_no_finding(self):
        findings = k8s_lint.check_readiness_probe(GOOD_DEPLOYMENT)
        assert findings == []

    def test_daemonset_no_readiness_required(self):
        # DaemonSets are not in READINESS_PROBE_KINDS
        d = json.loads(json.dumps(GOOD_DEPLOYMENT))
        d["kind"] = "DaemonSet"
        del d["spec"]["template"]["spec"]["containers"][0]["readinessProbe"]
        findings = k8s_lint.check_readiness_probe(d)
        assert findings == []


# ---------------------------------------------------------------------------
# K8S-005: Latest image tag
# ---------------------------------------------------------------------------

class TestLatestImageTag:
    def _make_with_image(self, image):
        d = json.loads(json.dumps(GOOD_DEPLOYMENT))
        d["spec"]["template"]["spec"]["containers"][0]["image"] = image
        return d

    def test_latest_tag_raises_k8s005(self):
        findings = k8s_lint.check_latest_image_tag(self._make_with_image("api:latest"))
        assert "K8S-005" in finding_ids(findings)

    def test_no_tag_raises_k8s005(self):
        findings = k8s_lint.check_latest_image_tag(self._make_with_image("api"))
        assert "K8S-005" in finding_ids(findings)

    def test_pinned_version_no_finding(self):
        findings = k8s_lint.check_latest_image_tag(self._make_with_image("api:v1.2.3"))
        assert findings == []

    def test_digest_pinned_no_finding(self):
        findings = k8s_lint.check_latest_image_tag(
            self._make_with_image("api:v1.2.3@sha256:abc123")
        )
        assert findings == []

    def test_registry_prefix_latest_raises(self):
        findings = k8s_lint.check_latest_image_tag(
            self._make_with_image("myregistry.io/myorg/api:latest")
        )
        assert "K8S-005" in finding_ids(findings)

    def test_severity_is_high(self):
        findings = k8s_lint.check_latest_image_tag(self._make_with_image("api:latest"))
        assert findings[0]["severity"] == "HIGH"


# ---------------------------------------------------------------------------
# K8S-006: Privileged container
# ---------------------------------------------------------------------------

class TestPrivilegedContainer:
    def test_privileged_true_raises_k8s006(self):
        d = json.loads(json.dumps(GOOD_DEPLOYMENT))
        d["spec"]["template"]["spec"]["containers"][0]["securityContext"]["privileged"] = True
        findings = k8s_lint.check_privileged_container(d)
        assert "K8S-006" in finding_ids(findings)

    def test_privileged_false_no_finding(self):
        d = json.loads(json.dumps(GOOD_DEPLOYMENT))
        d["spec"]["template"]["spec"]["containers"][0]["securityContext"]["privileged"] = False
        findings = k8s_lint.check_privileged_container(d)
        assert findings == []

    def test_no_privileged_key_no_finding(self):
        findings = k8s_lint.check_privileged_container(GOOD_DEPLOYMENT)
        assert findings == []

    def test_severity_is_critical(self):
        d = json.loads(json.dumps(GOOD_DEPLOYMENT))
        d["spec"]["template"]["spec"]["containers"][0]["securityContext"]["privileged"] = True
        findings = k8s_lint.check_privileged_container(d)
        assert findings[0]["severity"] == "CRITICAL"


# ---------------------------------------------------------------------------
# K8S-007: hostNetwork
# ---------------------------------------------------------------------------

class TestHostNetwork:
    def test_host_network_true_raises_k8s007(self):
        d = json.loads(json.dumps(GOOD_DEPLOYMENT))
        d["spec"]["template"]["spec"]["hostNetwork"] = True
        findings = k8s_lint.check_host_network(d)
        assert "K8S-007" in finding_ids(findings)

    def test_host_network_false_no_finding(self):
        d = json.loads(json.dumps(GOOD_DEPLOYMENT))
        d["spec"]["template"]["spec"]["hostNetwork"] = False
        findings = k8s_lint.check_host_network(d)
        assert findings == []

    def test_no_host_network_no_finding(self):
        findings = k8s_lint.check_host_network(GOOD_DEPLOYMENT)
        assert findings == []

    def test_severity_is_critical(self):
        d = json.loads(json.dumps(GOOD_DEPLOYMENT))
        d["spec"]["template"]["spec"]["hostNetwork"] = True
        findings = k8s_lint.check_host_network(d)
        assert findings[0]["severity"] == "CRITICAL"


# ---------------------------------------------------------------------------
# K8S-008: Security context
# ---------------------------------------------------------------------------

class TestSecurityContext:
    def test_no_security_context_raises_k8s008(self):
        d = json.loads(json.dumps(GOOD_DEPLOYMENT))
        del d["spec"]["template"]["spec"]["containers"][0]["securityContext"]
        findings = k8s_lint.check_security_context(d)
        assert "K8S-008" in finding_ids(findings)

    def test_run_as_non_root_true_no_finding(self):
        findings = k8s_lint.check_security_context(GOOD_DEPLOYMENT)
        assert findings == []

    def test_run_as_user_nonzero_no_finding(self):
        d = json.loads(json.dumps(GOOD_DEPLOYMENT))
        d["spec"]["template"]["spec"]["containers"][0]["securityContext"] = {"runAsUser": 1000}
        findings = k8s_lint.check_security_context(d)
        assert findings == []

    def test_run_as_user_zero_raises(self):
        d = json.loads(json.dumps(GOOD_DEPLOYMENT))
        d["spec"]["template"]["spec"]["containers"][0]["securityContext"] = {"runAsUser": 0}
        findings = k8s_lint.check_security_context(d)
        assert "K8S-008" in finding_ids(findings)

    def test_severity_is_high(self):
        d = json.loads(json.dumps(GOOD_DEPLOYMENT))
        del d["spec"]["template"]["spec"]["containers"][0]["securityContext"]
        findings = k8s_lint.check_security_context(d)
        assert findings[0]["severity"] == "HIGH"


# ---------------------------------------------------------------------------
# K8S-009: Single replica
# ---------------------------------------------------------------------------

class TestSingleReplica:
    def test_replicas_1_raises_k8s009(self):
        d = json.loads(json.dumps(GOOD_DEPLOYMENT))
        d["spec"]["replicas"] = 1
        findings = k8s_lint.check_single_replica(d)
        assert "K8S-009" in finding_ids(findings)

    def test_replicas_absent_raises_k8s009(self):
        d = json.loads(json.dumps(GOOD_DEPLOYMENT))
        del d["spec"]["replicas"]
        findings = k8s_lint.check_single_replica(d)
        assert "K8S-009" in finding_ids(findings)

    def test_replicas_2_no_finding(self):
        findings = k8s_lint.check_single_replica(GOOD_DEPLOYMENT)
        assert findings == []

    def test_non_deployment_kind_skipped(self):
        d = json.loads(json.dumps(GOOD_DEPLOYMENT))
        d["kind"] = "StatefulSet"
        d["spec"]["replicas"] = 1
        findings = k8s_lint.check_single_replica(d)
        assert findings == []

    def test_severity_is_medium(self):
        d = json.loads(json.dumps(GOOD_DEPLOYMENT))
        d["spec"]["replicas"] = 1
        findings = k8s_lint.check_single_replica(d)
        assert findings[0]["severity"] == "MEDIUM"


# ---------------------------------------------------------------------------
# Good Deployment — zero findings
# ---------------------------------------------------------------------------

class TestGoodDeployment:
    def test_good_deployment_no_findings(self):
        findings = k8s_lint.lint_manifest(GOOD_DEPLOYMENT)
        assert findings == [], f"Unexpected findings: {findings}"


# ---------------------------------------------------------------------------
# Sort order
# ---------------------------------------------------------------------------

class TestSortOrder:
    def test_critical_before_high_before_medium(self):
        d = json.loads(json.dumps(GOOD_DEPLOYMENT))
        d["spec"]["replicas"] = 1  # MEDIUM: K8S-009
        del d["spec"]["template"]["spec"]["containers"][0]["resources"]  # HIGH + MEDIUM
        d["spec"]["template"]["spec"]["containers"][0]["securityContext"]["privileged"] = True  # CRITICAL
        findings = k8s_lint.lint_manifest(d)
        severities = [f["severity"] for f in findings]
        crit_idx = next((i for i, s in enumerate(severities) if s == "CRITICAL"), None)
        high_idx = next((i for i, s in enumerate(severities) if s == "HIGH"), None)
        if crit_idx is not None and high_idx is not None:
            assert crit_idx < high_idx


# ---------------------------------------------------------------------------
# Load input — array vs single object
# ---------------------------------------------------------------------------

class TestLoadInput:
    def test_single_object_accepted(self, monkeypatch):
        import io
        data = json.dumps(GOOD_DEPLOYMENT)
        import sys as _sys
        monkeypatch.setattr(_sys, "stdin", io.StringIO(data))
        result = k8s_lint.load_input(None)
        assert len(result) == 1

    def test_array_accepted(self, monkeypatch):
        import io
        import sys as _sys
        data = json.dumps([GOOD_DEPLOYMENT, GOOD_DEPLOYMENT])
        monkeypatch.setattr(_sys, "stdin", io.StringIO(data))
        result = k8s_lint.load_input(None)
        assert len(result) == 2

    def test_missing_kind_raises(self, monkeypatch):
        import io
        import sys as _sys
        data = json.dumps({"apiVersion": "v1", "metadata": {"name": "x"}})
        monkeypatch.setattr(_sys, "stdin", io.StringIO(data))
        with pytest.raises(ValueError, match="kind"):
            k8s_lint.load_input(None)

    def test_empty_stdin_returns_empty(self, monkeypatch):
        import io
        import sys as _sys
        monkeypatch.setattr(_sys, "stdin", io.StringIO(""))
        result = k8s_lint.load_input(None)
        assert result == []


# ---------------------------------------------------------------------------
# Subprocess integration
# ---------------------------------------------------------------------------

class TestSubprocess:
    def test_valid_deployment_exits_zero(self):
        code, out, err = run_script(args=("-",), stdin_text=json.dumps(GOOD_DEPLOYMENT))
        assert code == 0

    def test_bad_json_exits_nonzero(self):
        code, _, err = run_script(args=("-",), stdin_text="not json")
        assert code != 0
        assert "ERROR" in err

    def test_missing_file_exits_nonzero(self):
        code, _, err = run_script(args=("/no/such/manifest.json",))
        assert code != 0
        assert "ERROR" in err

    def test_markdown_table_present(self):
        d = json.loads(json.dumps(GOOD_DEPLOYMENT))
        d["spec"]["replicas"] = 1  # trigger a finding
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(d))
        assert code == 0
        assert "## Kubernetes Manifest Linter Findings" in out

    def test_empty_array_exits_zero(self):
        code, out, _ = run_script(args=("-",), stdin_text="[]")
        assert code == 0

    def test_file_path_argument(self, tmp_path):
        p = tmp_path / "manifest.json"
        p.write_text(json.dumps(GOOD_DEPLOYMENT))
        code, out, _ = run_script(args=(str(p),))
        assert code == 0
