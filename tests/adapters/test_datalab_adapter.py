import json
from pathlib import Path

from ocrhub.adapters.datalab_adapter import DatalabAdapter, parse_datalab_json

FIXTURE = Path(__file__).parent.parent / "fixtures" / "datalab_sample.json"


def test_available_false_when_no_api_key(monkeypatch):
    monkeypatch.delenv("DATALAB_API_KEY", raising=False)
    assert DatalabAdapter(api_key=None).available() is False


def test_available_true_when_api_key_set():
    assert DatalabAdapter(api_key="fake-key").available() is True


def test_parse_datalab_json_flattens_blocks_in_reading_order():
    data = json.loads(FIXTURE.read_text())
    pages = parse_datalab_json(data)

    assert len(pages) == 1
    page = pages[0]
    assert len(page.boxes) == 6

    reading_orders = [b.reading_order for b in page.boxes]
    assert reading_orders == sorted(reading_orders)

    first = page.boxes[0]
    assert "Lesson 1" in first.text
    assert first.region_type == "Title"
    assert (first.x0, first.y0, first.x1, first.y1) == (113.0, 134.0, 987.0, 201.0)


def test_parse_datalab_json_strips_html_and_flattens_list_group():
    data = json.loads(FIXTURE.read_text())
    pages = parse_datalab_json(data)
    page = pages[0]

    list_box = next(b for b in page.boxes if "Master stillness" in b.text)
    assert "<" not in list_box.text
    assert "Don't fidget" in list_box.text
    assert list_box.region_type == "Text"


def test_parse_datalab_json_produces_page_text_from_boxes():
    data = json.loads(FIXTURE.read_text())
    pages = parse_datalab_json(data)
    page = pages[0]

    assert "Lesson 1: True Authority Effect" in page.text
    assert "People mirror your confidence back." in page.text


def test_parse_datalab_json_keeps_original_html_on_boxes():
    data = json.loads(FIXTURE.read_text())
    page = parse_datalab_json(data)[0]

    list_box = next(b for b in page.boxes if "Master stillness" in b.text)
    assert list_box.html.startswith("<ol")
    assert "<li>" in list_box.html
