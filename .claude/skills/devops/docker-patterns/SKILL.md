---
name: docker-patterns
skill_category: devops
description: >-
  Dockerfile optimization, multi-stage builds, image security, container best
  practices, and docker-compose patterns — with deterministic linting script.
  Covers image size reduction, layer caching, registry hygiene, and production
  deployment readiness. Use proactively when reviewing or writing Dockerfiles,
  debugging image size or build speed issues, running a container security
  review, or preparing images for production deployment. Run the linter for
  deterministic issue detection.
version: 2.0.0
source: .claude/skills/devops/docker-patterns.md (retired flat file); L3 linter added 2026-05-20
when_to_use:
  - Reviewing or writing Dockerfiles
  - CI pipeline fails due to image size or build speed
  - Security review of container images
  - Preparing images for production deployment
allowed-tools:
  - Read
  - Grep
  - Glob
  - Bash
tags: [docker, containers, devops, security, optimization]
trigger_files: ["Dockerfile*", "docker-compose*", ".dockerignore", "**/containers/**"]
trigger_keywords: [docker, container, dockerfile, image, multi-stage, layer, registry]
---

# Docker Patterns

Dockerfile optimisation, multi-stage builds, image security, and container best practices. Run the linter on every Dockerfile before review; use this prose guidance to explain findings and propose fixes.

## Purpose

- Produce small, secure production images using multi-stage builds
- Maximise layer cache hit rate to speed up CI pipelines
- Eliminate common image security vulnerabilities
- Ensure containers are production-ready with health checks

---

## Multi-Stage Build Pattern

Split the image into a **builder** stage (compile / install) and a **runtime** stage (minimal base). Never ship build tools in production images.

```dockerfile
# syntax=docker/dockerfile:1

# Stage 1: Builder
FROM node:20-alpine AS builder
WORKDIR /app

# Copy dependency manifests first (cache layer)
COPY package.json package-lock.json ./
RUN npm ci --frozen-lockfile

# Copy source and build
COPY . .
RUN npm run build

# Stage 2: Runtime (never includes node_modules/devDependencies or build tools)
FROM node:20-alpine AS runtime
WORKDIR /app

# Non-root user
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
USER appuser

# Copy only production artefacts from builder
COPY --from=builder --chown=appuser:appgroup /app/dist ./dist
COPY --from=builder --chown=appuser:appgroup /app/node_modules ./node_modules

EXPOSE 3000
ENTRYPOINT ["node", "dist/server.js"]
```

**Why this matters:** A typical Node.js image with dev dependencies can reach 800MB+. The runtime-only image is typically under 100MB.

---

## Layer Caching Optimisation

Docker caches each instruction. If a layer's checksum changes, all subsequent layers are invalidated.

**Optimal ordering (least-to-most-frequently-changing):**

```dockerfile
# 1. Base image (changes rarely)
FROM python:3.12-slim

# 2. System dependencies (changes rarely)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 3. App dependency manifests (changes when you add/remove packages)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Source code (changes every commit — LAST)
COPY . .
```

**Never:**
```dockerfile
# BAD: Copies all source first — every code change invalidates the pip install layer
COPY . .
RUN pip install -r requirements.txt
```

**.dockerignore essentials:**
```
.git
.github
node_modules
dist
__pycache__
*.pyc
.env*
coverage/
*.test.*
*.spec.*
README.md
Makefile
```

---

## Image Security Checklist

- [ ] **Non-root user** — always set `USER` directive; never run as root in production
- [ ] **Minimal base image** — prefer `alpine`, `distroless`, or `-slim` variants over full OS images
- [ ] **No secrets in image layers** — use build args at build time or runtime env vars; secrets baked into layers persist in image history
- [ ] **Pin base image versions** — never use `:latest` in production; use digest pinning for critical images (`FROM node:20.11.1-alpine@sha256:...`)
- [ ] **Scan for CVEs** — run Trivy or Snyk on every image before pushing to registry
- [ ] **Read-only filesystem** — where possible, use `--read-only` flag and only mount writable volumes where needed
- [ ] **Drop capabilities** — in Kubernetes/compose, drop all Linux capabilities and add back only what is required

```dockerfile
# Distroless example (Go)
FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY . .
RUN CGO_ENABLED=0 go build -o server .

FROM gcr.io/distroless/static-debian12 AS runtime
COPY --from=builder /app/server /server
ENTRYPOINT ["/server"]
```

---

## Health Check Patterns

Health checks allow orchestrators (Docker Swarm, Kubernetes) to know when a container is truly ready.

```dockerfile
# HTTP application
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://localhost:3000/health || exit 1

# TCP check (non-HTTP service)
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD nc -z localhost 5432 || exit 1
```

**Key parameters:**
- `--interval` — time between checks (default 30s)
- `--timeout` — time to wait for a response before marking unhealthy (default 30s)
- `--start-period` — grace period before checks count as failures (set to your app's boot time)
- `--retries` — consecutive failures before status becomes `unhealthy` (default 3)

Check **actual readiness** (can the app serve traffic?) not just process existence.

---

## Anti-Patterns

| Anti-Pattern | Problem | Fix |
|-------------|---------|-----|
| **Fat images (>500MB for app containers)** | Slow pulls, large attack surface, high registry costs | Multi-stage builds + minimal base image |
| **Running as root** | Container escape gives attacker root on host | Add non-root user with `USER` directive |
| **Secrets in ENV or ARG** | Visible in `docker inspect` and image history | Use Docker secrets, Vault, or runtime env injection |
| **Using :latest in production** | Unpredictable; pulls different image on each build | Pin to a specific version tag or digest |
| **Ignoring .dockerignore** | Copies `.git`, `node_modules`, `.env` into build context — slows builds and risks leaking secrets | Always create `.dockerignore` before first build |
| **Single-stage builds shipping dev deps** | Dev tools and test dependencies inflate image size and attack surface | Use multi-stage builds; runtime stage copies only artefacts |

---

## Invocation — Docker Linter (L3 Script)

Run the linter on any Dockerfile before review. Consume its **output only** — the script source never enters context.

**Input:** Raw Dockerfile text (not JSON). Pass the file directly or pipe via stdin.

**Run via Bash (file argument):**
```bash
python .claude/skills/devops/docker-patterns/scripts/docker_lint.py path/to/Dockerfile
```

**Run via Bash (stdin):**
```bash
cat Dockerfile | python .claude/skills/devops/docker-patterns/scripts/docker_lint.py -
```

**Output:**
1. JSON object with `findings` array (each finding has `id`, `severity`, `title`, `detail`, `reference`) and a `summary` of counts by severity.
2. Markdown findings table sorted by severity (CRITICAL → HIGH → MEDIUM → INFO).

**Findings covered:**

| ID | Check | Severity | Source |
|----|-------|----------|--------|
| DOCKER-001 | No USER directive / USER root | CRITICAL | CIS Docker Benchmark §4.1 |
| DOCKER-002 | FROM uses :latest or no tag | HIGH | Docker best practices |
| DOCKER-003 | Missing HEALTHCHECK | HIGH | Docker best practices |
| DOCKER-004 | apt-get without --no-install-recommends | MEDIUM | Slim-image best practices |
| DOCKER-005 | Secret-like value in ENV or ARG | CRITICAL | CIS Docker Benchmark §4.10 |
| DOCKER-006 | apt/apk without cache cleanup in same layer | MEDIUM | Layer hygiene best practices |
| DOCKER-007 | COPY . . before dependency manifest COPY | MEDIUM | Layer cache optimisation |

**What to do with the output:**
1. Read the markdown table — CRITICAL and HIGH findings must be addressed before the image ships.
2. Use the `detail` field from the JSON to explain why each finding matters and how to fix it.
3. MEDIUM findings are strongly recommended; accept risk only with documented justification.
4. The script exits 0 even when findings are present — the agent decides what to block on.

**Error handling:** The script exits non-zero with an ERROR message to stderr only on I/O failure (file not found, unreadable). It always exits 0 on valid Dockerfile text, even if findings are present.

---

## Related Resources

- [Docker Official Best Practices](https://docs.docker.com/develop/develop-images/dockerfile_best-practices/)
- [Trivy CVE Scanner](https://trivy.dev/)
- [Google Distroless Images](https://github.com/GoogleContainerTools/distroless)
- [CIS Docker Benchmark](https://www.cisecurity.org/benchmark/docker)
- Related skills: `kubernetes`, `ci-cd-patterns`
