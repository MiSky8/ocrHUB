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


from ocrhub.adapters import paddleocr_adapter


def _ocr_engine(text="HELLO", poly=((10, 10), (110, 10), (110, 40), (10, 40))):
    engine = MagicMock()
    engine.predict.return_value = [_fake_page(text, 0.9, [list(p) for p in poly])]
    return engine


def _layout_model(*boxes):
    model = MagicMock()
    model.predict.return_value = [{"boxes": list(boxes)}]
    return model


def test_layout_off_by_default_gives_plain_line_boxes(sample_image_bytes, monkeypatch):
    monkeypatch.delenv("PADDLE_LAYOUT", raising=False)
    adapter = PaddleOcrAdapter()
    with patch.object(adapter, "_build_engine", return_value=_ocr_engine()), \
         patch.object(adapter, "_build_layout_model") as build_layout:
        result = adapter.extract(sample_image_bytes, "s.png")
    build_layout.assert_not_called()
    assert result.pages[0].boxes[0].region_type is None
    assert adapter.capabilities() == []


def test_layout_on_adds_regions_and_a_picture(sample_image_bytes, monkeypatch):
    monkeypatch.setenv("PADDLE_LAYOUT", "1")
    adapter = PaddleOcrAdapter()
    layout = _layout_model(
        {"label": "text", "score": 0.9, "coordinate": [0, 0, 200, 60]},
        {"label": "image", "score": 0.8, "coordinate": [250, 10, 450, 100]},
    )
    with patch.object(adapter, "_build_engine", return_value=_ocr_engine()), \
         patch.object(adapter, "_build_layout_model", return_value=layout):
        result = adapter.extract(sample_image_bytes, "s.png")
    page = result.pages[0]
    assert [b.region_type for b in page.boxes] == ["Text", "Picture"]
    assert page.boxes[0].text == "HELLO"
    assert page.boxes[1].image
    assert page.text == "HELLO"
    assert "Picture" in adapter.capabilities()


def test_layout_failure_keeps_the_ocr_lines(sample_image_bytes, monkeypatch, caplog):
    monkeypatch.setenv("PADDLE_LAYOUT", "1")
    adapter = PaddleOcrAdapter()
    with patch.object(adapter, "_build_engine", return_value=_ocr_engine()), \
         patch.object(adapter, "_build_layout_model", side_effect=RuntimeError("download failed")):
        result = adapter.extract(sample_image_bytes, "s.png")
    assert result.ok is True
    assert result.pages[0].boxes[0].text == "HELLO"
    assert result.pages[0].boxes[0].region_type is None
    assert "layout" in caplog.text.lower()


def test_ocr_engine_is_released_before_layout_model_loads(sample_image_bytes, monkeypatch):
    monkeypatch.setenv("PADDLE_LAYOUT", "1")
    adapter = PaddleOcrAdapter()
    order = []
    monkeypatch.setattr(paddleocr_adapter, "_free_memory", lambda: order.append("free"))
    with patch.object(adapter, "_build_engine", side_effect=lambda: order.append("ocr") or _ocr_engine()), \
         patch.object(adapter, "_build_layout_model", side_effect=lambda: order.append("layout") or _layout_model()):
        adapter.extract(sample_image_bytes, "s.png")
    assert order.index("free") < order.index("layout")


def test_layout_model_loaded_once_for_multi_page_pdf(sample_scanned_pdf_bytes, monkeypatch):
    monkeypatch.setenv("PADDLE_LAYOUT", "1")
    adapter = PaddleOcrAdapter()
    with patch.object(adapter, "_build_engine", return_value=_ocr_engine()), \
         patch.object(adapter, "_build_layout_model", return_value=_layout_model()) as build_layout:
        adapter.extract(sample_scanned_pdf_bytes, "s.pdf")
    assert build_layout.call_count == 1
