#!/usr/bin/env bash
set -euo pipefail

# Simple helper: create a tag locally (annotated if message provided) and push it to origin

set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <tag> [message]"
  echo "Example: $0 v1.2.3 'Release v1.2.3'"
  exit 2
fi

TAG=$1
MSG=${2:-}

# Ensure we are in repository root (script may be executed from project root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
cd "$REPO_ROOT"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Error: not inside a git repository" >&2
  exit 1
fi

echo "Tag: $TAG"

if git rev-parse --verify --quiet "$TAG" >/dev/null; then
  echo "Tag '$TAG' already exists locally. Pushing it to origin..."
else
  if [ -n "$MSG" ]; then
    echo "Creating annotated tag '$TAG' with message: $MSG"
    git tag -a "$TAG" -m "$MSG"
  else
    echo "Creating lightweight tag '$TAG'"
    git tag "$TAG"
  fi
fi

echo "Pushing tag '$TAG' to origin..."
git push origin "$TAG"

echo "Done. Tag '$TAG' pushed to origin."
