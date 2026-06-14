# Rán — Spanish IRPF Explainer

**`ran.accordant.eu`** · Zero-retention · Open-source backend

---

## What it does

Rán accepts a Spanish IRPF tax return (Modelo 100 borrador) — one or two PDFs — and produces a plain-English explanation of what it contains, what it means, and anything worth checking. It is designed for expat professionals and international employees who receive their Spanish *declaración de la renta* each year and have no clear way to interpret it. You upload the PDF, you read the explanation on screen, you close the tab. That's it. Nothing is kept.

---

## Zero-retention architecture

```
PDF upload
    │
    ▼
FastAPI backend (RAM only)
    │
    ├── pdfplumber extracts text → BytesIO
    │   PDFs are NEVER written to disk.
    │
    ▼
Anthropic Claude API
    │
    ├── System prompt loaded from env var (not stored here)
    ├── PDF text sent as user message
    ├── Response streamed back to browser
    │
    ▼
Screen (browser)
    │
    └── Close tab → gone. Nothing stored.
```

**What persists:**
- `codes.txt` — valid/used invite codes (no user data, no document content)
- `ops_log.jsonl` — operational metadata only: timestamp, file size, response time, code used

**What never persists:**
- PDFs (never written to disk — `BytesIO` only)
- Extracted text (lives in Python memory for the duration of one request)
- The report (shown on screen, never stored)
- Any user-identifying information

**Anthropic API data policy:** Anthropic does not use API-submitted data for model training by default.
See: [https://www.anthropic.com/legal/aio](https://www.anthropic.com/legal/aio)

The architecture enforces zero-retention — not just policy. This code is intentionally short and auditable. Read `backend/main.py` in five minutes and verify it yourself.

---

## Environment variables

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `IRPF_SYSTEM_PROMPT` | The full system prompt (paste inline or load from file) |
| `IRPF_SYSTEM_PROMPT_FILE` | Alternative: path to a `.txt` file containing the prompt |
| `INVITE_CODES_FILE` | Path to `codes.txt` (one code per line, `USED:` prefix marks consumed codes) |
| `OPS_LOG_FILE` | Path to `ops_log.jsonl` (append-only operational log) |

**The system prompt is not committed to this repository.** It lives in a private store and is injected at runtime via `IRPF_SYSTEM_PROMPT` or `IRPF_SYSTEM_PROMPT_FILE`. This keeps the reasoning logic out of the public repo while keeping the infrastructure fully auditable.

Copy `.env.example` to `.env` and fill in your values before running.

---

## Running locally

**Requirements:** Python 3.11+, pip

```bash
# 1. Clone the repo
git clone https://github.com/accordant-eu/ran-web.git
cd ran-web

# 2. Install backend dependencies
cd backend
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env — add your ANTHROPIC_API_KEY and IRPF_SYSTEM_PROMPT

# 4. Create a codes file with at least one invite code
echo "RENTA-TEST01" > codes.txt

# 5. Start the backend
uvicorn main:app --reload --host 127.0.0.1 --port 8000

# 6. Open the frontend
# In a separate terminal or browser, open frontend/index.html
# Or serve it: python -m http.server 3000 --directory ../frontend
```

The backend runs at `http://127.0.0.1:8000`. The frontend HTML file can be served statically and points to `/process` on the same host by default.

---

## Deployment (VPS)

See `deploy/ran-web.service` for the systemd unit and `deploy/nginx.conf` for the nginx reverse proxy configuration targeting `ran.accordant.eu`.

HTTPS is handled by Let's Encrypt / Certbot — run `certbot --nginx -d ran.accordant.eu` after the nginx config is in place.

---

## What this is not

- Not a full accounting tool
- Not a replacement for a *gestor* or tax advisor — the system prompt is explicit about this
- Not connected to any database or persistence layer
- Not collecting analytics, cookies, or any tracking

---

## Repository structure

```
ran-web/
  README.md              ← you are here
  backend/
    main.py              ← FastAPI app (~150 lines, auditable)
    requirements.txt
    .env.example
  frontend/
    index.html           ← bilingual UI (Spanish primary, English)
    style.css
  deploy/
    nginx.conf           ← nginx reverse proxy for ran.accordant.eu
    ran-web.service      ← systemd unit for uvicorn
```

The prompts live in a private repository and are loaded at runtime. They are never committed here.

---

*Built by [Accordant](https://accordant.eu). Zero-retention by design.*
