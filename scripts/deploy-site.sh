#!/bin/bash
# Deploy the Optimize site (site/index.html) to GitHub Pages on this repo.
# Live at: https://kswork2001.github.io/Optimize/
set -euo pipefail
SITE_INDEX="$(cd "$(dirname "$0")/.." && pwd)/site/index.html"
[[ -f "$SITE_INDEX" ]] || { echo "error: site/index.html not found"; exit 1; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
git clone -q "$(git -C "$(dirname "$0")/.." remote get-url origin)" "$TMP/repo"
cd "$TMP/repo"
if git ls-remote --exit-code --heads origin gh-pages >/dev/null 2>&1; then
  git checkout -q gh-pages
else
  git checkout -q --orphan gh-pages; git rm -rfq . 2>/dev/null || true
fi
cp "$SITE_INDEX" index.html
git add index.html
if git diff --cached --quiet; then echo "site unchanged"; else
  git commit -qm "site: update landing page" && git push -q origin gh-pages
  echo "✅ deployed → https://kswork2001.github.io/Optimize/"
fi
