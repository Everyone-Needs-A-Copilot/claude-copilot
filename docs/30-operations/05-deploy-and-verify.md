# How to Deploy and Verify

**Diátaxis mode:** How-to

**Audience:** Developer who needs to deploy an app to staging or production and verify it worked. You know the project; you just need the right commands and sequence.

**Prerequisites:**
- Claude Copilot project setup complete (`/setup-project` run)
- `tc` CLI available (`tc --version`)
- `copilot` CLI on PATH if using `tc deploy wait` — see [SETUP.md external dependencies](../../SETUP.md#external-dependencies)

---

## The Short Version

```bash
# In Claude Code:
/protocol deploy to staging

# If you need tc deploy wait directly:
tc deploy wait <app-uuid>
tc deploy wait <app-uuid> --test tests/e2e/staging.spec.ts
```

That's it for most cases. Read on for what happens under the hood and how to handle edge cases.

---

## Step 1: Trigger Flow E (Infrastructure Flow)

Use `/protocol` with any infra-flavored description. The protocol recognizes deploy-related keywords and routes to `@agent-do` instead of the generic technical flow.

**Keywords that trigger Flow E:** deploy, staging, production, docker, kubernetes, ci/cd, infra, terraform, migration

```
/protocol deploy to staging
/protocol set up staging environment for the payments service
/protocol fix the production deployment failure
/protocol run the database migration on staging
```

**What you get back from Flow E:**

```
[PROTOCOL: INFRA | Agent: @agent-do | Action: INVOKING]
Detected: Infrastructure/deploy → Routing to DevOps...
```

`@agent-do` plans and executes the infra changes. If code changes are needed, it hands off to `@agent-me`. When done, `@agent-qa` verifies using `tc deploy wait` or health checks.

**If both infra and technical keywords are present** (e.g., "refactor and deploy the auth module"), Flow E takes precedence. Use `--skip-do` if you need to override and go straight to the technical flow.

---

## Step 2: Wait for Deploy to Complete

If `@agent-do` or `@agent-qa` calls `tc deploy wait` on your behalf, you don't need to do anything. But if you're running a deploy step manually or want to trigger verification yourself:

```bash
# Wait for deploy to complete (blocks until done or timeout)
tc deploy wait <app-uuid>

# Wait + run post-deploy tests when deploy succeeds
tc deploy wait <app-uuid> --test tests/e2e/staging.spec.ts

# Custom timeout (default is 300 seconds)
tc deploy wait <app-uuid> --timeout 600

# Combine flags
tc deploy wait <app-uuid> --test tests/e2e/staging.spec.ts --timeout 600
```

**Get the app UUID:**

```bash
copilot app list
# or check your .copilot/environments.json
```

**Exit codes:**

| Code | Meaning |
|------|---------|
| 0 | Deploy succeeded (and tests passed if `--test` was given) |
| 1 | Deploy failed or timed out |
| 2 | Tests ran but failed |
| 4 | `copilot` CLI not found on PATH |

Exit code 4 means the `copilot` CLI is not installed. `tc deploy wait` does not hang in this case — it fails fast with a clear error. See [SETUP.md](../../SETUP.md#external-dependencies) for installation.

---

## Step 3: QA Gate After Implementation

If your deploy involved code changes (Flow E routed through `@agent-me`), the QA gate will block the main session until `@agent-qa` provides a pass verdict.

**What you see:**

```
[QA GATE ACTIVE] @agent-me completed. Main session tools are gated.
Waiting for @agent-qa to run verification...
```

You do not need to do anything here. The gate resolves automatically when `@agent-qa` finishes. If QA fails 3 times in a row, the gate auto-unblocks and emits a human-review advisory — it cannot permanently lock you out.

**If you need to bypass the gate** (e.g., flaky tests, known issue, you're mid-debug):

```bash
export COPILOT_QA_GATE=off
```

Set this in your shell before starting the session, or in the session itself. Clear it when you're done: `unset COPILOT_QA_GATE`.

---

## Step 4: Verify Manually If Needed

After `tc deploy wait` completes, run your smoke tests or health checks:

```bash
# Health check
curl -s https://staging.example.com/health | jq .

# Or let QA do it
# In Claude Code: @agent-qa run post-deploy verification for staging
```

---

## Common Situations

### The deploy is taking longer than expected

Increase the timeout:

```bash
tc deploy wait <app-uuid> --timeout 900
```

If it's genuinely hung (not just slow), press Ctrl+C. `tc deploy wait` does not leave background processes running — it's a blocking poll, not a daemon.

### I need to deploy without going through the full Flow E routing

You can invoke `@agent-do` directly:

```
In Claude Code: @agent-do deploy the app to staging using the existing config
```

`@agent-do` still uses `tc deploy wait` internally. The QA gate still applies after any `@agent-me` handoff within that session.

### I have a deploy script that was working before (manual bash polling)

You don't need to rewrite it immediately. But when you're ready:

**Old pattern (avoid):**
```bash
until curl -s https://staging.example.com/health | grep -q '"status":"ok"'; do
  echo "Waiting..."
  sleep 5
done
```

**New pattern:**
```bash
tc deploy wait <app-uuid> --test tests/e2e/health.spec.ts
```

The old pattern requires you to invent the polling logic each time, gets copy-pasted across sessions, and has no consistent exit code. `tc deploy wait` is one call with predictable behavior.

### The `copilot` CLI is not installed

```bash
# Install from cli-copilot
brew install copilot-cli    # or follow SETUP.md

# Verify
copilot version

# Check tc can see it
tc deploy wait --help
```

If you cannot install `copilot` right now, `tc deploy wait` will exit with code 4. Your deploy can still proceed — you just won't have the blocking-wait primitive. Fall back to a one-shot health check:

```bash
curl -f https://staging.example.com/health
```

---

## Escape Hatches Reference

| Env Var | What it disables |
|---------|-----------------|
| `COPILOT_FORCE_DELEGATE=off` | Force-delegate hook (allows >5 consecutive same-tool calls) |
| `COPILOT_QA_GATE=off` | QA gate after @agent-me (main session unblocked immediately) |
| `COPILOT_SESSION_CAP=off` | Session-cap advisory at 500 turns |

These are scoped to the current shell. They do not persist across sessions.

---

## Related

- [Framework Restructure — why tc deploy wait exists](../10-architecture/04-framework-restructure-2026-04.md)
- [Hooks README](../../.claude/hooks/README.md) — full hook reference and state files
- [SETUP.md — External Dependencies](../../SETUP.md#external-dependencies) — copilot CLI installation
- [Working Protocol](01-working-protocol.md) — Flow E and other flow details
