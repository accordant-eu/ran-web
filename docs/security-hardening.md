# Security Hardening — ran.accordant.eu

This document is intentionally kept brief. Specific vulnerability details and
remediation notes are not published in this public repository.

## Status

A security audit was completed on 2026-06-14. All identified findings have been
addressed. The codebase is hardened against common web application attack classes
including CORS misconfiguration, race conditions, input validation gaps, and
information disclosure.

## Verification

After any infrastructure change, run:

```bash
# All tests must pass
python3 -m pytest tests/ -v

# Security headers
curl -sI https://ran.accordant.eu/ | grep -iE "strict-transport|content-security|x-frame|x-content|referrer|permissions"

# CORS blocks external origins (should return no Access-Control-Allow-Origin header)
curl -sI -X OPTIONS https://ran.accordant.eu/process \
  -H "Origin: https://evil.com" \
  -H "Access-Control-Request-Method: POST" | grep -i "access-control-allow-origin"

# Health check
curl -s https://ran.accordant.eu/health
```

## Reporting vulnerabilities

If you find a security issue, please report it privately to rufus@accordant.eu
rather than opening a public GitHub issue.
