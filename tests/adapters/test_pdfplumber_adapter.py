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


def test_extract_returns_line_boxes_with_font_style(sample_born_digital_pdf_bytes):
    result = PdfplumberAdapter().extract(sample_born_digital_pdf_bytes, "sample.pdf")

    page = result.pages[0]
    assert page.width and page.height
    box = next(b for b in page.boxes if "OCRHUB" in b.text)
    assert box.style["size"] > 0
    assert box.style["font"]
    assert box.x1 > box.x0 and box.y1 > box.y0
