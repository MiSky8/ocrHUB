from ocrhub.models import OcrResult, PageResult


def test_ocr_result_ok_when_no_error():
    result = OcrResult(
        engine="tesseract",
        text="hello",
        pages=[PageResult(page_number=1, text="hello", confidence=0.9)],
        confidence=0.9,
        elapsed_ms=42,
    )
    assert result.ok is True


def test_ocr_result_not_ok_when_error_set():
    result = OcrResult(
        engine="tesseract",
        text="",
        pages=[],
        confidence=None,
        elapsed_ms=5,
        error="model not loaded",
    )
    assert result.ok is False
