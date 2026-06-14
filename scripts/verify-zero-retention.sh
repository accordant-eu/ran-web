#!/usr/bin/env bash
# verify-zero-retention.sh — Live server zero-retention audit.
#
# Scans the running server for any retained document content after a session.
# Run this after a real session to confirm the production deployment matches
# the zero-retention guarantee.
#
# Usage:
#   ./scripts/verify-zero-retention.sh
#
# Exit codes:
#   0 — all checks passed (zero retention confirmed)
#   1 — one or more checks failed (retention detected or indeterminate)

set -euo pipefail

PASS=0
FAIL=0
WARN=0
DATA_DIR="${DATA_DIR:-/srv/ran-web/data}"
CONTAINER="${CONTAINER:-ran-web}"

green() { echo -e "\033[32m✓\033[0m  $*"; }
red()   { echo -e "\033[31m✗\033[0m  $*"; FAIL=$((FAIL+1)); }
warn()  { echo -e "\033[33m⚠\033[0m  $*"; WARN=$((WARN+1)); }
ok()    { green "$*"; PASS=$((PASS+1)); }

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Rán — Zero Retention Live Audit"
echo "  $(date -u +"%Y-%m-%d %H:%M UTC")"
echo "═══════════════════════════════════════════════════"
echo ""

# 1. Check /tmp on host
echo "1. Host /tmp — PDF files"
pdf_count=$(find /tmp -name "*.pdf" -o -name "pdfplumber*" 2>/dev/null | wc -l)
if [ "$pdf_count" -eq 0 ]; then
  ok "No PDF files in /tmp (host)"
else
  red "$pdf_count PDF-related files found in /tmp (host)"
  find /tmp -name "*.pdf" -o -name "pdfplumber*" 2>/dev/null
fi

# 2. Check /tmp inside container
echo ""
echo "2. Container /tmp — PDF files"
container_tmp=$(docker exec "$CONTAINER" find /tmp -name "*.pdf" 2>/dev/null | wc -l)
if [ "$container_tmp" -eq 0 ]; then
  ok "No PDF files in container /tmp"
else
  red "$container_tmp PDF files found in container /tmp"
  docker exec "$CONTAINER" find /tmp -name "*.pdf" 2>/dev/null
fi

# 3. Check /app inside container for unexpected files
echo ""
echo "3. Container /app — unexpected files outside data/ and prompts/"
unexpected=$(docker exec "$CONTAINER" find /app \
  -not -path "/app/data/*" \
  -not -path "/app/prompts/*" \
  -not -name "main.py" \
  -not -name "requirements.txt" \
  -not -name "*.pyc" \
  -type f 2>/dev/null | grep -v "__pycache__" | wc -l || true)
if [ "$unexpected" -eq 0 ]; then
  ok "No unexpected files in container /app"
else
  warn "$unexpected unexpected files in container /app (may be .pyc or similar)"
  docker exec "$CONTAINER" find /app \
    -not -path "/app/data/*" \
    -not -path "/app/prompts/*" \
    -not -name "main.py" \
    -not -name "*.pyc" \
    -type f 2>/dev/null | grep -v "__pycache__"
fi

# 4. Ops log — field audit
echo ""
echo "4. Ops log — field content audit"
if [ -f "$DATA_DIR/ops_log.jsonl" ] && [ -s "$DATA_DIR/ops_log.jsonl" ]; then
  forbidden_fields=("text" "content" "pdf_text" "document" "extracted" "name" "nif" "apellidos" "address")
  log_clean=true
  for field in "${forbidden_fields[@]}"; do
    if grep -q "\"$field\"" "$DATA_DIR/ops_log.jsonl" 2>/dev/null; then
      red "Forbidden field '$field' found in ops log"
      log_clean=false
    fi
  done
  if [ "$log_clean" = "true" ]; then
    ok "Ops log contains no forbidden content fields"
  fi
  echo "   Last entry: $(tail -1 "$DATA_DIR/ops_log.jsonl")"
else
  warn "Ops log is empty or does not exist — no sessions to audit yet"
fi

# 5. Nginx access log — no /process entries in the last hour
# (entries from before access_log was configured are expected; only flag recent ones)
echo ""
echo "5. Nginx access log — /process IP logging (last 60 min)"
CUTOFF=$(date -u -d "60 minutes ago" +"%d/%b/%Y:%H:%M" 2>/dev/null || date -u -v-60M +"%d/%b/%Y:%H:%M")
recent_process=$(sudo awk -v cutoff="$CUTOFF" '
  /POST \/process/ {
    match($4, /\[(.*)\]/, t)
    if (t[1] >= cutoff) print
  }
' /var/log/nginx/access.log 2>/dev/null | wc -l)
if [ "$recent_process" -gt 0 ]; then
  red "$recent_process recent /process entries found in nginx access log"
  warn "access_log off may not be active — check nginx config"
else
  ok "No recent /process entries in nginx access log (access_log off confirmed)"
fi

# 6. Nginx error log — check for unexpected PDF temp files
echo ""
echo "6. Nginx error log — PDF temp file references"
if sudo grep -qi "\.pdf" /var/log/nginx/error.log 2>/dev/null; then
  warn "PDF references found in nginx error log — review manually"
  sudo grep -i "\.pdf" /var/log/nginx/error.log 2>/dev/null | tail -5
else
  ok "No PDF references in nginx error log"
fi

# 7. Codes file — format check
echo ""
echo "7. Codes file — format integrity"
if [ -f "$DATA_DIR/codes.txt" ]; then
  invalid_lines=$(grep -v -E '^(USED:)?RENTA-[A-Z0-9]{4}(:[0-9]+)?$' \
    "$DATA_DIR/codes.txt" | grep -v "^$" | wc -l || true)
  if [ "$invalid_lines" -eq 0 ]; then
    total=$(grep -c "." "$DATA_DIR/codes.txt" || true)
    used=$(grep -c "^USED:" "$DATA_DIR/codes.txt" || true)
    ok "codes.txt format valid ($total codes, $used exhausted)"
  else
    red "$invalid_lines lines in codes.txt don't match expected format"
    grep -v -E '^(USED:)?RENTA-[A-Z0-9]{4}(:[0-9]+)?$' "$DATA_DIR/codes.txt" | grep -v "^$"
  fi
else
  warn "codes.txt not found at $DATA_DIR/codes.txt"
fi

# Summary
echo ""
echo "═══════════════════════════════════════════════════"
echo "  Results: ${PASS} passed  ${FAIL} failed  ${WARN} warnings"
echo "═══════════════════════════════════════════════════"
echo ""

if [ "$FAIL" -gt 0 ]; then
  echo "  ✗ AUDIT FAILED — retention detected or misconfiguration found"
  exit 1
else
  echo "  ✓ AUDIT PASSED — zero retention confirmed on this server"
  exit 0
fi
