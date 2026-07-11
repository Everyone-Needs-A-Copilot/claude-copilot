# Zero-Friction Bootstrap Orchestration — "The Bob Installer"

| | |
|---|---|
| **Status** | Design / Proposed (extends [`02-four-tier-and-github-topology.md`](../02-four-tier-and-github-topology.md), [`03-use-cases.md`](../03-use-cases.md)) |
| **Branch** | `ecosystem-extensions` |
| **Governing persona** | **Bob** — 55, non-technical accountant. No git, no SSH, no GitHub, no idea what "AI" is. One thing to run. Must end with a working AI partner. |
| **Design bar** | "If someone has to manually do this work they're never going to use this. The bar is too high." |

---

## 0. The one sentence

**Bob copies one line into his terminal.** Everything else — installing prerequisites, authenticating, cloning four layers, asking two plain-language questions, materializing, verifying, and teaching him how to extend — happens without him touching a config file, a key, or a URL.

```
/bin/bash -c "$(curl -fsSL https://get.copilot.enac.dev/bootstrap.sh)"
```

That URL is a stable redirect to the raw `bootstrap.sh` in the **public** foundation repo (`Everyone-Needs-A-Copilot/claude-copilot/install/bootstrap.sh`). It is public, anonymous, and versionless — the smallest possible thing that can pull the rest.

**Fallback for the truly terminal-averse:** IT (or ENAC) hands Bob a downloaded `copilot-setup.command` file (a double-clickable macOS shell script). Double-click → Terminal opens → same script runs. Same code path, zero typing.

---

## 1. The single entry point & the chicken-and-egg

**The problem:** the *foundation product* is what's supposed to orchestrate a guided, self-healing setup (it has agents, `cc`, memory, the whole apparatus). But you can't use the foundation to install the foundation. Something dumber has to exist first.

**The resolution — a three-ring model:**

```
RING 0  bootstrap.sh  (curl'd; ~200 lines of POSIX bash; NO dependencies)
          │  installs prerequisites, installs the foundation product, hands off
          ▼
RING 1  copilot doctor --bootstrap   (a real binary/verb, shipped in the foundation)
          │  drives every remaining phase as an idempotent state machine
          ▼
RING 2  the foundation product itself  (agents, cc, tc, memory — Bob's "partner")
```

Ring 0 is deliberately **stupid and stable**: it assumes nothing but `bash`, `curl`, and an internet connection (all present on stock macOS/Linux). Its only jobs are (a) make the machine capable of running Ring 1, and (b) install Ring 1, then `exec` into it. Ring 0 never asks Bob a question, never touches auth, and is safe to re-run. All the *intelligence* — the guided questions, the drift repair, the teaching — lives in Ring 1 (`copilot doctor`), which ships **with** the foundation and therefore always matches its version. This is the same split as `rustup`/`nvm`: a tiny installer that fetches a capable tool, then defers to it.

**Why not "paste a prompt into Claude Code"?** Because Bob doesn't have Claude Code yet, and installing Node + Claude Code + auth is exactly the friction we're removing. The prompt-in-Claude path is a *developer* convenience (Ring 1 can be driven by an agent), not Bob's path. Bob gets a `.sh`.

---

## 2. The install state machine

Every phase is a function in Ring 1 with four declared properties: **precondition** (what must be true to run), **action**, **idempotent check** (how it knows it's already done → skip), and **repair** (what it does on a broken/partial state). The phase runner walks them in order; each is individually re-entrant, so a crash at phase 6 resumes at phase 6 on the next run.

```
┌─ RING 0: bootstrap.sh ─────────────────────────────────────────────┐
│ P0  prereqs      detect/install: git, gh, node, then cc + tc        │
│                  pre: bash+curl · check: `command -v` all green     │
│                  repair: (re)install only the missing ones          │
│ P1  foundation   clone PUBLIC foundation (anon HTTPS), run cc setup  │
│                  pre: P0 · check: ~/.copilot/layers/foundation +     │
│                        `cc --version` · repair: git pull / reclone   │
│        ── Bob has a working partner NOW. Everything below is additive ──
│        ── exec into: copilot doctor --bootstrap (RING 1) ──          │
└─────────────────────────────────────────────────────────────────────┘
┌─ RING 1: copilot doctor --bootstrap ───────────────────────────────┐
│ P2  identity     is this Bob-in-a-company, or solo? auth as needed   │
│                  pre: P1 · check: cc config get layers.mode set      │
│ P3  org layer    clone ORG repo (if company) with right credential   │
│                  pre: P2 auth ok · check: layers/org exists+fresh    │
│ P4  ask dept     plain-language Q; persist cc config layers.dept     │
│                  pre: P3 · check: cc config get layers.department     │
│ P5  dept layer   clone DEPARTMENT repo for the chosen unit           │
│                  pre: P4 · check: layers/dept-<unit> exists+fresh     │
│ P6  personal     scaffold PERSONAL layer (local always; remote opt)  │
│                  pre: P1 · check: layers/personal/.git + manifest     │
│ P7  manifest     write copilot.layers.yml from present layers        │
│                  pre: ≥1 layer · check: manifest matches reality      │
│ P8  materialize  `copilot update` → resolve+materialize .claude/     │
│                  pre: P7 · check: copilot.lock == resolved SHAs       │
│ P9  verify       doctor self-check: agents load, cc/tc work, no drift │
│ P10 teach        print cheat-sheet; register `copilot add skill`      │
└─────────────────────────────────────────────────────────────────────┘
```

**Key ordering choice:** the foundation (P1) completes and hands Bob a usable partner *before* any auth, org, or department work. If Bob is solo (Sam, from Use Case 4), P3–P5 no-op and he's done after P6. If auth fails at P2, Bob still keeps the working foundation from P1 — failure never leaves him with nothing.

---

## 3. Self-healing / idempotency — `copilot doctor`

**Re-runnability is the whole design, not a feature.** `bootstrap.sh` and `copilot doctor` are the *same command* run twice: the first run installs, every subsequent run *repairs*. There is no separate "install" vs "update" mental model for Bob — he runs the one thing whenever something feels wrong.

**Drift detection** mirrors the existing `cc memory check` pattern (token-free deterministic checkers, 0–100 health score, non-zero exit on any `fail`-severity finding). `copilot doctor` runs a checker per invariant:

| Checker | Detects | Repair action |
|---|---|---|
| `prereq-resolve` | missing git/gh/node/cc/tc on PATH | install the missing one only |
| `layer-present` | a manifest layer whose clone dir is gone | re-clone from `source.repo` |
| `layer-fresh` | clone tip ≠ remote (or detached/dirty) | `git pull --ff-only`; if diverged, **stash-and-flag, never discard** |
| `layer-moved` | `source.repo` in manifest ≠ actual remote | update remote URL, re-fetch |
| `auth-live` | a private layer's credential no longer authenticates | re-run device-flow login for that identity only |
| `materialize-drift` | a file in `.claude/` ≠ its resolved-layer source SHA | re-materialize that item from the winning layer |
| `personal-safe` | personal layer has **uncommitted work** | **skip all writes to it; warn only** |

**The never-destroy invariant.** The single most important rule: `doctor` **owns `.claude/` (materialized, disposable) and owns lower layers (org/dept/foundation — read-only mirrors it can always re-clone). It does NOT own the personal layer's working tree.** Any personal-layer operation is gated on `git status --porcelain` being empty; if Bob has edited his accountant agent and not committed, doctor refuses to touch it and prints how to commit. Materialized `.claude/` files are always safe to overwrite because they're derived — the source of truth is the layers, not the materialization.

**What re-does vs skips:** every phase's idempotent check is a *cheap* predicate (a file exists, a SHA matches, a config key is set). Phases whose check passes are skipped silently. Only failing checks trigger their `repair`. So a fully-healthy re-run is nearly instant and prints one line: `✓ all 10 checks green (score 100)`.

**Two verbs, one engine:**
- `copilot doctor` — **read-only diagnosis.** Prints findings + score, exits non-zero on any fail. Safe for Bob to run anytime ("is my partner okay?").
- `copilot repair` — **doctor + apply repairs.** Runs the same checkers, then executes each finding's repair action. This is what `bootstrap.sh` calls internally (`copilot repair --bootstrap --yes`).

---

## 4. Auth for a non-technical user — the Bob path vs the developer path

Doc `02` §6 prescribes **SSH host aliases** (`github-personal`/`github-work`, `IdentitiesOnly yes`). That is correct — **for developers who have two GitHub identities on one machine** and hand-edit `~/.ssh/config`. Bob is not that person. Bob has **one** work identity (or none) and will never open `~/.ssh/config`. Forcing SSH-key generation on Bob is exactly the "bar too high" failure.

**Reconciliation — split by persona, not by policy:**

| | **Bob path (non-technical, ≤1 identity)** | **Developer path (2+ identities)** |
|---|---|---|
| Foundation (public) | **anon HTTPS** — no credential at all | anon HTTPS |
| Org / Dept (private) | **`gh auth login` device flow** — browser shows an 8-char code, Bob approves, done | **SSH host aliases** (`02` §6) — deterministic per-URL key selection |
| Credential storage | `gh` stores an OAuth token in the OS keychain; git uses `gh` as its HTTPS credential helper (`gh auth setup-git`) | `~/.ssh/id_ed25519_{personal,work}` + `IdentitiesOnly yes` |
| Machine identities | **one** — no hostname collision, so `gh`'s per-host token model is sufficient | **two on `github.com`** → collision → SSH aliases are the *only* clean answer (`02` §6.1) |
| Bob touches | a browser "approve" button | `~/.ssh/config` |

**The decisive simplification:** the `02` doc's SSH-alias requirement exists *only* to disambiguate **two credentials against one hostname**. Bob has one credential, so the collision never occurs, so `gh`'s hostname-keyed token model works perfectly — and `gh auth login` device flow is the lowest-friction private-repo auth that exists (no key, no PAT, no copy-paste of secrets; just a browser code).

**How doctor picks the path automatically:** at P2, `copilot doctor` counts distinct GitHub identities the manifest needs. **One or zero → Bob path (`gh` device flow).** **Two or more → developer path (SSH aliases), and it offers to *generate and upload the keys for him*** (`ssh-keygen -t ed25519` + `gh ssh-key add`) and write the `~/.ssh/config` blocks — so even the developer path is guided, never manual. Bob never sees this branch; it fires only when a second identity is actually required.

**Anon-first:** if a private clone fails auth, doctor degrades gracefully — foundation still works, and it prints "your company layers need sign-in; run `copilot repair` when ready." Bob is never blocked from having *a* partner by an auth hiccup.

---

## 5. The question flow — ask only what can't be derived

The governing rule (from the user's global instructions): **never ask something that can be derived.** Everything derivable is derived; only genuine unknowns are asked, in plain language, with a smart default pre-filled.

| # | Plain-language question | Default (derived / suggested) | Persisted as | Skipped when |
|---|---|---|---|---|
| Q1 | "Are you setting this up for a company, or just for yourself?" | inferred from `git config user.email` domain (corporate vs gmail) | `cc config set layers.mode {company\|solo}` | — asked once |
| Q2 | "What's your company?" | org suggested from email domain via `gh api /user/orgs` | `cc config set layers.org <slug>` | solo mode |
| Q3 | "What department or team are you on?" | **suggested** from `gh api /orgs/<org>/teams` membership (a numbered pick-list, not free text) | `cc config set layers.department <unit>` | solo, or single-dept org |
| Q4 | "Do you want your personal setup to follow you to other computers?" | default **No** (local-only personal layer) | offers to create a private GitHub repo *for* him if Yes | — |

**Everything else is derived, never asked:** OS/arch (uname), which prereqs are missing (`command -v`), the org repo URL (templated from `layers.org`), the department repo URL (templated from `layers.department` per `02` §5), the foundation URL (constant), the user's git identity (existing `git config`). Q3 in particular reuses `02` §5's rule exactly: the Teams API only **suggests** the pick-list; the stored `cc config` value is the contract, never a runtime lookup. If the API returns exactly one team, Q3 is auto-answered and skipped. Answers persist to `cc config` immediately, so a re-run of doctor never re-asks a settled question (its idempotent check is "is the config key set?").

---

## 6. Progressive extension UX — `copilot extend`

Bob adopts progressively: foundation first, then Knowledge Copilot, then CLI Copilot (per the ecosystem's layered families). Each is the **same guided, additive phase runner** — never a re-install, never re-doing settled phases.

```
copilot extend knowledge     # add the Knowledge Copilot product family
copilot extend cli           # add CLI Copilot
```

`copilot extend <product>` reuses the identical state machine, but its precondition checks find P0–P10 already satisfied (green) and **skip them all**, running only the product-specific phases (clone the product's layers, wire its `cc config`, materialize, teach). Because every phase is idempotent, `extend` is literally `doctor` with one extra layer added to the manifest — the foundation install is never touched, Bob's answers are never re-asked, and his personal layer is never disturbed. Same one-command mental model, scoped to what's new.

---

## 7. Teaching / self-service — the payoff phase (P10)

Install is worthless if Bob can't add his own accountant skill afterward. P10 is not a "done" message — it's onboarding into self-service. Two artifacts:

**(a) A printed cheat-sheet** (also saved to `~/.copilot/CHEATSHEET.md` and materialized into his `.claude/`):

```
  ✅ Your AI partner is ready. Here's everything you need:

  Talk to it            claude          (then just type what you want)
  Add a skill for YOU   copilot add skill --personal
  Get company updates   copilot update
  Something feels off?  copilot doctor      (checks) / copilot repair (fixes)
  Add more power        copilot extend knowledge   |   copilot extend cli

  Your private stuff lives in:  ~/.copilot/layers/personal   (only you can see it)
```

**(b) A guided authoring command** — `copilot add skill --personal` does for skills what the installer did for setup: it *asks*, it *scaffolds*, it *files in the right layer*. Bob never learns where the personal layer lives or what a SKILL.md looks like.

```
$ copilot add skill --personal
  What should this skill do? (plain English)
  > calculate quarterly estimated taxes from a P&L
  When should it kick in? (words that describe when you'd want it)
  > estimated taxes, quarterly, 1040-ES, P&L

  ✓ Created ~/.copilot/layers/personal/skills/quarterly-est-taxes/SKILL.md
  ✓ It's yours only — nobody else can see it.
  ✓ Ready to use now. Try: claude  →  "help me with my quarterly taxes"
```

Under the hood it writes a valid trigger-rich `description` (from Bob's "when" words), scaffolds the SKILL.md, commits to the personal layer if Q4 opted into sync (else leaves it local), and runs `copilot update` to materialize — the exact Use Case 4 flow, but with zero git/editor exposure. `--department` and `--org` variants exist for authors like Mira and Raj (`02`/`03` Use Cases 5–6), file into the correct private layer, and are gated on write permission — same guided pattern, wider audience.

---

## 8. Annotated stage-0 sketch (`bootstrap.sh`)

```bash
#!/usr/bin/env bash
# bootstrap.sh — Ring 0. Assumes only bash + curl. Safe to re-run.
set -euo pipefail
FOUNDATION_REPO="https://github.com/Everyone-Needs-A-Copilot/claude-copilot.git"
LAYERS="$HOME/.copilot/layers"

log() { printf '  %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

# ── P0: prerequisites — install ONLY what's missing (idempotent) ──────────
ensure_pkg_mgr() {                       # Bob may have no brew
  if [[ "$(uname)" == "Darwin" ]] && ! have brew; then
    log "Installing Homebrew (one-time)…"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    eval "$(/opt/homebrew/bin/brew shellenv)"
  fi
}
ensure() {                               # ensure <cmd> <brew-formula>
  have "$1" && { log "✓ $1"; return; }
  log "Installing $1…"; brew install "$2"
}
ensure_pkg_mgr
for pair in "git git" "gh gh" "node node"; do ensure $pair; done

# ── install cc + tc from the foundation checkout (idempotent) ─────────────
if [[ ! -d "$LAYERS/foundation/.git" ]]; then
  log "Fetching the foundation (your AI partner)…"
  git clone --depth 1 "$FOUNDATION_REPO" "$LAYERS/foundation"   # anon HTTPS, no auth
else
  git -C "$LAYERS/foundation" pull --ff-only || log "⚠ foundation pull skipped (local changes)"
fi
have cc || bash "$LAYERS/foundation/tools/cc/install.sh"
have tc || bash "$LAYERS/foundation/tools/tc/install.sh"

# ── P1 done: Bob has a working partner. Hand off to Ring 1. ───────────────
log "✓ Foundation ready. Personalizing…"
exec copilot doctor --bootstrap --yes         # Ring 1 drives P2–P10
```

## 9. The phase runner & `copilot doctor` logic (Ring 1)

```python
# Each phase: (name, precondition, is_done, action, repair). The runner is the
# SAME engine for install (--bootstrap), doctor (read-only), and repair (apply).
PHASES = [P2_identity, P3_org, P4_ask_dept, P5_dept,
          P6_personal, P7_manifest, P8_materialize, P9_verify, P10_teach]

def run(mode):                        # mode ∈ {bootstrap, doctor, repair}
    findings, score = [], 100
    for ph in PHASES:
        if not ph.precondition():     # e.g. solo user → skip org/dept phases
            continue
        if ph.is_done():              # cheap predicate: file/SHA/config check
            continue                  # ← idempotency: skip settled work silently
        findings.append(ph.name)
        if mode == "doctor":          # diagnose only
            score -= ph.severity
            continue
        try:
            ph.action() if mode == "bootstrap" else ph.repair()
        except AuthError:             # degrade, never abort — foundation stays up
            warn(f"{ph.name}: sign-in needed; run `copilot repair` later")
    if mode == "doctor":
        print_report(findings, score)
        sys.exit(0 if not findings else 1)   # mirrors `cc memory check`

# The never-destroy guard, applied before ANY personal-layer write:
def guard_personal(path):
    if git_dirty(path):               # uncommitted work in Bob's layer
        raise SkipWithWarning(f"{path} has unsaved changes — not touching it")
```

`--bootstrap` runs actions (first-time install). `repair` runs the same phases' repair actions (fix drift). `doctor` runs neither — it only reports. One state machine, three entry modes, and the personal-layer guard sits in front of every write so Bob's own work is structurally un-clobberable.

---

## 10. Failure modes & responses (the obsession)

| Failure | Detected by | Response (never leaves Bob stuck) |
|---|---|---|
| No Homebrew / no package manager | `have brew` false | install it silently in P0 |
| No internet mid-clone | git exit code | resume on re-run (idempotent); clear "check your wifi" message |
| Auth declined / device-flow abandoned | `gh auth status` | keep foundation; flag org/dept as "sign-in later" |
| Partial clone (crash mid-P5) | `layer-present` checker | re-clone that one layer on re-run |
| Bob edited a materialized file directly | `materialize-drift` | doctor warns it's derived; re-materialize overwrites (safe) |
| Bob edited his personal agent, uncommitted | `personal-safe` guard | **refuse to touch it**; print commit instructions |
| Department repo moved/renamed | `layer-moved` | update remote URL from manifest, re-fetch |
| A layer's remote is gone (deleted) | clone 404 | drop it from the effective set, warn, keep the rest |
| Two GitHub identities needed | P2 identity count ≥2 | switch to developer path; generate+upload keys *for* him |

---

## 11. Verdict

The installer is **one command that is also the repair tool and also the update tool** — Bob learns a single verb. The chicken-and-egg is resolved by a three-ring split: a dependency-free `bootstrap.sh` (Ring 0) installs a capable foundation whose own `copilot doctor` (Ring 1) drives every guided, idempotent phase (Ring 2). Self-healing is not bolted on — it *is* the architecture: every phase declares its own idempotent check and repair, and the personal layer is structurally protected from any write. Auth is split by persona, not policy — Bob rides `gh` device flow (one identity, browser code, zero keys), and the SSH-alias machinery from `02` §6 activates only when a second identity actually forces the collision it exists to solve, and even then the installer generates the keys for the developer. The four tiers, the manifest, the credentials — all invisible. Bob answers two questions a human can answer ("what company? what team?"), gets a working partner before any of it, and walks away knowing how to add a skill that's just his.
