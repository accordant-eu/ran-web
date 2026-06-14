#!/usr/bin/env bash
# fetch-prompt.sh — Pull the IRPF system prompt from the private accordant-eu/ran repo.
#
# Run this on deploy and whenever the prompt is updated in the repo.
# Requires GITHUB_TOKEN to be set (rufus-vidar PAT with read access to accordant-eu/ran).
#
# Usage:
#   GITHUB_TOKEN=ghp_... ./scripts/fetch-prompt.sh
#   or with .env loaded:
#   source .env && ./scripts/fetch-prompt.sh

set -euo pipefail

REPO="accordant-eu/ran"
PROMPT_PATH="prompts/irpf-reviewer-system-prompt.txt"
OUTPUT_DIR="$(dirname "$0")/../prompts"
OUTPUT_FILE="$OUTPUT_DIR/irpf-reviewer-system-prompt.txt"

if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "ERROR: GITHUB_TOKEN is not set." >&2
  echo "Set it to a GitHub PAT with read access to $REPO." >&2
  exit 1
fi

echo "Fetching prompt from $REPO/$PROMPT_PATH ..."

mkdir -p "$OUTPUT_DIR"

# Fetch via GitHub Contents API — returns base64-encoded content
RESPONSE=$(curl -sf \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3.raw" \
  "https://api.github.com/repos/$REPO/contents/$PROMPT_PATH")

echo "$RESPONSE" > "$OUTPUT_FILE"

LINES=$(wc -l < "$OUTPUT_FILE")
echo "✓ Prompt saved to $OUTPUT_FILE ($LINES lines)"
