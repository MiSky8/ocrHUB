# PaddleOCR layout regions and per-engine capability labels

Date: 2026-10-16. Branch: `restore-paddleocr`.

## Goal

Show what each engine can really do, side by side. PaddleOCR today returns text
lines only, so a page's pictures and structure are invisible in its panel. Add
PaddleOCR's own layout detection as a switchable stage, and make the dashboard
say plainly which engines do not detect figures.

## Non-goals

- No shared or engine-agnostic figure detector. Tesseract and pdfplumber stay
  as they are, because the dashboard is a comparison of each engine's own
  capabilities and must not credit an engine with something it cannot do.
- No table cell recognition (PP-StructureV3). Tables appear as regions only.
  The merge step leaves a clear place to add cell recognition later.
- No image preprocessing and no PaddleOCR speed work. In particular
  `_build_engine()` still runs per request; reloading models each time is the
  likely cause of the slow runs and is recommended as the next step.
- No change to `models.py`, `service.py`, the cache format, the MCP tool, or the
  Surya, Datalab, Tesseract and pdfplumber adapters.

## Design

### 1. PaddleOCR layout stage

- New env var `PADDLE_LAYOUT`, default `0`, passed through `docker-compose.yml`
  and documented in `.env.example` and the README (same pattern as
  `SURYA_LAYOUT`).
- When `1`, after the OCR lines for a page are computed, the adapter runs
  `paddleocr.LayoutDetection` (PP-DocLayout family, small variant by default)
  on the same RGB page image. The exact model name and its output keys are
  confirmed against the installed paddleocr 3.7.0 before implementing.
- Memory: the OCR engine is released before the layout model is loaded, and the
  layout model is released afterwards, so only one set of models is resident at
  a time (CLAUDE.md requirement).
- Merge, producing the page's `boxes`:
  - Each layout region becomes a `BoxResult` with `region_type` (for example
    Text, Title, Table, Caption, Picture), `reading_order`, and the region's
    confidence.
  - OCR lines whose centre falls inside a text-like region are joined, in
    reading order, into that region's `text`.
  - A figure region becomes `region_type="Picture"` with `image` set to a
    base64 JPEG crop and `text` empty (or the caption if one is attached). The
    dashboard already draws Picture boxes for Surya, Datalab and pdfplumber.
  - OCR lines that fall inside no region are kept as plain line boxes, so no
    recognised text is lost.
- Coordinates: layout and OCR both run on the same image, so all boxes are in
  that image's pixel space, consistent with the "pixels for the non-PDF
  engines" rule.
- With `PADDLE_LAYOUT=0` the output is exactly what it is today.

### 2. Errors

- Layout stage failure (download, load, or inference): log it, keep the OCR
  line boxes, and surface a warning. It does not fail the engine.
- A genuine PaddleOCR failure still returns `OcrResult.error`, is never cached,
  and does not stop other engines.

### 3. Dashboard

- A static capability map in `web/static/app.js`: which region types each engine
  can produce. Engines that cannot produce Picture show a short note in their
  panel header ("No figure detection"). The note comes from the capability map,
  not from whether the current page happens to contain a figure.
- PaddleOCR's capability depends on the toggle. `/engines` is extended to
  report it (for example `capabilities` per engine), so the dashboard does not
  hard-code PaddleOCR's state.
- Existing Boxes, Text and Order-number toggles and Picture drawing are reused.

### 4. Testing

- Unit tests with `paddleocr.PaddleOCR` and `LayoutDetection` mocked (same style
  as the Surya and Datalab mocks). Cases: lines inside a region are joined in
  order; lines in no region survive; a figure region becomes a Picture box with
  a crop; layout failure leaves the OCR lines and a warning; `PADDLE_LAYOUT=0`
  output is unchanged; `/engines` reports capabilities.
- Manual check in the real container, because mocked tests say nothing about
  real model output: the 4-page test PDF and the user's graphics PDF with
  `PADDLE_LAYOUT=1` and `refresh=true`. Verify box alignment on the dashboard
  and record time and peak memory with and without layout.

### 5. Docs

`docs/visualisations.md` (PaddleOCR section: what the layout stage returns,
measured time and memory, what was checked), `README.md` env table,
`.env.example`, `CHANGELOG.md`. Note that cached results must be refreshed
after the change.

## Open items to settle during implementation

- Exact layout model name and the keys of its output in paddleocr 3.7.0.
- Whether the first-run layout model download works through the existing
  `ocrhub-models` cache volume without extra configuration.
- Peak memory with layout on, measured, to confirm the one-set-at-a-time claim.
