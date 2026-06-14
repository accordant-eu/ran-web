# Rán — Spanish IRPF Explainer

**`ran.accordant.eu`** · Zero-retention by design · Open-source · Auditable

---

## What it does

Rán accepts a Spanish IRPF tax return (Modelo 100 borrador) — one or two PDFs — and produces a plain-language explanation of what it contains, what every figure means, and what is worth checking before filing. It is designed for expat professionals and international employees who receive their *declaración de la renta* each year and cannot easily interpret it.

You upload the PDF, you read the explanation on screen, you close the tab. That's it. Nothing is kept.

---

## Zero-Retention Architecture

This section documents every technical measure taken to ensure that no document content is retained after a session ends. The measures are architectural — enforced by the code — not just policy.

### Data flow

```
1. User uploads PDF(s)
        │
        ▼ (HTTPS — never plain HTTP)
2. nginx reverse proxy
        │  access_log off for /process — IP address never written to disk
        │  rate limiting: 5 req/min per IP, in RAM only
        ▼
3. FastAPI backend (ran-web container)
        │
        ├── PDF bytes read into BytesIO (in-memory buffer)
        │   PDFs are NEVER written to disk or any temp file.
        │
        ├── pdfplumber.open(BytesIO) extracts text
        │   No temp files created. Verified in test suite.
        │
        ├── PDF bytes released (Python GC)
        │   The PDF no longer exists anywhere on the server.
        │
        ├── Extracted text + system prompt → Anthropic Claude API (HTTPS)
        │   Only the text goes to the API, not the binary PDF.
        │
        ├── Claude response streamed back through the server to the browser
        │   Report never buffered to disk.
        │
        └── Request ends — extracted text released from memory
                │
                ▼
4. Browser renders the report on screen
        │
        └── User closes tab → report gone. Nothing to retrieve.
```

### What is written to disk

Only two files are ever written, and neither contains document content:

| File | What it contains | What it never contains |
|---|---|---|
| `codes.txt` | Invite codes + use counts (e.g. `RENTA-XXXX:3`) | Names, NIFs, document text, IP addresses |
| `ops_log.jsonl` | One JSON line per session: timestamp, file size in bytes, code used, response time, token counts, cost in USD, completion flag | Document content, extracted text, user identity, IP addresses |

Example ops log entry:
```json
{"ts": "2026-06-14T15:21:05Z", "code_used": "RENTA-B8K1", "returns_uploaded": 2, "file_size_bytes": 479180, "response_time_ms": 109072, "completed": true, "input_tokens": 18432, "output_tokens": 2841, "cost_usd": 0.097863}
```

### IP addresses

- nginx logs IP addresses for static file requests (HTML, CSS, JS) — standard web server behaviour
- **`access_log off`** is configured for `/process` and `/health` — no IP addresses are written to disk for document submissions
- nginx rate limiting uses `$binary_remote_addr` in a 10MB in-memory ring buffer — IPs used transiently to enforce limits, never persisted

### PDF handling — why BytesIO enforces zero retention

Python's `pdfplumber.open()` accepts a file-like object. We pass a `BytesIO` buffer:

```python
pdf_buffer = BytesIO(file_bytes)      # in-memory, never touches filesystem
with pdfplumber.open(pdf_buffer) as pdf:
    text = "\n\n".join(p.extract_text() or "" for p in pdf.pages)
# pdf_buffer goes out of scope — memory released to GC
```

This is not just a coding convention. `BytesIO` has no disk path. There is no temp file to leak. The `pdfplumber` library does not create temp files when given a `BytesIO` — this is verified in the test suite.

### Anthropic API

The extracted text (not the binary PDF) is sent to Anthropic's API over HTTPS. Anthropic's published policy for API usage:

> API inputs and outputs are not used to train Anthropic's models by default.
> API logs (inputs and outputs) are retained by Anthropic for **7 days**, then permanently deleted.

Reference: [https://www.anthropic.com/legal/aio](https://www.anthropic.com/legal/aio)

This is an external trust dependency. We link to Anthropic's published policy and do not make claims beyond it. We have applied for Zero Data Retention (ZDR) with Anthropic; once approved, even the 7-day log window is eliminated.

### The system prompt

The system prompt (the instructions that tell Claude how to analyse the return) is **not committed to this repository**. It lives in a private repository and is injected at runtime via the `IRPF_SYSTEM_PROMPT_FILE` environment variable. This keeps the analytical logic private while keeping the infrastructure fully auditable.

The backend substitutes a `{REPORT_LANGUAGE}` placeholder in the prompt at runtime to support Spanish and English output.

### Container isolation

`ran-web` runs inside a Docker container with:
- A non-root `ran` user (uid 1000)
- `PrivateTmp` and `ProtectSystem=strict` in the systemd unit
- Only `./data/` and `./prompts/` bind-mounted from the host — nothing else is accessible
- Runs on the same host as other services for Phase 0; migrated to a dedicated VPS before public launch

---

## Verification

### Automated tests

The test suite includes a dedicated zero-retention module:

```bash
pytest tests/test_zero_retention.py -v
```

Tests cover:
- PDF never written to `/tmp`, Python tempdir, or working directory
- Known text markers embedded in test PDFs do not appear in any log file after processing
- Ops log contains only the allowed metadata fields (including token counts and cost) — no document content
- BytesIO isolation: content from one session does not bleed into the next
- Code file contains only invite code patterns — no document content
- API response is a stream, not a URL pointing to a stored report

### Live server audit

```bash
./scripts/verify-zero-retention.sh
```

Checks the running server:
1. No PDF files in host `/tmp`
2. No PDF files in container `/tmp`
3. No unexpected files in container `/app` outside `data/` and `prompts/`
4. Ops log field audit — no forbidden content fields
5. nginx access log: no `/process` entries in last 60 minutes (confirms `access_log off`)
6. nginx error log: no PDF file references
7. `codes.txt` format: all lines match expected pattern — no document content

Exits `0` on pass, `1` on failure. Safe to run against the live production server.

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ | Anthropic API key — create a dedicated key for this service |
| `IRPF_SYSTEM_PROMPT_FILE` | ✅ | Path to system prompt `.txt` file (loaded at startup) |
| `IRPF_SYSTEM_PROMPT` | — | Alternative: inline prompt (prefer file path) |
| `INVITE_CODES_FILE` | ✅ | Path to `codes.txt` |
| `OPS_LOG_FILE` | ✅ | Path to `ops_log.jsonl` |
| `MAX_CODE_USES` | — | Max uses per invite code (default: `10`) |
| `ANTHROPIC_MODEL` | — | Model override (default: `claude-sonnet-4-6`) |
| `GITHUB_TOKEN` | — | GitHub PAT for `fetch-prompt.sh` (read access to prompt repo) |

Copy `backend/.env.example` to `backend/.env` and fill in values before running.

---

## Running locally

```bash
git clone https://github.com/accordant-eu/ran-web.git && cd ran-web
pip install -r backend/requirements.txt pytest httpx
cp backend/.env.example backend/.env   # fill in ANTHROPIC_API_KEY + prompt

# Generate test codes
python3 -c "
import random, string
for _ in range(5):
    print('RENTA-' + ''.join(random.choices(string.ascii_uppercase+string.digits, k=4)))
" > data/codes.txt

uvicorn backend.main:app --reload --port 8000
# Frontend: open frontend/index.html in browser (or serve via Python http.server)
```

---

## Deployment

See [`DEPLOYMENT.md`](DEPLOYMENT.md) for the full deploy sequence including Docker, nginx, TLS, prompt fetching, and invite code seeding.

---

## Repository structure

```
ran-web/
  README.md                   ← this file
  DEPLOYMENT.md               ← full deploy guide
  CONTRIBUTING.md             ← conventional commits, branch strategy
  Dockerfile
  docker-compose.yml
  docker-entrypoint.sh        ← fixes bind-mount permissions at startup
  pytest.ini
  backend/
    main.py                   ← FastAPI app — read this to verify zero retention
    requirements.txt
    .env.example
  frontend/
    index.html                ← bilingual UI (Spanish primary, English toggle)
    style.css
    marked.min.js             ← bundled markdown renderer (no CDN)
  deploy/
    nginx.conf                ← access_log off for /process, rate limiting
    ran-rate-limit.conf       ← nginx rate limit zone definition
    ran-web.service           ← systemd unit
  scripts/
    fetch-prompt.sh           ← pulls system prompt from private repo via GitHub API
    seed-codes.sh             ← generates initial invite code batch
    verify-zero-retention.sh  ← live server zero-retention audit
  tests/
    test_backend.py           ← unit + integration tests
    test_zero_retention.py    ← zero-retention verification tests (18 tests)
```

---

## Privacy Policy

The privacy policy is live at **`ran.accordant.eu/privacy`** — bilingual ES/EN, Spanish is the official version (AEPD/LOPDGDD jurisdiction).

The policy was written after a complete audit of the codebase and verified by an adversarial AI compliance reviewer. Every claim is traceable to a specific source file. See [`docs/privacy-policy-methodology.md`](docs/privacy-policy-methodology.md) for:

- Which source files were audited and what each confirmed
- Key findings that changed the draft (pseudonymous invite codes, selective nginx logging, Art. 9 consent)
- Full adversarial review findings and fixes (6 critical, 2 significant)
- Maintenance checklist and adversarial review template for future updates

**Key disclosures in brief:**

| Data | Retained? |
|---|---|
| PDF content / extracted text | Never — RAM only, discarded after request |
| Generated report | Never — streamed to browser, not stored |
| IP address (PDF upload route `/process`) | Never — `access_log off` |
| IP address (static file requests) | 30 days — standard nginx access log |
| Operational metadata (`ops_log.jsonl`) | 12 months maximum |
| Anthropic API logs | 7 days (Anthropic policy), then permanently deleted |

Anthropologic processes data under SCCs + EU-US DPF. No API data is used for model training.

---

## What this is not

- Not a full accounting tool
- Not a replacement for a *gestor* or tax advisor — the system prompt is explicit about this
- Not connected to any database or persistence layer
- Not collecting analytics, cookies, or tracking of any kind

---

*Built by [Accordant](https://accordant.eu). Zero-retention by design.*
