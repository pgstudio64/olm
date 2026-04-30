#!/usr/bin/env bash
#
# publish_to_github.sh — Publish the public subset of this repo to GitHub.
#
# The local repo contains both public source (olm/, README, pyproject…) and
# private notes (docs/, CLAUDE*, project/). GitHub must only receive the
# public subset. This script:
#
#   1. Creates a temporary clone of the current repo
#   2. Runs git-filter-repo on the clone to strip all private paths
#      from HEAD AND from the entire history
#   3. Verifies no private path remains in the cleaned clone
#   4. Shows a summary and asks for confirmation
#   5. Force-pushes the cleaned clone to github.com/pgstudio64/olm
#   6. Cleans up the temporary directory
#
# The local repo is NEVER modified. All work happens in the ephemeral clone.
#
# Requirements:
#   - git-filter-repo installed (pip install git-filter-repo)
#   - Write access to the github remote (credential cached or PAT configured)
#
# Usage: bash scripts/publish_to_github.sh

set -euo pipefail

# --- Configuration ---
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEMP_CLONE="/tmp/olm_public_publish_$$"
GITHUB_REMOTE_URL="https://github.com/pgstudio64/olm.git"
GITHUB_BRANCH="main"

# Paths stripped from the clone's HEAD and all history before push.
# Update this list if new private directories appear.
PRIVATE_PATHS=(
  "docs/"
  "CLAUDE.md"
  "CLAUDE_IMPLEMENTER.md"
  "project/"
  ".claude/"
  "solver_lab/"
)

# Glob patterns for files not captured by directory paths above.
PRIVATE_GLOBS=(
  "SESSION_RESUME*"
)

# Regex used to detect leftover private paths (must cover all entries above).
PRIVATE_REGEX='^(docs/|CLAUDE\.md|CLAUDE_IMPLEMENTER\.md|project/|\.claude/|solver_lab/|SESSION_RESUME)'

cd "$REPO_ROOT"

echo "=== OLM GitHub publish ==="
echo "Repo root:      $REPO_ROOT"
echo "Temp clone:     $TEMP_CLONE"
echo "Target remote:  $GITHUB_REMOTE_URL ($GITHUB_BRANCH)"
echo ""

# --- Pre-flight checks ---
if ! command -v git-filter-repo >/dev/null 2>&1; then
  echo "ERROR: git-filter-repo not found."
  echo "Install via: pip install git-filter-repo"
  exit 1
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "ERROR: $REPO_ROOT is not a git repo."
  exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
  echo "WARNING: You have uncommitted changes."
  echo "The publish will use your LAST COMMIT, not the uncommitted state."
  echo ""
  git status --short | head -10
  echo ""
  read -p "Continue anyway? [y/N] " ans
  [[ "$ans" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }
fi

LOCAL_HEAD=$(git rev-parse HEAD)
echo "Local HEAD:     $LOCAL_HEAD"
echo ""

# --- Step 1: clone ---
echo "[1/7] Cloning to $TEMP_CLONE..."
rm -rf "$TEMP_CLONE"
git clone --no-local "$REPO_ROOT" "$TEMP_CLONE" >/dev/null 2>&1

# --- Step 2: filter-repo ---
echo "[2/7] Filtering private paths..."
cd "$TEMP_CLONE"
FILTER_ARGS=()
for p in "${PRIVATE_PATHS[@]}"; do
  FILTER_ARGS+=(--path "$p")
done
for g in "${PRIVATE_GLOBS[@]}"; do
  FILTER_ARGS+=(--path-glob "$g")
done
git-filter-repo --invert-paths "${FILTER_ARGS[@]}" --force 2>&1 | tail -3

# --- Step 2b: translate commit messages to English ---
TRANSLATIONS_FILE="$REPO_ROOT/scripts/commit_translations.json"
if [ -f "$TRANSLATIONS_FILE" ]; then
  echo "[2b/7] Translating commit messages to English..."
  git-filter-repo --message-callback '
import json
_g = globals()
if "_trans" not in _g:
    with open("'"$TRANSLATIONS_FILE"'") as f:
        _g["_trans"] = json.load(f)
lines = message.split(b"\n")
first = lines[0].decode("utf-8", errors="replace")
if first in _g["_trans"]:
    lines[0] = _g["_trans"][first].encode("utf-8")
return b"\n".join(lines)
' --force 2>&1 | tail -3
else
  echo "[2b/7] No translations file found, skipping."
fi

# --- Step 3: verification ---
echo "[3/7] Verifying no private paths remain..."

# Check HEAD tree
LEAK_HEAD=$(git ls-files | grep -iE "$PRIVATE_REGEX" || true)

# Check all-commit history (every path ever added)
LEAK_HIST=$(git log --all --pretty=format: --name-only 2>/dev/null \
  | sort -u | grep -iE "$PRIVATE_REGEX" || true)

if [ -n "$LEAK_HEAD" ] || [ -n "$LEAK_HIST" ]; then
  echo "ERROR: private paths still present in filtered clone!"
  if [ -n "$LEAK_HEAD" ]; then
    echo "  HEAD leak:"
    echo "$LEAK_HEAD" | sed 's/^/    /'
  fi
  if [ -n "$LEAK_HIST" ]; then
    echo "  History leak:"
    echo "$LEAK_HIST" | sed 's/^/    /'
  fi
  echo ""
  echo "Aborted. Temp clone left at $TEMP_CLONE for inspection."
  exit 1
fi
echo "  OK — HEAD and history both clean."

# --- Step 4: summary and confirmation ---
echo "[4/7] Summary of what will be pushed:"
COMMIT_COUNT=$(git log --oneline | wc -l | tr -d ' ')
FILE_COUNT=$(git ls-files | wc -l | tr -d ' ')
echo "  Commits:     $COMMIT_COUNT"
echo "  Files:       $FILE_COUNT"
echo "  Top-level:   $(git ls-files | awk -F/ '{print $1}' | sort -u | tr '\n' ' ')"
echo ""
echo "  Last 5 commits:"
git log --oneline -5 | sed 's/^/    /'
echo ""

read -p "Force-push to $GITHUB_REMOTE_URL $GITHUB_BRANCH? [y/N] " ans
if [[ ! "$ans" =~ ^[Yy]$ ]]; then
  echo "Aborted before push. Cleaning temp clone."
  cd "$REPO_ROOT"
  rm -rf "$TEMP_CLONE"
  exit 0
fi

# --- Step 5: push ---
echo "[5/7] Pushing to GitHub..."
git remote add github "$GITHUB_REMOTE_URL"
git push github "$GITHUB_BRANCH" --force 2>&1 | tail -5

# --- Step 6: cleanup ---
echo "[6/7] Cleaning up temp clone..."
cd "$REPO_ROOT"
rm -rf "$TEMP_CLONE"

echo ""
echo "=== Published successfully. ==="
echo "  Local HEAD:   $LOCAL_HEAD (unchanged)"
echo "  GitHub HEAD:  (filtered copy of $LOCAL_HEAD)"
