---
name: tutorial-patterns
description: >-
  Tutorial and how-to guide patterns for progressive learning experiences.
  Covers Diátaxis tutorial/how-to structure, quickstart design, step-by-step
  walkthrough writing, anti-patterns, and progressive disclosure. Use proactively
  when writing tutorials, how-to guides, getting-started docs, or README files.
version: 1.0.0
allowed-tools: [Read, Edit, Glob, Grep, Write]
tags: [tutorial, guide, how-to, quickstart, documentation, anti-pattern, best-practice]
---

# Tutorial Patterns

Patterns for creating tutorials that take users from zero to success with minimal friction.

## Purpose

- Structure tutorials for progressive learning
- Ensure users can verify success at each step
- Reduce drop-off by addressing common failures

---

## Core Patterns

### Pattern 1: Quickstart Structure

**When to use:** Getting users to first success in under 5 minutes.

**Implementation:**
```markdown
# Quick Start

Get [feature] running in 5 minutes.

## Prerequisites
- [Tool] version X or higher
- [Credential/access] (get from [location])

## Steps

### 1. Install
```bash
npm install package-name
```

### 2. Configure
Create `config.json`:
```json
{
  "apiKey": "your-key-here"
}
```

### 3. Run
```bash
npm run start
```

Expected output:
```
Server running on http://localhost:3000
```

## Verify It Works
Open http://localhost:3000 - you should see [description].

## Next Steps
- [Link to detailed configuration]
- [Link to advanced features]
```

**Benefits:**
- Users reach success quickly
- Clear verification at each step
- Natural progression to deeper content

### Pattern 2: Task-Oriented Guide

**When to use:** Explaining how to accomplish a specific goal.

**Implementation:**
```markdown
# How to [Accomplish Goal]

This guide shows how to [specific outcome].

## Before You Begin
You'll need:
- [Prerequisite 1] - [why needed]
- [Prerequisite 2] - [why needed]

## Steps

### Step 1: [Action Verb] the [Thing]

[Brief explanation of why this step matters]

```bash
[command]
```

You should see:
```
[expected output]
```

> **Note:** If you see [error], try [fix].

### Step 2: [Action Verb] the [Thing]

[Continue pattern...]

## Verification

To confirm success:
1. [Check 1]
2. [Check 2]

## Troubleshooting

### Problem: [Common issue]
**Cause:** [Why it happens]
**Solution:** [How to fix]

### Problem: [Another issue]
**Cause:** [Why]
**Solution:** [Fix]
```

**Benefits:**
- Goal-focused, not feature-focused
- Anticipates problems
- Clear success criteria

---

## Anti-Patterns

### Anti-Pattern 1: Missing Prerequisites

| Aspect | Description |
|--------|-------------|
| **WHY** | Users hit walls mid-tutorial; frustration leads to abandonment |
| **DETECTION** | Tutorial jumps into steps without setup section; uses tools without mentioning installation |
| **FIX** | List all prerequisites with versions and how to obtain them |

**Bad Example:**
```markdown
# Deploy to Production

Run the deployment script:
```bash
./deploy.sh --env production
```
```

**Good Example:**
```markdown
# Deploy to Production

## Prerequisites
- Docker 20.0+ installed (`docker --version`)
- AWS CLI configured (`aws configure`)
- Production credentials in `.env.production`

## Steps
### 1. Build the container
```bash
docker build -t myapp:latest .
```

### 2. Deploy
```bash
./deploy.sh --env production
```
```

### Anti-Pattern 2: No Expected Output

| Aspect | Description |
|--------|-------------|
| **WHY** | Users don't know if step succeeded; silent failures cascade |
| **DETECTION** | Commands without "Expected output" or "You should see" |
| **FIX** | Show exact expected output after every command |

**Bad Example:**
```markdown
### Step 2: Start the server
```bash
npm run dev
```

### Step 3: Configure the database...
```

**Good Example:**
```markdown
### Step 2: Start the server
```bash
npm run dev
```

Expected output:
```
> app@1.0.0 dev
> vite

  VITE v5.0.0  ready in 500 ms

  ➜  Local:   http://localhost:5173/
  ➜  press h + enter to show help
```

> **Stuck?** If you see `EADDRINUSE`, port 5173 is busy. Run `npx kill-port 5173` first.

### Step 3: Configure the database...
```

### Anti-Pattern 3: Missing Troubleshooting

| Aspect | Description |
|--------|-------------|
| **WHY** | 80% of users hit the same issues; without help they abandon |
| **DETECTION** | No troubleshooting section; no inline warnings for common errors |
| **FIX** | Add troubleshooting section with top 3-5 issues; inline warnings for tricky steps |

**Bad Example:**
```markdown
## Conclusion
You've successfully set up the project!
```

**Good Example:**
```markdown
## Troubleshooting

### "Module not found" error
**Cause:** Dependencies not installed.
**Fix:** Run `npm install` in the project root.

### Server won't start
**Cause:** Another process on port 3000.
**Fix:** `npx kill-port 3000` or change PORT in `.env`.

### "Invalid token" on API calls
**Cause:** Token expired or wrong environment.
**Fix:** Generate new token from dashboard, ensure `.env` matches environment.

## Conclusion
You've successfully set up the project!
```

### Anti-Pattern 4: Wall of Text

| Aspect | Description |
|--------|-------------|
| **WHY** | Users skim tutorials; dense paragraphs hide critical information |
| **DETECTION** | Paragraphs > 3 sentences; no code blocks, lists, or tables |
| **FIX** | Use lists, tables, code blocks; one concept per paragraph |

**Bad Example:**
```markdown
To configure the database, you need to first create a new PostgreSQL instance.
Make sure you have PostgreSQL installed on your system. Then create a new
database called myapp_dev. You'll also need to set up a user with the right
permissions. The user should have CREATE and SELECT permissions. After that,
update your .env file with the connection string. The format is
postgresql://user:password@host:port/database.
```

**Good Example:**
```markdown
### Configure Database

1. Create database:
   ```bash
   createdb myapp_dev
   ```

2. Update `.env`:
   ```
   DATABASE_URL=postgresql://user:password@localhost:5432/myapp_dev
   ```

| Variable | Value | Notes |
|----------|-------|-------|
| `user` | Your postgres username | Usually `postgres` |
| `password` | Your postgres password | Set during install |
| `port` | 5432 | Default PostgreSQL port |
```

---

## Validation Checklist

### Pre-Writing
- [ ] Identified target audience and their starting point
- [ ] Tested full workflow myself
- [ ] Noted every place I got stuck

### Writing
- [ ] Prerequisites section complete with versions
- [ ] Every command shows expected output
- [ ] Inline warnings for tricky steps
- [ ] Troubleshooting covers common failures
- [ ] Clear verification of success

### Post-Writing
- [ ] Fresh user can complete in stated time
- [ ] All commands work on clean environment
- [ ] Links and references valid

---

## Related Resources

- Related skills: `cc skill get api-docs`
- Divio documentation system: https://documentation.divio.com/

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-13 | Initial version with anti-patterns |
