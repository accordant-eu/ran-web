"""
Rán — IRPF Explainer Backend
FastAPI app: zero-retention PDF processing via Anthropic Claude API.

Zero-retention guarantee:
  - PDFs are NEVER written to disk. All PDF handling uses BytesIO (in-memory only).
  - Extracted text lives in Python memory for the duration of one request, then discarded.
  - The only filesystem writes are: invite code state (codes.txt) and ops log (ops_log.jsonl).
    Neither contains document content or user-identifying information.

Auditable by design — keep this file short and obvious.
"""

import fcntl
import json
import logging
import os
import re
import secrets
import string
from contextlib import contextmanager
from datetime import datetime, timezone
from io import BytesIO
from typing import Generator

import anthropic
import pdfplumber
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

# ---------------------------------------------------------------------------
# Configuration — all values come from environment variables.
# Nothing sensitive is hardcoded here.
# ---------------------------------------------------------------------------

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL   = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# Cost per token in USD (claude-sonnet-4-6 as of 2026-06-14)
COST_PER_INPUT_TOKEN  = 3.00  / 1_000_000   # $3.00 / MTok
COST_PER_OUTPUT_TOKEN = 15.00 / 1_000_000   # $15.00 / MTok

INVITE_CODES_FILE = os.environ.get("INVITE_CODES_FILE", "codes.txt")
OPS_LOG_FILE      = os.environ.get("OPS_LOG_FILE",      "ops_log.jsonl")
MAX_CODE_USES     = int(os.environ.get("MAX_CODE_USES", "10"))   # uses per code

# ---------------------------------------------------------------------------
# Security limits
# ---------------------------------------------------------------------------

MAX_PDF_SIZE_BYTES  = 10 * 1024 * 1024   # 10 MB per file (nginx allows 25 MB total)
MAX_PDF_PAGES       = 100                # reject suspiciously large PDFs
MAX_EXTRACTED_CHARS = 200_000            # ~50k tokens — well above any real tax return
MAX_INVITE_CODE_LEN = 32                 # RENTA-XXXX is 10 chars; generous headroom

ALLOWED_LANGUAGES = frozenset(["es", "en"])

# Exclusive lock file for atomic codes.txt operations — works across processes.
_codes_dir  = os.path.dirname(INVITE_CODES_FILE)
CODE_LOCK_FILE = os.path.join(_codes_dir or ".", ".codes.lock")

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

LANGUAGE_STRINGS = {
    "es": "español claro y sencillo",
    "en": "plain, simple English",
}


def load_system_prompt(language: str = "es") -> str:
    """Load system prompt and substitute the {REPORT_LANGUAGE} placeholder."""
    prompt = os.environ.get("IRPF_SYSTEM_PROMPT", "")
    if not prompt:
        prompt_file = os.environ.get("IRPF_SYSTEM_PROMPT_FILE", "")
        if prompt_file and os.path.exists(prompt_file):
            with open(prompt_file, "r") as f:
                prompt = f.read().strip()
        else:
            raise RuntimeError(
                "No system prompt configured. Set IRPF_SYSTEM_PROMPT or IRPF_SYSTEM_PROMPT_FILE."
            )
    lang_str = LANGUAGE_STRINGS.get(language, LANGUAGE_STRINGS["es"])
    return prompt.replace("{REPORT_LANGUAGE}", lang_str)


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ran")

app = FastAPI(
    title="Rán",
    description="Zero-retention Spanish IRPF explainer",
    version="0.1.0",
    # Disable auto-generated API docs in production — schema is not public.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# CORS: production origin only. Never wildcard.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://ran.accordant.eu"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Invite code management
# ---------------------------------------------------------------------------

@contextmanager
def codes_lock():
    """
    Exclusive file lock for codes.txt operations.

    Prevents race conditions when multiple workers or concurrent requests attempt
    to validate and burn an invite code simultaneously. fcntl.LOCK_EX is
    process-safe on Linux, so this works correctly with --workers > 1.
    """
    os.makedirs(os.path.dirname(CODE_LOCK_FILE) or ".", exist_ok=True)
    with open(CODE_LOCK_FILE, "w") as lf:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def load_codes() -> dict[str, int]:
    """
    Read codes.txt and return a dict of {code: use_count}.
    Format:
      RENTA-XXXX        → fresh (0 uses)
      RENTA-XXXX:3      → used 3 times
      USED:RENTA-XXXX   → exhausted (legacy / explicitly retired)

    Caller must hold codes_lock().
    """
    if not os.path.exists(INVITE_CODES_FILE):
        return {}
    codes: dict[str, int] = {}
    with open(INVITE_CODES_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("USED:"):
                codes[line[5:]] = MAX_CODE_USES
            elif ":" in line:
                code, count = line.rsplit(":", 1)
                try:
                    codes[code] = int(count)
                except ValueError:
                    codes[line] = 0
            else:
                codes[line] = 0
    return codes


def mark_code_used(code: str) -> None:
    """
    Increment use count for a code. Mark USED: when MAX_CODE_USES is reached.
    Caller must hold codes_lock().
    """
    lines: list[str] = []
    if os.path.exists(INVITE_CODES_FILE):
        with open(INVITE_CODES_FILE, "r") as f:
            lines = f.readlines()

    updated = []
    for line in lines:
        stripped = line.strip()
        if stripped == code or stripped.startswith(f"{code}:"):
            current = 0
            if ":" in stripped and not stripped.startswith("USED:"):
                try:
                    current = int(stripped.rsplit(":", 1)[1])
                except ValueError:
                    pass
            new_count = current + 1
            updated.append(f"USED:{code}\n" if new_count >= MAX_CODE_USES else f"{code}:{new_count}\n")
        else:
            updated.append(line)

    with open(INVITE_CODES_FILE, "w") as f:
        f.writelines(updated)


def generate_new_codes(n: int = 5, existing: set | None = None) -> list[str]:
    """
    Generate n new invite codes and append them to codes.txt.
    Format: RENTA-XXXX where XXXX is 4 uppercase alphanumeric characters.

    Uses secrets.choice (cryptographically secure PRNG) rather than random.choices.
    Caller must hold codes_lock().
    """
    alphabet = string.ascii_uppercase + string.digits
    if existing is None:
        existing = set(load_codes().keys())
    new_codes: list[str] = []
    while len(new_codes) < n:
        suffix = "".join(secrets.choice(alphabet) for _ in range(4))
        code = f"RENTA-{suffix}"
        if code not in existing and code not in new_codes:
            new_codes.append(code)

    with open(INVITE_CODES_FILE, "a") as f:
        for code in new_codes:
            f.write(f"{code}\n")

    return new_codes


# ---------------------------------------------------------------------------
# Ops log
# ---------------------------------------------------------------------------

def append_ops_log(entry: dict) -> None:
    """
    Append one JSON line to the ops log.
    The ops log captures operational metadata only — never document content.
    """
    with open(OPS_LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# PDF extraction — BytesIO only, never touches disk
# ---------------------------------------------------------------------------

_XML_TAG_RE = re.compile(r"<[^>]{0,200}>")


def sanitize_pdf_text(text: str) -> str:
    """
    Strip XML/HTML-style tags from extracted PDF text.

    Prevents a malicious PDF from embedding tags like </declaracion_1> to
    escape the XML envelope we wrap content in before sending to the LLM.
    This is defence-in-depth: the system prompt provides the primary protection;
    this layer removes the most obvious structural injection vector.
    """
    return _XML_TAG_RE.sub("", text)


def extract_pdf_text(file_bytes: bytes) -> str:
    """
    Extract text from a PDF using pdfplumber.

    IMPORTANT: PDFs are never written to disk. file_bytes is a bytes object
    held in RAM. pdfplumber.open() accepts a file-like object (BytesIO),
    so no temporary file is created at any point.

    Raises ValueError when MAX_PDF_PAGES is exceeded.
    Truncates extracted text to MAX_EXTRACTED_CHARS.
    Sanitizes output against XML prompt injection.
    """
    pdf_buffer = BytesIO(file_bytes)
    text_parts: list[str] = []

    with pdfplumber.open(pdf_buffer) as pdf:
        if len(pdf.pages) > MAX_PDF_PAGES:
            raise ValueError(
                f"PDF has {len(pdf.pages)} pages; maximum allowed is {MAX_PDF_PAGES}."
            )
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)

    extracted = "\n\n".join(text_parts)

    if len(extracted) > MAX_EXTRACTED_CHARS:
        logger.warning(
            "Extracted text truncated: %d → %d chars.", len(extracted), MAX_EXTRACTED_CHARS
        )
        extracted = extracted[:MAX_EXTRACTED_CHARS]

    return sanitize_pdf_text(extracted)


# ---------------------------------------------------------------------------
# Anthropic streaming
# ---------------------------------------------------------------------------

def stream_claude_response(
    system_prompt: str,
    user_message: str,
    new_codes: list[str],
    usage_out: dict | None = None,
) -> Generator[str, None, None]:
    """
    Call the Anthropic API and stream the response back.
    Appends the new invite codes as a __CODES__:[...] line after the report.
    Populates usage_out with input_tokens, output_tokens, cost_usd if provided.

    Timeout: 120 s — intentionally shorter than nginx proxy_read_timeout (300 s)
    so a hung API call surfaces as a clean error rather than a silent gateway timeout.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=120.0)

    with client.messages.stream(
        model=ANTHROPIC_MODEL,
        max_tokens=8192,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        for text_chunk in stream.text_stream:
            yield text_chunk
        if usage_out is not None:
            try:
                msg = stream.get_final_message()
                usage_out["input_tokens"]  = msg.usage.input_tokens
                usage_out["output_tokens"] = msg.usage.output_tokens
                usage_out["cost_usd"] = round(
                    msg.usage.input_tokens  * COST_PER_INPUT_TOKEN +
                    msg.usage.output_tokens * COST_PER_OUTPUT_TOKEN,
                    6,
                )
            except Exception:
                pass  # usage tracking is non-critical

    yield "\n\n__CODES__:" + json.dumps(new_codes)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok"}


@app.post("/process")
async def process(
    invite_code: str = Form(...),
    language: str = Form("es"),
    pdfs: list[UploadFile] = File(...),
):
    """
    Main endpoint: accepts invite code + 1 or 2 PDF uploads.

    Flow:
      1. Validate and sanitise inputs (length, language allowlist)
      2. Atomic check-and-burn of invite code under exclusive file lock
      3. Read PDFs into RAM; validate magic bytes, per-file size, page count
      4. Extract text via pdfplumber (BytesIO); sanitize against prompt injection
      5. Build user message from extracted text
      6. Stream Claude response (120 s timeout) back to client
      7. Append ops log with actual completed status on teardown

    Returns StreamingResponse (text/plain): report + __CODES__:[...] line.
    """
    # --- Input validation ---
    if not pdfs or len(pdfs) > 2:
        raise HTTPException(status_code=400, detail="Upload 1 or 2 PDF files.")

    invite_code = invite_code.strip().upper()
    if len(invite_code) > MAX_INVITE_CODE_LEN:
        raise HTTPException(status_code=400, detail="Invalid invite code format.")

    # Strict language allowlist — unknown values silently default to 'es'
    if language not in ALLOWED_LANGUAGES:
        language = "es"

    # --- Atomic check-and-burn under exclusive file lock ---
    # load → validate → mark_code_used → generate_new_codes all happen inside
    # one lock acquisition, preventing race conditions across concurrent requests
    # and multiple uvicorn workers.
    with codes_lock():
        codes = load_codes()
        if invite_code not in codes or codes[invite_code] >= MAX_CODE_USES:
            raise HTTPException(status_code=403, detail="Invalid or exhausted invite code.")
        mark_code_used(invite_code)
        new_codes = generate_new_codes(5, existing=set(codes.keys()))

    # --- Load system prompt ---
    try:
        system_prompt = load_system_prompt(language)
    except RuntimeError as e:
        logger.error("System prompt not configured: %s", e)
        raise HTTPException(status_code=500, detail="Service misconfigured.")

    # --- Read and extract PDFs (in memory — never disk) ---
    extracted_texts: list[str] = []
    total_bytes = 0

    for i, pdf_file in enumerate(pdfs):
        pdf_bytes = await pdf_file.read()

        # Per-file size guard (decompression bomb / memory exhaustion defence)
        if len(pdf_bytes) > MAX_PDF_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"PDF {i + 1} exceeds the 10 MB limit.",
            )

        # Magic bytes check — valid PDFs start with %PDF
        if not pdf_bytes.startswith(b"%PDF"):
            raise HTTPException(
                status_code=422,
                detail=f"File {i + 1} does not appear to be a valid PDF.",
            )

        total_bytes += len(pdf_bytes)

        try:
            text = extract_pdf_text(pdf_bytes)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Exception as e:
            logger.warning("PDF extraction failed for file %d: %s", i + 1, e)
            raise HTTPException(
                status_code=422,
                detail=f"Could not extract text from PDF {i + 1}. Is it a valid, text-based PDF?",
            )

        extracted_texts.append(text)

    # --- Build user message ---
    if len(extracted_texts) == 1:
        user_message = f"<declaracion_1>\n{extracted_texts[0]}\n</declaracion_1>"
    else:
        user_message = (
            f"<declaracion_1>\n{extracted_texts[0]}\n</declaracion_1>\n\n"
            f"<declaracion_2>\n{extracted_texts[1]}\n</declaracion_2>\n\n"
            "Analyse both declarations together as a household filing."
        )

    start_ts = datetime.now(timezone.utc).isoformat()

    # --- Stream the response ---
    def response_generator():
        start_ms  = datetime.now(timezone.utc).timestamp() * 1000
        usage: dict = {}
        completed = False
        try:
            yield from stream_claude_response(system_prompt, user_message, new_codes, usage_out=usage)
            completed = True
        finally:
            end_ms = datetime.now(timezone.utc).timestamp() * 1000
            entry: dict = {
                "ts":              start_ts,
                "code_used":       invite_code,
                "returns_uploaded": len(pdfs),
                "file_size_bytes": total_bytes,
                "response_time_ms": round(end_ms - start_ms),
                "completed":       completed,
            }
            if usage:
                entry["input_tokens"]  = usage.get("input_tokens")
                entry["output_tokens"] = usage.get("output_tokens")
                entry["cost_usd"]      = usage.get("cost_usd")
            append_ops_log(entry)

    return StreamingResponse(response_generator(), media_type="text/plain")
