# Deployment Guide

## Architecture

Rán runs as a Docker container behind an nginx reverse proxy.

```
Internet
   │
nginx (host) — ran.accordant.eu, TLS via Let's Encrypt
   │
   └── Docker: ran-web container (localhost:8000)
         ├── uvicorn + FastAPI (main.py)
         ├── pdfplumber + anthropic
         ├── bind mount: ./prompts/   (prompt file, fetched on deploy)
         └── bind mount: ./data/      (codes.txt, ops_log.jsonl)
```

PDFs are processed in memory inside the container. Nothing is written outside `./data/`.

---

## Phase 0 — Docker on existing server

Runs on the same host as other services. Docker provides namespace isolation (separate filesystem, network, process space). Sufficient for a small invite-only cohort.

**Known limitation:** Docker uses the host kernel. A container escape via a kernel exploit would expose the host. Acceptable at Phase 0 scale; migrate to a dedicated VPS before public launch.

## Phase 0 → Phase 1 gate

Before opening to the public (Phase 1), migrate to a dedicated VPS. This is a hard gate — do not skip it.

Checklist before migration:
- [ ] Phase 0 cohort completed (10+ sessions, referral chain visible in ops log)
- [ ] Dedicated Hetzner CAX11 VPS provisioned
- [ ] `ran-web` re-deployed on new VPS using same procedure below
- [ ] DNS updated: `ran.accordant.eu` → new VPS IP
- [ ] OpenClaw server confirmed unchanged and isolated

## Phase 1+ — Dedicated VPS (recommended)

For public launch, run `ran-web` on a separate VPS. This gives full hardware isolation — if `ran-web` is compromised, there is no path to other services.

Recommended: **Hetzner CAX11** (2 vCPU ARM, 4GB RAM, 40GB SSD, ~€4/month). The deploy procedure below is identical on a dedicated VPS.

---

## Prerequisites

- Docker and Docker Compose installed
- nginx installed on the host
- `certbot` for TLS (`certbot --nginx -d ran.accordant.eu`)
- DNS: `ran.accordant.eu` → server IP

---

## Deploy from scratch

```bash
# 1. Clone the web app
git clone git@github.com:accordant-eu/ran-web.git /srv/ran-web
cd /srv/ran-web
mkdir -p prompts data

# 2. Configure environment
cp backend/.env.example backend/.env
# Edit backend/.env:
#   ANTHROPIC_API_KEY=sk-ant-...     (dedicated key for Rán)
#   GITHUB_TOKEN=ghp_...             (read access to accordant-eu/ran)
#   IRPF_SYSTEM_PROMPT_FILE=/app/prompts/irpf-reviewer-system-prompt.txt

# 3. Fetch the system prompt (single HTTPS call — no repo clone)
./scripts/fetch-prompt.sh

# 4. Generate initial invite codes (20 by default)
./scripts/seed-codes.sh
# To generate a different number: ./scripts/seed-codes.sh 50

# 5. Build and start the container
docker compose up -d

# 6. Configure nginx
sudo cp deploy/nginx.conf /etc/nginx/sites-available/ran-web
sudo ln -s /etc/nginx/sites-available/ran-web /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# 7. Issue TLS certificate
sudo certbot --nginx -d ran.accordant.eu
```

---

## Updating the app

```bash
cd /srv/ran-web
git pull
docker compose build
docker compose up -d
```

## Updating the system prompt

The prompt lives in the private `accordant-eu/ran` repo. To pull a new version:

```bash
cd /srv/ran-web
./scripts/fetch-prompt.sh
docker compose restart ran-web
```

---

## Checking status

```bash
# Container logs
docker compose logs -f ran-web

# Health check
curl http://localhost:8000/health

# Ops log (metadata only — no document content)
tail -f /srv/ran-web/data/ops_log.jsonl
```

---

## Invite codes

Codes live in `data/codes.txt`, one per line. Used codes are prefixed `USED:`.

To add codes manually:
```bash
echo "RENTA-XXXX" >> /srv/ran-web/data/codes.txt
```

To check how many valid codes remain:
```bash
grep -v "^USED:" /srv/ran-web/data/codes.txt | grep -v "^$" | wc -l
```
