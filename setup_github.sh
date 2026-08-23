#!/usr/bin/env bash
# setup_github.sh — one-time: put this project on GitHub so the cloud runner works.
#
# HOW TO USE:
#   1. Create an EMPTY private repo on github.com (no README, no .gitignore).
#      Copy its URL, e.g. https://github.com/<you>/polymarket-paper.git
#   2. In Terminal, from this folder, run:
#        bash setup_github.sh https://github.com/<you>/polymarket-paper.git
#
# It is safe to re-run; it won't wipe anything.

set -euo pipefail

REPO_URL="${1:-}"
if [ -z "$REPO_URL" ]; then
  echo "ERROR: pass your empty GitHub repo URL, e.g."
  echo "  bash setup_github.sh https://github.com/<you>/polymarket-paper.git"
  exit 1
fi

cd "$(dirname "$0")"
echo "Working in: $(pwd)"

# 1. init (safe if already a repo)
if [ ! -d .git ]; then
  git init
  git branch -M main
fi

# 2. sanity: make sure the cache isn't about to be committed
if [ ! -f .gitignore ] || ! grep -q ".pmc_cache/" .gitignore; then
  echo "WARNING: .gitignore missing or doesn't exclude .pmc_cache/ — stopping so"
  echo "you don't commit ~13k cache files. Restore .gitignore and re-run."
  exit 1
fi

# 3. stage + commit
git add -A
if git diff --cached --quiet; then
  echo "Nothing new to commit."
else
  git commit -m "Polymarket paper-trade: engine, ledger, cloud runner"
fi

# 4. wire the remote (replace if it already exists)
if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REPO_URL"
else
  git remote add origin "$REPO_URL"
fi

# 5. push
echo "Pushing to $REPO_URL ..."
git push -u origin main

echo
echo "DONE. Next: on github.com open your repo -> Settings -> Actions -> General"
echo "-> Workflow permissions -> enable 'Read and write permissions' -> Save."
echo "Then Actions tab -> 'Polymarket paper-trade daily' -> Run workflow (to test)."
