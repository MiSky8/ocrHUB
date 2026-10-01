from unittest.mock import MagicMock, patch

import pytest

from ocrhub.adapters.surya_adapter import SuryaAdapter, build_region_boxes


@pytest.fixture(autouse=True)
def _plain_lines(monkeypatch):
    """The older tests below cover line output; layout is tested separately."""
    monkeypatch.setenv("SURYA_LAYOUT", "0")


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


def _line(text, bbox, conf=0.9):
    return {"text": text, "bbox": bbox, "confidence": conf}


def test_regions_group_lines_and_follow_layout_order():
    lines = [
        _line("Body paragraph", [10, 100, 200, 120], 0.8),
        _line("Second line", [10, 125, 200, 145], 0.6),
        _line("Heading", [10, 10, 100, 40], 1.0),
    ]
    regions = [
        {"label": "Text", "position": 1, "bbox": [0, 90, 220, 160]},
        {"label": "SectionHeader", "position": 0, "bbox": [0, 0, 220, 50]},
    ]

    boxes = build_region_boxes(lines, regions)

    assert [b.region_type for b in boxes] == ["Title", "Text"]
    assert [b.reading_order for b in boxes] == [0, 1]
    assert boxes[0].text == "Heading"
    assert boxes[1].text == "Body paragraph\nSecond line"
    assert boxes[1].confidence == pytest.approx(70.0)
    assert (boxes[1].x0, boxes[1].y0, boxes[1].x1, boxes[1].y1) == (0.0, 90.0, 220.0, 160.0)


def test_line_goes_to_smallest_enclosing_region_and_orphans_are_kept():
    lines = [_line("inside caption", [20, 20, 60, 30]), _line("stray", [500, 500, 520, 510])]
    regions = [
        {"label": "Text", "position": 0, "bbox": [0, 0, 300, 300]},
        {"label": "Caption", "position": 1, "bbox": [10, 10, 100, 40]},
    ]

    boxes = build_region_boxes(lines, regions)

    caption = next(b for b in boxes if b.region_type == "Caption")
    assert caption.text == "inside caption"
    assert all(b.text != "inside caption" for b in boxes if b.region_type == "Text")
    stray = boxes[-1]
    assert stray.text == "stray"
    assert stray.reading_order is None and stray.region_type is None


def test_blank_and_empty_text_regions_are_dropped_but_pictures_stay():
    regions = [
        {"label": "Blank", "position": 0, "bbox": [0, 0, 10, 10]},
        {"label": "Text", "position": 1, "bbox": [0, 20, 10, 30]},
        {"label": "Figure", "position": 2, "bbox": [0, 40, 50, 90]},
    ]

    boxes = build_region_boxes([], regions, pictures={2: "AAAA"})

    assert len(boxes) == 1
    assert boxes[0].region_type == "Picture"
    assert boxes[0].image == "AAAA"


def test_table_region_gets_html_with_cell_text_and_spans():
    lines = [
        _line("Item", [10, 10, 50, 20]),
        _line("Cost", [110, 10, 150, 20]),
        _line("A&B", [10, 40, 50, 50]),
        _line("3", [110, 40, 150, 50]),
    ]
    regions = [{"label": "Table", "position": 0, "bbox": [0, 0, 200, 60]}]
    cells = [
        {"bbox": [0, 0, 100, 30], "row": 0, "col": 0, "rowspan": 1, "colspan": 1, "header": True},
        {"bbox": [100, 0, 200, 30], "row": 0, "col": 1, "rowspan": 1, "colspan": 1, "header": True},
        {"bbox": [0, 30, 100, 60], "row": 1, "col": 0, "rowspan": 1, "colspan": 1, "header": False},
        {"bbox": [100, 30, 200, 60], "row": 1, "col": 1, "rowspan": 2, "colspan": 1, "header": False},
    ]

    [box] = build_region_boxes(lines, regions, tables={0: cells})

    assert box.region_type == "Table"
    assert box.html == (
        "<table><tr><th>Item</th><th>Cost</th></tr>"
        '<tr><td>A&amp;B</td><td rowspan="2">3</td></tr></table>'
    )
    assert box.text == "Item | Cost\nA&B | 3"


def test_extract_with_layout_returns_region_boxes_and_runs_table_model(sample_image_bytes):
    adapter = SuryaAdapter()
    lines = [
        MagicMock(text="Heading", confidence=0.9, bbox=[10.0, 10.0, 90.0, 30.0]),
        MagicMock(text="cell", confidence=0.8, bbox=[12.0, 60.0, 50.0, 75.0]),
    ]
    recognition = MagicMock(return_value=[MagicMock(text_lines=lines)])
    layout_boxes = [
        MagicMock(label="SectionHeader", position=0, bbox=[0, 0, 100, 40]),
        MagicMock(label="Table", position=1, bbox=[0, 50, 100, 90]),
    ]
    layout = MagicMock(return_value=[MagicMock(bboxes=layout_boxes)])
    cell = MagicMock(bbox=[0, 0, 100, 40], row_id=0, col_id=0, rowspan=None, colspan=1, is_header=False)
    table = MagicMock(return_value=[MagicMock(cells=[cell])])

    with patch.object(SuryaAdapter, "_recognition_predictor_cls", MagicMock(return_value=recognition)), patch.object(
        SuryaAdapter, "_detection_predictor_cls", MagicMock()
    ), patch.object(SuryaAdapter, "_layout_predictor_cls", MagicMock(return_value=layout)), patch.object(
        SuryaAdapter, "_table_predictor_cls", MagicMock(return_value=table)
    ), patch.dict("os.environ", {"SURYA_LAYOUT": "1"}):
        result = adapter.extract(sample_image_bytes, "sample.png")

    boxes = result.pages[0].boxes
    assert [(b.region_type, b.reading_order) for b in boxes] == [("Title", 0), ("Table", 1)]
    # the table crop starts at (0, 50), so its cell is placed back on the page
    assert boxes[1].html == "<table><tr><td>cell</td></tr></table>"
    table.assert_called_once()


def test_extract_falls_back_to_lines_when_layout_fails(sample_image_bytes):
    adapter = SuryaAdapter()
    line = MagicMock(text="OCRHUB TEST", confidence=0.95, bbox=[10.0, 40.0, 180.0, 70.0])
    recognition = MagicMock(return_value=[MagicMock(text_lines=[line])])
    broken = MagicMock(side_effect=RuntimeError("model download failed"))

    with patch.object(SuryaAdapter, "_recognition_predictor_cls", MagicMock(return_value=recognition)), patch.object(
        SuryaAdapter, "_detection_predictor_cls", MagicMock()
    ), patch.object(SuryaAdapter, "_layout_predictor_cls", broken), patch.dict("os.environ", {"SURYA_LAYOUT": "1"}):
        result = adapter.extract(sample_image_bytes, "sample.png")

    assert result.ok
    assert [b.text for b in result.pages[0].boxes] == ["OCRHUB TEST"]
    assert result.pages[0].boxes[0].reading_order is None


def test_table_text_keeps_cell_order_when_line_heights_differ():
    lines = [
        _line("$12,450", [110, 12, 150, 22]),  # sits slightly higher than its row neighbour
        _line("North", [10, 14, 50, 24]),
    ]
    regions = [{"label": "Table", "position": 0, "bbox": [0, 0, 200, 30]}]
    cells = [
        {"bbox": [0, 0, 100, 30], "row": 0, "col": 0, "rowspan": 1, "colspan": 1, "header": False},
        {"bbox": [100, 0, 200, 30], "row": 0, "col": 1, "rowspan": 1, "colspan": 1, "header": False},
    ]

    [box] = build_region_boxes(lines, regions, tables={0: cells})

    assert box.text == "North | $12,450"


def test_list_marker_stays_on_the_same_line_as_its_text():
    # the marker is detected as its own line, a little lower than the text
    lines = [
        _line("Regions", [60, 100, 200, 130]),
        _line("\\bullet", [20, 108, 50, 138]),
        _line("North", [60, 150, 200, 180]),
        _line("\\bullet", [20, 158, 50, 188]),
    ]
    regions = [{"label": "Text", "position": 0, "bbox": [0, 90, 220, 200]}]

    [box] = build_region_boxes(lines, regions)

    assert box.text == "\\bullet Regions\n\\bullet North"
