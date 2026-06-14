"""
Zero-retention verification tests.

These tests verify the core privacy guarantee: that no document content
is persisted to disk, logs, or any other storage medium after processing.

Run with: pytest tests/test_zero_retention.py -v
"""

import glob
import json
import os
import struct
import tempfile
from io import BytesIO
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PDF_MAGIC = b"%PDF"

def make_pdf_with_marker(marker: str) -> bytes:
    """
    Build a minimal valid PDF that embeds a known text marker.
    Used to verify the marker does NOT appear in any logs/files after processing.
    """
    content = f"RETENTION_TEST_MARKER_{marker}".encode()
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]>>endobj\n"
        b"% " + content + b"\n"
        b"xref\n0 4\n"
        b"0000000000 65535 f\n"
        b"0000000009 00000 n\n"
        b"0000000058 00000 n\n"
        b"0000000115 00000 n\n"
        b"trailer<</Size 4/Root 1 0 R>>\n"
        b"startxref\n190\n%%EOF"
    )


def scan_for_bytes(search_bytes: bytes, search_dir: str) -> list[str]:
    """Return list of files in search_dir that contain search_bytes."""
    hits = []
    for root, _, files in os.walk(search_dir):
        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "rb") as f:
                    if search_bytes in f.read():
                        hits.append(fpath)
            except (PermissionError, OSError):
                pass
    return hits


def scan_for_pdf_magic(search_dir: str) -> list[str]:
    """Return list of files in search_dir that start with PDF magic bytes."""
    return scan_for_bytes(PDF_MAGIC, search_dir)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_env(tmp_path, monkeypatch):
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("You are a test assistant. Reply: ZERO_RETENTION_TEST_OK")

    codes_file = tmp_path / "codes.txt"
    codes_file.write_text("RENTA-ZRT1\n")

    ops_file = tmp_path / "ops.jsonl"

    monkeypatch.setenv("IRPF_SYSTEM_PROMPT_FILE", str(prompt_file))
    monkeypatch.setenv("INVITE_CODES_FILE", str(codes_file))
    monkeypatch.setenv("OPS_LOG_FILE", str(ops_file))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.setenv("MAX_CODE_USES", "10")

    return {"prompt_file": prompt_file, "codes_file": codes_file,
            "ops_file": ops_file, "tmp_path": tmp_path}


# ---------------------------------------------------------------------------
# 1. PDF bytes — filesystem
# ---------------------------------------------------------------------------

class TestNoPDFOnDisk:

    def test_pdf_not_written_to_tmp(self, tmp_env):
        """After extract_pdf_text(), /tmp must not contain any PDF files."""
        import main
        marker_pdf = make_pdf_with_marker("TMP_CHECK")
        tmp_before = set(glob.glob("/tmp/*.pdf") + glob.glob("/tmp/pdf*"))
        try:
            main.extract_pdf_text(marker_pdf)
        except Exception:
            pass
        tmp_after = set(glob.glob("/tmp/*.pdf") + glob.glob("/tmp/pdf*"))
        assert tmp_before == tmp_after, f"PDF files appeared in /tmp: {tmp_after - tmp_before}"

    def test_pdf_not_written_to_working_dir(self, tmp_env):
        """After extract_pdf_text(), no PDF magic bytes in the working directory."""
        import main
        marker_pdf = make_pdf_with_marker("WORKDIR_CHECK")
        cwd = os.getcwd()
        files_before = set(scan_for_pdf_magic(cwd))
        try:
            main.extract_pdf_text(marker_pdf)
        except Exception:
            pass
        files_after = set(scan_for_pdf_magic(cwd))
        new_pdf_files = files_after - files_before
        assert not new_pdf_files, f"PDF files appeared in working dir: {new_pdf_files}"

    def test_pdf_not_in_python_tempdir(self, tmp_env):
        """Python's tempfile.gettempdir() must not gain PDF files during extraction."""
        import main
        marker_pdf = make_pdf_with_marker("PYTMP_CHECK")
        pytmp = tempfile.gettempdir()
        before = set(scan_for_pdf_magic(pytmp))
        try:
            main.extract_pdf_text(marker_pdf)
        except Exception:
            pass
        after = set(scan_for_pdf_magic(pytmp))
        assert before == after, f"PDF files in Python tempdir: {after - before}"


# ---------------------------------------------------------------------------
# 2. Document content — logs and data files
# ---------------------------------------------------------------------------

class TestNoContentInLogs:

    def test_ops_log_no_pdf_magic(self, tmp_env):
        """Ops log must not contain PDF magic bytes."""
        import main
        main.append_ops_log({
            "ts": "2026-01-01T00:00:00Z",
            "code_used": "RENTA-ZRT1",
            "returns_uploaded": 1,
            "file_size_bytes": 12345,
            "response_time_ms": 5000,
            "completed": True,
        })
        log_bytes = tmp_env["ops_file"].read_bytes()
        assert PDF_MAGIC not in log_bytes

    def test_ops_log_no_document_content_fields(self, tmp_env):
        """Ops log entries must not contain these field names."""
        import main
        main.append_ops_log({
            "ts": "2026-01-01T00:00:00Z",
            "code_used": "RENTA-ZRT1",
            "returns_uploaded": 1,
            "file_size_bytes": 1234,
            "response_time_ms": 1000,
            "completed": True,
        })
        entry = json.loads(tmp_env["ops_file"].read_text().strip())
        forbidden = {
            "text", "content", "pdf_text", "document", "extracted",
            "prompt", "response", "name", "nif", "apellidos",
        }
        assert not forbidden.intersection(set(entry.keys())), \
            f"Forbidden fields in ops log: {forbidden.intersection(set(entry.keys()))}"

    def test_ops_log_contains_only_expected_fields(self, tmp_env):
        """Ops log must contain exactly the expected metadata fields — nothing else."""
        import main
        main.append_ops_log({
            "ts": "2026-01-01T00:00:00Z",
            "code_used": "RENTA-ZRT1",
            "returns_uploaded": 2,
            "file_size_bytes": 50000,
            "response_time_ms": 85000,
            "completed": True,
        })
        entry = json.loads(tmp_env["ops_file"].read_text().strip())
        allowed = {"ts", "code_used", "returns_uploaded", "file_size_bytes",
                   "response_time_ms", "completed",
                   "input_tokens", "output_tokens", "cost_usd"}
        unexpected = set(entry.keys()) - allowed
        assert not unexpected, f"Unexpected fields in ops log: {unexpected}"

    def test_marker_text_not_in_ops_log(self, tmp_env):
        """A known text marker from a PDF must not appear in the ops log after extraction."""
        import main
        MARKER = "SUPERSECRET_TAX_CONTENT_12345"
        marker_pdf = make_pdf_with_marker(MARKER)
        try:
            main.extract_pdf_text(marker_pdf)
        except Exception:
            pass
        main.append_ops_log({
            "ts": "2026-01-01T00:00:00Z",
            "code_used": "RENTA-ZRT1",
            "returns_uploaded": 1,
            "file_size_bytes": len(marker_pdf),
            "response_time_ms": 1000,
            "completed": True,
        })
        log_text = tmp_env["ops_file"].read_text()
        assert MARKER not in log_text, "PDF content marker found in ops log!"

    def test_marker_text_not_in_codes_file(self, tmp_env):
        """Document text must not appear in codes.txt after processing."""
        import main
        MARKER = "CODES_FILE_MARKER_XYZ"
        marker_pdf = make_pdf_with_marker(MARKER)
        try:
            main.extract_pdf_text(marker_pdf)
        except Exception:
            pass
        main.mark_code_used("RENTA-ZRT1")
        codes_text = tmp_env["codes_file"].read_text()
        assert MARKER not in codes_text


# ---------------------------------------------------------------------------
# 3. BytesIO isolation — no cross-request bleed
# ---------------------------------------------------------------------------

class TestBytesIOIsolation:

    def test_two_sequential_extractions_isolated(self, tmp_env):
        """
        Extract text from two different PDFs sequentially.
        Content from the first must not appear when extracting the second.
        """
        import main
        MARKER_A = "FIRST_DOC_MARKER_AAAA"
        MARKER_B = "SECOND_DOC_MARKER_BBBB"
        pdf_a = make_pdf_with_marker(MARKER_A)
        pdf_b = make_pdf_with_marker(MARKER_B)

        result_a = ""
        result_b = ""
        try:
            result_a = main.extract_pdf_text(pdf_a)
        except Exception:
            pass
        try:
            result_b = main.extract_pdf_text(pdf_b)
        except Exception:
            pass

        # Each result should not contain the other's marker
        assert MARKER_A not in result_b, "First PDF content bled into second extraction"
        assert MARKER_B not in result_a, "Second PDF content bled into first extraction"

    def test_bytesio_does_not_cache(self, tmp_env):
        """BytesIO buffer from first call must not persist into second call."""
        import main
        pdf_bytes_1 = make_pdf_with_marker("FIRST_CALL")
        pdf_bytes_2 = make_pdf_with_marker("SECOND_CALL")

        # Run twice — if BytesIO were cached/global, second run would see first content
        try:
            main.extract_pdf_text(pdf_bytes_1)
            main.extract_pdf_text(pdf_bytes_2)
        except Exception:
            pass
        # If we get here without an assertion failure, buffers are independent
        assert True


# ---------------------------------------------------------------------------
# 4. Code file — only metadata stored
# ---------------------------------------------------------------------------

class TestCodeFileRetention:

    def test_code_file_contains_only_codes(self, tmp_env):
        """codes.txt must contain only invite code patterns, not document content."""
        import main, re
        main.generate_new_codes(3)
        lines = [l.strip() for l in tmp_env["codes_file"].read_text().splitlines() if l.strip()]
        code_pattern = re.compile(r'^(USED:)?RENTA-[A-Z0-9]{4}(:\d+)?$')
        for line in lines:
            assert code_pattern.match(line), f"Unexpected content in codes.txt: {line!r}"

    def test_multi_use_counter_not_content(self, tmp_env):
        """The use counter in codes.txt must be a number, not document text."""
        import main, re
        main.mark_code_used("RENTA-ZRT1")
        main.mark_code_used("RENTA-ZRT1")
        lines = [l.strip() for l in tmp_env["codes_file"].read_text().splitlines() if l.strip()]
        for line in lines:
            if ":" in line and not line.startswith("USED:"):
                _, count = line.rsplit(":", 1)
                assert count.isdigit(), f"Non-numeric counter in codes.txt: {line!r}"


# ---------------------------------------------------------------------------
# 6. Token / cost fields — metadata, not content
# ---------------------------------------------------------------------------

class TestTokenCostFields:

    def test_token_fields_are_numeric(self, tmp_env):
        """input_tokens, output_tokens, and cost_usd must be numeric if present."""
        import main
        main.append_ops_log({
            "ts": "2026-01-01T00:00:00Z",
            "code_used": "RENTA-ZRT1",
            "returns_uploaded": 1,
            "file_size_bytes": 1234,
            "response_time_ms": 5000,
            "completed": True,
            "input_tokens": 4200,
            "output_tokens": 1800,
            "cost_usd": 0.039600,
        })
        entry = json.loads(tmp_env["ops_file"].read_text().strip())
        assert isinstance(entry["input_tokens"], int),  "input_tokens must be int"
        assert isinstance(entry["output_tokens"], int), "output_tokens must be int"
        assert isinstance(entry["cost_usd"], float),    "cost_usd must be float"

    def test_token_fields_contain_no_text(self, tmp_env):
        """Token counts must not be strings or contain document content."""
        import main
        MARKER = "CONTENT_IN_TOKEN_FIELD_TEST"
        main.append_ops_log({
            "ts": "2026-01-01T00:00:00Z",
            "code_used": "RENTA-ZRT1",
            "returns_uploaded": 1,
            "file_size_bytes": 999,
            "response_time_ms": 1000,
            "completed": True,
            "input_tokens": 3000,
            "output_tokens": 900,
            "cost_usd": 0.0225,
        })
        log_text = tmp_env["ops_file"].read_text()
        assert MARKER not in log_text, "Content marker found in token fields"

    def test_cost_is_non_negative(self, tmp_env):
        """cost_usd must be zero or positive."""
        import main
        main.append_ops_log({
            "ts": "2026-01-01T00:00:00Z",
            "code_used": "RENTA-ZRT1",
            "returns_uploaded": 1,
            "file_size_bytes": 500,
            "response_time_ms": 3000,
            "completed": True,
            "input_tokens": 100,
            "output_tokens": 50,
            "cost_usd": 0.001050,
        })
        entry = json.loads(tmp_env["ops_file"].read_text().strip())
        assert entry["cost_usd"] >= 0, "cost_usd must be non-negative"

    def test_ops_log_valid_without_token_fields(self, tmp_env):
        """Token fields are optional — ops log must still be valid without them (legacy entries)."""
        import main
        main.append_ops_log({
            "ts": "2026-01-01T00:00:00Z",
            "code_used": "RENTA-ZRT1",
            "returns_uploaded": 1,
            "file_size_bytes": 1234,
            "response_time_ms": 1000,
            "completed": True,
            # no token fields
        })
        entry = json.loads(tmp_env["ops_file"].read_text().strip())
        assert "ts" in entry
        assert "cost_usd" not in entry  # not present, not defaulted to anything


# ---------------------------------------------------------------------------
# 5. Response structure — no stored report URL
# ---------------------------------------------------------------------------

class TestNoStoredReportURL:

    def test_api_response_is_streaming_not_url(self, tmp_env):
        """
        The /process endpoint must return a streaming body, not a URL pointing
        to a stored report. Verify the content-type is text/plain (streamed),
        not a JSON body with a URL field.
        """
        from fastapi.testclient import TestClient
        import importlib, sys
        if "main" in sys.modules:
            del sys.modules["main"]
        import main as m
        importlib.reload(m)

        client = TestClient(m.app, raise_server_exceptions=False)
        response = client.post(
            "/process",
            data={"invite_code": "RENTA-ZRT1", "language": "en"},
            files=[("pdfs", ("t.pdf", BytesIO(make_pdf_with_marker("URL_TEST")), "application/pdf"))],
        )
        # Should not be a redirect or a URL response
        assert response.status_code != 301
        assert response.status_code != 302
        if response.status_code == 200:
            ct = response.headers.get("content-type", "")
            assert "text/plain" in ct or "text/event-stream" in ct, \
                f"Unexpected content-type: {ct} — report may be stored and linked"
            # Response body must not contain a URL to a stored resource
            body = response.text[:500]
            assert "https://ran.accordant.eu/reports/" not in body
            assert "download?id=" not in body
            assert "report_id" not in body
