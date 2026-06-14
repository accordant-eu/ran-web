#!/bin/sh
# docker-entrypoint.sh — fix bind-mount permissions before starting the app
# Ensures the ran user can read prompts and write to data/ regardless of
# how the host directories were created.

set -e

# Fix permissions on bind-mounted directories if running as root
if [ "$(id -u)" = "0" ]; then
  chown -R ran:ran /app/data /app/prompts 2>/dev/null || true
  chmod 775 /app/data 2>/dev/null || true
  chmod 664 /app/data/*.txt /app/data/*.jsonl 2>/dev/null || true
  exec su-exec ran "$@"
fi

exec "$@"
