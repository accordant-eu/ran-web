# Security Hardening — ran.accordant.eu

Last updated: 2026-06-14. Based on a full adversarial security audit of the codebase.

## Status

| Category | Items | Status |
|---|---|---|
| Critical (C-1–C-4) | CORS, API docs, race condition, oracle | ✅ All fixed |
| High (H-1–H-5) | Validation, locking, timeout, logging, CSPRNG | ✅ All fixed |
| Medium (M-1–M-5) | Headers, nginx version, prompt injection, file perms, TLS | ✅ All fixed |
| Medium (M-6) | Egress restriction | ⚠️ Partial — named network created; iptables pending manual decision |
| Low (L-1–L-5) | Input limits, language allowlist, SRI, health response, rootfs | ✅ All fixed |
| CSP `unsafe-inline` | Inline scripts and onclick handlers | ✅ Removed — strict `script-src 'self'` |

36/36 tests passing. All changes committed and pushed. CI green.

---

## What was implemented (all automatic, in code)

| Finding | Fix | Where |
|---|---|---|
| C-1 CORS wildcard | `allow_origins=["https://ran.accordant.eu"]` | `backend/main.py` |
| C-2 API docs exposed | `docs_url=None, redoc_url=None, openapi_url=None` | `backend/main.py` |
| C-3 Race condition on codes.txt | `fcntl.LOCK_EX` exclusive lock — atomic check-and-burn | `backend/main.py` |
| C-4 Invite code oracle | Unified error message for invalid and exhausted | `backend/main.py` |
| H-1 No file validation / decompression bomb | Per-file 10 MB limit, `%PDF` magic bytes, 100-page cap, 200k char truncation | `backend/main.py` |
| H-2 Code burned before stream | Burn inside lock; new_codes generated atomically | `backend/main.py` |
| H-3 Single worker + no API timeout | `timeout=120.0` on Anthropic client, `--workers 2` | `backend/main.py`, `Dockerfile` |
| H-4 `completed: True` hardcoded | Flag tracks actual stream outcome | `backend/main.py` |
| H-5 `random.choices` not CSPRNG | `secrets.choice` for invite code generation | `backend/main.py` |
| M-1 No security headers | HSTS, CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy | nginx |
| M-2 nginx version disclosed | `server_tokens off` | nginx |
| M-3 Prompt injection via PDF text | `sanitize_pdf_text()` strips XML tags from extracted content | `backend/main.py` |
| M-4 data/ files world-readable | `chmod 640` on codes.txt and ops_log.jsonl | host filesystem |
| M-5 TLS 1.0/1.1 in global nginx.conf | `ssl_protocols TLSv1.2 TLSv1.3` | `/etc/nginx/nginx.conf` |
| L-1 No invite code length limit | `MAX_INVITE_CODE_LEN = 32` guard | `backend/main.py` |
| L-2 language not validated | `ALLOWED_LANGUAGES` frozenset, unknown → `'es'` | `backend/main.py` |
| L-3 No SRI on marked.min.js | `integrity="sha384-..."` attribute | `frontend/index.html` |
| L-4 /health leaks service name | Removed `"service": "ran"` from response | `backend/main.py` |
| L-5 Writable container rootfs | `read_only: true` + `tmpfs` for /tmp and /run | `docker-compose.yml` |

---

## What still requires manual action

### M-6 — Egress restriction (iptables)

The Docker container can make outbound connections to any host. It only needs to reach `api.anthropic.com:443`. True egress restriction requires host iptables rules.

Docker's networking doesn't provide per-container egress filtering without additional tooling. The options:

**Option A: iptables rules (recommended)**

```bash
# Allow the ran-web container to reach Anthropic API only
# Container IP range for ran-net (adjust if different):
CONTAINER_RANGE="172.18.0.0/16"

# Resolve Anthropic API IPs (these change; use DNS-based approach below instead)
# Better: allow by hostname via a DNS-aware firewall (nftables with ct helper, etc.)

# Basic approach: allow outbound 443 from container range, block everything else
iptables -I DOCKER-USER -s $CONTAINER_RANGE ! -d api.anthropic.com -p tcp --dport 443 -j DROP
iptables -I DOCKER-USER -s $CONTAINER_RANGE -p tcp --dport 443 -j ACCEPT
iptables -I DOCKER-USER -s $CONTAINER_RANGE -j DROP
```

Note: Anthropic's IP ranges change. A more robust approach uses a DNS-aware firewall (nftables with ipset) or an HTTP proxy that only allows `api.anthropic.com`.

**Option B: HTTP proxy (more robust)**

Deploy a forward proxy (e.g. Squid or Tinyproxy) in the Docker network, configure it to whitelist `api.anthropic.com` only, and set `HTTPS_PROXY` in the container environment. The container's direct internet access can then be blocked.

**Option C: Accept current risk**

For the current threat model (small invite-only service), the risk of container compromise leading to significant exfiltration is low. The containers run as non-root (`ran` user), and the read-only rootfs limits what an attacker can install. Documenting this gap and revisiting if the service scales is a reasonable position.

---

## Future hardening (follow-up, not yet implemented)

### Extract inline scripts to enable strict CSP

Current CSP has `script-src 'self' 'unsafe-inline'` because:
1. Static `onclick=` handlers in `index.html` (print button, file remove chips)
2. Inline `<script>` blocks in both `index.html` and `privacy/index.html`

To remove `'unsafe-inline'` from `script-src`:
1. Move all inline `<script>` blocks to `app.js` / `privacy.js`
2. Replace `onclick=` attributes with `addEventListener()` calls in the JS files
3. Update CSP to `script-src 'self'`

This gives a fully strict CSP that blocks DOM-based XSS via injected scripts.

### Implement log rotation for ops_log.jsonl

The 12-month retention obligation (GDPR Art. 5.1.e) needs automated enforcement. Currently deletion is manual. Add a cron job or logrotate config:

```bash
# /etc/logrotate.d/ran-ops-log
/srv/ran-web/data/ops_log.jsonl {
    daily
    rotate 365
    compress
    missingok
    notifempty
    dateext
    copytruncate
}
```

Alternatively, add a periodic purge script that removes lines older than 365 days from the JSONL file.

### nginx log retention for `/` access log

Static file access logs (IPs) at `/var/log/nginx/access.log` rotate via the default logrotate config. Verify the rotation interval matches the 30-day commitment in the privacy policy:

```bash
grep -A5 "nginx" /etc/logrotate.d/nginx
```

If the default rotation is longer than 30 days, update `/etc/logrotate.d/nginx` accordingly.

---

## Verification

After any infrastructure change, run:

```bash
# All 36 tests must pass
python3 -m pytest tests/ -v

# Zero-retention audit
bash scripts/verify-zero-retention.sh

# Security headers
curl -sI https://ran.accordant.eu/ | grep -iE "strict-transport|content-security|x-frame|x-content|referrer|permissions"

# Confirm no API schema exposure
curl -s -o /dev/null -w "%{http_code}" https://ran.accordant.eu/openapi.json
# Should be 200 (nginx returns frontend HTML) — FastAPI schema is disabled

# Confirm CORS blocks external origins
curl -sI -X OPTIONS https://ran.accordant.eu/process \
  -H "Origin: https://evil.com" \
  -H "Access-Control-Request-Method: POST" | grep -i "access-control-allow-origin"
# Should return nothing (no header) — evil.com is rejected
```
