# Setup Knowledge Sync

Install a project Git hook that updates product Knowledge after release tags.

## 1. Resolve prerequisites

Use the nearest configured Knowledge tier; do not assume `~/.claude/knowledge` is configured.

```bash
eval "$(cc env)"
KNOWLEDGE_REPO_PATH="${CC_KNOWLEDGE_REPOS%%,*}"
if [[ -n "$KNOWLEDGE_REPO_PATH" && -f "$KNOWLEDGE_REPO_PATH/knowledge-manifest.json" ]]; then
  echo "FOUND: $KNOWLEDGE_REPO_PATH"
else
  echo "MISSING"
fi
git rev-parse --is-inside-work-tree 2>/dev/null && echo "GIT_OK" || echo "NOT_GIT"
```

- On `MISSING`, tell the user to run `/knowledge-copilot`, then stop.
- On `NOT_GIT`, explain that tag-based sync requires a Git repository, then stop.

Resolve project identity:

```bash
PROJECT_ROOT="$(git rev-parse --show-toplevel)"
PROJECT_NAME="$(basename "$PROJECT_ROOT")"
```

## 2. Check for an existing install

```bash
test -f "$PROJECT_ROOT/.git/hooks/post-tag" && echo HOOK_EXISTS || echo HOOK_MISSING
test -f "$PROJECT_ROOT/.git/hooks/sync-knowledge.sh" && echo SCRIPT_EXISTS || echo SCRIPT_MISSING
```

If both exist, ask whether to Reinstall, Test, or Cancel. Cancel stops. Test runs the dry-run command in step 4 without copying files.

## 3. Install

```bash
mkdir -p "$PROJECT_ROOT/.git/hooks"
cp ~/.claude/copilot/scripts/knowledge-sync/sync-knowledge.sh "$PROJECT_ROOT/.git/hooks/"
cp ~/.claude/copilot/scripts/knowledge-sync/extract-release-changes.sh "$PROJECT_ROOT/.git/hooks/"
cp ~/.claude/copilot/scripts/knowledge-sync/update-product-knowledge.sh "$PROJECT_ROOT/.git/hooks/"
cp ~/.claude/copilot/templates/hooks/post-tag "$PROJECT_ROOT/.git/hooks/"

# Git hooks run outside an env-hydrated shell. Bake in the tier selected above.
sed -i.bak "s|--tag \"\$TAG\"|--tag \"\$TAG\" --knowledge-repo \"$KNOWLEDGE_REPO_PATH\"|" "$PROJECT_ROOT/.git/hooks/post-tag"
rm -f "$PROJECT_ROOT/.git/hooks/post-tag.bak"
chmod +x "$PROJECT_ROOT/.git/hooks/post-tag" \
  "$PROJECT_ROOT/.git/hooks/sync-knowledge.sh" \
  "$PROJECT_ROOT/.git/hooks/extract-release-changes.sh" \
  "$PROJECT_ROOT/.git/hooks/update-product-knowledge.sh"
```

Verify that all four files exist and are executable. A missing or non-executable file means installation failed; do not report success.

## 4. Offer a dry run

```bash
git describe --tags --abbrev=0 2>/dev/null || echo NO_TAGS
```

If a tag exists, ask whether to test. On Yes:

```bash
"$PROJECT_ROOT/.git/hooks/sync-knowledge.sh" --dry-run --knowledge-repo "$KNOWLEDGE_REPO_PATH"
```

Show what would change; a dry run must not write or commit Knowledge.

## 5. Report

State the resolved Knowledge tier and installed files:

- `.git/hooks/post-tag`: release-tag trigger
- `.git/hooks/sync-knowledge.sh`: orchestrator
- `.git/hooks/extract-release-changes.sh`: changes between tags
- `.git/hooks/update-product-knowledge.sh`: product Knowledge writer

Explain that a matching `v*.*.*` tag extracts changes, updates `$KNOWLEDGE_REPO_PATH/03-products/$PROJECT_NAME.md`, and commits in that Knowledge repository. It becomes available to projects whose `paths.knowledge_repo` ladder includes that tier.

The installed hook captures the selected repository path at install time because ordinary `git tag` does not run in a shell hydrated by `cc env`. If the configured ladder changes, reinstall before the next release. Do not silently redirect an existing hook to another tier.

Manual commands:

```bash
.git/hooks/sync-knowledge.sh --knowledge-repo "$KNOWLEDGE_REPO_PATH"
.git/hooks/sync-knowledge.sh --tag v2.4.0 --knowledge-repo "$KNOWLEDGE_REPO_PATH"
.git/hooks/sync-knowledge.sh --tag v2.4.0 --dry-run --knowledge-repo "$KNOWLEDGE_REPO_PATH"
```

## Troubleshooting and uninstall

- Hook not running: verify executable bits and run the dry-run command.
- Repository not found: run `/knowledge-copilot`, inspect `eval "$(cc env)"; echo "$CC_KNOWLEDGE_REPOS"`, then reinstall so the hook receives the new path.
- Changes absent: use conventional `feat:`, `fix:`, `docs:`, or `chore:` commits and inspect the dry-run output.
- History: `git -C "$KNOWLEDGE_REPO_PATH" log -- "03-products/$PROJECT_NAME.md"`.

Release tags follow `v*.*.*`; examples include `v1.0.0`, `v2.4.0`, and prerelease variants. Other tag names are ignored. Conventional commit prefixes improve categorization, and `feat!:` or a `BREAKING CHANGE:` footer marks a breaking change.

Uninstall only these installed hook files:

```bash
rm "$PROJECT_ROOT/.git/hooks/post-tag" \
  "$PROJECT_ROOT/.git/hooks/sync-knowledge.sh" \
  "$PROJECT_ROOT/.git/hooks/extract-release-changes.sh" \
  "$PROJECT_ROOT/.git/hooks/update-product-knowledge.sh"
```
