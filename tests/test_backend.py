"""
Tests for Rán backend.

Key principles under test:
  1. Correctness — invite code flow, PDF extraction, ops log format
  2. Zero-retention — no temp files, no document content in logs
  3. Input validation — reject bad codes, oversized uploads, non-PDFs
"""

import json
import os
import tempfile
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

MINIMAL_SYSTEM_PROMPT = "You are a test assistant. Reply with: TEST_OK"

MINIMAL_PDF_BYTES = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/MediaBox[0 0 3 3]>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f\n"
    b"0000000009 00000 n\n0000000058 00000 n\n"
    b"0000000115 00000 n\n"
    b"trailer<</Size 4/Root 1 0 R>>\n"
    b"startxref\n190\n%%EOF"
)


@pytest.fixture
def tmp_env(tmp_path, monkeypatch):
    """Set up a temporary environment with a prompt file and codes file."""
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text(MINIMAL_SYSTEM_PROMPT)

    codes_file = tmp_path / "codes.txt"
    codes_file.write_text("RENTA-TEST\nRENTA-USED\n")

    ops_file = tmp_path / "ops.jsonl"

    monkeypatch.setenv("IRPF_SYSTEM_PROMPT_FILE", str(prompt_file))
    monkeypatch.setenv("INVITE_CODES_FILE", str(codes_file))
    monkeypatch.setenv("OPS_LOG_FILE", str(ops_file))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used-in-unit-tests")

    return {
        "prompt_file": prompt_file,
        "codes_file": codes_file,
        "ops_file": ops_file,
        "tmp_path": tmp_path,
    }


@pytest.fixture
def client(tmp_env):
    """FastAPI test client with isolated temp environment."""
    # Import app after env vars are set
    import importlib
    import sys
    if "main" in sys.modules:
        del sys.modules["main"]
    import main
    importlib.reload(main)
    return TestClient(main.app)


# ---------------------------------------------------------------------------
# Unit tests — invite code management
# ---------------------------------------------------------------------------

class TestInviteCodes:
    def test_load_codes_valid(self, tmp_env):
        import main
        codes = main.load_codes()
        assert "RENTA-TEST" in codes
        assert codes["RENTA-TEST"] is False  # not used

    def test_load_codes_used_prefix(self, tmp_env):
        # Mark a code used by writing USED: prefix directly
        tmp_env["codes_file"].write_text("USED:RENTA-USED\nRENTA-FRESH\n")
        import main
        codes = main.load_codes()
        assert codes["RENTA-USED"] is True
        assert codes["RENTA-FRESH"] is False

    def test_mark_code_used(self, tmp_env):
        import main
        main.mark_code_used("RENTA-TEST")
        codes = main.load_codes()
        assert codes["RENTA-TEST"] is True

    def test_generate_new_codes_count(self, tmp_env):
        import main
        new_codes = main.generate_new_codes(5)
        assert len(new_codes) == 5

    def test_generate_new_codes_format(self, tmp_env):
        import main
        new_codes = main.generate_new_codes(3)
        for code in new_codes:
            assert code.startswith("RENTA-")
            assert len(code) == 10  # "RENTA-" (6) + 4 chars

    def test_generate_new_codes_no_duplicates(self, tmp_env):
        import main
        new_codes = main.generate_new_codes(20)
        assert len(new_codes) == len(set(new_codes))

    def test_generate_new_codes_persisted(self, tmp_env):
        import main
        new_codes = main.generate_new_codes(3)
        codes = main.load_codes()
        for code in new_codes:
            assert code in codes


# ---------------------------------------------------------------------------
# Unit tests — system prompt loading
# ---------------------------------------------------------------------------

class TestSystemPrompt:
    def test_load_from_file(self, tmp_env):
        import main
        prompt = main.load_system_prompt()
        assert prompt == MINIMAL_SYSTEM_PROMPT

    def test_load_from_env_var(self, tmp_env, monkeypatch):
        monkeypatch.setenv("IRPF_SYSTEM_PROMPT", "INLINE_PROMPT")
        import importlib, main
        importlib.reload(main)
        prompt = main.load_system_prompt()
        assert prompt == "INLINE_PROMPT"

    def test_raises_when_not_configured(self, monkeypatch):
        monkeypatch.delenv("IRPF_SYSTEM_PROMPT", raising=False)
        monkeypatch.delenv("IRPF_SYSTEM_PROMPT_FILE", raising=False)
        import importlib, main
        importlib.reload(main)
        with pytest.raises(RuntimeError, match="No system prompt configured"):
            main.load_system_prompt()


# ---------------------------------------------------------------------------
# Unit tests — PDF extraction
# ---------------------------------------------------------------------------

class TestPDFExtraction:
    def test_bytesio_only(self, tmp_env, tmp_path):
        """PDF extraction must not create any temp files."""
        import main
        tmp_files_before = set(tmp_path.glob("**/*"))
        try:
            main.extract_pdf_text(MINIMAL_PDF_BYTES)
        except Exception:
            pass  # minimal PDF may not have extractable text — that's ok
        tmp_files_after = set(tmp_path.glob("**/*"))
        # No new files should have appeared in tmp_path
        assert tmp_files_before == tmp_files_after

    def test_system_tmp_not_written(self, tmp_env):
        """Verify pdfplumber doesn't leave files in /tmp."""
        import main, glob
        tmp_before = set(glob.glob("/tmp/pdf*") + glob.glob("/tmp/pdfplumber*"))
        try:
            main.extract_pdf_text(MINIMAL_PDF_BYTES)
        except Exception:
            pass
        tmp_after = set(glob.glob("/tmp/pdf*") + glob.glob("/tmp/pdfplumber*"))
        assert tmp_before == tmp_after

    def test_invalid_bytes_raises(self, tmp_env):
        import main
        with pytest.raises(Exception):
            main.extract_pdf_text(b"not a pdf at all")


# ---------------------------------------------------------------------------
# Unit tests — ops log
# ---------------------------------------------------------------------------

class TestOpsLog:
    def test_ops_log_written(self, tmp_env):
        import main
        main.append_ops_log({"ts": "2026-01-01T00:00:00Z", "test": True})
        lines = tmp_env["ops_file"].read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["test"] is True

    def test_ops_log_no_content_fields(self, tmp_env):
        """Ops log entries must not contain document text fields."""
        import main
        entry = {
            "ts": "2026-01-01T00:00:00Z",
            "code_used": "RENTA-TEST",
            "returns_uploaded": 1,
            "file_size_bytes": 12345,
            "response_time_ms": 8000,
            "completed": True,
        }
        main.append_ops_log(entry)
        lines = tmp_env["ops_file"].read_text().strip().split("\n")
        logged = json.loads(lines[0])
        # These fields must never appear in the ops log
        forbidden = {"text", "content", "prompt", "extracted", "pdf_text", "document"}
        assert not forbidden.intersection(set(logged.keys()))


# ---------------------------------------------------------------------------
# API tests — /health
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# API tests — /process input validation
# ---------------------------------------------------------------------------

class TestProcessValidation:
    def test_invalid_code_returns_403(self, client):
        response = client.post(
            "/process",
            data={"invite_code": "INVALID-CODE"},
            files=[("pdfs", ("test.pdf", BytesIO(MINIMAL_PDF_BYTES), "application/pdf"))],
        )
        assert response.status_code == 403

    def test_too_many_pdfs_returns_400(self, client):
        response = client.post(
            "/process",
            data={"invite_code": "RENTA-TEST"},
            files=[
                ("pdfs", ("a.pdf", BytesIO(MINIMAL_PDF_BYTES), "application/pdf")),
                ("pdfs", ("b.pdf", BytesIO(MINIMAL_PDF_BYTES), "application/pdf")),
                ("pdfs", ("c.pdf", BytesIO(MINIMAL_PDF_BYTES), "application/pdf")),
            ],
        )
        assert response.status_code == 400

    def test_used_code_returns_403(self, tmp_env, client):
        # Write a used code
        tmp_env["codes_file"].write_text("USED:RENTA-TEST\n")
        response = client.post(
            "/process",
            data={"invite_code": "RENTA-TEST"},
            files=[("pdfs", ("test.pdf", BytesIO(MINIMAL_PDF_BYTES), "application/pdf"))],
        )
        assert response.status_code == 403
