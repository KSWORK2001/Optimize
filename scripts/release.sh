#!/bin/bash
# Release Optimize → releases on this (public) repo, Echo-style feed included.
# Usage: scripts/release.sh [--draft] [--version X.Y.Z] [notes...]
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="KSWORK2001/Optimize"
DRAFT=0; NOTES=""; VERSION_SET=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --draft) DRAFT=1; shift ;;
    --version) VERSION_SET="$2"; shift 2 ;;
    *) NOTES="${NOTES:+$NOTES }$1"; shift ;;
  esac
done
[[ -n "$(git status --porcelain)" ]] && { echo "error: working tree not clean — commit first"; exit 1; }
git push -q origin main 2>/dev/null || true
git diff --quiet HEAD origin/main || { echo "error: local main differs from origin/main"; exit 1; }
VERSION="$(python3 -c 'import re; print(re.search(r"version = \"([^\"]+)\"", open("pyproject.toml").read()).group(1))')"
if [[ -n "$VERSION_SET" && "$VERSION_SET" != "$VERSION" ]]; then
  sed -i '' "s/version = \"$VERSION\"/version = \"$VERSION_SET\"/" pyproject.toml
  git add pyproject.toml && git commit -qm "chore: release v$VERSION_SET" && git push -q origin main
  VERSION="$VERSION_SET"
fi
TAG="v$VERSION"
git rev-parse "$TAG" >/dev/null 2>&1 && { echo "error: tag $TAG exists"; exit 1; }
git tag "$TAG" && git push -q origin "$TAG"
TARBALL="pc-optimize-$TAG.tar.gz"
git archive --format=tar.gz --prefix="pc-optimize/" -o "$TARBALL" "$TAG"
shasum -a 256 "$TARBALL" > SHA256SUMS
[[ -z "$NOTES" ]] && NOTES="pc-optimize $TAG — measure, change only what's supported, verify."
DRAFT_FLAG=(); [[ $DRAFT -eq 1 ]] && DRAFT_FLAG=(--draft)
gh release create "$TAG" -R "$REPO" --title "Optimize $VERSION" --notes "$NOTES" "${DRAFT_FLAG[@]+"${DRAFT_FLAG[@]}"}"
gh release upload "$TAG" -R "$REPO" "$TARBALL" SHA256SUMS
rm -f "$TARBALL" SHA256SUMS
echo "✅ Optimize $VERSION → $REPO ($TAG)"
