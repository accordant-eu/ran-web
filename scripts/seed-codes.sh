#!/usr/bin/env bash
# seed-codes.sh — Generate the initial batch of invite codes.
#
# Run once on first deploy to populate data/codes.txt.
# Safe to re-run — skips codes that already exist.
#
# Usage:
#   ./scripts/seed-codes.sh           # generates 20 codes (default)
#   ./scripts/seed-codes.sh 50        # generates 50 codes

set -euo pipefail

COUNT="${1:-20}"
DATA_DIR="$(dirname "$0")/../data"
CODES_FILE="$DATA_DIR/codes.txt"

mkdir -p "$DATA_DIR"
touch "$CODES_FILE"

# Load existing codes to avoid duplicates
existing=$(grep -v "^USED:" "$CODES_FILE" 2>/dev/null | grep -v "^$" || true)
used=$(grep "^USED:" "$CODES_FILE" 2>/dev/null | sed 's/^USED://' || true)
all_existing=$(printf "%s\n%s" "$existing" "$used" | grep -v "^$" || true)

generated=0
attempts=0
max_attempts=$((COUNT * 10))

while [ "$generated" -lt "$COUNT" ] && [ "$attempts" -lt "$max_attempts" ]; do
  # Generate RENTA-XXXX: 4 uppercase alphanumeric characters
  suffix=$(cat /dev/urandom | tr -dc 'A-Z0-9' | head -c 4)
  code="RENTA-${suffix}"

  # Skip if already exists
  if echo "$all_existing" | grep -qx "$code"; then
    attempts=$((attempts + 1))
    continue
  fi

  echo "$code" >> "$CODES_FILE"
  all_existing=$(printf "%s\n%s" "$all_existing" "$code")
  generated=$((generated + 1))
  attempts=$((attempts + 1))
done

echo "✓ Generated $generated invite codes → $CODES_FILE"
echo ""
echo "Valid codes ready to use:"
grep -v "^USED:" "$CODES_FILE" | grep -v "^$"
