import base64

from PIL import Image

from ocrhub.adapters._paddle_layout import merge_layout

IMG = Image.new("RGB", (1000, 1000), "white")


def line(text, x0, y0, x1, y1, conf=0.9):
    return {"text": text, "confidence": conf, "bbox": (x0, y0, x1, y1)}


def region(label, x0, y0, x1, y1, score=0.8):
    return {"label": label, "score": score, "coordinate": [x0, y0, x1, y1]}


def test_lines_inside_a_region_are_joined_in_reading_order():
    lines = [line("second", 10, 60, 90, 80), line("first", 10, 10, 90, 30)]
    boxes = merge_layout(lines, [region("text", 0, 0, 100, 100)], IMG)
    assert len(boxes) == 1
    assert boxes[0].text == "first\nsecond"
    assert boxes[0].region_type == "Text"
    assert boxes[0].confidence == 90.0
    assert (boxes[0].x0, boxes[0].y0, boxes[0].x1, boxes[0].y1) == (0.0, 0.0, 100.0, 100.0)


def test_label_mapping():
    layout = [
        region("paragraph_title", 0, 0, 100, 40),
        region("figure_title", 0, 100, 100, 140),
        region("table", 0, 200, 100, 240),
    ]
    lines = [line("T", 5, 5, 50, 30), line("C", 5, 105, 50, 130), line("cells", 5, 205, 50, 230)]
    types = [b.region_type for b in merge_layout(lines, layout, IMG)]
    assert types == ["Title", "Caption", "Table"]


def test_unmapped_label_is_ignored_and_its_lines_survive():
    boxes = merge_layout([line("42", 5, 5, 30, 20)], [region("number", 0, 0, 100, 100)], IMG)
    assert len(boxes) == 1
    assert boxes[0].text == "42"
    assert boxes[0].region_type is None


def test_regions_without_lines_are_dropped():
    assert merge_layout([], [region("text", 0, 0, 100, 100)], IMG) == []


def test_figure_becomes_a_picture_box_with_a_crop():
    boxes = merge_layout([], [region("image", 100, 100, 500, 400)], IMG)
    assert len(boxes) == 1
    pic = boxes[0]
    assert pic.region_type == "Picture"
    assert pic.text == ""
    assert pic.confidence is None
    assert base64.b64decode(pic.image)[:2] == b"\xff\xd8"  # JPEG magic


def test_duplicate_image_and_chart_regions_collapse_to_the_higher_score():
    layout = [
        region("chart", 138, 773, 1181, 1728, score=0.54),
        region("image", 138, 767, 1179, 1732, score=0.67),
    ]
    boxes = merge_layout([], layout, Image.new("RGB", (1300, 1800), "white"))
    assert len(boxes) == 1
    assert (boxes[0].x0, boxes[0].y0) == (138.0, 767.0)


def test_text_inside_a_picture_stays_as_a_line_box():
    layout = [region("image", 0, 0, 500, 500)]
    boxes = merge_layout([line("Q3 revenue", 100, 100, 300, 130)], layout, IMG)
    assert [b.region_type for b in boxes] == ["Picture", None]
    assert boxes[1].text == "Q3 revenue"


def test_smallest_containing_region_owns_the_line():
    layout = [region("text", 0, 0, 500, 500), region("table", 100, 100, 300, 300)]
    boxes = merge_layout([line("cell", 150, 150, 250, 180)], layout, IMG)
    assert [(b.region_type, b.text) for b in boxes] == [("Table", "cell")]


def test_regions_ordered_top_to_bottom_then_left_to_right_and_numbered():
    layout = [region("text", 0, 300, 100, 340), region("text", 200, 0, 300, 40), region("text", 0, 0, 100, 40)]
    lines = [line("c", 5, 305, 50, 330), line("b", 205, 5, 250, 30), line("a", 5, 5, 50, 30)]
    boxes = merge_layout(lines, layout, IMG)
    assert [b.text for b in boxes] == ["a", "b", "c"]
    assert [b.reading_order for b in boxes] == [0, 1, 2]


def test_leftover_lines_follow_the_regions():
    layout = [region("text", 0, 0, 100, 100)]
    lines = [line("in", 5, 5, 50, 30), line("out", 500, 500, 600, 530, conf=0.5)]
    boxes = merge_layout(lines, layout, IMG)
    assert [b.text for b in boxes] == ["in", "out"]
    assert [b.reading_order for b in boxes] == [0, 1]
    assert boxes[1].confidence == 50.0


def test_no_regions_returns_plain_line_boxes():
    boxes = merge_layout([line("a", 0, 0, 10, 10), line("b", 0, 20, 10, 30)], [], IMG)
    assert [b.text for b in boxes] == ["a", "b"]
    assert all(b.region_type is None for b in boxes)
