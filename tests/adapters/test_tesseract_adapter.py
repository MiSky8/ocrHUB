import shutil

import pytest

from ocrhub.adapters.tesseract_adapter import TesseractAdapter

pytestmark = pytest.mark.skipif(
    shutil.which("tesseract") is None, reason="tesseract binary not installed"
)


def test_available_true_when_binary_present():
    assert TesseractAdapter().available() is True


def test_extract_reads_text_from_image(sample_image_bytes):
    adapter = TesseractAdapter()
    result = adapter.extract(sample_image_bytes, "sample.png")

    assert result.ok is True
    assert "OCRHUB" in result.text.upper()
    assert len(result.pages) == 1


def test_extract_reads_text_from_scanned_pdf(sample_scanned_pdf_bytes):
    adapter = TesseractAdapter()
    result = adapter.extract(sample_scanned_pdf_bytes, "sample.pdf")

    assert result.ok is True
    assert len(result.pages) == 1
    assert "OCRHUB" in result.text.upper()
