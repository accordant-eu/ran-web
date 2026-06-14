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

import json
import logging
import os
import random
import string
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
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
INVITE_CODES_FILE = os.environ.get("INVITE_CODES_FILE", "codes.txt")
OPS_LOG_FILE = os.environ.get("OPS_LOG_FILE", "ops_log.jsonl")

# System prompt: loaded from env var directly, or from a file path.
# The prompt is NOT committed to this repository — it lives in a private store
# and is injected at runtime.
def load_system_prompt() -> str:
    prompt = os.environ.get("IRPF_SYSTEM_PROMPT", "")
    if prompt:
        return prompt
    prompt_file = os.environ.get("IRPF_SYSTEM_PROMPT_FILE", "")
    if prompt_file and os.path.exists(prompt_file):
        with open(prompt_file, "r") as f:
            return f.read().strip()
    raise RuntimeError(
        "No system prompt configured. Set IRPF_SYSTEM_PROMPT or IRPF_SYSTEM_PROMPT_FILE."
    )


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ran")

app = FastAPI(
    title="Rán",
    description="Zero-retention Spanish IRPF explainer",
    version="0.1.0",
)

# CORS: allow the frontend origin. Tighten this for production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: restrict to ran.accordant.eu in production
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Invite code management
# ---------------------------------------------------------------------------

def load_codes() -> dict[str, bool]:
    """
    Read codes.txt and return a dict of {code: used}.
    Format: one code per line. Used codes are prefixed with "USED:".
    """
    if not os.path.exists(INVITE_CODES_FILE):
        return {}
    codes = {}
    with open(INVITE_CODES_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("USED:"):
                codes[line[5:]] = True
            else:
                codes[line] = False
    return codes


def mark_code_used(code: str) -> None:
    """Mark an invite code as used in codes.txt."""
    lines = []
    if os.path.exists(INVITE_CODES_FILE):
        with open(INVITE_CODES_FILE, "r") as f:
            lines = f.readlines()

    updated = []
    for line in lines:
        stripped = line.strip()
        if stripped == code:
            updated.append(f"USED:{code}\n")
        else:
            updated.append(line)

    with open(INVITE_CODES_FILE, "w") as f:
        f.writelines(updated)


def generate_new_codes(n: int = 5) -> list[str]:
    """
    Generate n new invite codes and append them to codes.txt.
    Format: RENTA-XXXX where XXXX is 4 uppercase alphanumeric characters.
    """
    existing = set(load_codes().keys())
    new_codes = []
    while len(new_codes) < n:
        suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
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

def extract_pdf_text(file_bytes: bytes) -> str:
    """
    Extract text from a PDF using pdfplumber.

    IMPORTANT: PDFs are never written to disk. file_bytes is a bytes object
    held in memory. pdfplumber.open() accepts a file-like object (BytesIO),
    so no temporary file is created at any point.
    """
    # PDFs are never written to disk — BytesIO keeps everything in RAM
    pdf_buffer = BytesIO(file_bytes)
    text_parts = []

    with pdfplumber.open(pdf_buffer) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)

    return "\n\n".join(text_parts)


# ---------------------------------------------------------------------------
# Anthropic streaming
# ---------------------------------------------------------------------------

def stream_claude_response(
    system_prompt: str,
    user_message: str,
    new_codes: list[str],
) -> Generator[str, None, None]:
    """
    Call the Anthropic API and stream the response back as server-sent events.
    Appends the new invite codes at the end of the stream.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    with client.messages.stream(
        model=ANTHROPIC_MODEL,
        max_tokens=8192,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        for text_chunk in stream.text_stream:
            yield text_chunk

    # After the report, append the new invite codes as structured JSON
    # so the frontend can render them separately.
    yield "\n\n__CODES__:" + json.dumps(new_codes)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    """Health check — returns OK if the service is running."""
    return {"status": "ok", "service": "ran"}


@app.post("/process")
async def process(
    invite_code: str = Form(...),
    pdfs: list[UploadFile] = File(...),
):
    """
    Main endpoint: accepts invite code + 1 or 2 PDF uploads.

    Flow:
      1. Validate invite code
      2. Read PDF bytes into memory (never disk)
      3. Extract text via pdfplumber (BytesIO)
      4. Build user message from extracted text
      5. Stream Claude response back to client
      6. On completion: mark code used, generate 5 new codes, append ops log

    Returns a StreamingResponse (text/plain) with the report followed by
    a __CODES__:[...] line the frontend parses to display invite codes.
    """
    # --- Validate input ---
    if not pdfs or len(pdfs) > 2:
        raise HTTPException(status_code=400, detail="Upload 1 or 2 PDF files.")

    invite_code = invite_code.strip().upper()

    # --- Validate invite code ---
    codes = load_codes()
    if invite_code not in codes:
        raise HTTPException(status_code=403, detail="Invalid invite code.")
    if codes[invite_code]:
        raise HTTPException(status_code=403, detail="Invite code already used.")

    # --- Load system prompt ---
    try:
        system_prompt = load_system_prompt()
    except RuntimeError as e:
        logger.error("System prompt not configured: %s", e)
        raise HTTPException(status_code=500, detail="Service misconfigured.")

    # --- Read and extract PDFs (in memory — never disk) ---
    extracted_texts = []
    total_bytes = 0

    for i, pdf_file in enumerate(pdfs):
        # PDFs are never written to disk — read bytes directly into memory
        pdf_bytes = await pdf_file.read()
        total_bytes += len(pdf_bytes)

        try:
            text = extract_pdf_text(pdf_bytes)
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
        # Two returns — use household cross-analysis framing
        user_message = (
            f"<declaracion_1>\n{extracted_texts[0]}\n</declaracion_1>\n\n"
            f"<declaracion_2>\n{extracted_texts[1]}\n</declaracion_2>\n\n"
            "Analyse both declarations together as a household filing."
        )

    # --- Mark code used and generate new codes ---
    # We do this before streaming so codes are ready to append at the end.
    mark_code_used(invite_code)
    new_codes = generate_new_codes(5)

    # --- Record start time for ops log ---
    start_ts = datetime.now(timezone.utc).isoformat()

    # --- Stream the response ---
    def response_generator():
        start_ms = datetime.now(timezone.utc).timestamp() * 1000
        try:
            yield from stream_claude_response(system_prompt, user_message, new_codes)
        finally:
            end_ms = datetime.now(timezone.utc).timestamp() * 1000
            # Append ops log entry — metadata only, no document content
            append_ops_log(
                {
                    "ts": start_ts,
                    "code_used": invite_code,
                    "returns_uploaded": len(pdfs),
                    "file_size_bytes": total_bytes,
                    "response_time_ms": round(end_ms - start_ms),
                    "completed": True,
                }
            )

    return StreamingResponse(response_generator(), media_type="text/plain")
