from unittest.mock import MagicMock, patch

import pytest

from ocrhub.adapters.surya_adapter import SuryaAdapter


def test_available_false_when_surya_not_installed():
    with patch.dict("sys.modules", {"surya": None, "surya.recognition": None, "surya.detection": None}):
        assert SuryaAdapter().available() is False


def test_extract_uses_recognition_predictor(sample_image_bytes):
    adapter = SuryaAdapter()

    fake_line = MagicMock(text="OCRHUB TEST", confidence=0.95, bbox=[10.0, 40.0, 180.0, 70.0])
    fake_prediction = MagicMock(text_lines=[fake_line])

    fake_recognition_cls = MagicMock(return_value=MagicMock(return_value=[fake_prediction]))
    fake_detection_cls = MagicMock(return_value=MagicMock())

    with patch.object(SuryaAdapter, "_recognition_predictor_cls", fake_recognition_cls), patch.object(
        SuryaAdapter, "_detection_predictor_cls", fake_detection_cls
    ):
        result = adapter.extract(sample_image_bytes, "sample.png")

    assert result.ok is True
    assert "OCRHUB TEST" in result.text
    assert result.pages[0].confidence == pytest.approx(0.95)


def test_extract_returns_boxes_and_page_image(sample_image_bytes):
    adapter = SuryaAdapter()

    fake_line = MagicMock(text="OCRHUB TEST", confidence=0.95, bbox=[10.0, 40.0, 180.0, 70.0])
    fake_prediction = MagicMock(text_lines=[fake_line])

    fake_recognition_cls = MagicMock(return_value=MagicMock(return_value=[fake_prediction]))
    fake_detection_cls = MagicMock(return_value=MagicMock())

    with patch.object(SuryaAdapter, "_recognition_predictor_cls", fake_recognition_cls), patch.object(
        SuryaAdapter, "_detection_predictor_cls", fake_detection_cls
    ):
        result = adapter.extract(sample_image_bytes, "sample.png")

    page = result.pages[0]
    assert page.image_base64 is not None
    assert len(page.image_base64) > 0

    assert len(page.boxes) == 1
    box = page.boxes[0]
    assert box.text == "OCRHUB TEST"
    assert (box.x0, box.y0, box.x1, box.y1) == (10.0, 40.0, 180.0, 70.0)
    assert box.confidence == pytest.approx(95.0)
    assert box.reading_order is None


def test_extract_strips_markup_from_line_text(sample_image_bytes):
    adapter = SuryaAdapter()

    fake_line = MagicMock(text="<b>INVOICE</b> A &amp; B", confidence=0.9, bbox=[1.0, 2.0, 30.0, 40.0])
    fake_prediction = MagicMock(text_lines=[fake_line])

    fake_recognition_cls = MagicMock(return_value=MagicMock(return_value=[fake_prediction]))
    fake_detection_cls = MagicMock(return_value=MagicMock())

    with patch.object(SuryaAdapter, "_recognition_predictor_cls", fake_recognition_cls), patch.object(
        SuryaAdapter, "_detection_predictor_cls", fake_detection_cls
    ):
        result = adapter.extract(sample_image_bytes, "sample.png")

    assert result.text == "INVOICE A & B"
    assert result.pages[0].boxes[0].text == "INVOICE A & B"


def test_remove_incomplete_models_deletes_only_unfinished_dirs(tmp_path):
    from ocrhub.adapters.surya_adapter import remove_incomplete_models

    good = tmp_path / "text_detection" / "2025_05_07"
    bad = tmp_path / "text_recognition" / "2025_05_16"
    for d in (good, bad):
        d.mkdir(parents=True)
        (d / "README.md").write_text("x")
    (good / "manifest.json").write_text("{}")

    removed = remove_incomplete_models(tmp_path, lambda d: (d / "manifest.json").exists())

    assert removed == [bad]
    assert good.exists()
    assert not bad.exists()


def test_remove_incomplete_models_ignores_missing_cache_dir(tmp_path):
    from ocrhub.adapters.surya_adapter import remove_incomplete_models

    assert remove_incomplete_models(tmp_path / "nope", lambda d: False) == []


def test_strip_html_keeps_table_cells_and_list_items_apart():
    from ocrhub.adapters._text import strip_html

    table = "<table><tr><th>Region</th><th>Q1</th></tr><tr><td>North</td><td>$12,450</td></tr></table>"
    assert strip_html(table) == "Region | Q1\nNorth | $12,450"
    assert strip_html("<ul><li>One</li><li>Two</li></ul>") == "One\nTwo"
    assert strip_html("<b>bold</b> &amp; plain") == "bold & plain"


def test_html_to_text_adds_list_markers_unless_already_in_text():
    from ocrhub.adapters._text import html_to_text

    assert html_to_text("<ul><li>One</li><li>Two</li></ul>") == "• One\n• Two"
    assert html_to_text("<ol><li>One</li><li>Two</li></ol>") == "1. One\n2. Two"
    marked = '<ol style="list-style-type: none"><li>1. One</li></ol>'
    assert html_to_text(marked) == "1. One"
    table = "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
    assert html_to_text(table) == "A | B\n1 | 2"


def test_html_to_text_adds_markers_when_list_marks_none_but_text_has_no_marker():
    from ocrhub.adapters._text import html_to_text

    raw = '<ol style="list-style-type: none"><li>Review</li><li>Plan</li></ol>'
    assert html_to_text(raw) == "1. Review\n2. Plan"
