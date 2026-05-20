---
name: kubernetes
skill_category: devops
description: Kubernetes deployment patterns, resource management, and cluster best practices — with deterministic manifest linting script
version: 2.0.0
source: .claude/skills/devops/kubernetes.md (retired flat file); L3 linter added 2026-05-20
when_to_use:
  - Reviewing or writing Kubernetes manifests
  - Debugging pod scheduling failures or OOM kills
  - Security review of cluster workloads
  - Preparing workloads for production deployment
allowed-tools:
  - Read
  - Grep
  - Glob
  - Bash
tags: [kubernetes, k8s, containers, anti-pattern, best-practice, deployment]
trigger_files: ["**/k8s/*.yaml", "**/k8s/*.yml", "**/kubernetes/*.yaml", "**/kubernetes/*.yml", "**/deployment.yaml", "Helm*", "**/charts/**/*.yaml"]
trigger_keywords: [kubernetes, k8s, kubectl, deployment, pod, service, ingress, helm, container orchestration]
---

# Kubernetes Patterns

Best practices and anti-patterns for Kubernetes deployments, resource configuration, and cluster management. Run the linter on every manifest before review; use this prose guidance to explain findings and propose fixes.

## Purpose

- Ensure reliable, scalable Kubernetes deployments
- Prevent resource exhaustion and scheduling failures
- Establish security and observability patterns

---

## Core Patterns

### Pattern 1: Resource Requests and Limits

**When to use:** Every production container deployment.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-service
spec:
  template:
    spec:
      containers:
        - name: api
          image: api:v1.2.3
          resources:
            requests:
              memory: "256Mi"
              cpu: "250m"
            limits:
              memory: "512Mi"
              cpu: "500m"
```

**Benefits:** Predictable scheduling, protection against resource exhaustion, fair resource sharing across pods.

### Pattern 2: Health Probes

**When to use:** All production deployments.

```yaml
containers:
  - name: api
    livenessProbe:
      httpGet:
        path: /health
        port: 8080
      initialDelaySeconds: 30
      periodSeconds: 10
      failureThreshold: 3
    readinessProbe:
      httpGet:
        path: /ready
        port: 8080
      initialDelaySeconds: 5
      periodSeconds: 5
      successThreshold: 1
```

**Benefits:** Auto-restart unhealthy pods, traffic only to ready pods, graceful startup handling.

### Pattern 3: Pod Disruption Budgets

**When to use:** Production services requiring high availability.

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: api-pdb
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: api
```

---

## Anti-Patterns

### Anti-Pattern 1: No Resource Limits

| Aspect | Description |
|--------|-------------|
| **WHY** | Unlimited resources cause node exhaustion, OOM kills, and unpredictable scheduling. One pod can starve others. |
| **DETECTION** | Missing `resources.limits` in container specs. |
| **FIX** | Always set requests (guaranteed) and limits (maximum). |

### Anti-Pattern 2: Using :latest Tag

| Aspect | Description |
|--------|-------------|
| **WHY** | Non-reproducible deployments. Rollbacks impossible. Different nodes may pull different versions. |
| **DETECTION** | Image tags ending in `:latest` or no tag specified. |
| **FIX** | Use specific semantic version tags. Pin to exact digest for critical workloads. |

### Anti-Pattern 3: Missing Health Probes

| Aspect | Description |
|--------|-------------|
| **WHY** | Kubernetes can't detect unhealthy pods. Traffic goes to broken pods. No auto-recovery. |
| **DETECTION** | Deployments without `livenessProbe` or `readinessProbe`. |
| **FIX** | Add both probes. Liveness for restart, readiness for traffic routing. |

### Anti-Pattern 4: Running as Root

| Aspect | Description |
|--------|-------------|
| **WHY** | Container escape vulnerabilities are exploitable as root. Violates least privilege. |
| **DETECTION** | No `securityContext` or `runAsNonRoot: false`. Missing `runAsUser`. |
| **FIX** | Set `runAsNonRoot: true`. Specify non-root user. Drop all capabilities. |

### Anti-Pattern 5: Single Replica in Production

| Aspect | Description |
|--------|-------------|
| **WHY** | No fault tolerance. Pod restart = downtime. No rolling update capability. |
| **DETECTION** | `replicas: 1` in production deployments. No PDB defined. |
| **FIX** | Minimum 2 replicas for production. Add PodDisruptionBudget. Use anti-affinity. |

---

## Validation Checklist

### Implementation
- [ ] Resource requests and limits set
- [ ] Specific image tags (no :latest)
- [ ] Liveness and readiness probes configured
- [ ] Security context with non-root user
- [ ] ConfigMaps/Secrets for configuration
- [ ] Multiple replicas with anti-affinity
- [ ] PodDisruptionBudget defined

### Post-Implementation
- [ ] Pods schedule successfully
- [ ] Health checks pass consistently
- [ ] Rolling updates work without downtime
- [ ] `kubectl get events` shows no warnings

---

## Invocation — Kubernetes Manifest Linter (L3 Script)

Run the linter on every manifest before review. Consume its **output only** — the script source never enters context.

**Input:** JSON representation of one or more Kubernetes manifests. YAML must be converted to JSON first (see below).

**YAML to JSON conversion:**
```bash
python3 -c "import sys,json,yaml; print(json.dumps(yaml.safe_load(sys.stdin)))" < deployment.yaml \
  | python .claude/skills/devops/kubernetes/scripts/k8s_lint.py -
```

Or with `yq`:
```bash
yq -o json deployment.yaml | python .claude/skills/devops/kubernetes/scripts/k8s_lint.py -
```

**Run via Bash (file argument — JSON):**
```bash
python .claude/skills/devops/kubernetes/scripts/k8s_lint.py manifest.json
```

**Run via Bash (stdin — JSON):**
```bash
cat manifest.json | python .claude/skills/devops/kubernetes/scripts/k8s_lint.py -
```

**Input format — single manifest:**
```json
{"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "api"}, "spec": {...}}
```

**Input format — multiple manifests:**
```json
[
  {"kind": "Deployment", ...},
  {"kind": "Service", ...}
]
```

**Output:**
1. JSON object with `findings` array (each finding has `id`, `severity`, `manifest`, `container`, `title`, `detail`, `reference`) and `summary` counts.
2. Markdown findings table sorted by severity (CRITICAL → HIGH → MEDIUM).

**Findings covered:**

| ID | Check | Severity | Source |
|----|-------|----------|--------|
| K8S-001 | Missing resource requests | MEDIUM | Kubernetes Resource Management docs |
| K8S-002 | Missing resource limits | HIGH | Kubernetes docs; CIS §5.3 |
| K8S-003 | Missing liveness probe | HIGH | Kubernetes Configure Probes docs |
| K8S-004 | Missing readiness probe | MEDIUM | Kubernetes Configure Probes docs |
| K8S-005 | Image tag :latest or untagged | HIGH | Kubernetes best practices |
| K8S-006 | privileged: true | CRITICAL | CIS Kubernetes Benchmark §5.2.1 |
| K8S-007 | hostNetwork: true | CRITICAL | CIS Kubernetes Benchmark §5.2.4 |
| K8S-008 | No non-root securityContext | HIGH | CIS Kubernetes Benchmark §5.2.6 |
| K8S-009 | Single replica Deployment | MEDIUM | Kubernetes HA best practices |

**What to do with the output:**
1. CRITICAL findings (privileged containers, hostNetwork) must be blocked — these are container escape paths.
2. HIGH findings must be addressed before production deployment.
3. MEDIUM findings are strongly recommended; document and justify any exceptions.

**Error handling:** The script exits non-zero with an ERROR message to stderr on I/O failure or invalid JSON. The `kind` field is required in every manifest.

---

## Quick Reference

| Task | Pattern |
|------|---------|
| Prevent resource exhaustion | Set requests and limits |
| Auto-restart broken pods | Liveness probe |
| Route traffic to ready pods | Readiness probe |
| Reproducible deployments | Specific version tags |
| Secure containers | Non-root, drop capabilities |
| High availability | Multiple replicas + PDB |
| External configuration | ConfigMaps + Secrets |
