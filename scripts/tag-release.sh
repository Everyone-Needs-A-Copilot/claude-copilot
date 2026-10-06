#!/usr/bin/env bash
# Tag a framework release: the step that turns a merged version bump into a
# release a project lock can name.
#
# WHY THIS EXISTS. `/update-copilot` installs main's HEAD and the project lock
# writer records `release_tag: v<VERSION.json framework>` for whatever it
# installed. Version bumps reach main as squash-merged PRs, and nothing in that
# path creates the tag -- so 5.15.3 and 5.15.4 shipped into project locks while
# the newest tag was still v5.15.2, and every installed project's fitness check
# (FF12) failed against a release that did not exist. Run this after every
# version bump lands on main; .github/workflows/release-tag-check.yml turns main
# red until you do.
#
# Usage:
#   scripts/tag-release.sh [--at <commit>] [--push]
#
#   --at <commit>  Tag an earlier commit (retroactive tagging). The commit must
#                  be on origin/main and its own VERSION.json names the version.
#                  Default: HEAD, which must equal origin/main.
#   --push         Push the new tag to origin.
#
# Checks (all must hold, nothing is created otherwise):
#   - VERSION.json framework == package.json version == .claude-plugin
#     plugin.json and marketplace.json versions, at the target commit
#   - CHANGELOG.md at the target commit has a `## [X.Y.Z]` entry
#   - the target commit is on origin/main
#   - vX.Y.Z does not exist yet, or already points at the target (no-op)
# The tag is annotated and signed (tag.gpgsign / user.signingkey), titled from
# the CHANGELOG heading, and verified with `git tag -v`. A HEAD release must then
# pass scripts/verify-foundation-release.sh (Claude release signer on both the
# commit and the tag) before any push.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET=""
PUSH=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --at)   TARGET="$2"; shift 2 ;;
    --push) PUSH=true; shift ;;
    -h|--help) sed -n '2,32p' "$0"; exit 0 ;;
    *) echo "error: unknown argument: $1" >&2; exit 2 ;;
  esac
done

die() { echo "error: $*" >&2; exit 1; }

REPO="$(git rev-parse --show-toplevel)"
cd "$REPO"

git fetch --quiet --tags origin main || die "cannot fetch origin"

if [ -z "$TARGET" ]; then
  [ -z "$(git status --porcelain --untracked-files=no)" ] || die "working tree has uncommitted changes"
  [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] ||
    die "HEAD is not origin/main; release tags are cut from main as merged (use --at for an earlier main commit)"
  TARGET=HEAD
fi
COMMIT="$(git rev-parse --verify "${TARGET}^{commit}")" || die "no such commit: $TARGET"
git merge-base --is-ancestor "$COMMIT" origin/main || die "$COMMIT is not on origin/main"

field() {  # field <path-at-commit> <python expression over `d`>
  git show "${COMMIT}:$1" 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print($2)" ||
    die "cannot read $1 at $COMMIT"
}
VERSION="$(field VERSION.json "d['framework']")"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "VERSION.json framework is not X.Y.Z: $VERSION"
for pair in \
  "package.json|d['version']" \
  ".claude-plugin/plugin.json|d['version']" \
  ".claude-plugin/marketplace.json|d['plugins'][0]['version']"; do
  file="${pair%%|*}"
  got="$(field "$file" "${pair#*|}")"
  [ "$got" = "$VERSION" ] || die "$file says $got, VERSION.json says $VERSION"
done

HEADING="$(git show "${COMMIT}:CHANGELOG.md" | grep -m1 -E "^## \[${VERSION//./\\.}\]" || true)"
[ -n "$HEADING" ] || die "CHANGELOG.md has no '## [$VERSION]' entry at $COMMIT"
TITLE="$(printf '%s' "$HEADING" | sed -E 's/^## \[[^]]*\][^—]*— [^—]*— ?//')"

TAG="v${VERSION}"
CREATED=""
if git rev-parse -q --verify "refs/tags/${TAG}" >/dev/null; then
  existing="$(git rev-parse "${TAG}^{commit}")"
  [ "$existing" = "$COMMIT" ] || die "${TAG} already exists at ${existing}, not ${COMMIT}"
  echo "${TAG} already tags ${COMMIT}"
else
  git tag -s -a "$TAG" -m "Claude Copilot ${VERSION}: ${TITLE}" "$COMMIT"
  git tag -v "$TAG" >/dev/null 2>&1 || { git tag -d "$TAG" >/dev/null; die "signature on ${TAG} does not verify; tag removed"; }
  echo "tagged ${TAG} at ${COMMIT}"
  CREATED=1
fi

# A release cut from main HEAD must pass the foundation preflight (release-key
# commit AND tag signatures, exact target, main ancestry) before it is
# published; a tag that fails it is removed, never pushed. Retroactive --at tags
# mark versions that already shipped from GitHub merge commits, whose merge
# signature the preflight cannot accept -- they anchor history, they are not
# foundation sources, and that is stated rather than hidden.
if [ "$TARGET" = "HEAD" ]; then
  if ! bash "$SCRIPT_DIR/verify-foundation-release.sh" "$REPO" "$TAG" "$COMMIT" main; then
    [ -n "$CREATED" ] && git tag -d "$TAG" >/dev/null
    die "${TAG} failed the foundation release preflight${CREATED:+; tag removed}"
  fi
else
  echo "note: ${TAG} is a retroactive history tag; ${COMMIT} is not checked as a foundation release source"
fi

if $PUSH; then
  git push origin "refs/tags/${TAG}"
fi
