---
last_updated: 2026-06-28
status: active
extends: do
type: extension
description: Hetzner Cloud and Mac Mini infrastructure patterns
overrideSections:
  - Infrastructure Overview
  - Debug Commands
  - SSL Certificate Gotchas
preserveSections:
  - Core Methodologies
  - Safety Protocols
fallback: use_base
---

# DevOps Admin Extensions

## Infrastructure Overview

### Hetzner Cloud (Coolify)
- **Server:** CCX23 (4 vCPU, 16GB RAM, 160GB NVMe) in Ashburn, VA
- **Platform:** Coolify (self-hosted PaaS)
- **Proxy:** Traefik with Let's Encrypt SSL
- **Domain:** ineedacopilot.com (Cloudflare DNS)

**Deployed Apps:**
| App | Stack | Domain |
|-----|-------|--------|
| research-copilot | Laravel/Docker | research.ineedacopilot.com |
| preflight-copilot | Next.js/Docker | preflight.ineedacopilot.com |
| insights-copilot API | Python/Docker | insights.ineedacopilot.com |
| insights-copilot Admin | Next.js | insightsadmin.ineedacopilot.com |

### Mac Mini M4 (Local)
- **Runtime:** Colima (business apps)
- **Services:** NocoDB, n8n, Metabase, Docmost, PostgreSQL, Redis

### Application DBs (split across providers — corrected 2026-06-28)
- preflight-copilot → **DigitalOcean** Managed PostgreSQL (`db-postgresql-nyc3-78597`) — still on DO
- research-copilot → **Supabase** PostgreSQL 17.4 (legacy DO MySQL retired)
- insights-copilot → **Coolify/Hetzner** PostgreSQL (DO `research-engine-copilot` is legacy/inactive)

---

## Connectivity Chain

Always check the full connectivity chain when debugging:

```
DNS → Cloudflare → Traefik → Container → App → Database
```

| Layer | What to Check |
|-------|---------------|
| **DNS** | `dig domain.ineedacopilot.com` — points to correct IP |
| **Cloudflare** | Proxy status, SSL mode (Full Strict for production) |
| **Traefik** | `docker logs coolify-proxy` — routing rules active |
| **Container** | `docker ps` — running, healthy |
| **App** | Container logs — no startup errors |
| **Database** | Connection string, credentials, network access |

---

## Debug Commands

### Coolify/Hetzner
```bash
# SSH access
ssh -i ~/.ssh/hetzner_coolify root@<HETZNER_IP>

# Proxy logs
docker logs coolify-proxy --tail 100

# Application logs
docker logs <container_name> --tail 100

# SSL/ACME issues
docker logs coolify-proxy 2>&1 | grep -i "acme\|certificate\|error"

# Check all containers
docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Resource usage
docker stats --no-stream
```

### Mac Mini
```bash
docker ps -a          # All containers
docker logs <service> --tail 100
curl -v http://localhost:<port>

# Colima status
colima status
colima restart  # If containers not starting
```

---

## SSL Certificate Gotchas

1. **Force HTTPS must be OFF** during initial certificate generation
2. Let's Encrypt needs direct HTTP access for ACME challenge
3. Re-enable Force HTTPS after certificate is issued
4. Cloudflare proxy (orange cloud) must be OFF until cert issued
5. After cert: Cloudflare "Full (Strict)" SSL mode

### SSL Debug Sequence
```bash
# 1. Check current cert status
docker logs coolify-proxy 2>&1 | grep -i "certificate"

# 2. If renewal failing, disable Cloudflare proxy temporarily
# 3. Check ACME logs
docker logs coolify-proxy 2>&1 | grep -i "acme"

# 4. Force renewal (if needed)
# Via Coolify UI: Remove and re-add the domain
```

---

## Product-Specific Notes

### Research Copilot (Laravel)
- **Container:** research-copilot
- **Queue:** Requires Redis for Laravel queues
- **Env issues:** Check `.env` mounting in Docker

### Insights Copilot (Python)
- **API Container:** insights-copilot-api
- **Admin Container:** insights-copilot-admin
- **Database:** Uses DigitalOcean managed PostgreSQL
- **Migrations:** Run via Alembic inside container

### Pre-Flight Copilot (Next.js)
- **Container:** preflight-copilot
- **Build issues:** Check Next.js build logs, memory limits

---

## Reference Documents

### Always Load
- `04-shared-systems/platform/00-overview.md` — Infrastructure topology

### Load As Needed
| Document | Trigger |
|----------|---------|
| `02-products/*/20-deployment.md` | Product-specific deployment |
| `03-ai-enabling/03-operations/02-security-guidelines.md` | Security questions |

---

## Safety Checks

Before acting on production:
- [ ] Is this production? (Extra caution)
- [ ] Could this cause data loss? (Backup first, human approval)
- [ ] Does this affect other services? (Notify/coordinate)
- [ ] Is this reversible? (Document rollback plan)
- [ ] Does this involve secrets? (Human handles)

---

## Golden Rule

**Diagnose first. One change at a time. Verify before proceeding.**

---

_Last Updated: December 2025_
