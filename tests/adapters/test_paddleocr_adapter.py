from unittest.mock import MagicMock, patch

import pytest

from ocrhub.adapters.paddleocr_adapter import PaddleOcrAdapter


def test_available_false_when_paddleocr_not_installed():
    with patch.dict("sys.modules", {"paddleocr": None}):
        assert PaddleOcrAdapter().available() is False


def test_extract_parses_paddleocr_result_format(sample_image_bytes, tmp_path):
    adapter = PaddleOcrAdapter()

    # PaddleOCR's .ocr() returns: [[ [box, (text, confidence)], ... ]] per image
    fake_result = [[[[[0, 0], [1, 0], [1, 1], [0, 1]], ("OCRHUB TEST", 0.88)]]]
    fake_engine = MagicMock()
    fake_engine.ocr.return_value = fake_result

    with patch.object(adapter, "_build_engine", return_value=fake_engine):
        result = adapter.extract(sample_image_bytes, "sample.png")

    assert result.ok is True
    assert "OCRHUB TEST" in result.text
    assert result.pages[0].confidence == pytest.approx(0.88)


def test_extract_handles_blank_page_none_result(sample_image_bytes):
    """PaddleOCR returns [None] (a single None entry, not []) for a
    blank/textless page rather than an empty list of lines."""
    adapter = PaddleOcrAdapter()

    fake_engine = MagicMock()
    fake_engine.ocr.return_value = [None]

    with patch.object(adapter, "_build_engine", return_value=fake_engine):
        result = adapter.extract(sample_image_bytes, "sample.png")

    assert result.ok is True
    assert result.text == ""
    assert result.pages[0].confidence is None
