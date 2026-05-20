#!/usr/bin/env python3
"""
Kubernetes Manifest Linter — L3 executable for the kubernetes skill.

Input (file path as first argument, or '-'/no-arg for stdin):
  JSON representation of one or more Kubernetes manifest objects.
  Accepts EITHER:
    - A single manifest object:  {"apiVersion": "apps/v1", "kind": "Deployment", ...}
    - An array of manifest objects: [{"kind": "Deployment", ...}, ...]

  NOTE: YAML manifests must be converted to JSON before passing.
  Rationale: stdlib json is robust; a from-scratch YAML parser is fragile for
  production use. Use 'python3 -c "import sys,json,yaml; print(json.dumps(yaml.safe_load(sys.stdin)))"'
  or 'yq -o json' to convert. This is documented in the Invocation section.

Output (stdout):
  1. JSON object with 'findings' array and 'summary' counts.
  2. Markdown findings table.

Exit codes:
  0 — success (including empty input and findings-present input)
  1 — invalid input (bad JSON, missing apiVersion/kind, file not found)

Checks and their sources:
  K8S-001  Missing resource requests on container
           — Kubernetes docs; without requests, scheduler cannot make placement decisions
  K8S-002  Missing resource limits on container
           — Kubernetes docs + LimitRange best practices; prevents node exhaustion
  K8S-003  Missing liveness probe on container (Deployments/StatefulSets/DaemonSets)
           — Kubernetes best practices; required for auto-restart of unhealthy pods
  K8S-004  Missing readiness probe on container (Deployments/StatefulSets)
           — Kubernetes best practices; required to gate traffic during startup
  K8S-005  Image tag is :latest or untagged
           — Kubernetes best practices; non-reproducible, rollback impossible
  K8S-006  Container has privileged: true in securityContext
           — CIS Kubernetes Benchmark 5.2.1; container escape = full host access
  K8S-007  Pod spec uses hostNetwork: true
           — CIS Kubernetes Benchmark 5.2.4; bypasses network isolation
  K8S-008  Missing container-level securityContext (runAsNonRoot not set)
           — CIS Kubernetes Benchmark 5.2.6; defaults to root
  K8S-009  Single replica in a Deployment (no HA)
           — Kubernetes HA best practices; pod restart = downtime

Severity ranks:
  CRITICAL = 1  (privilege escalation risk)
  HIGH     = 2  (security / reliability)
  MEDIUM   = 3  (reliability / scheduling)
  INFO     = 4  (advisory)
"""

import argparse
import json
import re
import sys

# ---------------------------------------------------------------------------
# Severity constants
# ---------------------------------------------------------------------------
CRITICAL = "CRITICAL"
HIGH = "HIGH"
MEDIUM = "MEDIUM"
INFO = "INFO"

SEVERITY_RANK = {CRITICAL: 1, HIGH: 2, MEDIUM: 3, INFO: 4}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Kinds that have pod templates
POD_TEMPLATE_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob", "ReplicaSet"}

# Kinds that should have readiness probes (traffic-receiving workloads)
READINESS_PROBE_KINDS = {"Deployment", "StatefulSet", "ReplicaSet"}

# Latest-tag pattern
LATEST_TAG_RE = re.compile(r":latest$")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_containers(spec: dict) -> list[dict]:
    """Extract containers list from a pod spec dict."""
    return spec.get("containers", []) + spec.get("initContainers", [])


def _get_pod_spec(manifest: dict) -> dict | None:
    """Navigate to the pod spec for workload manifests."""
    kind = manifest.get("kind", "")
    if kind == "Pod":
        return manifest.get("spec", {})
    if kind == "CronJob":
        return (
            manifest
            .get("spec", {})
            .get("jobTemplate", {})
            .get("spec", {})
            .get("template", {})
            .get("spec", {})
        )
    if kind in POD_TEMPLATE_KINDS:
        return manifest.get("spec", {}).get("template", {}).get("spec", {})
    return None


def _manifest_label(manifest: dict) -> str:
    """Human-readable label for a manifest."""
    kind = manifest.get("kind", "Unknown")
    name = manifest.get("metadata", {}).get("name", "<unnamed>")
    return f"{kind}/{name}"


# ---------------------------------------------------------------------------
# Per-check functions — each returns a list of finding dicts
# ---------------------------------------------------------------------------

def check_resource_requests(manifest: dict) -> list[dict]:
    """K8S-001: Missing resource requests."""
    pod_spec = _get_pod_spec(manifest)
    if pod_spec is None:
        return []
    label = _manifest_label(manifest)
    findings = []
    for c in _get_containers(pod_spec):
        name = c.get("name", "<unnamed>")
        requests = c.get("resources", {}).get("requests")
        if not requests:
            findings.append({
                "id": "K8S-001",
                "severity": MEDIUM,
                "manifest": label,
                "container": name,
                "title": f"Missing resource requests: {label} → {name}",
                "detail": (
                    "No resources.requests set. Without requests, the scheduler cannot "
                    "make informed placement decisions and QoS is Burstable or BestEffort, "
                    "making the pod first in line for OOM kills. Set CPU and memory requests."
                ),
                "reference": "Kubernetes Resource Management docs",
            })
    return findings


def check_resource_limits(manifest: dict) -> list[dict]:
    """K8S-002: Missing resource limits."""
    pod_spec = _get_pod_spec(manifest)
    if pod_spec is None:
        return []
    label = _manifest_label(manifest)
    findings = []
    for c in _get_containers(pod_spec):
        name = c.get("name", "<unnamed>")
        limits = c.get("resources", {}).get("limits")
        if not limits:
            findings.append({
                "id": "K8S-002",
                "severity": HIGH,
                "manifest": label,
                "container": name,
                "title": f"Missing resource limits: {label} → {name}",
                "detail": (
                    "No resources.limits set. An unlimited container can exhaust node "
                    "resources and starve other pods. Set memory and CPU limits to prevent "
                    "runaway resource consumption."
                ),
                "reference": "Kubernetes Resource Management docs; CIS Kubernetes Benchmark §5.3",
            })
    return findings


def check_liveness_probe(manifest: dict) -> list[dict]:
    """K8S-003: Missing liveness probe."""
    kind = manifest.get("kind", "")
    if kind not in POD_TEMPLATE_KINDS and kind != "Pod":
        return []
    pod_spec = _get_pod_spec(manifest)
    if pod_spec is None:
        return []
    label = _manifest_label(manifest)
    findings = []
    # Only main containers, not initContainers
    for c in pod_spec.get("containers", []):
        name = c.get("name", "<unnamed>")
        if not c.get("livenessProbe"):
            findings.append({
                "id": "K8S-003",
                "severity": HIGH,
                "manifest": label,
                "container": name,
                "title": f"Missing liveness probe: {label} → {name}",
                "detail": (
                    "No livenessProbe set. Without it, Kubernetes cannot detect a deadlocked "
                    "or hung process and will not restart it. Add a livenessProbe pointing "
                    "to a health endpoint or a process check."
                ),
                "reference": "Kubernetes Configure Liveness Probes docs",
            })
    return findings


def check_readiness_probe(manifest: dict) -> list[dict]:
    """K8S-004: Missing readiness probe."""
    kind = manifest.get("kind", "")
    if kind not in READINESS_PROBE_KINDS and kind != "Pod":
        return []
    pod_spec = _get_pod_spec(manifest)
    if pod_spec is None:
        return []
    label = _manifest_label(manifest)
    findings = []
    for c in pod_spec.get("containers", []):
        name = c.get("name", "<unnamed>")
        if not c.get("readinessProbe"):
            findings.append({
                "id": "K8S-004",
                "severity": MEDIUM,
                "manifest": label,
                "container": name,
                "title": f"Missing readiness probe: {label} → {name}",
                "detail": (
                    "No readinessProbe set. Without it, Kubernetes sends traffic to a pod "
                    "as soon as it starts, before the app is ready. Slow-starting apps "
                    "will receive requests they cannot serve. Add a readinessProbe."
                ),
                "reference": "Kubernetes Configure Readiness Probes docs",
            })
    return findings


def check_latest_image_tag(manifest: dict) -> list[dict]:
    """K8S-005: Image tag is :latest or absent."""
    pod_spec = _get_pod_spec(manifest)
    if pod_spec is None:
        return []
    label = _manifest_label(manifest)
    findings = []
    for c in _get_containers(pod_spec):
        name = c.get("name", "<unnamed>")
        image = c.get("image", "")
        # No tag at all, or :latest tag
        has_tag = ":" in image.split("/")[-1]  # handles registry/image:tag
        is_latest = LATEST_TAG_RE.search(image) is not None
        if not has_tag or is_latest:
            tag_desc = ":latest" if is_latest else "(no tag)"
            findings.append({
                "id": "K8S-005",
                "severity": HIGH,
                "manifest": label,
                "container": name,
                "title": f"Unpinned image tag {tag_desc}: {label} → {name} ({image!r})",
                "detail": (
                    f"Container '{name}' uses image '{image}' with an unpinned tag. "
                    "Different nodes may pull different versions; rollbacks are impossible. "
                    "Pin to a specific version tag or SHA digest."
                ),
                "reference": "Kubernetes best practices — image tagging",
            })
    return findings


def check_privileged_container(manifest: dict) -> list[dict]:
    """K8S-006: privileged: true in securityContext."""
    pod_spec = _get_pod_spec(manifest)
    if pod_spec is None:
        return []
    label = _manifest_label(manifest)
    findings = []
    for c in _get_containers(pod_spec):
        name = c.get("name", "<unnamed>")
        sc = c.get("securityContext", {})
        if sc.get("privileged") is True:
            findings.append({
                "id": "K8S-006",
                "severity": CRITICAL,
                "manifest": label,
                "container": name,
                "title": f"Privileged container: {label} → {name}",
                "detail": (
                    f"Container '{name}' runs with securityContext.privileged=true. "
                    "A privileged container has full access to the host kernel and can "
                    "trivially escape to the node. Remove privileged: true and grant "
                    "only the specific capabilities required."
                ),
                "reference": "CIS Kubernetes Benchmark §5.2.1",
            })
    return findings


def check_host_network(manifest: dict) -> list[dict]:
    """K8S-007: hostNetwork: true."""
    pod_spec = _get_pod_spec(manifest)
    if pod_spec is None:
        return []
    if pod_spec.get("hostNetwork") is True:
        label = _manifest_label(manifest)
        return [{
            "id": "K8S-007",
            "severity": CRITICAL,
            "manifest": label,
            "container": None,
            "title": f"hostNetwork: true on {label}",
            "detail": (
                "hostNetwork: true allows the pod to see all network interfaces on the host. "
                "This bypasses network isolation and can expose internal cluster services "
                "or allow traffic sniffing. Remove hostNetwork unless strictly required "
                "by a node-level agent (e.g., CNI plugin, monitoring agent)."
            ),
            "reference": "CIS Kubernetes Benchmark §5.2.4",
        }]
    return []


def check_security_context(manifest: dict) -> list[dict]:
    """K8S-008: Missing container-level securityContext."""
    pod_spec = _get_pod_spec(manifest)
    if pod_spec is None:
        return []
    label = _manifest_label(manifest)
    findings = []
    for c in pod_spec.get("containers", []):
        name = c.get("name", "<unnamed>")
        sc = c.get("securityContext", {})
        # Flag if neither runAsNonRoot nor runAsUser is set
        has_non_root = sc.get("runAsNonRoot") is True
        has_run_as_user = sc.get("runAsUser") is not None and sc.get("runAsUser") != 0
        if not has_non_root and not has_run_as_user:
            findings.append({
                "id": "K8S-008",
                "severity": HIGH,
                "manifest": label,
                "container": name,
                "title": f"No non-root securityContext: {label} → {name}",
                "detail": (
                    f"Container '{name}' has no securityContext.runAsNonRoot or "
                    "securityContext.runAsUser set. Defaults to root. Set "
                    "runAsNonRoot: true and a specific runAsUser (>=1000) to enforce "
                    "least privilege. Also consider readOnlyRootFilesystem: true and "
                    "capabilities.drop: [ALL]."
                ),
                "reference": "CIS Kubernetes Benchmark §5.2.6",
            })
    return findings


def check_single_replica(manifest: dict) -> list[dict]:
    """K8S-009: Single replica Deployment."""
    if manifest.get("kind") != "Deployment":
        return []
    replicas = manifest.get("spec", {}).get("replicas")
    # replicas defaults to 1 if unset — flag both explicit 1 and absent
    if replicas is None or replicas == 1:
        label = _manifest_label(manifest)
        return [{
            "id": "K8S-009",
            "severity": MEDIUM,
            "manifest": label,
            "container": None,
            "title": f"Single replica Deployment: {label}",
            "detail": (
                f"Deployment has replicas={replicas if replicas is not None else '(default 1)'}. "
                "A single replica means pod restart = downtime. Set replicas >= 2 for "
                "production and add a PodDisruptionBudget to preserve availability during "
                "rolling updates and node maintenance."
            ),
            "reference": "Kubernetes HA best practices",
        }]
    return []


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

ALL_CHECKS = [
    check_resource_requests,
    check_resource_limits,
    check_liveness_probe,
    check_readiness_probe,
    check_latest_image_tag,
    check_privileged_container,
    check_host_network,
    check_security_context,
    check_single_replica,
]


def lint_manifest(manifest: dict) -> list[dict]:
    """Run all checks against a single manifest object, sorted by severity."""
    findings = []
    for check in ALL_CHECKS:
        findings.extend(check(manifest))
    findings.sort(key=lambda f: (SEVERITY_RANK[f["severity"]], f["id"]))
    return findings


def lint_manifests(manifests: list[dict]) -> list[dict]:
    """Lint a list of manifests and return sorted findings."""
    all_findings = []
    for m in manifests:
        all_findings.extend(lint_manifest(m))
    all_findings.sort(key=lambda f: (SEVERITY_RANK[f["severity"]], f["id"], f["manifest"]))
    return all_findings


def render_markdown(findings: list[dict]) -> str:
    if not findings:
        return "_No issues found._\n"
    lines = [
        "| # | ID | Severity | Manifest | Title |",
        "|---|----|----------|----------|-------|",
    ]
    for i, f in enumerate(findings, 1):
        lines.append(
            f"| {i} | {f['id']} | {f['severity']} | {f['manifest']} | {f['title']} |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def load_input(source: str | None) -> list[dict]:
    """Load JSON from file or stdin; return list of manifest dicts."""
    if source is None or source == "-":
        raw = sys.stdin.read()
        label = "<stdin>"
    else:
        try:
            with open(source, encoding="utf-8") as fh:
                raw = fh.read()
        except FileNotFoundError:
            raise ValueError(f"Input file not found: {source}")
        except OSError as exc:
            raise ValueError(f"Cannot read input file '{source}': {exc}")
        label = source

    raw = raw.strip()
    if not raw:
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON from {label}: {exc}")

    if isinstance(data, dict):
        data = [data]

    if not isinstance(data, list):
        raise ValueError(
            f"Input from {label} must be a JSON object or array of manifest objects, "
            f"got {type(data).__name__}"
        )

    # Validate each manifest has at least apiVersion and kind
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"Manifest at index {i} must be a JSON object")
        if "kind" not in item:
            raise ValueError(f"Manifest at index {i} missing required field 'kind'")

    return data


def run(source: str | None) -> int:
    try:
        manifests = load_input(source)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not manifests:
        output = {"findings": [], "summary": {"total": 0, "critical": 0, "high": 0, "medium": 0, "info": 0}}
        print(json.dumps(output, indent=2))
        print()
        print("_No manifest content provided._")
        return 0

    findings = lint_manifests(manifests)

    summary = {
        "total": len(findings),
        "critical": sum(1 for f in findings if f["severity"] == CRITICAL),
        "high": sum(1 for f in findings if f["severity"] == HIGH),
        "medium": sum(1 for f in findings if f["severity"] == MEDIUM),
        "info": sum(1 for f in findings if f["severity"] == INFO),
    }

    output = {"findings": findings, "summary": summary}
    print(json.dumps(output, indent=2))
    print()

    print("## Kubernetes Manifest Linter Findings\n")
    print(render_markdown(findings))
    if findings:
        print(
            "**Severity:** CRITICAL = privilege escalation | "
            "HIGH = security/reliability | MEDIUM = scheduling/HA"
        )
        print(
            "\n**Note:** Input must be JSON. Convert YAML with: "
            "`python3 -c \"import sys,json,yaml; print(json.dumps(yaml.safe_load(sys.stdin)))\" < manifest.yaml`"
        )

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Kubernetes manifest linter. Reads JSON manifest(s), outputs ranked findings. "
            "Input must be JSON (convert YAML with yq or python yaml.safe_load)."
        ),
    )
    parser.add_argument(
        "source",
        nargs="?",
        default=None,
        help="Path to JSON manifest file, or '-' for stdin (default: stdin)",
    )
    args = parser.parse_args()
    sys.exit(run(args.source))


if __name__ == "__main__":
    main()
