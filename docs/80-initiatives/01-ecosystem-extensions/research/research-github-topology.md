# GitHub Topology + Multi-Account Credential Architecture — 4-Tier Layered Framework

| | |
|---|---|
| **Status** | Research / Proposed |
| **Branch** | `ecosystem-extensions` |
| **Question** | 4 tiers (personal / department / org / foundation), each in a DIFFERENT GitHub account-or-org, one dev machine must pull + reconcile all four non-interactively |
| **Anchors** | §5.2 git topology + §9 risks 4/7/9 of `00-findings-and-recommendations.md`; personal `claude-copilot-private/bootstrap.sh` |

The existing doc frames **three** layers (public → company → personal). This splits the middle "company" tier into **department** and **org**, giving four. The two new tiers share ONE GitHub org, which is the whole trick of the topology question.

---

## 1. Repo topology per tier

| Tier | Owner / namespace | Repo | Visibility | Precedence |
|------|-------------------|------|------------|------------|
| **1 · Personal** | `github.com/<user>` (personal account) | `<user>/claude-copilot-private` | private | **highest** (wins) |
| **2 · Department** | `github.com/acme-corp` (enterprise org) | `acme-corp/copilot-dept-<name>` | private (team-scoped) | above org |
| **3 · Org** | `github.com/acme-corp` (same org) | `acme-corp/copilot-org` | private (org-wide) | above foundation |
| **4 · Foundation** | `github.com/Everyone-Needs-A-Copilot` | `Everyone-Needs-A-Copilot/claude-copilot` | public | **lowest** (base) |

Resolver precedence (last-writer-wins per named unit): **personal > department > org > foundation.**

### The department-vs-org sub-question: separate repos, team-restricted (recommend **option a**)

Department and org live in the same org `acme-corp`. Three candidate designs:

- **(a) Separate repos** — `acme-corp/copilot-org` (org-wide) + one `acme-corp/copilot-dept-eng`, `-dept-sales`, … per department. **← RECOMMEND.**
- **(b) One repo, department subfolders, path-based access** — rejected: GitHub has **no path-level ACLs**. `CODEOWNERS` governs *review routing*, not *read access*. Anyone who can clone the repo reads every department's folder. That collapses the confidentiality boundary the department tier exists to create.
- **(c) GitHub sub-teams as the boundary** — teams are the *access mechanism*, not a substitute for the repo split. Used *with* (a), not instead.

**Why (a) wins — GitHub's real primitives.** GitHub's access-control atoms are: org membership, teams (assignable per-repo), *nested* teams (a child inherits the parent's grants), repo-level collaborators, and CODEOWNERS (review only). Read access is granted **at the repository granularity** — the finest confidentiality unit GitHub offers is a repo, not a directory. So a per-department confidentiality boundary *must* be a per-department repo. Map:

```
Team: acme-corp/engineering            (parent, department)
  └── read/write → acme-corp/copilot-dept-eng
Team: acme-corp/everyone  (or org base permission = read)
  └── read       → acme-corp/copilot-org
```

**Nested teams map cleanly to org→department precedence — but note the direction.** GitHub inheritance flows *parent → child*: granting the **parent** team access to a repo cascades to all child teams. So the natural mapping is **parent team = department, child teams = sub-squads within it** (parent grants the dept repo, squads inherit). The **org tier is not a parent team** — it is the org base permission (or an `everyone` team) that every member already has. Do **not** try to model "org is the parent of department" via nesting: that would grant *every* org member the department repo (inheritance cascades *down*, and org is the top). Org-wide read is the org base-permission/`everyone` grant; department read is a *narrower* team grant on a *separate* repo. Two repos, two grant scopes — the precedence in the resolver (dept > org) is independent of GitHub's team tree and lives in the manifest.

This also satisfies §9 risk 9 (governance): each dept repo gets its own CODEOWNERS + review policy, distinct from the org repo's, without leaking cross-department.

---

## 2. Multi-account auth on ONE machine — the core problem

The machine must act as **three distinct credentials against two hosts-that-are-both github.com**:

1. **personal identity** → clone `<user>/claude-copilot-private`
2. **enterprise identity** → clone `acme-corp/copilot-org` **and** `acme-corp/copilot-dept-eng`
3. **anonymous HTTPS** → clone the public `Everyone-Needs-A-Copilot/claude-copilot`

All four URLs resolve to the same `github.com`. The auth mechanism must pick the right key **from the URL alone**, deterministically, with **no prompt** (must work headless / in CI / from a `copilot update` cron). That single requirement eliminates most options.

### Options and tradeoffs

| Mechanism | Deterministic per-URL? | Headless? | Verdict |
|-----------|------------------------|-----------|---------|
| **SSH host aliases** (`git@github-personal:` vs `git@github-work:`, per-host `IdentityFile`) | **Yes** — the alias in the URL selects the key | Yes (key + `IdentitiesOnly yes`) | **RECOMMEND for personal + enterprise (private) tiers** |
| `includeIf` gitconfig | Selects *identity/signing* (user.email, signingkey), **not** the auth credential | n/a | **Complement, not the auth** — use for commit identity/signing per tier |
| `gh auth switch` / gh as credential helper | **No** — active account is **global per host**; gh can't disambiguate two github.com accounts by URL for a fan-out (open issue cli/cli#8875) | Switch is stateful, not per-clone | Reject as the pull mechanism; fine for interactive human use |
| Fine-grained PAT | Yes, via URL-embedded or helper token | Yes, but human-tied, ~monthly expiry, manual rotation | OK for a single personal tier; poor for org automation |
| **GitHub App installation token** | Yes | Yes — short-lived (1h), org-managed, auto-refresh | **RECOMMEND for org+dept in CI / shared automation** |
| Deploy key (per-repo SSH key) | Yes (repo-scoped) | Yes | Good fallback for a single locked-down repo; doesn't scale to N dept repos |
| osxkeychain helper | Stores HTTPS creds, but keychain is **keyed by host** not account → same collision as gh | Yes | Insufficient alone for two github.com accounts |

**The decisive fact:** every HTTPS-based helper (gh, osxkeychain, PAT-in-keychain) keys credentials **by hostname**, and both private tiers are `github.com`. Two different identities against one hostname collide. **SSH host aliases are the only mechanism that resolves the identity from the URL string itself** — because the alias (`github-personal` / `github-work`) *is* a distinct SSH `Host` block with its own `IdentityFile`, even though both `HostName github.com`. That is why the classic multi-account pattern is SSH aliases, and it is exactly what a deterministic 4-tier fan-out needs.

### Recommended concrete setup (copy-pasteable)

**`~/.ssh/config`** — two aliases, one real host, pinned keys:

```sshconfig
# Personal identity (tier 1)
Host github-personal
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_personal
    IdentitiesOnly yes

# Enterprise identity (tiers 2 + 3 — same org, one enterprise key)
Host github-work
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_work
    IdentitiesOnly yes
```

`IdentitiesOnly yes` is mandatory — without it ssh-agent offers *every* loaded key and github.com returns whichever account matches first, breaking determinism.

**Layer remote URLs** (what the resolver clones — the alias is baked into the URL):

```
tier 1 personal    → git@github-personal:<user>/claude-copilot-private.git
tier 2 department  → git@github-work:acme-corp/copilot-dept-eng.git
tier 3 org         → git@github-work:acme-corp/copilot-org.git
tier 4 foundation  → https://github.com/Everyone-Needs-A-Copilot/claude-copilot.git   # anon, no key
```

**`~/.gitconfig`** — `includeIf` sets commit identity + signing per tier (auth is already handled by the SSH alias; this handles *who you commit as*):

```gitconfig
[includeIf "hasconfig:remote.*.url:git@github-personal:**/**"]
    path = ~/.config/git/personal.inc
[includeIf "hasconfig:remote.*.url:git@github-work:**/**"]
    path = ~/.config/git/work.inc
```

`~/.config/git/work.inc`:
```gitconfig
[user]
    name = Jane Dev
    email = jane@acme-corp.com
    signingkey = ~/.ssh/id_ed25519_work.pub
[gpg]
    format = ssh
[commit]
    gpgsign = true
```

(`hasconfig:remote.*.url` matching requires **Git 2.36+** and keys off the remote URL, so identity follows the repo wherever it's checked out — no dependence on directory layout.)

### Manifest `auth` field values

The §5.2 manifest already carries an `auth` hint per layer. Give it these enum values:

```yaml
# copilot.layers.yml
layers:
  - name: personal
    repo: git@github-personal:<user>/claude-copilot-private.git
    auth: ssh-personal      # → SSH Host alias "github-personal"
  - name: department
    repo: git@github-work:acme-corp/copilot-dept-${DEPARTMENT}.git
    auth: ssh-work          # → SSH Host alias "github-work"
  - name: org
    repo: git@github-work:acme-corp/copilot-org.git
    auth: ssh-work
  - name: foundation
    repo: https://github.com/Everyone-Needs-A-Copilot/claude-copilot.git
    auth: anon              # → plain HTTPS, no credential
```

Optional CI variant for the private enterprise tiers: `auth: gh-app:<app-slug>` → resolver mints a short-lived installation token and clones over HTTPS with it (best for shared/headless runners where per-developer SSH keys don't exist — see §2 table, GitHub App row).

---

## 3. How the resolver / fan-out picks the credential per layer

`copilot update` iterates the manifest and maps `auth` → transport with **zero prompting**:

```
for layer in manifest.layers:
    case layer.auth:
      "ssh-personal" | "ssh-work":
          # URL already carries the Host alias → ssh picks IdentityFile.
          # Nothing to inject; the alias IS the credential selector.
          GIT_SSH_COMMAND="ssh -o IdentitiesOnly=yes -o BatchMode=yes" \
            git -C <layerdir> pull --ff-only
      "anon":
          git -C <layerdir> pull --ff-only        # public HTTPS, no cred
      "gh-app:<slug>":
          TOKEN=$(mint_installation_token <slug>)  # short-lived
          git -C <layerdir> \
            -c http.extraHeader="Authorization: Bearer $TOKEN" pull --ff-only
```

Key properties:
- The **SSH-alias-in-URL is self-selecting** — the resolver doesn't switch global state (unlike `gh auth switch`); each clone independently resolves its key from its own URL. Four layers pull in one pass, three different identities, no ordering hazard.
- `BatchMode=yes` guarantees a missing/locked key **fails fast** instead of hanging on a passphrase prompt (headless-safe).
- Enforces §9 risk 4 (secrets): the resolver only ever *reads* from layer repos into `.claude/`; auth material stays in `~/.ssh` / the GitHub App, never materialized into a tracked tree.

---

## 4. Department identity determination — recommend the config value

How does the machine know the user is in `engineering` (to pull `copilot-dept-eng`)?

| Option | Deterministic? | Offline / headless? | Verdict |
|--------|----------------|---------------------|---------|
| **Config value** `cc config set org.department engineering` | **Yes** — explicit, pinned | **Yes** | **RECOMMEND** |
| GitHub team-membership API lookup (`GET /orgs/acme-corp/teams/*/memberships/<user>`) | No — needs network + token scope `read:org`, and a user in *multiple* teams is ambiguous | No | Reject as source of truth (good as a *bootstrap suggestion*) |
| Org-provided manifest mapping user→dept | Centralized but needs a fetch + a maintained mapping file | Partial | Reject as primary |

**Recommendation:** a single deterministic config value, mirroring the existing `paths.knowledge_repo` machine-config discipline:

```bash
cc config set org.department engineering
```

The manifest then interpolates it: `repo: git@github-work:acme-corp/copilot-dept-${DEPARTMENT}.git`. This keeps `copilot update` fully offline-capable and reproducible (§9 risk 5). **Use the team-membership API only once, at onboarding**, to *suggest* the default (`gh api ...` to read the user's teams and pre-fill the prompt), then persist the answer as the config value. Runtime never depends on a live API call.

---

## 5. Enterprise onboarding flow

Mirror the personal `claude-copilot-private/bootstrap.sh` (which symlinks private stores in and runs `cc config add paths.knowledge_repo`). The enterprise bootstrap wires **three** tiers and leaves the personal seam open:

```bash
#!/usr/bin/env bash
# acme-onboard.sh — wire org + department + foundation for a new acme-corp dev.
set -euo pipefail
ORG=acme-corp
PUBLIC_DIR="${1:-$(pwd)/claude-copilot}"

# 0. Preconditions (fail loud, headless-safe)
command -v cc >/dev/null || { echo "install tools/cc first"; exit 1; }
ssh -T git@github-work 2>&1 | grep -q "successfully authenticated" \
  || { echo "add your enterprise SSH key as Host github-work (see §2)"; exit 1; }

# 1. Determine department — suggest via API, persist as config (deterministic)
DEPT="$(cc config get org.department 2>/dev/null || true)"
if [[ -z "$DEPT" ]]; then
  SUGGEST="$(gh api "/orgs/$ORG/teams" --jq '.[].slug' 2>/dev/null | head -1 || true)"
  read -rp "Your department [${SUGGEST:-engineering}]: " DEPT
  DEPT="${DEPT:-${SUGGEST:-engineering}}"
  cc config set org.department "$DEPT"
fi

# 2. Clone the three enterprise/public layers with the right identity per URL
clone() { [[ -d "$2" ]] || git clone "$1" "$2"; }
clone "git@github-work:$ORG/copilot-org.git"          "$HOME/.copilot/layers/org"
clone "git@github-work:$ORG/copilot-dept-$DEPT.git"   "$HOME/.copilot/layers/dept"
clone "https://github.com/Everyone-Needs-A-Copilot/claude-copilot.git" \
                                                       "$HOME/.copilot/layers/foundation"

# 3. Wire the manifest layers (foundation < org < dept < personal)
cc config add paths.layer "$HOME/.copilot/layers/foundation:anon"
cc config add paths.layer "$HOME/.copilot/layers/org:ssh-work"
cc config add paths.layer "$HOME/.copilot/layers/dept:ssh-work"

# 4. Leave room for the personal layer (highest precedence) — printed, not forced
cat <<EOF
Enterprise layers wired (foundation < org < dept-$DEPT).
Optional PERSONAL layer (wins over all): clone your own private repo and run
  cc config add paths.layer "\$HOME/.copilot/layers/personal:ssh-personal"
(after adding Host github-personal to ~/.ssh/config — see §2).

Materialize now:  copilot update
EOF
```

The personal tier stays a documented opt-in (the user runs the existing personal `bootstrap.sh`), so one machine ends with all four tiers and the resolver orders them personal > dept > org > foundation.

---

## 6. Prior art — patterns that transfer

**Three patterns to adopt, from the strongest analogues:**

1. **GitLab subgroups → confidentiality is a *container* boundary, and inheritance flows parent→child.** GitLab supports up to 20 nested subgroup levels; a member added to a parent group inherits that role in every subgroup. This validates two design choices: (a) precedence should be a first-class tree, and (b) inheritance cascades *downward* — which is exactly why we made **department the parent team and org the base permission**, not the reverse. GitLab also proves the confidentiality unit is the *group/project container*, mirroring GitHub's "repo is the finest read boundary" → separate repos per department.

2. **npm scopes + org teams → namespace-per-owner prevents dependency confusion.** npm gives every org a unique scope (`@acme/*`) and grants team permissions per package. Transfers directly to the resolver's optional **layer namespacing** (§5.3): scope items `acme/qa` vs `pablo/qa` so a department agent can co-exist with the org one when override is *not* intended — closing the dependency-confusion-class bug the doc already flags. Auth is per-scope; our `auth` hint is the per-layer analogue.

3. **chezmoi's "one file, one owner" layering → single-writer per unit + explicit materialize.** chezmoi lets a public dotfiles repo carry work+personal without leaking secrets across machines, and the advanced nix→chezmoi→apm stack enforces **each file owned by exactly one layer** with `.chezmoiignore` policing boundaries and a fixed install order. This is precisely the doc's §5.1 *materialize-don't-merge* + whole-unit-override decision, now extended to four tiers: fixed resolve order (foundation→org→dept→personal), one winner per name, materialize into `.claude/`. chezmoi's public-repo-with-encrypted-secrets model also backs §9 risk 4 — the foundation repo stays public and clean via `@machine` sentinels; no private-tier secret is ever copied into it.

(Backstage catalog ownership and Terraform Cloud org/workspace/team were reviewed; both confirm a 3+ level owner hierarchy with per-level RBAC but add nothing beyond the GitLab pattern for this problem, so they're noted, not adopted.)

---

## 7. Recommendations at a glance

| Decision | Recommendation | Priority |
|----------|----------------|----------|
| Dept-vs-org repo topology | **Separate repos** (`copilot-org` + `copilot-dept-<name>`), team-restricted; dept = parent team, org = base permission | **P0** |
| Multi-account auth | **SSH host aliases** (`github-personal` / `github-work`, `IdentitiesOnly yes`) for private tiers; **anon HTTPS** for foundation; **GitHub App tokens** for shared CI | **P0** |
| Commit identity/signing | `includeIf "hasconfig:remote.*.url:..."` per tier (Git 2.36+) | P1 |
| `auth` manifest values | `ssh-personal` / `ssh-work` / `anon` / `gh-app:<slug>` | **P0** |
| Department identity | **Deterministic config value** `cc config set org.department`; API only to *suggest* at onboarding | **P0** |
| Namespacing | Optional layer scopes (`acme/qa`) to prevent cross-tier collisions | P1 |

**Bottom line:** the four-tier topology is buildable on GitHub's real primitives with **no new GitHub features** — the only hard constraint is that read-confidentiality is per-repo, which forces separate department/org repos; and the only auth mechanism that deterministically disambiguates two github.com identities in a headless fan-out is **SSH host aliases**, because it is the one mechanism that selects the credential from the URL string rather than the hostname.

---

### Sources
- [git multiple accounts — SSH host aliases + includeIf + insteadOf](https://oneuptime.com/blog/post/2026-01-24-git-config-multiple-accounts/view)
- [git includeIf hasconfig:remote.*.url (Git 2.36+)](https://www.eddgrant.com/blog/2023/03/28/automatically-configuring-git-based-on-remote-url)
- [GitHub Apps vs PATs vs Deploy Keys vs OIDC — SCM identity choice](https://www.systemshardening.com/articles/cicd/scm-identity-choice/)
- [GitHub nested teams — parent→child inheritance](https://github.blog/news-insights/product-news/nested-teams-add-depth-to-your-team-structure/)
- [About organization teams — GitHub Docs](https://docs.github.com/en/organizations/organizing-members-into-teams/about-teams)
- [gh CLI multiple accounts — active-account-per-host limitation](https://github.com/cli/cli/blob/trunk/docs/multiple-accounts.md)
- [gh multi-account credential-helper gap (cli/cli#8875)](https://github.com/cli/cli/issues/8875)
- [GitLab subgroups — nested inheritance](https://docs.gitlab.com/user/group/subgroups/)
- [npm organization scopes and packages](https://docs.npmjs.com/about-organization-scopes-and-packages/)
- [chezmoi — public repo, per-machine secrets, layer ownership](https://www.chezmoi.io/why-use-chezmoi/)
