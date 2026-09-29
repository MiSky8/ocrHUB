# Compare Engines Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the Surya and PaddleOCR adapters to emit word/line-level bounding boxes and a page image (matching what `TesseractAdapter` already does), then replace ocrHub's minimal web UI with a "Compare engines" dashboard that shows up to 3 engines' box-annotated output side by side or overlaid, with a sortable per-engine detections table.

**Architecture:** Backend: `BoxResult`/`PageResult` (`src/ocrhub/models.py`) already have every field this needs (`boxes`, `image_base64`, `reading_order`, `region_type`) — no model changes. Two adapters gain box/image extraction using the exact same shape `TesseractAdapter` already produces. Frontend: the current single-engine vanilla-JS box overlay (`web/templates/index.html` + `web/static/app.js`) is replaced wholesale with a new dashboard, still vanilla JS/CSS (no framework), built against a Claude-Design mockup whose exact colors/fonts/spacing are specified inline in each task below.

**Tech Stack:** Python 3.11, FastAPI, pytest, vanilla JS/CSS (no frontend framework), surya-ocr==0.14.7, paddleocr==2.7.3.

**Spec:** `docs/superpowers/specs/2026-09-28-ocrhub-design.md` (original v1 spec — explicitly excludes EasyOCR and mandates "lightweight server-rendered/vanilla JS — no heavy frontend framework"). This plan has no separate design doc; the design was worked out in conversation and is fully specified in this plan's tasks, including exact mockup values pulled from `/Users/ali/Downloads/Compare engines-html/Main.dc.html`.

## Global Constraints

- No frontend framework — vanilla JS/CSS only (per spec).
- `EasyOCR` is out of v1 scope — do not add it anywhere, including the dashboard's engine list.
- The dashboard's comparison view shows **at most 3 engines at once** (side-by-side or overlay); this cap applies only to how many are *displayed together*, never to how many can be *run* via `/ocr` (unlimited, unchanged).
- If an engine doesn't produce a `reading_order` for a box, leave it `None` — never fabricate one. The dashboard's "Order numbers" and "Reading path" UI must render nothing for a box whose `reading_order` is `None`, not an error or a placeholder number.
- `BoxResult.confidence` is normalized to a 0–100 scale for every engine that sets it (new requirement — see Task 1/2 for exactly how). `OcrResult.confidence` / `PageResult.confidence` (the pre-existing page-level aggregate) keep their current per-engine scale (0–1 for Surya/PaddleOCR, unset for Tesseract) — do **not** change those, existing tests assert exact values on the 0–1 scale (`tests/adapters/test_surya_adapter.py::test_extract_uses_recognition_predictor` asserts `0.95`; `tests/adapters/test_paddleocr_adapter.py::test_extract_parses_paddleocr_result_format` asserts `0.88`).
- Every task's implementation must be verified against real behavior, not just mocked unit tests: adapter tasks verify against a real Docker image with the real library installed (`ocrhub-full:latest` already exists locally from earlier work, or rebuild via `docker build --build-arg ENGINES=surya,paddleocr,tesseract -t ocrhub-full .`); dashboard tasks verify in a real browser via the `claude-in-chrome` tools against a real running server, not just by reading the code.

---

## Task 1: Surya adapter emits boxes + page image

**Files:**
- Modify: `src/ocrhub/adapters/surya_adapter.py`
- Test: `tests/adapters/test_surya_adapter.py`

**Interfaces:**
- Consumes: `ocrhub.models.BoxResult(text, x0, y0, x1, y1, confidence=None, reading_order=None, region_type=None)`, `ocrhub.models.PageResult(page_number, text, confidence=None, boxes=[], image_base64=None)` — both already exist, unchanged.
- Produces: `SuryaAdapter.extract()` now returns `PageResult`s with `boxes` populated (one `BoxResult` per `TextLine`) and `image_base64` set (base64-encoded PNG of the exact page image passed to the recognition predictor).

Surya's `TextLine` (verified against the real installed `surya-ocr==0.14.7` package, class `surya.recognition.schema.TextLine`) has:
- `.text: str`
- `.confidence: float | None` — 0–1 scale (or `None`)
- `.bbox` — a `@computed_field @property` returning `[x0, y0, x1, y1]` as `List[float]`, computed as `[min(xs), min(ys), max(xs), max(ys)]` from `.polygon`. Use `.bbox` directly — don't recompute it from `.polygon` yourself.

There is no reading-order field on `TextLine` — leave `BoxResult.reading_order=None` for every Surya box, per the Global Constraints rule (don't fabricate one from list position).

- [ ] **Step 1: Write the failing test**

Add to `tests/adapters/test_surya_adapter.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/test_surya_adapter.py::test_extract_returns_boxes_and_page_image -v`
Expected: FAIL — `AttributeError` or `assert [] == 1` (boxes not populated yet), since `MagicMock(text=..., confidence=..., bbox=...)` will succeed as a mock but the current `extract()` never reads `.bbox` or builds `BoxResult`s.

- [ ] **Step 3: Implement**

Replace `src/ocrhub/adapters/surya_adapter.py` in full:

```python
import base64
import io
import time

from PIL import Image

from ocrhub.models import BoxResult, OcrResult, PageResult
from ocrhub.pdf_utils import is_pdf, rasterize_pdf


class SuryaAdapter:
    name = "surya"

    def available(self) -> bool:
        try:
            import surya.detection  # noqa: F401
            import surya.recognition  # noqa: F401
        except ImportError:
            return False
        return True

    @property
    def _recognition_predictor_cls(self):
        from surya.recognition import RecognitionPredictor

        return RecognitionPredictor

    @property
    def _detection_predictor_cls(self):
        from surya.detection import DetectionPredictor

        return DetectionPredictor

    def extract(self, file_bytes: bytes, filename: str) -> OcrResult:
        start = time.monotonic()

        if is_pdf(filename):
            page_images = rasterize_pdf(file_bytes)
        else:
            page_images = [file_bytes]

        recognition_predictor = self._recognition_predictor_cls()
        detection_predictor = self._detection_predictor_cls()

        pages: list[PageResult] = []
        for i, page_bytes in enumerate(page_images, start=1):
            img = Image.open(io.BytesIO(page_bytes))
            [prediction] = recognition_predictor([img], det_predictor=detection_predictor)

            boxes: list[BoxResult] = []
            for line in prediction.text_lines:
                x0, y0, x1, y1 = line.bbox
                boxes.append(
                    BoxResult(
                        text=line.text,
                        x0=float(x0),
                        y0=float(y0),
                        x1=float(x1),
                        y1=float(y1),
                        confidence=line.confidence * 100 if line.confidence is not None else None,
                    )
                )

            text = "\n".join(line.text for line in prediction.text_lines)
            confidences = [line.confidence for line in prediction.text_lines if line.confidence is not None]
            page_confidence = sum(confidences) / len(confidences) if confidences else None

            png_buf = io.BytesIO()
            img.convert("RGB").save(png_buf, format="PNG")
            image_base64 = base64.b64encode(png_buf.getvalue()).decode("ascii")

            pages.append(
                PageResult(
                    page_number=i,
                    text=text,
                    confidence=page_confidence,
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

Note `page_confidence`/`overall_confidence` (the pre-existing `PageResult.confidence`/`OcrResult.confidence` fields) are computed from `line.confidence` directly (0–1 scale, unchanged) — only the new `BoxResult.confidence` is multiplied by 100. This is what keeps the existing `test_extract_uses_recognition_predictor` test (which asserts `result.pages[0].confidence == pytest.approx(0.95)`) passing unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/adapters/test_surya_adapter.py -v`
Expected: both `test_extract_uses_recognition_predictor` (pre-existing, still 0–1 scale) and the new `test_extract_returns_boxes_and_page_image` PASS.

- [ ] **Step 5: Verify against the real library in Docker**

The mocked test proves the parsing logic; this step proves the real `surya-ocr==0.14.7` API actually matches what was mocked (`.bbox` returning `[x0,y0,x1,y1]` was confirmed by inspecting the installed package's source directly — `docker run --rm ocrhub-full:latest python -c "from surya.recognition.schema import PolygonBox; import inspect; print(inspect.getsource(PolygonBox.bbox.fget))"` — but the adapter itself needs a real end-to-end run too):

```bash
docker build --build-arg ENGINES=surya -t ocrhub-surya-test .
docker run --rm -p 8002:8000 ocrhub-surya-test &
sleep 5
curl -s -F "file=@tests/fixtures/datalab_sample.json" -F "engines=surya" http://localhost:8002/ocr  # will fail — use a real image instead, e.g. any PNG/JPG on disk
```

Use a real image file (not the Datalab JSON fixture, which isn't an image) — generate one the same way earlier verification in this project did:

```bash
python3 -c "
from PIL import Image, ImageDraw, ImageFont
img = Image.new('RGB', (500,120), color='white')
d = ImageDraw.Draw(img)
try:
    font = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', 32)
except Exception:
    font = ImageFont.load_default(size=32)
d.text((10,40), 'SURYA BOX TEST', fill='black', font=font)
img.save('/tmp/surya_test.png')
"
curl -s -F "file=@/tmp/surya_test.png" -F "engines=surya" http://localhost:8002/ocr | python3 -m json.tool
```

Expected: the response's `results[0].pages[0].boxes` is a non-empty list of objects with real `x0/y0/x1/y1/text/confidence` values (confidence in the 0–100 range), and `image_base64` is a long non-empty string. Stop the container (`docker stop $(docker ps -q --filter ancestor=ocrhub-surya-test)`) once confirmed.

- [ ] **Step 6: Commit**

```bash
git add src/ocrhub/adapters/surya_adapter.py tests/adapters/test_surya_adapter.py
git commit -m "feat: Surya adapter emits word boxes and page image"
```

---

## Task 2: PaddleOCR adapter emits boxes + page image

**Files:**
- Modify: `src/ocrhub/adapters/paddleocr_adapter.py`
- Test: `tests/adapters/test_paddleocr_adapter.py`

**Interfaces:**
- Consumes: same `BoxResult`/`PageResult` as Task 1.
- Produces: `PaddleOcrAdapter.extract()` now returns `PageResult`s with `boxes` populated (one `BoxResult` per detected line) and `image_base64` set.

PaddleOCR's `.ocr()` (pinned `paddleocr==2.7.3`) returns, per image, a list containing one list of `[box, (text, confidence)]` entries (already partially used by the existing adapter — `entry[1][0]` is text, `entry[1][1]` is confidence 0–1 float). `entry[0]` (currently unused) is the box: a 4-point polygon `[[x1,y1],[x2,y2],[x3,y3],[x4,y4]]` — confirmed by the existing test fixture at `tests/adapters/test_paddleocr_adapter.py:17` (`fake_result = [[[[[0, 0], [1, 0], [1, 1], [0, 1]], ("OCRHUB TEST", 0.88)]]]`). Convert to an axis-aligned box via min/max over the 4 points. No native reading-order field — leave `reading_order=None`.

- [ ] **Step 1: Write the failing test**

Add to `tests/adapters/test_paddleocr_adapter.py`:

```python
def test_extract_returns_boxes_and_page_image(sample_image_bytes):
    adapter = PaddleOcrAdapter()

    fake_result = [[[[[10, 20], [110, 20], [110, 50], [10, 50]], ("OCRHUB TEST", 0.88)]]]
    fake_engine = MagicMock()
    fake_engine.ocr.return_value = fake_result

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
    assert box.reading_order is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/test_paddleocr_adapter.py::test_extract_returns_boxes_and_page_image -v`
Expected: FAIL — `assert [] == 1` (no `BoxResult`s built yet).

- [ ] **Step 3: Implement**

Replace `src/ocrhub/adapters/paddleocr_adapter.py` in full:

```python
import base64
import io
import time

from PIL import Image

from ocrhub.models import BoxResult, OcrResult, PageResult
from ocrhub.pdf_utils import is_pdf, rasterize_pdf


class PaddleOcrAdapter:
    name = "paddleocr"

    def available(self) -> bool:
        try:
            import paddleocr  # noqa: F401
        except ImportError:
            return False
        return True

    def _build_engine(self):
        from paddleocr import PaddleOCR

        return PaddleOCR(use_angle_cls=True, lang="en", show_log=False)

    def extract(self, file_bytes: bytes, filename: str) -> OcrResult:
        import numpy as np

        start = time.monotonic()

        if is_pdf(filename):
            page_images = rasterize_pdf(file_bytes)
        else:
            page_images = [file_bytes]

        engine = self._build_engine()

        pages: list[PageResult] = []
        for i, page_bytes in enumerate(page_images, start=1):
            img = Image.open(io.BytesIO(page_bytes)).convert("RGB")
            [lines] = engine.ocr(np.array(img), cls=True)
            # PaddleOCR returns [None] (a single None entry, not an empty
            # list) for a blank/textless page rather than [].
            lines = lines or []

            boxes: list[BoxResult] = []
            for entry in lines:
                polygon, (text, confidence) = entry
                xs = [pt[0] for pt in polygon]
                ys = [pt[1] for pt in polygon]
                boxes.append(
                    BoxResult(
                        text=text,
                        x0=float(min(xs)),
                        y0=float(min(ys)),
                        x1=float(max(xs)),
                        y1=float(max(ys)),
                        confidence=confidence * 100,
                    )
                )

            texts = [entry[1][0] for entry in lines]
            confidences = [entry[1][1] for entry in lines]
            text = "\n".join(texts)
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

Same rule as Task 1: `page.confidence`/`overall_confidence` stay on the 0–1 scale (unchanged, keeps `test_extract_parses_paddleocr_result_format`'s `pytest.approx(0.88)` assertion passing) — only `BoxResult.confidence` is `* 100`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/adapters/test_paddleocr_adapter.py -v`
Expected: all 4 tests PASS (2 pre-existing + `test_extract_returns_boxes_and_page_image`; `test_extract_handles_blank_page_none_result` must still pass with `page.boxes == []` for the `[None]` blank-page case — verify this explicitly since `lines = lines or []` means the boxes loop simply doesn't execute).

- [ ] **Step 5: Verify against the real library in Docker**

The real `paddleocr==2.7.3` package could not be exercised directly in this planning session (`docker run --rm ocrhub-full:latest python -c "import paddleocr"` failed with `zlib.error: Error -2 while decompressing data: inconsistent stream state` inside `pyclipper`, a pre-existing native-extension issue unrelated to this change — investigate if it blocks this step; it may require rebuilding `ocrhub-full` fresh rather than reusing the stale image). Once a working container is available:

```bash
docker build --build-arg ENGINES=paddleocr -t ocrhub-paddle-test .
docker run --rm -p 8003:8000 ocrhub-paddle-test &
sleep 5
curl -s -F "file=@/tmp/surya_test.png" -F "engines=paddleocr" http://localhost:8003/ocr | python3 -m json.tool
```

(Reuse `/tmp/surya_test.png` from Task 1 Step 5, or regenerate it — same snippet.)

Expected: `results[0].pages[0].boxes` is a non-empty list with real coordinates and confidence in the 0–100 range; `image_base64` is present. If PaddleOCR still segfaults or fails to import on this machine's architecture (a known risk flagged in `pyproject.toml`'s comments on the `paddleocr` extra), note that clearly rather than silently marking this step done — the mocked unit test still proves the parsing logic is correct even if the live run can't be exercised on this hardware.

- [ ] **Step 6: Commit**

```bash
git add src/ocrhub/adapters/paddleocr_adapter.py tests/adapters/test_paddleocr_adapter.py
git commit -m "feat: PaddleOCR adapter emits line boxes and page image"
```

---

## Task 3: Dashboard shell — layout, sidebar, engine list, upload

**Files:**
- Modify: `src/ocrhub/web/templates/index.html` (full rewrite)
- Create: `src/ocrhub/web/static/dashboard.css`
- Modify: `src/ocrhub/web/static/app.js` (full rewrite, starting with just engine-list + upload wiring; comparison rendering comes in Task 4)
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `GET /engines` (existing, returns `{"engines": [str, ...]}`), `POST /ocr` (existing, `file` + repeated `engines` form fields + optional `refresh`).
- Produces: a page with `id="engine-list"` (existing test `tests/test_web.py::test_index_page_loads` asserts this exact selector still exists — preserve it) and a new `id="run-all-btn"` button, `id="file-input"` file input, `id="results-grid"` container for Task 4 to render into.

All values below are copied verbatim from `/Users/ali/Downloads/Compare engines-html/Main.dc.html` (the approved Claude-Design mockup).

**Design tokens (put these in `dashboard.css` as CSS custom properties on `:root`):**

```css
:root {
  --bg: #f4f2ee;
  --text: #1c1b19;
  --sidebar-bg: #ebe8e1;
  --sidebar-border: #d6d1c6;
  --muted: #5b574f;
  --muted-2: #4a463f;
  --border: #d6d1c6;
  --border-light: #e2ded5;
  --card-bg: #ffffff;
  --input-bg: #fbfaf7;
  --input-border: #a7a195;
  --swatch-bg: #fefdfb;
  --swatch-border: #b9b4a8;
  --dark-bg: #1c1b19;
  --dark-fg: #faf9f5;
  --toggle-track: #e2ded5;
  --divider: #cfcac0;
  --success: #2f7d4f;
  --row-alt: #faf9f6;
  --warn: #b04a06;
}
body {
  margin: 0;
  font-family: 'IBM Plex Sans', system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
}
.mono { font-family: 'IBM Plex Mono', monospace; }
button { font-family: inherit; cursor: pointer; }
button:focus-visible { outline: 2px solid var(--text); outline-offset: 2px; }
```

Load the same Google Fonts the mockup uses, in `index.html`'s `<head>`:

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<link rel="stylesheet" href="/static/dashboard.css">
```

**Layout (translate the mockup's inline styles into `dashboard.css` classes — don't inline-style the HTML, use classes so Task 4/5/6 can extend them cleanly):**

- `.app-shell`: `display: flex; height: 100vh; overflow: hidden;`
- `.sidebar`: `width: 272px; flex-shrink: 0; box-sizing: border-box; padding: 24px 20px; display: flex; flex-direction: column; gap: 28px; background: var(--sidebar-bg); border-right: 1px solid var(--sidebar-border); overflow-y: auto;`
- `.sidebar-brand`: `display: flex; align-items: center; gap: 10px;` containing a 28×28px `border-radius: 7px; background: var(--dark-bg);` logo box and `ocrHub` text at `font-size: 18px; font-weight: 600; letter-spacing: -0.01em;`
- `.sidebar-section`: `display: flex; flex-direction: column; gap: 10px;`
- `.sidebar-label`: `font-size: 11px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted);`
- `.upload-dropzone`: `display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 18px 12px; border: 1.5px dashed var(--input-border); border-radius: 10px; background: transparent; color: #3a3733; font-size: 13px; line-height: 1.4; text-align: center; width: 100%; box-sizing: border-box;`
- `.file-chip`: `display: flex; align-items: center; gap: 10px; padding: 10px 12px; background: var(--input-bg); border: 1px solid var(--border); border-radius: 8px;`
- `.engine-row`: `display: flex; align-items: center; gap: 6px; padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--input-bg); box-sizing: border-box;` (plain container `<div>` — holds `.engine-select-btn` and, once Task 4 adds it, a `.compare-toggle-btn`)
- `.engine-select-btn`: `display: flex; align-items: center; gap: 12px; flex-grow: 1; min-width: 0; border: 0; background: transparent; color: var(--text); text-align: left; padding: 0;`
- `.engine-checkbox`: `width: 18px; height: 18px; box-sizing: border-box; flex-shrink: 0; border-radius: 4px; border: 1.5px solid var(--_engine-color, #999); display: flex; align-items: center; justify-content: center;` — set `--_engine-color` inline per row from a JS-assigned engine color (see Task 4's `ENGINE_COLORS` map).
- `.main`: `flex-grow: 1; min-width: 0; box-sizing: border-box; padding: 24px 28px; display: flex; flex-direction: column; gap: 16px; overflow-y: auto;`
- `.main-header`: `display: flex; align-items: center; gap: 16px;` with an `<h1>` at `font-size: 24px; font-weight: 600; letter-spacing: -0.015em; margin: 0;` reading "Compare engines"
- `.run-all-btn`: `display: flex; align-items: center; gap: 8px; padding: 10px 16px; border: 0; border-radius: 8px; background: var(--dark-bg); color: var(--dark-fg); font-size: 14px; font-weight: 500;`

**Markup structure for `index.html`:**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>ocrHub</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
  <link rel="stylesheet" href="/static/dashboard.css">
</head>
<body>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="sidebar-brand">
        <div class="logo-box"></div>
        <div>ocrHub</div>
      </div>

      <div class="sidebar-section">
        <div class="sidebar-label">Input</div>
        <label class="upload-dropzone">
          <input type="file" id="file-input" style="display:none" />
          <span>Drop an image or click to upload</span>
        </label>
        <div id="file-chip" class="file-chip" hidden>
          <div class="file-thumb"></div>
          <div>
            <div id="file-name" class="mono"></div>
            <div id="file-meta"></div>
          </div>
        </div>
      </div>

      <div class="sidebar-section">
        <div class="sidebar-label">Engines</div>
        <div id="engine-list"></div>
      </div>
    </aside>

    <main class="main">
      <div class="main-header">
        <h1>Compare engines</h1>
        <div style="flex-grow:1"></div>
        <button type="button" id="run-all-btn" class="run-all-btn">Run all engines</button>
      </div>

      <div id="results-grid"></div>
    </main>
  </div>

  <script src="/static/app.js"></script>
</body>
</html>
```

**`app.js` for this task (engine list + upload only — no result rendering yet, that's Task 4):**

```javascript
const ENGINE_COLORS = {
  tesseract: "#1f5fa8",
  surya: "#b04a06",
  paddleocr: "#6b3fa0",
  datalab: "#2f7d4f",
  "ollama-deepseek": "#a7a195",
};

const state = {
  engines: [],
  selected: new Set(),
  file: null,
};

async function loadEngines() {
  const resp = await fetch("/engines");
  const data = await resp.json();
  state.engines = data.engines;
  renderEngineList();
}

function renderEngineList() {
  // NOTE: `.engine-row` is a <div>, not a <button> — Task 4 adds a second,
  // separate "Compare" <button> inside this row once that engine has a
  // result, and HTML forbids nesting <button> inside <button>. The row's
  // own select/deselect behavior lives on `.engine-select-btn` below.
  const container = document.getElementById("engine-list");
  container.innerHTML = "";
  state.engines.forEach((name) => {
    const row = document.createElement("div");
    row.className = "engine-row";

    const selectBtn = document.createElement("button");
    selectBtn.type = "button";
    selectBtn.className = "engine-select-btn";
    selectBtn.setAttribute("aria-pressed", state.selected.has(name));

    const box = document.createElement("div");
    box.className = "engine-checkbox";
    box.style.setProperty("--_engine-color", ENGINE_COLORS[name] || "#999");
    box.style.background = state.selected.has(name) ? (ENGINE_COLORS[name] || "#999") : "transparent";

    const label = document.createElement("span");
    label.textContent = name;

    selectBtn.appendChild(box);
    selectBtn.appendChild(label);
    selectBtn.addEventListener("click", () => toggleEngine(name));
    row.appendChild(selectBtn);
    container.appendChild(row);
  });
}

function toggleEngine(name) {
  if (state.selected.has(name)) {
    state.selected.delete(name);
  } else {
    state.selected.add(name);
  }
  renderEngineList();
}

function handleFileChosen(file) {
  state.file = file;
  const chip = document.getElementById("file-chip");
  const nameEl = document.getElementById("file-name");
  chip.hidden = false;
  nameEl.textContent = file.name;
}

document.addEventListener("DOMContentLoaded", () => {
  loadEngines();
  document.getElementById("file-input").addEventListener("change", (e) => {
    if (e.target.files[0]) handleFileChosen(e.target.files[0]);
  });
});
```

- [ ] **Step 1: Write the failing test**

`tests/test_web.py` already has `test_index_page_loads` asserting `'id="engine-list"'` is present — this continues to pass unchanged. Add one new test:

```python
def test_index_page_has_dashboard_elements(tmp_path):
    client = TestClient(create_app(build_registry(), ResultStore(tmp_path)))
    resp = client.get("/")

    assert resp.status_code == 200
    assert 'id="run-all-btn"' in resp.text
    assert 'id="file-input"' in resp.text
    assert 'id="results-grid"' in resp.text


def test_dashboard_css_is_served(tmp_path):
    client = TestClient(create_app(build_registry(), ResultStore(tmp_path)))
    resp = client.get("/static/dashboard.css")

    assert resp.status_code == 200
    assert "text/css" in resp.headers["content-type"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_web.py -v`
Expected: `test_index_page_has_dashboard_elements` and `test_dashboard_css_is_served` FAIL (elements/file don't exist yet); `test_index_page_loads` and `test_static_app_js_is_served` still PASS.

- [ ] **Step 3: Implement**

Write `src/ocrhub/web/static/dashboard.css`, replace `src/ocrhub/web/templates/index.html`, and replace `src/ocrhub/web/static/app.js`, exactly as specified above.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_web.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 5: Verify visually in a real browser**

Start a local dev server (reuse the pattern already used earlier in this project — a free port, not 8000 if a Docker container is already running there):

```bash
source /Users/ali/miniconda3/bin/activate ocrHub
cd /Users/ali/Code/ocrHub
python -c "
import uvicorn
from ocrhub.api import build_registry, create_app
app = create_app(build_registry())
uvicorn.run(app, host='0.0.0.0', port=8001)
" &
```

Use the `claude-in-chrome` tools (`tabs_context_mcp`, `navigate`, `computer` screenshot) to open `http://localhost:8001`, confirm the sidebar/header render with the right fonts/colors/spacing (compare against a screenshot of the original mockup at `/Users/ali/Downloads/Compare engines-html/Main.dc.html` if needed), and that clicking an engine row visually toggles its checkbox fill. Stop the server when done.

- [ ] **Step 6: Commit**

```bash
git add src/ocrhub/web/templates/index.html src/ocrhub/web/static/dashboard.css src/ocrhub/web/static/app.js tests/test_web.py
git commit -m "feat: dashboard shell — sidebar, engine list, upload"
```

---

## Task 4: Run engines, render side-by-side panels with box overlays

**Files:**
- Modify: `src/ocrhub/web/static/app.js`
- Modify: `src/ocrhub/web/static/dashboard.css`

**Interfaces:**
- Consumes: `POST /ocr` (existing) — response shape `{"results": [{"engine": str, "text": str, "ok": bool, "error": str|None, "elapsed_ms": int, "confidence": float|None, "pages": [{"page_number": int, "text": str, "confidence": float|None, "image_base64": str|None, "boxes": [{"text": str, "x0": float, "y0": float, "x1": float, "y1": float, "confidence": float|None, "reading_order": int|None, "region_type": str|None}]}]}]}`.
- Produces: `state.results` (an in-memory map of `engine name -> OcrResult`, populated after a run) and `state.compare` (a `Set` of at most 3 engine names currently shown in the comparison grid) — Task 5/6 build on both.

**Behavior:**
- Clicking "Run all engines" (or a new per-run trigger) calls `POST /ocr` once with every `state.selected` engine, then stores each result in `state.results` keyed by engine name.
- A result becomes available for comparison display once it's returned. Modify Task 3's `renderEngineList()` (defined in `src/ocrhub/web/static/app.js`, the `.engine-row` div) to append a "Compare" button — `.compare-toggle-btn` — after `.engine-select-btn`, but **only** when `state.results[name]` exists:

```javascript
// Insert into renderEngineList()'s per-engine loop, after `row.appendChild(selectBtn);`:
if (state.results[name]) {
  const compareBtn = document.createElement("button");
  compareBtn.type = "button";
  compareBtn.className = "compare-toggle-btn" + (state.compare.has(name) ? " active" : "");
  compareBtn.textContent = "Compare";
  compareBtn.addEventListener("click", (e) => { e.stopPropagation(); toggleCompare(name); });
  row.appendChild(compareBtn);
}
```

`.compare-toggle-btn` CSS: `padding: 4px 8px; border-radius: 6px; font-size: 11px; font-weight: 500; border: 1px solid var(--input-border); background: transparent; color: #3a3733; flex-shrink: 0;` — `.active`: `border-color: var(--dark-bg); background: var(--dark-bg); color: var(--dark-fg);`.

`toggleCompare(name)` (defined below) adds/removes `name` from `state.compare`. If `state.compare` already has 3 engines and a 4th is toggled on, **do not add it** — this is the "max 3 shown at once" rule from the Global Constraints. (Running stays unlimited — this cap only affects `state.compare`, never `state.selected`.) After `runAll()` populates `state.results`, it must call `renderEngineList()` again (not just `renderResultsGrid()`) so the newly-available Compare buttons actually appear — add this call explicitly in `runAll()`.
- `#results-grid` renders one panel per engine in `state.compare`, `display: grid; grid-template-columns: repeat(N, minmax(0, 1fr)); gap: 16px;` where N is `state.compare.size` (1, 2, or 3 columns).
- Each panel (`.engine-panel` — `box-sizing: border-box; padding: 12px; display: flex; flex-direction: column; gap: 10px; background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px;`) shows: a header row with the engine's colored square (10×10px, `border-radius: 3px`, `background: <engine color>`) + name at `font-size: 14px; font-weight: 600;`, and stats (`box count · confidence% · elapsed ms`) at `font-family: 'IBM Plex Mono', monospace; font-size: 11.5px; color: var(--muted-2);` — then the page image with an absolutely-positioned SVG box overlay, same technique already proven for the single-engine Tesseract view (`viewBox` set to the image's natural dimensions on load, so box coordinates need no manual scaling math).
- Box color per engine comes from `ENGINE_COLORS` (already defined in Task 3). Box style: `fill: <color>22` (hex + `22` alpha suffix), `stroke: <color>`, `stroke-width: 1.5`.
- If a box has `reading_order !== null`, render a small circular order badge at its top-left corner (`position: absolute; left: -8px; top: -8px; width: 15px; height: 15px; border-radius: 50%; background: #fff; border: 1.5px solid <engine color>; font-family: 'IBM Plex Mono', monospace; font-size: 8px; font-weight: 600; line-height: 12px; text-align: center;`, containing `reading_order`). If `reading_order === null`, don't render the badge at all for that box (Global Constraints rule).
- If an engine's `OcrResult.ok` is `false`, the panel shows the `error` text instead of an image (reuse the existing `.error` handling style from the current single-engine implementation).

- [ ] **Step 1: Manual verification plan (no automated JS test harness exists in this project — vanilla JS with no test runner configured; verification is via real browser, same as Task 3 Step 5 and as this project's Tesseract box-overlay work was verified earlier this session)**

Write down exactly what "done" looks like before implementing, so Step 4 has a concrete checklist:
- Select 2 engines with real box data (e.g. `tesseract` + `surya`, assuming Task 1/2 are done and a full Docker image is built), click Run, see both panels render side by side with correctly positioned boxes.
- Toggle a 3rd engine into compare — grid becomes 3 columns.
- Attempt a 4th — nothing changes, still 3 columns, no error thrown (check browser console).
- An engine that failed (e.g. wrong file type for `pdfplumber`) shows its error text, not a broken image.

- [ ] **Step 2: Implement**

Extend `app.js` with the run/render logic described above:

```javascript
state.results = {};
state.compare = new Set();

async function runAll() {
  if (!state.file || state.selected.size === 0) return;
  const formData = new FormData();
  formData.append("file", state.file);
  state.selected.forEach((name) => formData.append("engines", name));

  const resp = await fetch("/ocr", { method: "POST", body: formData });
  const data = await resp.json();
  data.results.forEach((r) => { state.results[r.engine] = r; });
  renderEngineList();
  renderResultsGrid();
}

function toggleCompare(name) {
  if (state.compare.has(name)) {
    state.compare.delete(name);
  } else if (state.compare.size < 3) {
    state.compare.add(name);
  }
  renderResultsGrid();
}

function renderResultsGrid() {
  const grid = document.getElementById("results-grid");
  grid.innerHTML = "";
  grid.style.display = "grid";
  grid.style.gap = "16px";
  const names = Array.from(state.compare);
  grid.style.gridTemplateColumns = `repeat(${Math.max(1, names.length)}, minmax(0, 1fr))`;

  names.forEach((name) => {
    const result = state.results[name];
    if (!result) return;
    grid.appendChild(renderPanel(name, result));
  });
}

function renderPanel(name, result) {
  const panel = document.createElement("section");
  panel.className = "engine-panel";

  const header = document.createElement("div");
  header.className = "panel-header";
  const dot = document.createElement("span");
  dot.style.cssText = `display:inline-block;width:10px;height:10px;border-radius:3px;background:${ENGINE_COLORS[name] || "#999"};margin-right:6px;`;
  const nameEl = document.createElement("span");
  nameEl.style.cssText = "font-size:14px;font-weight:600;";
  nameEl.textContent = name;
  header.appendChild(dot);
  header.appendChild(nameEl);

  if (!result.ok) {
    const err = document.createElement("pre");
    err.textContent = result.error;
    panel.appendChild(header);
    panel.appendChild(err);
    return panel;
  }

  const page = result.pages[0];
  const stats = document.createElement("div");
  stats.className = "panel-stats mono";
  const conf = page.confidence != null ? Math.round(page.confidence <= 1 ? page.confidence * 100 : page.confidence) + "%" : "–";
  stats.textContent = `${page.boxes.length} boxes · ${conf} conf · ${result.elapsed_ms} ms`;
  header.appendChild(stats);
  panel.appendChild(header);

  panel.appendChild(renderPageWithBoxes(page, name));
  return panel;
}

function renderPageWithBoxes(page, engineName) {
  const wrap = document.createElement("div");
  wrap.className = "page-image-wrap";
  if (!page.image_base64) return wrap;

  const img = document.createElement("img");
  img.src = `data:image/png;base64,${page.image_base64}`;

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("box-overlay");

  img.addEventListener("load", () => {
    svg.setAttribute("viewBox", `0 0 ${img.naturalWidth} ${img.naturalHeight}`);
    drawBoxes(svg, page.boxes, ENGINE_COLORS[engineName] || "#999");
  });

  wrap.appendChild(img);
  wrap.appendChild(svg);
  return wrap;
}

function drawBoxes(svg, boxes, color) {
  if (!state.show.boxes && !state.show.text && !state.show.orderNumbers) return;
  boxes.forEach((box) => {
    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");

    if (state.show.boxes) {
      const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      rect.setAttribute("x", box.x0);
      rect.setAttribute("y", box.y0);
      rect.setAttribute("width", box.x1 - box.x0);
      rect.setAttribute("height", box.y1 - box.y0);
      rect.setAttribute("fill", color + "22");
      rect.setAttribute("stroke", color);
      rect.setAttribute("stroke-width", "1.5");
      g.appendChild(rect);
    }

    if (state.show.text) {
      const label = document.createElementNS("http://www.w3.org/2000/svg", "foreignObject");
      label.setAttribute("x", box.x0 - 1);
      label.setAttribute("y", box.y1 + 1);
      label.setAttribute("width", Math.max(box.x1 - box.x0 + 40, 20));
      label.setAttribute("height", 14);
      const div = document.createElement("div");
      div.className = "mono";
      div.style.cssText = `background:${color};color:#fff;font-size:9px;line-height:12px;padding:0 3px;display:inline-block;white-space:nowrap;`;
      div.textContent = box.text;
      label.appendChild(div);
      g.appendChild(label);
    }

    if (state.show.orderNumbers && box.reading_order !== null && box.reading_order !== undefined) {
      const badge = document.createElementNS("http://www.w3.org/2000/svg", "foreignObject");
      badge.setAttribute("x", box.x0 - 8);
      badge.setAttribute("y", box.y0 - 8);
      badge.setAttribute("width", 15);
      badge.setAttribute("height", 15);
      const div = document.createElement("div");
      div.className = "mono box-order-badge";
      div.style.borderColor = color;
      div.textContent = box.reading_order;
      badge.appendChild(div);
      g.appendChild(badge);
    }

    svg.appendChild(g);
  });
}
```

Wire `runAll` to the `#run-all-btn` click handler and initialize `state.show = { boxes: true, text: true, orderNumbers: true }` in the `DOMContentLoaded` listener (this anticipates Task 5's toggles — default them on now so Task 4 is independently testable with boxes/text/order all visible, matching the mockup's initial state).

Extend `dashboard.css` with `.engine-panel`, `.panel-header`, `.panel-stats`, `.page-image-wrap`, `.box-overlay`, `.box-order-badge` classes matching the inline-style values given in this task's prose above (translate them into classes — don't inline-style from JS beyond per-box dynamic values like color/position that must be computed at render time). `.box-order-badge` specifically: `box-sizing: border-box; width: 15px; height: 15px; border-radius: 50%; background: #ffffff; border: 1.5px solid; color: var(--text); font-size: 8px; font-weight: 600; line-height: 12px; text-align: center;` (border-color set inline per-box from JS, as shown above).

- [ ] **Step 3: Run the full pytest suite to confirm nothing broke**

Run: `pytest -q`
Expected: all existing tests still pass (this task touches no Python files, but run it anyway — cheap and catches accidental regressions from any adjacent edits).

- [ ] **Step 4: Verify in a real browser against real data**

Requires Task 1 and 2 done and a Docker image built with `ENGINES=surya` (or `surya,paddleocr` if Task 2's real-library verification succeeded) so there's real box data to look at, not just Tesseract. If Task 2 is blocked by the `pyclipper` issue noted there, verify with `tesseract` + `surya` only (2 engines) — that's still sufficient to prove the multi-panel rendering, box overlay, and 3-engine cap logic all work; PaddleOCR's panel can be verified later once Task 2's blocker is resolved.

```bash
docker build --build-arg ENGINES=surya -t ocrhub-dashboard-test .
docker run --rm -p 8004:8000 -v ocrhub-models:/home/ocrhub/.cache ocrhub-dashboard-test &
```

Use `claude-in-chrome` to open `http://localhost:8004`, upload a real test image (reuse `/tmp/surya_test.png` from Task 1), select `tesseract` + `surya`, click Run, screenshot the result, and confirm against the Step 1 checklist. Stop the container when done.

- [ ] **Step 5: Commit**

```bash
git add src/ocrhub/web/static/app.js src/ocrhub/web/static/dashboard.css
git commit -m "feat: run engines and render side-by-side box-overlay comparison"
```

---

## Task 5: Overlay mode + SHOW toggles

**Files:**
- Modify: `src/ocrhub/web/static/app.js`
- Modify: `src/ocrhub/web/static/dashboard.css`

**Interfaces:**
- Consumes: `state.compare`, `state.results` (from Task 4).
- Produces: `state.layoutMode` (`"side-by-side" | "overlay"`), `state.show` (`{boxes: bool, text: bool, orderNumbers: bool}`) — both default to `side-by-side` and `{boxes:true, text:true, orderNumbers:true}` respectively, matching the mockup's initial state (`S.boxes=true, S.text=true, S.order=true, S.path=false`). (This plan omits the mockup's "Reading path" toggle — the polyline-through-reading-order-points feature — as an explicit scope cut: it's a nice-to-have on top of order numbers, not requested by the user this session. If picked up later, `mkPath`/`showPath` in the mockup's `Main.dc.html:129-135,245` is the reference implementation.)

**Layout toolbar (add above `#results-grid`, matching the mockup's exact styling):**

```html
<div class="toolbar">
  <div class="mode-switch" role="group" aria-label="Layout">
    <button type="button" id="mode-side-by-side" class="mode-btn">Side by side</button>
    <button type="button" id="mode-overlay" class="mode-btn">Overlay</button>
  </div>
  <div class="toolbar-divider"></div>
  <div class="sidebar-label">Show</div>
  <div class="show-toggles">
    <button type="button" id="toggle-boxes" class="show-toggle">Boxes</button>
    <button type="button" id="toggle-text" class="show-toggle">Text</button>
    <button type="button" id="toggle-order" class="show-toggle">Order numbers</button>
  </div>
</div>
```

CSS (values from the mockup):
- `.toolbar`: `display: flex; align-items: center; gap: 14px; flex-wrap: wrap;`
- `.mode-switch`: `display: flex; padding: 3px; gap: 3px; background: var(--toggle-track); border-radius: 9px;`
- `.mode-btn`: `padding: 7px 14px; border: 0; border-radius: 7px; font-size: 13px; font-weight: 500; background: transparent; color: var(--text);` — when active: `background: #ffffff;`
- `.toolbar-divider`: `width: 1px; height: 24px; background: var(--divider);`
- `.show-toggles`: `display: flex; gap: 6px;`
- `.show-toggle`: `padding: 7px 14px; border-radius: 999px; font-size: 13px; font-weight: 500; border: 1px solid var(--input-border); background: transparent; color: #3a3733;` — when active: `border-color: var(--dark-bg); background: var(--dark-bg); color: var(--dark-fg);`

**Behavior:**
- `Boxes`/`Text`/`Order numbers` toggles control, respectively: whether the SVG box `<rect>`s render at all, whether each box's recognized text renders as a label (`position: absolute; left: -1px; top: 100%; margin-top: 1px; padding: 0 3px; white-space: nowrap; background: <engine color>; color: #fff; font-family: 'IBM Plex Mono', monospace; font-size: 9px; line-height: 12px;`, matching the mockup's box-label styling), and whether order badges render (still gated by `reading_order !== null` regardless of this toggle being on).
- `Side by side` (default) is exactly Task 4's grid-of-panels behavior.
- `Overlay` renders **one** panel containing all `state.compare` engines' boxes superimposed on a single shared image. **Canonical image + coordinate scaling:** use the first engine in `state.compare` (iteration order) that has a non-null `image_base64` on its first page as the canonical image. For every other engine being overlaid, if its own page's image dimensions differ from the canonical image's dimensions (compare `naturalWidth`/`naturalHeight` after both images are loaded via an offscreen `Image()` object — do not assume they match), scale that engine's box coordinates by `(canonicalWidth / thisEngineWidth, canonicalHeight / thisEngineHeight)` before rendering its boxes on the shared SVG. Since all engines here are run against the exact same uploaded file and page, dimensions will typically already match (same rasterization) — but the scaling logic must exist rather than assume equality, since a future engine could rasterize at a different DPI.

- [ ] **Step 1: Manual verification plan**

- With 3 engines in `state.compare`, click "Overlay" — grid collapses to 1 panel showing all 3 engines' boxes in their own colors on one image.
- Toggle "Boxes" off — all `<rect>`s disappear, image remains.
- Toggle "Text" off — box labels disappear, boxes (if still on) remain.
- Toggle "Order numbers" off — order badges disappear even for boxes that have a `reading_order`.
- Switch back to "Side by side" — returns to Task 4's per-engine grid, toggle states persist.

- [ ] **Step 2: Implement**

Add the toolbar markup/CSS as specified, and this JS:

```javascript
state.layoutMode = "side-by-side";

function setLayoutMode(mode) {
  state.layoutMode = mode;
  document.getElementById("mode-side-by-side").classList.toggle("active", mode === "side-by-side");
  document.getElementById("mode-overlay").classList.toggle("active", mode === "overlay");
  renderResultsGrid();
}

function toggleShow(key) {
  state.show[key] = !state.show[key];
  document.getElementById(`toggle-${key === "orderNumbers" ? "order" : key}`).classList.toggle("active", state.show[key]);
  renderResultsGrid();
}

// Replaces renderResultsGrid's body from Task 4 to branch on layoutMode.
function renderResultsGrid() {
  const grid = document.getElementById("results-grid");
  grid.innerHTML = "";
  const names = Array.from(state.compare).filter((n) => state.results[n] && state.results[n].ok);
  if (names.length === 0) return;

  if (state.layoutMode === "side-by-side") {
    grid.style.display = "grid";
    grid.style.gridTemplateColumns = `repeat(${names.length}, minmax(0, 1fr))`;
    names.forEach((name) => grid.appendChild(renderPanel(name, state.results[name])));
  } else {
    grid.style.display = "block";
    grid.appendChild(renderOverlayPanel(names));
  }
}

function renderOverlayPanel(names) {
  const panel = document.createElement("section");
  panel.className = "engine-panel";

  const header = document.createElement("div");
  header.className = "panel-header";
  names.forEach((name) => {
    const chip = document.createElement("span");
    chip.style.cssText = `display:inline-flex;align-items:center;gap:6px;font-size:14px;font-weight:600;margin-right:12px;`;
    chip.innerHTML = `<span style="display:inline-block;width:10px;height:10px;border-radius:3px;background:${ENGINE_COLORS[name] || "#999"}"></span>${name}`;
    header.appendChild(chip);
  });
  panel.appendChild(header);

  // Canonical image: first engine (in `names` order) whose first page has an image.
  const canonicalName = names.find((n) => state.results[n].pages[0].image_base64);
  if (!canonicalName) return panel;
  const canonicalPage = state.results[canonicalName].pages[0];

  const wrap = document.createElement("div");
  wrap.className = "page-image-wrap";
  const img = document.createElement("img");
  img.src = `data:image/png;base64,${canonicalPage.image_base64}`;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("box-overlay");

  img.addEventListener("load", () => {
    svg.setAttribute("viewBox", `0 0 ${img.naturalWidth} ${img.naturalHeight}`);
    const canonicalW = img.naturalWidth, canonicalH = img.naturalHeight;

    names.forEach((name) => {
      const page = state.results[name].pages[0];
      let scaleX = 1, scaleY = 1;
      if (page.image_base64 && name !== canonicalName) {
        // Measure this engine's own image dimensions before scaling its boxes.
        const probe = new Image();
        probe.onload = () => {
          scaleX = canonicalW / probe.naturalWidth;
          scaleY = canonicalH / probe.naturalHeight;
          drawBoxes(svg, scaleBoxes(page.boxes, scaleX, scaleY), ENGINE_COLORS[name] || "#999");
        };
        probe.src = `data:image/png;base64,${page.image_base64}`;
      } else {
        drawBoxes(svg, page.boxes, ENGINE_COLORS[name] || "#999");
      }
    });
  });

  wrap.appendChild(img);
  wrap.appendChild(svg);
  panel.appendChild(wrap);
  return panel;
}

function scaleBoxes(boxes, scaleX, scaleY) {
  return boxes.map((b) => ({
    ...b,
    x0: b.x0 * scaleX, y0: b.y0 * scaleY, x1: b.x1 * scaleX, y1: b.y1 * scaleY,
  }));
}
```

Wire `#mode-side-by-side`/`#mode-overlay` clicks to `setLayoutMode`, and `#toggle-boxes`/`#toggle-text`/`#toggle-order` clicks to `toggleShow("boxes")`/`toggleShow("text")`/`toggleShow("orderNumbers")`, in the `DOMContentLoaded` listener. Give the 5 toolbar buttons `.active` default classes matching Task 4's defaults (`mode-side-by-side` and all 3 `show-toggle` buttons start active).

- [ ] **Step 3: Run the full pytest suite**

Run: `pytest -q`
Expected: unchanged, all pass (no Python changes in this task).

- [ ] **Step 4: Verify in a real browser**

Same server setup as Task 4 Step 4. Walk through the Step 1 checklist using `claude-in-chrome`, screenshotting each state.

- [ ] **Step 5: Commit**

```bash
git add src/ocrhub/web/static/app.js src/ocrhub/web/static/dashboard.css
git commit -m "feat: overlay comparison mode and Boxes/Text/Order-numbers toggles"
```

---

## Task 6: Detections table

**Files:**
- Modify: `src/ocrhub/web/static/app.js`
- Modify: `src/ocrhub/web/static/dashboard.css`
- Modify: `src/ocrhub/web/templates/index.html` (the Detections markup below is page
  structure, not JS-generated content — add it as static HTML in the template, in the
  same place Tasks 3/4/5 added their own markup, matching the pattern Task 5 was
  corrected to use after its own plan omitted `index.html` the same way)

**Interfaces:**
- Consumes: `state.results`, `state.compare`.
- Produces: nothing new consumed by later tasks — this is the last piece of the dashboard.

**Markup (below `#results-grid`):**

```html
<section class="detections">
  <div class="detections-header">
    <div class="detections-title">Detections</div>
    <div id="detections-tabs" class="detections-tabs"></div>
    <div style="flex-grow:1"></div>
    <div class="detections-note">Sorted by reading order as reported by the engine, where available</div>
  </div>
  <div class="detections-columns">
    <div>Order</div><div>Text</div><div>Conf.</div><div>Box x, y, w, h</div>
  </div>
  <div id="detections-rows" class="detections-rows"></div>
</section>
```

CSS (values from the mockup):
- `.detections`: `display: flex; flex-direction: column; background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; margin-top: 16px;`
- `.detections-header`: `display: flex; align-items: center; gap: 16px; padding: 10px 14px; border-bottom: 1px solid var(--border-light);`
- `.detections-title`: `font-size: 14px; font-weight: 600;`
- `.detections-tabs`: `display: flex; gap: 4px;`
- `.detections-tab`: `display: flex; align-items: center; gap: 7px; padding: 6px 12px; border-radius: 7px; font-size: 13px; font-weight: 500; border: 1px solid var(--border); background: transparent; color: var(--text);` — active: `background: var(--sidebar-bg); border-color: var(--input-border);`
- `.detections-note`: `font-size: 12px; color: var(--muted-2);`
- `.detections-columns`: `display: grid; grid-template-columns: 64px minmax(0, 1fr) 90px 210px; gap: 12px; padding: 8px 14px; font-size: 11px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); background: var(--bg);`
- `.detections-rows`: `max-height: 320px; overflow-y: auto;`
- `.detections-row`: `display: grid; grid-template-columns: 64px minmax(0, 1fr) 90px 210px; gap: 12px; align-items: center; padding: 6px 14px; font-family: 'IBM Plex Mono', monospace; font-size: 12.5px;` — alternate rows: `background: var(--row-alt);` / `background: #fff;`
- `.conf-bar`: `width: 34px; height: 5px; border-radius: 3px; background: var(--toggle-track);` containing `.conf-bar-fill`: `height: 5px; border-radius: 3px;` with `background: var(--success)` if confidence ≥ 70, else `background: var(--warn)`, and `width` set to `confidence% of 34px`.

**Behavior:**
- Tabs list every engine currently in `state.compare` (not all selected engines — only the ones being compared, since those are the only ones with rendered panels to cross-reference against). Clicking a tab sets `state.detectionsTab` and re-renders rows from that engine's first page's `boxes`.
- Rows: if `box.reading_order !== null`, show it in the Order column; otherwise show `–` (an em dash, not a fabricated number). Order the rows by `reading_order` when every box in the list has one; otherwise keep the engine's original array order (don't attempt to invent a sort for engines with no reading order — the note text already says "where available").
- Text column: `white-space: nowrap; overflow: hidden; text-overflow: ellipsis;`, full text available via a `title` attribute (native browser tooltip) for truncated rows.
- Conf. column: the bar + percentage, using `box.confidence` directly (already 0–100 per Task 1/2's normalization) — if `confidence === null`, show `–` and no bar.
- Box column: `${round(x0)}, ${round(y0)}, ${round(x1-x0)}, ${round(y1-y0)}` (x, y, width, height — matching the mockup's display convention, converted from our stored corner coordinates).

- [ ] **Step 1: Manual verification plan**

- With 2 engines in `state.compare`, the Detections section shows 2 tabs; clicking each swaps the rows to that engine's boxes.
- An engine with no `reading_order` on any box shows `–` in every Order cell, rows in original array order.
- An engine with `reading_order` set on every box shows ascending numbers, sorted.
- A box with `confidence === null` shows `–` in Conf., no bar rendered (not a zero-width bar, which would look like a bug rather than "no data").

- [ ] **Step 2: Implement**

Add the markup/CSS as specified, and this JS (called at the end of `renderResultsGrid` so the tabs/table stay in sync with the current comparison set):

```javascript
state.detectionsTab = null;

function renderDetections() {
  const tabsEl = document.getElementById("detections-tabs");
  const rowsEl = document.getElementById("detections-rows");
  tabsEl.innerHTML = "";
  rowsEl.innerHTML = "";

  const names = Array.from(state.compare).filter((n) => state.results[n] && state.results[n].ok);
  if (names.length === 0) return;
  if (!state.detectionsTab || !names.includes(state.detectionsTab)) {
    state.detectionsTab = names[0];
  }

  names.forEach((name) => {
    const tab = document.createElement("button");
    tab.type = "button";
    tab.className = "detections-tab" + (name === state.detectionsTab ? " active" : "");
    const dot = `<span style="display:inline-block;width:9px;height:9px;border-radius:3px;background:${ENGINE_COLORS[name] || "#999"}"></span>`;
    tab.innerHTML = `${dot} ${name}`;
    tab.addEventListener("click", () => { state.detectionsTab = name; renderDetections(); });
    tabsEl.appendChild(tab);
  });

  const page = state.results[state.detectionsTab].pages[0];
  const allOrdered = page.boxes.length > 0 && page.boxes.every((b) => b.reading_order !== null && b.reading_order !== undefined);
  const rows = allOrdered
    ? [...page.boxes].sort((a, b) => a.reading_order - b.reading_order)
    : page.boxes;

  rows.forEach((box, i) => {
    const row = document.createElement("div");
    row.className = "detections-row";
    row.style.background = i % 2 ? "var(--row-alt)" : "#fff";

    const order = document.createElement("div");
    order.style.fontWeight = "600";
    order.textContent = box.reading_order !== null && box.reading_order !== undefined ? box.reading_order : "–";

    const text = document.createElement("div");
    text.style.cssText = "white-space:nowrap;overflow:hidden;text-overflow:ellipsis;";
    text.textContent = box.text;
    text.title = box.text;

    const conf = document.createElement("div");
    if (box.confidence !== null && box.confidence !== undefined) {
      const pct = Math.round(box.confidence);
      const barWrap = document.createElement("div");
      barWrap.style.cssText = "display:flex;align-items:center;gap:8px;";
      const bar = document.createElement("div");
      bar.className = "conf-bar";
      const fill = document.createElement("div");
      fill.className = "conf-bar-fill";
      fill.style.width = Math.round(34 * (pct / 100)) + "px";
      fill.style.background = pct >= 70 ? "var(--success)" : "var(--warn)";
      bar.appendChild(fill);
      barWrap.appendChild(bar);
      const span = document.createElement("span");
      span.textContent = pct + "%";
      barWrap.appendChild(span);
      conf.appendChild(barWrap);
    } else {
      conf.textContent = "–";
    }

    const bbox = document.createElement("div");
    bbox.style.color = "var(--muted-2)";
    bbox.textContent = `${Math.round(box.x0)}, ${Math.round(box.y0)}, ${Math.round(box.x1 - box.x0)}, ${Math.round(box.y1 - box.y0)}`;

    row.appendChild(order);
    row.appendChild(text);
    row.appendChild(conf);
    row.appendChild(bbox);
    rowsEl.appendChild(row);
  });
}
```

Task 5's `renderResultsGrid()` has an early `if (names.length === 0) return;` before its side-by-side/overlay branches — calling `renderDetections()` only after that function's existing final line would skip it whenever `names` is empty (leaving a stale Detections table visible with no matching comparison panels). Fix this by replacing that early return with a guard around the render logic instead, so there's one exit point that always calls `renderDetections()`:

```javascript
// Replace the `if (names.length === 0) return;` line and everything below
// it in renderResultsGrid with:
if (names.length > 0) {
  if (state.layoutMode === "side-by-side") {
    grid.style.display = "grid";
    grid.style.gridTemplateColumns = `repeat(${names.length}, minmax(0, 1fr))`;
    names.forEach((name) => grid.appendChild(renderPanel(name, state.results[name])));
  } else {
    grid.style.display = "block";
    grid.appendChild(renderOverlayPanel(names));
  }
}
renderDetections();
```

`renderDetections()` already handles the empty case correctly on its own (it clears `tabsEl`/`rowsEl` before its own early return), so calling it unconditionally here is safe and keeps the table in sync with `state.compare` in every case, including when the comparison set is empty.

- [ ] **Step 3: Run the full pytest suite**

Run: `pytest -q`
Expected: unchanged, all pass.

- [ ] **Step 4: Verify in a real browser**

Same server setup as Task 4 Step 4, walk the Step 1 checklist with `claude-in-chrome`.

- [ ] **Step 5: Commit**

```bash
git add src/ocrhub/web/static/app.js src/ocrhub/web/static/dashboard.css
git commit -m "feat: detections table with per-engine tabs"
```

---

## Task 7: Final end-to-end verification

**Files:** none (verification-only task, no code changes expected — if this step finds a bug, fix it in the relevant task's files and re-run this task).

- [ ] **Step 1: Full test suite**

Run: `pytest -q`
Expected: all tests pass (should be ~10 more than the pre-plan baseline of 55: 2 from Task 1, 1 from Task 2, 2 from Task 3 — Tasks 4/5/6 add no automated tests per their own scope, being pure-JS with no test runner in this project).

- [ ] **Step 2: Real Docker build with every visual engine**

```bash
docker build --build-arg ENGINES=surya,paddleocr -t ocrhub-final-test .
```

If this fails on the `paddleocr`/`pyclipper` issue noted in Task 2, fall back to `--build-arg ENGINES=surya` and note PaddleOCR's dashboard panel as unverified-on-this-hardware (not a plan failure — the mocked unit tests already prove its parsing logic; the live-library issue is a pre-existing environment constraint, not something this plan introduces or can fix).

- [ ] **Step 3: Run via docker compose, exercise the full dashboard against real multi-engine data**

```bash
cp .env.example .env
# edit .env: ENGINES=surya,paddleocr (or surya alone per Step 2's fallback)
docker compose up --build -d
```

Using `claude-in-chrome`: upload a real test image, select all available engines, run, add 3 to compare, exercise both layout modes and all three SHOW toggles, check the Detections table tabs. Screenshot at least one fully-populated state (3-engine side-by-side, boxes+text+order all on) as evidence.

- [ ] **Step 4: Tear down and clean up**

```bash
docker compose down
rm .env
```

- [ ] **Step 5: Report**

Summarize what was verified live vs. what remains unverified-on-this-hardware (e.g. PaddleOCR's real API if Step 2 hit the `pyclipper` blocker), so the user has an accurate picture before treating this feature as fully done.
