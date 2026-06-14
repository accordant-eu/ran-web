#!/usr/bin/env bash
# deploy.sh — pull latest, stamp version, rebuild backend if needed
# Usage: sudo bash scripts/deploy.sh
# Run from anywhere; resolves paths relative to this script.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

echo "=== Rán deploy $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

# ── 1. Pull ──────────────────────────────────────────────────────────────────
echo "→ git pull"
git pull

SHORT_HASH=$(git rev-parse --short HEAD)
DATE=$(date -u +%Y-%m-%d)
VERSION="${DATE}.${SHORT_HASH}"
echo "→ version: ${VERSION}"

# ── 2. Stamp meta version in the live frontend file ──────────────────────────
# This modifies the deployed file only — the repo keeps content="dev" as baseline.
echo "→ stamping frontend/index.html"
sed -i "s|<meta name=\"version\" content=\"[^\"]*\" />|<meta name=\"version\" content=\"${VERSION}\" />|" \
  "$REPO_DIR/frontend/index.html"

# Verify the stamp landed
STAMPED=$(grep -o "content=\"${VERSION}\"" "$REPO_DIR/frontend/index.html" || true)
if [ -z "$STAMPED" ]; then
  echo "✗ version stamp failed — check meta tag format in index.html"
  exit 1
fi
echo "  ✓ stamped: ${STAMPED}"

# ── 3. Rebuild + restart Docker if backend or image config changed ────────────
BACKEND_CHANGED=$(git diff HEAD~1 HEAD --name-only 2>/dev/null \
  | grep -E "^(backend/|Dockerfile|docker-compose\.yml|docker-entrypoint\.sh)" || true)

if [ -n "$BACKEND_CHANGED" ]; then
  echo "→ backend changes detected — rebuilding Docker image"
  echo "  changed: $(echo "$BACKEND_CHANGED" | tr '\n' ' ')"
  docker compose build --no-cache ran-web
  docker compose up -d ran-web
  echo "  ✓ container restarted"
else
  echo "→ no backend changes — skipping Docker rebuild"
fi

# ── 4. Health check ──────────────────────────────────────────────────────────
echo "→ health check"
sleep 1
HTTP=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health || true)
if [ "$HTTP" = "200" ]; then
  echo "  ✓ /health ${HTTP}"
else
  echo "  ✗ /health returned ${HTTP} — check container logs"
  docker compose logs --tail=20 ran-web
  exit 1
fi

echo ""
echo "✓ deploy complete — version ${VERSION}"
