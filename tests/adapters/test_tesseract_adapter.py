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


def test_extract_returns_word_boxes_and_page_image(sample_image_bytes):
    adapter = TesseractAdapter()
    result = adapter.extract(sample_image_bytes, "sample.png")

    page = result.pages[0]
    assert page.image_base64 is not None
    assert len(page.image_base64) > 0

    assert len(page.boxes) > 0
    words = "".join(b.text.upper() for b in page.boxes)
    assert "OCRHUB" in words

    for box in page.boxes:
        assert box.x1 > box.x0
        assert box.y1 > box.y0


def test_extract_reads_text_from_scanned_pdf(sample_scanned_pdf_bytes):
    adapter = TesseractAdapter()
    result = adapter.extract(sample_scanned_pdf_bytes, "sample.pdf")

    assert result.ok is True
    assert len(result.pages) == 1
    assert "OCRHUB" in result.text.upper()


def test_extract_groups_words_into_ordered_line_boxes(sample_image_bytes):
    result = TesseractAdapter().extract(sample_image_bytes, "sample.png")

    page = result.pages[0]
    assert page.confidence is not None
    box = next(b for b in page.boxes if "OCRHUB" in b.text.upper())
    assert box.reading_order is not None
    assert len(box.words) >= 1
    assert all(w["x1"] > w["x0"] for w in box.words)
    assert [b.reading_order for b in page.boxes] == list(range(len(page.boxes)))
