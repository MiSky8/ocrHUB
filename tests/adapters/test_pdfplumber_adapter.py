import pytest

from ocrhub.adapters.pdfplumber_adapter import PdfplumberAdapter


def test_available_is_always_true():
    assert PdfplumberAdapter().available() is True


def test_extract_returns_text_from_born_digital_pdf(sample_born_digital_pdf_bytes):
    adapter = PdfplumberAdapter()
    result = adapter.extract(sample_born_digital_pdf_bytes, "sample.pdf")

    assert result.ok is True
    assert "OCRHUB" in result.text
    assert len(result.pages) == 1


def test_extract_rejects_non_pdf():
    adapter = PdfplumberAdapter()
    with pytest.raises(ValueError):
        adapter.extract(b"not a pdf", "photo.png")
