# Live Docs — `cc docs`

**Diátaxis mode:** Explanation + How-to

Agents fetch version-specific documentation for installed packages instead of relying on training-data memory, so they code against the real installed API.

---

## The Problem: Stale Training-Data APIs

When an agent implements a call to a third-party library — say, `openai`, `stripe`, `fastapi`, or `react-router` — it draws on training data that was frozen at a cutoff date. Your project's installed version may be months or years newer (or older). The agent has no way to know this, so it synthesizes plausible-looking API calls that may compile but silently use renamed methods, removed parameters, or changed return shapes.

This is a **silent correctness gap**, not a type error. Tests may not catch it. The agent does not warn you. The failure surface only appears at runtime.

Live Docs closes the gap by giving agents a command to look up what the installed version actually exports, before writing any code.

---

## How It Works

### Source Order (Local-First)

`cc docs get <pkg>` resolves documentation through a prioritised source chain:

| Priority | Source | Availability | Version accuracy |
|----------|--------|--------------|-----------------|
| 1 (primary) | Installed package files on disk | Always (offline) | Exact — reads the files in your virtualenv or `node_modules` |
| 2 (fallback) | Fetch: `llms.txt` at project URL | Requires `httpx` extra + network | Approximate — may lag a patch |
| 3 (fallback) | Fetch: GitHub raw at version tag | Requires `httpx` extra + network | Good — tag-pinned |
| 4 (fallback) | Fetch: package docs site | Requires `httpx` extra + network | Variable |

The fallback chain only runs if local discovery fails (package not installed, no extractable docs on disk). The `exact: bool` field in every response tells you which path was used.

**Offline/headless guarantee:** The local-first path has no network dependency. CI, air-gapped environments, and containerised agents all work without the `httpx` extra installed.

### Response Format

`cc docs get` returns a focused docs slice — not a raw file dump. It contains:

- Detected package version
- `exact: bool` — `true` if sourced from installed files
- Relevant API surface for the requested topic (or top-level exports if no `--topic` given)
- Source label (local / fetch + which fallback tier)

---

## Command Reference

### `cc docs get <pkg>`

Fetch documentation for an installed package. This is the primary command agents call.

```bash
# Get top-level docs for the installed version of openai
cc docs get openai

# Get docs scoped to a specific topic
cc docs get openai --topic chat-completions

# Force a fresh fetch, ignoring cache
cc docs get stripe --refresh

# JSON output (for agent consumption)
cc docs get fastapi --topic routing --json

# Override source resolution (local|fetch|auto)
cc docs get react-router --source local
```

**Flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `--topic <topic>` | — | Scope output to a specific API area |
| `--source auto\|local\|fetch` | `auto` | Override source order; `local` never fetches |
| `--refresh` | false | Bypass cache and re-resolve |
| `--json` | false | Emit structured JSON (for programmatic use) |

---

### `cc docs resolve <pkg>`

Print the detected installed version and which source would be used, without fetching docs. Use this to diagnose version detection before a `get`.

```bash
cc docs resolve openai
# → openai 1.35.3 | source: local | exact: true
```

---

### `cc docs search <pkg> <query>`

Keyword search within cached docs for a package. Returns matching sections.

```bash
cc docs search stripe "payment intent create"
cc docs search fastapi "dependency injection"
```

---

### `cc docs sources`

List all registered source backends and their status (enabled, requires extra, configured endpoint).

```bash
cc docs sources
# → local    enabled   (always available)
# → fetch    requires cc[fetch] extra
# → context7 disabled  (no endpoint configured — see docs.context7_endpoint)
```

---

### `cc docs cache`

Inspect or flush the local documentation cache.

```bash
# Show cache status (packages cached, sizes, age)
cc docs cache --status

# Clear cache for one package
cc docs cache --clear openai

# Clear entire cache
cc docs cache --clear
```

---

## Configuration Keys

All keys are set via `cc config set <key> <value>`:

| Key | Default | Description |
|-----|---------|-------------|
| `docs.cache_ttl_hours` | `168` (7 days) | How long cached docs are considered fresh |
| `docs.context7_endpoint` | — | Reserved — enables Context7 backend when set (see [Context7 note](#context7-deferred)) |

Cache files are gitignored. They live in the `cc` tool's cache directory and do not travel with the repo.

---

## Agent Usage

### When agents should reach for `cc docs`

@agent-me and @agent-ta are wired with the following trigger in their shared behaviors:

> Before implementing against any installed third-party package, run `cc docs get <pkg> --topic <relevant-area> --json` to verify the actual installed API surface.

In practice: any time an agent is about to call an external library's method, constructor, or hook — not a stdlib function — it should first check Live Docs if it has not already done so in the current task.

### Example: agent workflow

```bash
# Agent is about to implement a chat call using the openai package
cc docs get openai --topic chat-completions --json
# → { "version": "1.35.3", "exact": true, "content": "... ChatCompletion.create signature ..." }

# Agent now implements against the confirmed API, not training-data memory
```

### In a `python3` api block (Code Execution Path)

When batching multiple ops, agents can call `cc docs` via Bash before the python3 block, or use the CLI in sequence:

```bash
# Resolve first, then get topic
cc docs resolve openai && cc docs get openai --topic embeddings --json
```

The `cc docs` commands are not part of `cc.api` (they are read-only reference lookups, not database writes), so single CLI calls are appropriate here.

---

## Installing the Optional Fetch Extra

The base `cc` install is network-free. To enable the fetch fallback chain:

```bash
pip install "cc[fetch]"
```

This installs `httpx`. Without it, `cc docs get` works only when the package is installed locally. If local docs are unavailable and `httpx` is not installed, the command returns a clear error rather than silently returning training-data content.

---

## Limitations

Be honest about what Live Docs can and cannot do:

| Limitation | Detail |
|-----------|--------|
| **Local docs only as good as what ships on disk** | Some packages ship minimal or no extractable documentation in their installed files (wheel/egg). For those, local resolution will find little and fall through to the fetch chain. |
| **Fetch requires `httpx` and network** | Air-gapped environments and CI without the extra installed will only have local resolution. |
| **npm + pip only** | Go modules, Cargo crates, Ruby gems, and other ecosystems are not supported in this release. |
| **Context7 not included** | See below. |
| **`exact: true` means source was local — not that the docs are complete** | A package may install with partial or auto-generated docs. The flag confirms the version, not the coverage. |

---

## Context7 Deferred

Context7 was evaluated during design and deliberately excluded (ADR-002). The reasons:

- Context7 is an external, authenticated service. Requiring it reintroduces the headless/offline fragility that the local-first design explicitly avoids.
- CI environments, air-gapped machines, and containerised agents all become dependent on a third-party endpoint.
- The local-first chain already covers the highest-value case (exact installed version) without any external dependency.

A **pluggable `SourceBackend` seam** is built into the implementation. The reserved `docs.context7_endpoint` config key means Context7 can be enabled for a project or machine by setting one config value — no code change required. It is a drop-in when the time is right.

---

## Troubleshooting

**`cc docs get openai` returns nothing / "no local docs found"**

The package may not ship extractable docs in its installed files. Try:

```bash
cc docs resolve openai          # Confirm version is detected
cc docs get openai --source fetch   # Force fetch path (requires httpx extra)
```

**`cc docs get` fails with "httpx not installed"**

You are hitting the fetch fallback without the extra installed. Either install `cc[fetch]` or use `--source local` to restrict to on-disk docs.

**Cached docs are stale**

```bash
cc docs cache --clear openai    # Clear one package
cc docs get openai --refresh    # Or force refresh on next call
```

**Agent still using training-data APIs despite Live Docs**

Check that the agent called `cc docs get` before implementing (not after). If the response had `exact: false`, the fetch path was used — inspect `cc docs resolve <pkg>` to understand why local resolution failed.
