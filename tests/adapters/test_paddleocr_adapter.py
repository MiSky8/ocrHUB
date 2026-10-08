from unittest.mock import MagicMock, patch

import pytest

from ocrhub.adapters.paddleocr_adapter import PaddleOcrAdapter


def _fake_page(text, score, polygon):
    # PaddleOCR 3.x predict() returns one dict-like result per image, with
    # parallel lists for the recognised lines.
    return {"rec_texts": [text], "rec_scores": [score], "rec_polys": [polygon]}


def test_available_false_when_paddleocr_not_installed():
    with patch.dict("sys.modules", {"paddleocr": None}):
        assert PaddleOcrAdapter().available() is False


def test_extract_parses_paddleocr_result_format(sample_image_bytes, tmp_path):
    adapter = PaddleOcrAdapter()

    fake_engine = MagicMock()
    fake_engine.predict.return_value = [_fake_page("OCRHUB TEST", 0.88, [[0, 0], [1, 0], [1, 1], [0, 1]])]

    with patch.object(adapter, "_build_engine", return_value=fake_engine):
        result = adapter.extract(sample_image_bytes, "sample.png")

    assert result.ok is True
    assert "OCRHUB TEST" in result.text
    assert result.pages[0].confidence == pytest.approx(0.88)


def test_extract_handles_blank_page_none_result(sample_image_bytes):
    """A textless page comes back with empty parallel lists."""
    adapter = PaddleOcrAdapter()

    fake_engine = MagicMock()
    fake_engine.predict.return_value = [{"rec_texts": [], "rec_scores": [], "rec_polys": []}]

    with patch.object(adapter, "_build_engine", return_value=fake_engine):
        result = adapter.extract(sample_image_bytes, "sample.png")

    assert result.ok is True
    assert result.text == ""
    assert result.pages[0].confidence is None


def test_extract_returns_boxes_and_page_image(sample_image_bytes):
    adapter = PaddleOcrAdapter()

    fake_engine = MagicMock()
    fake_engine.predict.return_value = [
        _fake_page("OCRHUB TEST", 0.88, [[10, 20], [110, 20], [110, 50], [10, 50]])
    ]

    with patch.object(adapter, "_build_engine", return_value=fake_engine):
        result = adapter.extract(sample_image_bytes, "sample.png")

    page = result.pages[0]
    assert page.image_base64 is not None
    assert len(page.image_base64) > 0

    assert len(page.boxes) == 1
    box = page.boxes[0]
    assert box.text == "OCRHUB TEST"
    assert (box.x0, box.y0, box.x1, box.y1) == (10.0, 20.0, 110.0, 50.0)
    assert box.confidence == pytest.approx(88.0)
    assert box.reading_order == 0
