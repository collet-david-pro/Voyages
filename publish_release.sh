#!/usr/bin/env bash
set -euo pipefail

# publish_release.sh
# USAGE:
#   ./scripts/publish_release.sh v1.2.3 "Release title" "Release body text"
#
# This script will:
#  - create an annotated git tag (if not exists), push it to origin
#  - create a GitHub Release for the tag and publish it
#
# It prefers to use the GitHub CLI (gh) if available. Otherwise it will use the
# GitHub REST API and requires GITHUB_TOKEN env var set to create the release.

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <tag> [title] [body]"
  exit 2
fi

TAG=$1
TITLE=${2:-"Release $TAG"}
BODY=${3:-"Release ${TAG}"}

echo "Preparing release for tag: $TAG"

# Ensure we are in repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Error: not inside a git repository"
  exit 1
fi

# create annotated tag if not present
if git rev-parse "$TAG" >/dev/null 2>&1; then
  echo "Tag $TAG already exists locally. Skipping tag creation."
else
  echo "Creating annotated tag $TAG"
  git tag -a "$TAG" -m "$TITLE"
fi

echo "Pushing tag $TAG to origin"
git push origin --tags --follow-tags -q

if command -v gh >/dev/null 2>&1; then
  echo "Using gh CLI to create release..."
  gh release create "$TAG" -t "$TITLE" -n "$BODY"
  echo "Release created with gh: $TAG"
  exit 0
fi

# fallback: use GitHub API
if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "Error: gh not found and GITHUB_TOKEN not set. Install gh or set GITHUB_TOKEN to use REST fallback." >&2
  exit 2
fi

# Try to determine owner/repo from git remote
REMOTE_URL=$(git remote get-url origin || true)
if [ -z "$REMOTE_URL" ]; then
  echo "Error: no git remote 'origin' configured." >&2
  exit 1
fi

_parse_owner_repo() {
  url="$1"
  # ssh format: git@github.com:owner/repo.git
  if [[ "$url" =~ ^git@github.com:(.+)/(.+)\.git$ ]]; then
    echo "${BASH_REMATCH[1]}/${BASH_REMATCH[2]}"
    return
  fi
  # https format: https://github.com/owner/repo.git
  if [[ "$url" =~ ^https://github.com/(.+)/(.+)(\.git)?$ ]]; then
    echo "${BASH_REMATCH[1]}/${BASH_REMATCH[2]}"
    return
  fi
  # attempt naive fallback
  echo "${url##*/}" | sed 's/.git$//'
}

OWNER_REPO=$(_parse_owner_repo "$REMOTE_URL")
if [[ "$OWNER_REPO" != */* ]]; then
  echo "Could not parse owner/repo from remote url: $REMOTE_URL" >&2
  exit 1
fi

OWNER=${OWNER_REPO%%/*}
REPO=${OWNER_REPO##*/}

echo "Using GitHub repo: ${OWNER}/${REPO}"

CREATE_RESPONSE=$(curl -sS -X POST "https://api.github.com/repos/${OWNER}/${REPO}/releases" \
  -H "Authorization: token ${GITHUB_TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  -d @- <<JSON
{
  "tag_name": "${TAG}",
  "name": "${TITLE}",
  "body": "${BODY}",
  "draft": false,
  "prerelease": false
}
JSON
)

if echo "$CREATE_RESPONSE" | grep -q '"html_url"'; then
  echo "Release created:"
  echo "$CREATE_RESPONSE" | sed -n 's/.*"html_url": "\([^"]*\)".*/\1/p'
  exit 0
else
  echo "Failed to create release. Response from GitHub API:" >&2
  echo "$CREATE_RESPONSE" >&2
  exit 4
fi
