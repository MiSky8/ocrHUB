# PaddleOCR Layout Regions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a switchable PaddleOCR layout stage (figures, tables, titles, text regions) and make the dashboard state which engines do not detect figures.

**Architecture:** After PaddleOCR's text-line pass, `paddleocr.LayoutDetection` (PP-DocLayout-S) runs on the same page images; a pure merge function turns layout regions plus OCR lines into `BoxResult`s, with figures as `Picture` boxes carrying a crop. Each adapter exposes `capabilities()`; `/engines` reports them and the dashboard prints "No figure detection" for engines without `Picture`.

**Tech Stack:** Python 3.11, paddleocr 3.7.0 (`LayoutDetection`), FastAPI, vanilla JS dashboard, pytest.

**Spec:** `docs/superpowers/specs/2026-10-16-paddleocr-layout-design.md`

## Global Constraints

- Layout is off by default: `PADDLE_LAYOUT` unset or `0` gives exactly today's PaddleOCR output.
- Only one model set resident at a time: release the OCR engine before loading the layout model, release the layout model afterwards (CLAUDE.md, Surya memory rule).
- Per-engine isolation: a layout failure keeps the OCR lines; a real engine failure still returns `OcrResult.error` and is never cached.
- Coordinates are image pixels, taken from the same image for OCR and layout.
- No change to `models.py`, `service.py`, the cache format, the MCP tool, or any Tesseract, Surya, Datalab or pdfplumber behaviour. No shared figure detector: engines show only what they produce.
- Do not touch or delete `data/` (user files, gitignored).
- Tests mock PaddleOCR and `LayoutDetection`; real-model behaviour is checked in the container (Task 5).
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Facts verified against paddleocr 3.7.0 in the container

- `from paddleocr import LayoutDetection`; `LayoutDetection(model_name="PP-DocLayout-S")`.
- `[res] = model.predict(rgb_ndarray)`; `res["boxes"]` is a list of dicts: `{"cls_id": int, "label": str, "score": float, "coordinate": [x0, y0, x1, y1]}` in image pixels.
- The same figure came back twice (`image` and `chart`, near-identical boxes), so pictures must be de-duplicated.
- Real timings on a 2339x1653 page: load 25 s (including first download), predict 0.5 s.
- Layout output has no reading order; this plan orders regions top-to-bottom then left-to-right.

## File Structure

- Create `src/ocrhub/imaging.py`: `crop_jpeg_b64` moved out of the Surya adapter so two adapters share it.
- Create `src/ocrhub/adapters/_paddle_layout.py`: label map and `merge_layout` (pure, no paddle import).
- Modify `src/ocrhub/adapters/paddleocr_adapter.py`: two-pass extract, layout stage, `capabilities()`.
- Modify `src/ocrhub/adapters/{surya,datalab,pdfplumber,tesseract}_adapter.py`: `capabilities()` only (Surya also imports the moved helper).
- Modify `src/ocrhub/adapters/base.py`, `registry.py`, `api.py`: capabilities plumbing.
- Modify `src/ocrhub/web/static/app.js`, `dashboard.css`: the note.
- Modify `docker-compose.yml`, `.env.example`, `README.md`, `CHANGELOG.md`, `docs/visualisations.md`.
- Tests: `tests/test_imaging.py`, `tests/adapters/test_paddle_layout.py`, `tests/adapters/test_paddleocr_adapter.py`, `tests/test_registry.py`, `tests/test_api.py`, `tests/test_web.py`.

---

### Task 1: Share the picture-crop helper

**Files:**
- Create: `src/ocrhub/imaging.py`
- Modify: `src/ocrhub/adapters/surya_adapter.py` (remove `_MAX_PICTURE_SIDE` at line 66 and `_crop_jpeg_b64` at lines 213-226; import the shared helper; call site at line ~381)
- Test: `tests/test_imaging.py`

**Interfaces:**
- Produces: `ocrhub.imaging.crop_jpeg_b64(img: PIL.Image.Image, bbox) -> str | None` (base64 JPEG, longest side at most 800 px, `None` if the crop is under 2 px or anything fails).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_imaging.py
import base64
import io

from PIL import Image

from ocrhub.imaging import crop_jpeg_b64


def test_crop_returns_jpeg_of_the_region():
    img = Image.new("RGB", (400, 300), "white")
    out = crop_jpeg_b64(img, (10, 20, 110, 70))
    crop = Image.open(io.BytesIO(base64.b64decode(out)))
    assert crop.format == "JPEG"
    assert crop.size == (100, 50)


def test_crop_is_downscaled_to_800px():
    img = Image.new("RGB", (3000, 2000), "white")
    out = crop_jpeg_b64(img, (0, 0, 3000, 2000))
    assert max(Image.open(io.BytesIO(base64.b64decode(out))).size) == 800


def test_crop_clamps_to_image_and_rejects_tiny_regions():
    img = Image.new("RGB", (100, 100), "white")
    assert crop_jpeg_b64(img, (-50, -50, 40, 40)) is not None
    assert crop_jpeg_b64(img, (10, 10, 11, 11)) is None
    assert crop_jpeg_b64(img, ("a", 0, 1, 1)) is None
```

- [ ] **Step 2: Run it to see it fail**

Run: `pytest tests/test_imaging.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'ocrhub.imaging'`

- [ ] **Step 3: Create the module and point Surya at it**

```python
# src/ocrhub/imaging.py
import base64
import io

from PIL import Image

MAX_PICTURE_SIDE = 800


def crop_jpeg_b64(img: Image.Image, bbox) -> str | None:
    """Region crop as a downscaled base64 JPEG, for the dashboard's picture boxes."""
    try:
        x0, y0, x1, y1 = (int(v) for v in bbox)
        crop = img.convert("RGB").crop((max(x0, 0), max(y0, 0), min(x1, img.width), min(y1, img.height)))
        if crop.width < 2 or crop.height < 2:
            return None
        crop.thumbnail((MAX_PICTURE_SIDE, MAX_PICTURE_SIDE))
        buf = io.BytesIO()
        crop.save(buf, format="JPEG", quality=70)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:  # noqa: BLE001 - the crop is a nicety; the region is still reported
        return None
```

In `surya_adapter.py`: delete the `_MAX_PICTURE_SIDE = 800` line and the whole `_crop_jpeg_b64` function, add `from ocrhub.imaging import crop_jpeg_b64` next to the other `ocrhub` imports, and change the call `_crop_jpeg_b64(img, r["bbox"])` to `crop_jpeg_b64(img, r["bbox"])`. Then run `grep -n "base64\|^import io\|_MAX_PICTURE" src/ocrhub/adapters/surya_adapter.py`; remove the `base64` and `io` imports only if nothing else in the file uses them.

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_imaging.py tests/adapters/test_surya_adapter.py -q`
Expected: all PASS (Surya tests prove the move did not break it)

- [ ] **Step 5: Commit**

```bash
git add src/ocrhub/imaging.py src/ocrhub/adapters/surya_adapter.py tests/test_imaging.py
git commit -m "Move picture-crop helper to ocrhub.imaging

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Layout merge function

**Files:**
- Create: `src/ocrhub/adapters/_paddle_layout.py`
- Test: `tests/adapters/test_paddle_layout.py`

**Interfaces:**
- Consumes: `ocrhub.imaging.crop_jpeg_b64`, `ocrhub.models.BoxResult`.
- Produces: `LAYOUT_MODEL = "PP-DocLayout-S"`; `PICTURE = "Picture"`; `merge_layout(lines: list[dict], layout_boxes: list[dict], image: PIL.Image.Image) -> list[BoxResult]`.
  - A line is `{"text": str, "confidence": float | None (0 to 1), "bbox": (x0, y0, x1, y1)}`.
  - A layout box is the raw LayoutDetection dict (`label`, `score`, `coordinate`).

Behaviour (each point has a test below): unmapped labels are ignored; overlapping pictures are de-duplicated keeping the higher score; a line belongs to the smallest non-picture region containing its centre; lines inside a picture stay as plain line boxes (text inside images must stay visible); regions with no lines are dropped unless they are pictures; regions are ordered top-to-bottom then left-to-right and numbered from 0; leftover lines follow, numbered after the regions; region confidence is the mean line confidence times 100, `None` for pictures.

- [ ] **Step 1: Write the failing tests**

```python
# tests/adapters/test_paddle_layout.py
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
```

- [ ] **Step 2: Run to see them fail**

Run: `pytest tests/adapters/test_paddle_layout.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'ocrhub.adapters._paddle_layout'`

- [ ] **Step 3: Implement**

```python
# src/ocrhub/adapters/_paddle_layout.py
"""Merge PaddleOCR text lines with PP-DocLayout regions into dashboard boxes.

Pure functions, no paddle import, so the merge is testable without models.
"""
from PIL import Image

from ocrhub.imaging import crop_jpeg_b64
from ocrhub.models import BoxResult

LAYOUT_MODEL = "PP-DocLayout-S"
PICTURE = "Picture"

# PP-DocLayout label -> the region_type names the dashboard already uses.
# Labels not listed (page numbers, formula numbers) are ignored and their lines
# stay as plain line boxes.
_REGION_TYPES = {
    "text": "Text",
    "abstract": "Text",
    "content": "Text",
    "reference": "Text",
    "reference_content": "Text",
    "aside_text": "Text",
    "footnote": "Text",
    "paragraph_title": "Title",
    "doc_title": "Title",
    "figure_title": "Caption",
    "header": "Header",
    "footer": "Footer",
    "table": "Table",
    "formula": "Formula",
    "image": PICTURE,
    "chart": PICTURE,
    "seal": PICTURE,
}


def _area(b) -> float:
    return max(b[2] - b[0], 0.0) * max(b[3] - b[1], 0.0)


def _overlap(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix * iy


def _dedupe_pictures(regions: list[dict]) -> list[dict]:
    """PP-DocLayout often reports one figure as both `image` and `chart`; keep the best."""
    kept: list[dict] = []
    for r in sorted(regions, key=lambda r: -r["score"]):
        if r["type"] == PICTURE and any(
            k["type"] == PICTURE
            and _overlap(k["bbox"], r["bbox"]) > 0.8 * min(_area(k["bbox"]), _area(r["bbox"]))
            for k in kept
        ):
            continue
        kept.append(r)
    return kept


def _contains(bbox, x: float, y: float) -> bool:
    return bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]


def _line_key(ln: dict):
    return (ln["bbox"][1], ln["bbox"][0])


def _line_box(ln: dict, order: int) -> BoxResult:
    x0, y0, x1, y1 = ln["bbox"]
    conf = ln["confidence"]
    return BoxResult(
        text=ln["text"], x0=x0, y0=y0, x1=x1, y1=y1,
        confidence=conf * 100 if conf is not None else None,
        reading_order=order,
    )


def merge_layout(lines: list[dict], layout_boxes: list[dict], image: Image.Image) -> list[BoxResult]:
    regions = []
    for lb in layout_boxes:
        rtype = _REGION_TYPES.get(lb["label"])
        if rtype is None:
            continue
        regions.append({
            "type": rtype,
            "score": float(lb["score"]),
            "bbox": tuple(float(v) for v in lb["coordinate"]),
        })
    regions = _dedupe_pictures(regions)

    owned: dict[int, list[dict]] = {i: [] for i in range(len(regions))}
    leftovers: list[dict] = []
    for ln in lines:
        cx = (ln["bbox"][0] + ln["bbox"][2]) / 2
        cy = (ln["bbox"][1] + ln["bbox"][3]) / 2
        candidates = [
            i for i, r in enumerate(regions)
            if r["type"] != PICTURE and _contains(r["bbox"], cx, cy)
        ]
        if candidates:
            owned[min(candidates, key=lambda i: _area(regions[i]["bbox"]))].append(ln)
        else:
            leftovers.append(ln)

    boxes: list[BoxResult] = []
    for i in sorted(range(len(regions)), key=lambda i: (regions[i]["bbox"][1], regions[i]["bbox"][0])):
        r = regions[i]
        inside = sorted(owned[i], key=_line_key)
        if r["type"] != PICTURE and not inside:
            continue
        confs = [ln["confidence"] for ln in inside if ln["confidence"] is not None]
        x0, y0, x1, y1 = r["bbox"]
        box = BoxResult(
            text="\n".join(ln["text"] for ln in inside),
            x0=x0, y0=y0, x1=x1, y1=y1,
            confidence=sum(confs) / len(confs) * 100 if confs else None,
            reading_order=len(boxes),
            region_type=r["type"],
        )
        if r["type"] == PICTURE:
            box.image = crop_jpeg_b64(image, r["bbox"])
        boxes.append(box)

    for ln in sorted(leftovers, key=_line_key):
        boxes.append(_line_box(ln, len(boxes)))
    return boxes
```

- [ ] **Step 4: Run to see them pass**

Run: `pytest tests/adapters/test_paddle_layout.py -q`
Expected: 11 PASS

- [ ] **Step 5: Commit**

```bash
git add src/ocrhub/adapters/_paddle_layout.py tests/adapters/test_paddle_layout.py
git commit -m "Add layout merge for PaddleOCR lines and PP-DocLayout regions

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: PaddleOCR layout stage in the adapter

**Files:**
- Modify: `src/ocrhub/adapters/paddleocr_adapter.py` (whole `extract`, plus new helpers)
- Test: `tests/adapters/test_paddleocr_adapter.py` (existing tests must keep passing unchanged)

**Interfaces:**
- Consumes: `merge_layout`, `LAYOUT_MODEL`, `PICTURE` from `_paddle_layout`.
- Produces: `PaddleOcrAdapter._build_layout_model()`, `PaddleOcrAdapter.capabilities() -> list[str]` (`[]` when layout is off), module function `_layout_enabled() -> bool` (env `PADDLE_LAYOUT`, off by default; on for `1`, `true`, `yes`, `on`).

Flow: pass 1 runs OCR on every page and collects lines; the OCR engine is released; if layout is on, pass 2 loads the layout model once, predicts each page (re-decoding from the page bytes, so full-size images are not all held in memory), and releases it; then boxes are built.

- [ ] **Step 1: Write the failing tests** (append to `tests/adapters/test_paddleocr_adapter.py`)

```python
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
```

- [ ] **Step 2: Run to see them fail**

Run: `pytest tests/adapters/test_paddleocr_adapter.py -q`
Expected: the five new tests FAIL (`AttributeError: ... '_build_layout_model'` or `capabilities`); the old tests PASS.

- [ ] **Step 3: Implement** (replace the file's top-level imports and `extract`; keep `available` and `_build_engine` as they are)

Add at the top of `paddleocr_adapter.py`:

```python
import gc
import logging
import os

from ocrhub.adapters._paddle_layout import LAYOUT_MODEL, PICTURE, merge_layout

logger = logging.getLogger(__name__)

_LAYOUT_REGION_TYPES = ["Text", "Title", "Caption", "Header", "Footer", "Table", "Formula", PICTURE]


def _layout_enabled() -> bool:
    return os.environ.get("PADDLE_LAYOUT", "0").strip().lower() in ("1", "true", "yes", "on")


def _free_memory() -> None:
    gc.collect()
```

Add these methods to `PaddleOcrAdapter` (below `_build_engine`):

```python
    def capabilities(self) -> list[str]:
        return list(_LAYOUT_REGION_TYPES) if _layout_enabled() else []

    def _build_layout_model(self):
        from paddleocr import LayoutDetection

        return LayoutDetection(model_name=LAYOUT_MODEL)

    def _detect_layouts(self, page_images: list[bytes]) -> list[list[dict]] | None:
        """Layout boxes per page, or None if the layout stage failed (OCR lines are kept)."""
        import numpy as np

        model = None
        try:
            model = self._build_layout_model()
            layouts = []
            for page_bytes in page_images:
                img = Image.open(io.BytesIO(page_bytes)).convert("RGB")
                [res] = model.predict(np.array(img))
                layouts.append(list(res["boxes"]))
            return layouts
        except Exception:  # noqa: BLE001 - good OCR lines must survive a layout failure
            logger.warning("PaddleOCR layout stage failed; returning plain lines", exc_info=True)
            return None
        finally:
            del model
            _free_memory()
```

Replace `extract` with:

```python
    def extract(self, file_bytes: bytes, filename: str) -> OcrResult:
        import numpy as np

        start = time.monotonic()

        if is_pdf(filename):
            page_images = rasterize_pdf(file_bytes)
        else:
            page_images = [file_bytes]

        # Pass 1: text lines for every page, then release the OCR models so the
        # layout model never shares memory with them.
        engine = self._build_engine()
        page_lines: list[list[dict]] = []
        for page_bytes in page_images:
            img = Image.open(io.BytesIO(page_bytes)).convert("RGB")
            # predict() returns one result per input image; its parallel lists
            # (empty for a textless page) hold the recognised lines.
            [page_result] = engine.predict(np.array(img))
            lines = []
            for text, score, polygon in zip(
                page_result["rec_texts"], page_result["rec_scores"], page_result["rec_polys"]
            ):
                xs = [pt[0] for pt in polygon]
                ys = [pt[1] for pt in polygon]
                lines.append({
                    "text": text,
                    "confidence": float(score),
                    "bbox": (float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))),
                })
            page_lines.append(lines)
        del engine
        _free_memory()

        # Pass 2 (optional): layout regions for every page.
        layouts = self._detect_layouts(page_images) if _layout_enabled() else None

        pages: list[PageResult] = []
        for i, (page_bytes, lines) in enumerate(zip(page_images, page_lines), start=1):
            img = Image.open(io.BytesIO(page_bytes)).convert("RGB")
            confidences = [ln["confidence"] for ln in lines]

            if layouts is not None:
                boxes = merge_layout(lines, layouts[i - 1], img)
                text = "\n".join(b.text for b in boxes if b.text)
            else:
                boxes = [
                    BoxResult(
                        text=ln["text"],
                        x0=ln["bbox"][0], y0=ln["bbox"][1], x1=ln["bbox"][2], y1=ln["bbox"][3],
                        confidence=ln["confidence"] * 100,
                        reading_order=order,
                    )
                    for order, ln in enumerate(lines)
                ]
                text = "\n".join(ln["text"] for ln in lines)
            confidence = sum(confidences) / len(confidences) if confidences else None

            png_buf = io.BytesIO()
            img.save(png_buf, format="PNG")
            image_base64 = base64.b64encode(png_buf.getvalue()).decode("ascii")

            pages.append(
                PageResult(
                    page_number=i,
                    text=text,
                    confidence=confidence,
                    boxes=boxes,
                    image_base64=image_base64,
                )
            )

        elapsed_ms = int((time.monotonic() - start) * 1000)
        full_text = "\n".join(p.text for p in pages)
        page_confidences = [p.confidence for p in pages if p.confidence is not None]
        overall_confidence = sum(page_confidences) / len(page_confidences) if page_confidences else None
        return OcrResult(
            engine=self.name,
            text=full_text,
            pages=pages,
            confidence=overall_confidence,
            elapsed_ms=elapsed_ms,
        )
```

- [ ] **Step 4: Run to see them pass**

Run: `pytest tests/adapters/test_paddleocr_adapter.py tests/adapters/test_paddle_layout.py -q`
Expected: all PASS (the old tests prove layout-off output is unchanged)

- [ ] **Step 5: Commit**

```bash
git add src/ocrhub/adapters/paddleocr_adapter.py tests/adapters/test_paddleocr_adapter.py
git commit -m "PaddleOCR: optional PP-DocLayout stage behind PADDLE_LAYOUT

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Capabilities in `/engines` and the dashboard note

**Files:**
- Modify: `src/ocrhub/adapters/base.py`, `registry.py`, `api.py`, and `surya_adapter.py`, `datalab_adapter.py`, `pdfplumber_adapter.py`, `tesseract_adapter.py` (add `capabilities()`)
- Modify: `src/ocrhub/web/static/app.js`, `src/ocrhub/web/static/dashboard.css`
- Test: `tests/test_registry.py`, `tests/test_api.py`, `tests/test_web.py`

**Interfaces:**
- Produces: `OcrAdapter.capabilities() -> list[str]` (optional; a missing method means `[]`); `EngineRegistry.capabilities() -> dict[str, list[str]]` for available engines; `GET /engines` returns `{"engines": [...], "capabilities": {name: [...]}}`; JS `state.capabilities` and `capabilityNote(name)`.
- Capability lists: pdfplumber `["Text", "Table", "Picture"]`; Tesseract `[]`; Datalab `["Text", "Title", "Table", "Caption", "Header", "Footer", "Picture"]`; Surya `["Text", "Title", "Header", "Footer", "Table", "Picture"]` when `SURYA_LAYOUT` is on, else `[]`; PaddleOCR from Task 3.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_registry.py`:

```python
def test_capabilities_reports_available_engines_and_defaults_to_empty():
    class WithCaps:
        name = "a"
        def available(self): return True
        def capabilities(self): return ["Picture"]

    class NoCaps:
        name = "b"
        def available(self): return True

    class Unavailable:
        name = "c"
        def available(self): return False
        def capabilities(self): return ["Picture"]

    registry = EngineRegistry()
    for adapter in (WithCaps(), NoCaps(), Unavailable()):
        registry.register(adapter)
    assert registry.capabilities() == {"a": ["Picture"], "b": []}
```

(add `from ocrhub.registry import EngineRegistry` at the top of the file if it is not already imported.)

In `tests/test_api.py`, change the assertion in `test_engines_lists_available_only` from `{"engines": ["stub"]}` to:

```python
    assert resp.json() == {"engines": ["stub"], "capabilities": {"stub": []}}
```

and add a test for the real adapters:

```python
def test_real_adapter_capabilities():
    from ocrhub.adapters.pdfplumber_adapter import PdfplumberAdapter
    from ocrhub.adapters.tesseract_adapter import TesseractAdapter
    from ocrhub.adapters.datalab_adapter import DatalabAdapter

    assert "Picture" in PdfplumberAdapter().capabilities()
    assert TesseractAdapter().capabilities() == []
    assert "Picture" in DatalabAdapter().capabilities()


def test_surya_capabilities_follow_surya_layout(monkeypatch):
    from ocrhub.adapters.surya_adapter import SuryaAdapter

    monkeypatch.setenv("SURYA_LAYOUT", "0")
    assert SuryaAdapter().capabilities() == []
    monkeypatch.setenv("SURYA_LAYOUT", "1")
    assert "Picture" in SuryaAdapter().capabilities()
```

Append to `tests/test_web.py`:

```python
def test_app_js_has_capability_note(tmp_path):
    client = TestClient(create_app(build_registry(), ResultStore(tmp_path)))
    js = client.get("/static/app.js").text
    assert "capabilityNote" in js
    assert "No figure detection" in js
```

- [ ] **Step 2: Run to see them fail**

Run: `pytest tests/test_registry.py tests/test_api.py tests/test_web.py -q`
Expected: new tests FAIL (`AttributeError` / `KeyError` / missing strings).

- [ ] **Step 3: Implement the backend**

`base.py`: add to the `OcrAdapter` protocol:

```python
    def capabilities(self) -> list[str]:
        """Region types this engine can return (for example "Picture"). Optional: a
        missing method means the engine returns text lines only."""
        ...
```

`registry.py`: add

```python
    def capabilities(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for name in self.available_engines():
            method = getattr(self._adapters[name], "capabilities", None)
            try:
                result[name] = list(method()) if method else []
            except Exception:  # noqa: BLE001 - one adapter must not break /engines
                result[name] = []
        return result
```

`api.py`: replace the `/engines` return with

```python
        return {"engines": registry.available_engines(), "capabilities": registry.capabilities()}
```

Adapters, each as a method of the adapter class:

```python
# pdfplumber_adapter.py
    def capabilities(self) -> list[str]:
        return ["Text", "Table", "Picture"]

# tesseract_adapter.py
    def capabilities(self) -> list[str]:
        return []

# datalab_adapter.py
    def capabilities(self) -> list[str]:
        return ["Text", "Title", "Table", "Caption", "Header", "Footer", "Picture"]

# surya_adapter.py
    def capabilities(self) -> list[str]:
        return ["Text", "Title", "Header", "Footer", "Table", "Picture"] if _layout_enabled() else []
```

- [ ] **Step 4: Implement the dashboard**

`app.js`: add `capabilities: {},` to the `state` object. In `loadEngines()` add `state.capabilities = data.capabilities || {};` after `state.engines = data.engines;`. Add the helper above `renderPanel`:

```javascript
// Engines that cannot return pictures say so, so a blank figure area is not
// mistaken for "nothing there". Driven by /engines, not by the current page.
function capabilityNote(name) {
  const caps = state.capabilities[name];
  if (!caps || caps.includes("Picture")) return null;
  const note = document.createElement("div");
  note.className = "capability-note";
  note.textContent = "No figure detection";
  return note;
}
```

In `renderPanel`, append the note after each successful header is added. In the `isTextOnly(result)` branch and in the final branch, insert immediately after `panel.appendChild(header);`:

```javascript
  const capNote = capabilityNote(name);
  if (capNote) panel.appendChild(capNote);
```

(two insertions: one in the text-only branch, one before `panel.appendChild(renderPageWithBoxes(page, name));`.)

`dashboard.css`, next to `.panel-note`:

```css
.capability-note {
  padding: 4px 14px;
  font-size: 12px;
  color: var(--muted-2);
  border-bottom: 1px solid var(--border, rgba(0, 0, 0, 0.08));
}
```

(If `--border` is not defined in the stylesheet, `grep -n "^\s*--" src/ocrhub/web/static/dashboard.css` and use the variable the other panel borders use.)

- [ ] **Step 5: Run the full suite, then commit**

Run: `pytest -q`
Expected: all PASS

```bash
git add src tests
git commit -m "Report engine capabilities and label engines without figure detection

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Config, docs and real-container verification

**Files:**
- Modify: `docker-compose.yml`, `.env.example`, `README.md`, `CHANGELOG.md`, `docs/visualisations.md`

- [ ] **Step 1: Wire the env var**

`docker-compose.yml`, in `environment`:

```yaml
      # PaddleOCR layout regions (figures, tables, titles) via PP-DocLayout-S.
      # Off by default: adds one small model download and a little time.
      - PADDLE_LAYOUT=${PADDLE_LAYOUT:-0}
```

`.env.example`, after the Surya layout lines:

```
# PaddleOCR can also run a layout model (PP-DocLayout-S) after text recognition,
# giving typed regions and figure crops. Set to 1 to turn it on.
# PADDLE_LAYOUT=0
```

- [ ] **Step 2: Rebuild and run the real files**

```bash
ENGINES=paddleocr,datalab PADDLE_LAYOUT=1 docker compose up -d --build
sleep 15 && curl -s localhost:8000/engines
```

Expected: `capabilities.paddleocr` contains `"Picture"`; `tesseract` is `[]`.

Run the 4-page test PDF and the user's graphics PDF in the dashboard with **refresh** on (cached results hide the new behaviour). Confirm and record:
- the page-4 graphic of `OCR Test Document.pdf` appears as a Picture box in the PaddleOCR panel and the table lines are inside a Table region;
- the RiseGuide cover is reported sensibly (an illustration is a Picture; title, subtitle and tagline are Text/Title regions);
- Tesseract's panel shows "No figure detection" and PaddleOCR's does not;
- elapsed time and peak memory with layout off versus on (`docker stats --no-stream` while a file runs);
- run once with `PADDLE_LAYOUT=0` and confirm output is the old line boxes.

If any of this fails, stop and report; do not paper over it in docs.

- [ ] **Step 3: Docs**

- `docs/visualisations.md`, PaddleOCR section: replace "and nothing else: no layout regions, no tables, no pictures" with the layout-on/off behaviour; document label mapping, that tables are regions with lines inside (no cell grid), the top-to-bottom reading order (the layout model gives none), that lines inside a figure stay as separate line boxes, that a layout failure is logged and plain lines are returned, and the measured time and memory from Step 2 and what was checked.
- `README.md`: add `PADDLE_LAYOUT` next to the `SURYA_LAYOUT` note (around line 185) and a short capability note.
- `CHANGELOG.md`, under Unreleased: `PaddleOCR layout regions and figure crops with PADDLE_LAYOUT=1 (PP-DocLayout-S); /engines reports capabilities; dashboard labels engines without figure detection. Re-run with refresh=true after upgrading: cached results keep the old output.`

- [ ] **Step 4: Final checks and commit**

Run: `pytest -q`
Expected: all PASS

```bash
git add docker-compose.yml .env.example README.md CHANGELOG.md docs/visualisations.md
git commit -m "Document PADDLE_LAYOUT and wire it through compose

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

## Self-Review against the spec

- Layout stage, env var, one-model-at-a-time, merge rules, Picture crop, plain-line fallback, off-by-default: Tasks 2, 3 and 5.
- `/engines` capabilities and the dashboard note: Task 4.
- Tests with mocks plus real-container checks: Tasks 2 to 5.
- Docs and changelog: Task 5.
- Spec deviations the user must know about: (1) the spec says a layout failure should "surface a warning", but `OcrResult` has no warning field and the spec forbids changing `models.py`, so the failure is logged only; (2) the layout model gives no reading order, so regions are ordered top-to-bottom then left-to-right, which will misorder multi-column pages.
