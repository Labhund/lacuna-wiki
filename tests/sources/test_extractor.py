import subprocess
from pathlib import Path
import pytest
from lacuna_wiki.sources.extractor import extract_text


def test_extract_md_returns_content(tmp_path):
    md = tmp_path / "test.md"
    md.write_text("# Hello\n\nWorld.\n")
    assert extract_text(md) == "# Hello\n\nWorld.\n"


def test_extract_markdown_extension(tmp_path):
    f = tmp_path / "test.markdown"
    f.write_text("content")
    assert extract_text(f) == "content"


def test_extract_unsupported_raises(tmp_path):
    f = tmp_path / "test.docx"
    f.write_text("content")
    with pytest.raises(ValueError, match="Unsupported"):
        extract_text(f)


def test_extract_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        extract_text(tmp_path / "missing.md")


def test_extract_pdf_calls_pdftotext(tmp_path, monkeypatch):
    """PDF extraction shells out to pdftotext."""
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")  # not a real PDF — pdftotext is mocked

    def fake_run(args, **kwargs):
        class R:
            returncode = 0
            stdout = b"Extracted text from PDF."
            stderr = b""
        return R()

    monkeypatch.setattr("lacuna_wiki.sources.extractor.subprocess.run", fake_run)
    result = extract_text(pdf)
    assert result == "Extracted text from PDF."


def test_extract_pdf_raises_on_pdftotext_failure(tmp_path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    def fake_run(args, **kwargs):
        class R:
            returncode = 1
            stdout = b""
            stderr = b"Error: PDF damaged"
        return R()

    monkeypatch.setattr("lacuna_wiki.sources.extractor.subprocess.run", fake_run)
    with pytest.raises(RuntimeError, match="pdftotext failed"):
        extract_text(pdf)
