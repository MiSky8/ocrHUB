# ocrHub Implementation Plan

> **Historical note:** this document was written before the first release. PaddleOCR and the Ollama (DeepSeek) engine it describes were later removed, so ignore them. The rest is kept as written.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single Docker image exposing multiple OCR engines (Tesseract, pdfplumber, Surya, PaddleOCR, DeepSeek-via-Ollama) behind one FastAPI service, reachable via a web UI, REST API, and MCP tool.

**Architecture:** One Python package (`ocrhub`) with a common `OcrAdapter` interface; each engine is a small adapter class registered into a startup-time registry that reports availability. A single service function (`process_document`) is the one code path all three interfaces (web UI, REST API, MCP) call into.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, pytesseract, pdfplumber, PyMuPDF (`fitz`), surya-ocr, paddleocr, httpx (for Ollama), `mcp` Python SDK, pytest, fpdf2 (test fixture generation).

**Spec:** `docs/superpowers/specs/2026-09-28-ocrhub-design.md`

## Global Constraints

- Per-engine failures must never crash a multi-engine request — each engine's error is captured per-result (spec: Error handling).
- Tesseract and pdfplumber are always installed (default-on); Surya and PaddleOCR are only installed when named in the `ENGINES` Docker build arg (spec: Build-time engine selection).
- The Ollama/DeepSeek adapter is always present in code but reports unavailable (not an error) when `OLLAMA_HOST` is unset or unreachable (spec: Risks).
- `GET /engines` (and the MCP tool) must only ever offer engines that are actually available — never advertise an engine that will fail.
- Web UI, REST API, and MCP server all call the same `ocrhub.service.process_document` — no duplicated orchestration logic per interface.
- GPU-heavy engines (Surya, PaddleOCR, Ollama) are skipped in CI; only Tesseract/pdfplumber paths run in CI (spec: Testing).

---

## File Structure

```
ocrHub/
├── pyproject.toml
├── Dockerfile
├── LICENSE
├── README.md
├── .github/workflows/ci.yml
├── src/ocrhub/
│   ├── __init__.py
│   ├── models.py                    # OcrResult, PageResult
│   ├── pdf_utils.py                 # rasterize_pdf, is_pdf
│   ├── registry.py                  # EngineRegistry
│   ├── service.py                   # process_document()
│   ├── api.py                       # FastAPI app + REST routes
│   ├── mcp_server.py                # MCP tool wrapping service
│   ├── main.py                      # wires api + mcp + static/web, uvicorn entrypoint
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── base.py                  # OcrAdapter Protocol
│   │   ├── pdfplumber_adapter.py
│   │   ├── tesseract_adapter.py
│   │   ├── surya_adapter.py
│   │   ├── paddleocr_adapter.py
│   │   └── ollama_adapter.py
│   └── web/
│       ├── templates/index.html
│       └── static/app.js
└── tests/
    ├── conftest.py
    ├── test_models.py
    ├── test_pdf_utils.py
    ├── test_registry.py
    ├── test_service.py
    ├── test_api.py
    ├── test_web.py
    ├── test_mcp_server.py
    └── adapters/
        ├── test_pdfplumber_adapter.py
        ├── test_tesseract_adapter.py
        ├── test_surya_adapter.py
        ├── test_paddleocr_adapter.py
        └── test_ollama_adapter.py
```

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/ocrhub/__init__.py`
- Create: `.gitignore`
- Create: `LICENSE`
- Test: `tests/test_package.py`

**Interfaces:**
- Produces: an installable `ocrhub` package (`pip install -e ".[dev]"`), `pytest` runnable from repo root.

- [ ] **Step 1: Write pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "ocrhub"
version = "0.1.0"
description = "One Docker image, many OCR engines, one API."
requires-python = ">=3.11"
license = { text = "MIT" }
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "jinja2>=3.1",
    "python-multipart>=0.0.9",
    "pydantic>=2.6",
    "pytesseract>=0.3.10",
    "Pillow>=10.0",
    "pdfplumber>=0.11",
    "pymupdf>=1.24",
    "httpx>=0.27",
    "mcp>=1.0",
]

[project.optional-dependencies]
surya = ["surya-ocr>=0.6"]
paddleocr = ["paddleocr>=2.7", "paddlepaddle>=2.5"]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "fpdf2>=2.7"]

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: Write package init**

```python
# src/ocrhub/__init__.py
__version__ = "0.1.0"
```

- [ ] **Step 3: Write .gitignore**

```
__pycache__/
*.pyc
.venv/
*.egg-info/
.pytest_cache/
dist/
build/
```

- [ ] **Step 4: Write LICENSE**

Use the standard MIT License text, copyright line `Copyright (c) 2026 <author>`.

- [ ] **Step 5: Write a trivial package test**

```python
# tests/test_package.py
import ocrhub


def test_version_is_set():
    assert ocrhub.__version__ == "0.1.0"
```

- [ ] **Step 6: Install and run**

Run: `pip install -e ".[dev]" && pytest tests/test_package.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/ocrhub/__init__.py .gitignore LICENSE tests/test_package.py
git commit -m "chore: scaffold ocrhub package"
```

---

### Task 2: Data models

**Files:**
- Create: `src/ocrhub/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces:
  - `PageResult(page_number: int, text: str, confidence: float | None)`
  - `OcrResult(engine: str, text: str, pages: list[PageResult], confidence: float | None, elapsed_ms: int, error: str | None = None)`
  - `OcrResult.ok -> bool` property (True when `error is None`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
from ocrhub.models import OcrResult, PageResult


def test_ocr_result_ok_when_no_error():
    result = OcrResult(
        engine="tesseract",
        text="hello",
        pages=[PageResult(page_number=1, text="hello", confidence=0.9)],
        confidence=0.9,
        elapsed_ms=42,
    )
    assert result.ok is True


def test_ocr_result_not_ok_when_error_set():
    result = OcrResult(
        engine="paddleocr",
        text="",
        pages=[],
        confidence=None,
        elapsed_ms=5,
        error="model not loaded",
    )
    assert result.ok is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ocrhub.models'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ocrhub/models.py
from dataclasses import dataclass, field


@dataclass
class PageResult:
    page_number: int
    text: str
    confidence: float | None = None


@dataclass
class OcrResult:
    engine: str
    text: str
    pages: list[PageResult] = field(default_factory=list)
    confidence: float | None = None
    elapsed_ms: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ocrhub/models.py tests/test_models.py
git commit -m "feat: add OcrResult/PageResult models"
```

---

### Task 3: Adapter protocol + engine registry

**Files:**
- Create: `src/ocrhub/adapters/__init__.py`
- Create: `src/ocrhub/adapters/base.py`
- Create: `src/ocrhub/registry.py`
- Test: `tests/test_registry.py`

**Interfaces:**
- Consumes: `OcrResult` from Task 2 (`ocrhub.models`).
- Produces:
  - `OcrAdapter` Protocol with `name: str`, `def available(self) -> bool`, `def extract(self, file_bytes: bytes, filename: str) -> OcrResult`.
  - `EngineRegistry` class: `.register(adapter: OcrAdapter) -> None`, `.available_engines() -> list[str]`, `.get(name: str) -> OcrAdapter` (raises `KeyError` if unknown), `.all() -> list[OcrAdapter]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_registry.py
import pytest

from ocrhub.models import OcrResult
from ocrhub.registry import EngineRegistry


class FakeAdapter:
    def __init__(self, name: str, is_available: bool):
        self.name = name
        self._is_available = is_available

    def available(self) -> bool:
        return self._is_available

    def extract(self, file_bytes: bytes, filename: str) -> OcrResult:
        return OcrResult(engine=self.name, text="fake", elapsed_ms=1)


def test_available_engines_only_lists_available_adapters():
    registry = EngineRegistry()
    registry.register(FakeAdapter("on", is_available=True))
    registry.register(FakeAdapter("off", is_available=False))

    assert registry.available_engines() == ["on"]


def test_get_returns_registered_adapter():
    registry = EngineRegistry()
    adapter = FakeAdapter("on", is_available=True)
    registry.register(adapter)

    assert registry.get("on") is adapter


def test_get_unknown_engine_raises_key_error():
    registry = EngineRegistry()
    with pytest.raises(KeyError):
        registry.get("nope")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ocrhub.registry'`

- [ ] **Step 3: Write the adapter protocol**

```python
# src/ocrhub/adapters/__init__.py
```

```python
# src/ocrhub/adapters/base.py
from typing import Protocol

from ocrhub.models import OcrResult


class OcrAdapter(Protocol):
    name: str

    def available(self) -> bool:
        """Return True if this engine's dependencies/config are ready to use."""
        ...

    def extract(self, file_bytes: bytes, filename: str) -> OcrResult:
        """Run OCR/extraction on a single page/image's raw bytes."""
        ...
```

- [ ] **Step 4: Write the registry**

```python
# src/ocrhub/registry.py
from ocrhub.adapters.base import OcrAdapter


class EngineRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, OcrAdapter] = {}

    def register(self, adapter: OcrAdapter) -> None:
        self._adapters[adapter.name] = adapter

    def available_engines(self) -> list[str]:
        return [name for name, adapter in self._adapters.items() if adapter.available()]

    def get(self, name: str) -> OcrAdapter:
        return self._adapters[name]

    def all(self) -> list[OcrAdapter]:
        return list(self._adapters.values())
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_registry.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/ocrhub/adapters/__init__.py src/ocrhub/adapters/base.py src/ocrhub/registry.py tests/test_registry.py
git commit -m "feat: add OcrAdapter protocol and engine registry"
```

---

### Task 4: PDF utilities (rasterization + fixtures)

**Files:**
- Create: `src/ocrhub/pdf_utils.py`
- Create: `tests/conftest.py`
- Test: `tests/test_pdf_utils.py`

**Interfaces:**
- Produces:
  - `is_pdf(filename: str) -> bool`
  - `rasterize_pdf(file_bytes: bytes, dpi: int = 200) -> list[bytes]` — returns one PNG-encoded image per page.
  - `pdf_has_text_layer(file_bytes: bytes) -> bool`
- Produces pytest fixtures (in `conftest.py`) used by every later test module:
  - `sample_image_bytes` — PNG bytes with rendered text "OCRHUB TEST".
  - `sample_born_digital_pdf_bytes` — single-page PDF with a real text layer, generated via `fpdf2`.
  - `sample_scanned_pdf_bytes` — single-page PDF with no text layer, built by embedding `sample_image_bytes` as the page content (via PyMuPDF).

- [ ] **Step 1: Write the fixtures**

```python
# tests/conftest.py
import io

import fitz  # PyMuPDF
import pytest
from fpdf import FPDF
from PIL import Image, ImageDraw


@pytest.fixture
def sample_image_bytes() -> bytes:
    img = Image.new("RGB", (400, 100), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((10, 40), "OCRHUB TEST", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def sample_born_digital_pdf_bytes() -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=14)
    pdf.cell(0, 10, "OCRHUB TEXT LAYER")
    return bytes(pdf.output())


@pytest.fixture
def sample_scanned_pdf_bytes(sample_image_bytes: bytes) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    rect = fitz.Rect(0, 0, page.rect.width, page.rect.height)
    page.insert_image(rect, stream=sample_image_bytes)
    buf = doc.tobytes()
    doc.close()
    return buf
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_pdf_utils.py
from ocrhub.pdf_utils import is_pdf, pdf_has_text_layer, rasterize_pdf


def test_is_pdf_by_filename():
    assert is_pdf("doc.pdf") is True
    assert is_pdf("scan.PDF") is True
    assert is_pdf("photo.png") is False


def test_rasterize_pdf_returns_one_image_per_page(sample_scanned_pdf_bytes):
    pages = rasterize_pdf(sample_scanned_pdf_bytes)
    assert len(pages) == 1
    assert pages[0][:4] == b"\x89PNG"


def test_pdf_has_text_layer_true_for_born_digital(sample_born_digital_pdf_bytes):
    assert pdf_has_text_layer(sample_born_digital_pdf_bytes) is True


def test_pdf_has_text_layer_false_for_scanned(sample_scanned_pdf_bytes):
    assert pdf_has_text_layer(sample_scanned_pdf_bytes) is False
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_pdf_utils.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ocrhub.pdf_utils'`

- [ ] **Step 4: Write minimal implementation**

```python
# src/ocrhub/pdf_utils.py
import fitz  # PyMuPDF


def is_pdf(filename: str) -> bool:
    return filename.lower().endswith(".pdf")


def rasterize_pdf(file_bytes: bytes, dpi: int = 200) -> list[bytes]:
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages: list[bytes] = []
    try:
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            pages.append(pix.tobytes("png"))
    finally:
        doc.close()
    return pages


def pdf_has_text_layer(file_bytes: bytes, min_chars: int = 10) -> bool:
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    try:
        total_chars = sum(len(page.get_text().strip()) for page in doc)
        return total_chars >= min_chars
    finally:
        doc.close()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_pdf_utils.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/ocrhub/pdf_utils.py tests/conftest.py tests/test_pdf_utils.py
git commit -m "feat: add PDF rasterization utilities and shared test fixtures"
```

---

### Task 5: pdfplumber adapter

**Files:**
- Create: `src/ocrhub/adapters/pdfplumber_adapter.py`
- Test: `tests/adapters/test_pdfplumber_adapter.py`

**Interfaces:**
- Consumes: `OcrAdapter` (Task 3), `OcrResult`/`PageResult` (Task 2).
- Produces: `PdfplumberAdapter` class, `name = "pdfplumber"`, `available()` always `True`, `extract(file_bytes, filename)` — raises `ValueError` if `filename` is not a PDF (caller's responsibility to only route PDFs here; service layer enforces this in Task 7).

- [ ] **Step 1: Write the failing test**

```python
# tests/adapters/test_pdfplumber_adapter.py
import pytest

from ocrhub.adapters.pdfplumber_adapter import PdfplumberAdapter


def test_available_is_always_true():
    assert PdfplumberAdapter().available() is True


def test_extract_returns_text_from_born_digital_pdf(sample_born_digital_pdf_bytes):
    adapter = PdfplumberAdapter()
    result = adapter.extract(sample_born_digital_pdf_bytes, "sample.pdf")

    assert result.ok is True
    assert "OCRHUB" in result.text
    assert len(result.pages) == 1


def test_extract_rejects_non_pdf():
    adapter = PdfplumberAdapter()
    with pytest.raises(ValueError):
        adapter.extract(b"not a pdf", "photo.png")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/test_pdfplumber_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ocrhub.adapters.pdfplumber_adapter'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ocrhub/adapters/pdfplumber_adapter.py
import io
import time

import pdfplumber

from ocrhub.models import OcrResult, PageResult
from ocrhub.pdf_utils import is_pdf


class PdfplumberAdapter:
    name = "pdfplumber"

    def available(self) -> bool:
        return True

    def extract(self, file_bytes: bytes, filename: str) -> OcrResult:
        if not is_pdf(filename):
            raise ValueError("pdfplumber adapter only accepts PDF files")

        start = time.monotonic()
        pages: list[PageResult] = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                pages.append(PageResult(page_number=i, text=text))

        elapsed_ms = int((time.monotonic() - start) * 1000)
        full_text = "\n".join(p.text for p in pages)
        return OcrResult(
            engine=self.name,
            text=full_text,
            pages=pages,
            confidence=None,
            elapsed_ms=elapsed_ms,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/adapters/test_pdfplumber_adapter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ocrhub/adapters/pdfplumber_adapter.py tests/adapters/test_pdfplumber_adapter.py
git commit -m "feat: add pdfplumber adapter for born-digital PDFs"
```

---

### Task 6: Tesseract adapter

**Files:**
- Create: `src/ocrhub/adapters/tesseract_adapter.py`
- Test: `tests/adapters/test_tesseract_adapter.py`

**Interfaces:**
- Consumes: `OcrAdapter` (Task 3), `OcrResult`/`PageResult` (Task 2), `is_pdf`/`rasterize_pdf` (Task 4).
- Produces: `TesseractAdapter` class, `name = "tesseract"`, `available()` returns `True` only if the `tesseract` binary is on `PATH` (via `shutil.which`), `extract(file_bytes, filename)` handles both images and PDFs (rasterizing PDFs page by page first).

- [ ] **Step 1: Write the failing test**

```python
# tests/adapters/test_tesseract_adapter.py
import shutil

import pytest

from ocrhub.adapters.tesseract_adapter import TesseractAdapter

pytestmark = pytest.mark.skipif(
    shutil.which("tesseract") is None, reason="tesseract binary not installed"
)


def test_available_true_when_binary_present():
    assert TesseractAdapter().available() is True


def test_extract_reads_text_from_image(sample_image_bytes):
    adapter = TesseractAdapter()
    result = adapter.extract(sample_image_bytes, "sample.png")

    assert result.ok is True
    assert "OCRHUB" in result.text.upper()
    assert len(result.pages) == 1


def test_extract_reads_text_from_scanned_pdf(sample_scanned_pdf_bytes):
    adapter = TesseractAdapter()
    result = adapter.extract(sample_scanned_pdf_bytes, "sample.pdf")

    assert result.ok is True
    assert len(result.pages) == 1
    assert "OCRHUB" in result.text.upper()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/test_tesseract_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ocrhub.adapters.tesseract_adapter'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ocrhub/adapters/tesseract_adapter.py
import io
import shutil
import time

import pytesseract
from PIL import Image

from ocrhub.models import OcrResult, PageResult
from ocrhub.pdf_utils import is_pdf, rasterize_pdf


class TesseractAdapter:
    name = "tesseract"

    def available(self) -> bool:
        return shutil.which("tesseract") is not None

    def extract(self, file_bytes: bytes, filename: str) -> OcrResult:
        start = time.monotonic()

        if is_pdf(filename):
            page_images = rasterize_pdf(file_bytes)
        else:
            page_images = [file_bytes]

        pages: list[PageResult] = []
        for i, page_bytes in enumerate(page_images, start=1):
            img = Image.open(io.BytesIO(page_bytes))
            text = pytesseract.image_to_string(img)
            pages.append(PageResult(page_number=i, text=text))

        elapsed_ms = int((time.monotonic() - start) * 1000)
        full_text = "\n".join(p.text for p in pages)
        return OcrResult(
            engine=self.name,
            text=full_text,
            pages=pages,
            confidence=None,
            elapsed_ms=elapsed_ms,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/adapters/test_tesseract_adapter.py -v`
Expected: PASS (or SKIPPED if `tesseract` isn't installed locally — install via `brew install tesseract` / `apt-get install tesseract-ocr` to actually run it)

- [ ] **Step 5: Commit**

```bash
git add src/ocrhub/adapters/tesseract_adapter.py tests/adapters/test_tesseract_adapter.py
git commit -m "feat: add Tesseract adapter for images and scanned PDFs"
```

---

### Task 7: Service layer (process_document)

**Files:**
- Create: `src/ocrhub/service.py`
- Test: `tests/test_service.py`

**Interfaces:**
- Consumes: `EngineRegistry` (Task 3), `OcrResult` (Task 2), `is_pdf`/`pdf_has_text_layer` (Task 4).
- Produces: `process_document(registry: EngineRegistry, file_bytes: bytes, filename: str, engine_names: list[str]) -> list[OcrResult]`
  - For each requested engine name: if not in `registry.available_engines()`, append an `OcrResult(engine=name, text="", error="engine not available")` and continue.
  - Otherwise call `registry.get(name).extract(file_bytes, filename)`; if the adapter raises, catch it and wrap as `OcrResult(engine=name, text="", error=str(exc))` — a single engine's exception never propagates.
  - Order of returned results matches `engine_names` order.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_service.py
from ocrhub.models import OcrResult
from ocrhub.registry import EngineRegistry
from ocrhub.service import process_document


class WorkingAdapter:
    name = "working"

    def available(self) -> bool:
        return True

    def extract(self, file_bytes: bytes, filename: str) -> OcrResult:
        return OcrResult(engine=self.name, text="ok", elapsed_ms=1)


class BrokenAdapter:
    name = "broken"

    def available(self) -> bool:
        return True

    def extract(self, file_bytes: bytes, filename: str) -> OcrResult:
        raise RuntimeError("model crashed")


def _registry() -> EngineRegistry:
    registry = EngineRegistry()
    registry.register(WorkingAdapter())
    registry.register(BrokenAdapter())
    return registry


def test_process_document_returns_results_in_requested_order():
    results = process_document(_registry(), b"bytes", "f.png", ["working", "broken"])
    assert [r.engine for r in results] == ["working", "broken"]


def test_process_document_captures_adapter_exception_as_error():
    results = process_document(_registry(), b"bytes", "f.png", ["broken"])
    assert results[0].ok is False
    assert "model crashed" in results[0].error


def test_process_document_marks_unregistered_engine_unavailable():
    results = process_document(_registry(), b"bytes", "f.png", ["missing"])
    assert results[0].ok is False
    assert results[0].error == "engine not available"


def test_process_document_one_failure_does_not_block_others():
    results = process_document(_registry(), b"bytes", "f.png", ["broken", "working"])
    by_engine = {r.engine: r for r in results}
    assert by_engine["broken"].ok is False
    assert by_engine["working"].ok is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ocrhub.service'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ocrhub/service.py
from ocrhub.models import OcrResult
from ocrhub.registry import EngineRegistry


def process_document(
    registry: EngineRegistry,
    file_bytes: bytes,
    filename: str,
    engine_names: list[str],
) -> list[OcrResult]:
    results: list[OcrResult] = []
    available = set(registry.available_engines())

    for name in engine_names:
        if name not in available:
            results.append(OcrResult(engine=name, text="", error="engine not available"))
            continue

        adapter = registry.get(name)
        try:
            results.append(adapter.extract(file_bytes, filename))
        except Exception as exc:  # noqa: BLE001 - per-engine isolation is the point
            results.append(OcrResult(engine=name, text="", error=str(exc)))

    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ocrhub/service.py tests/test_service.py
git commit -m "feat: add process_document service orchestrating adapters"
```

---

### Task 8: REST API

**Files:**
- Create: `src/ocrhub/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `EngineRegistry` (Task 3), `process_document` (Task 7), `PdfplumberAdapter` (Task 5), `TesseractAdapter` (Task 6).
- Produces:
  - `build_registry() -> EngineRegistry` — registers `PdfplumberAdapter()` and `TesseractAdapter()` unconditionally (Surya/PaddleOCR/Ollama registered in Task 9-11 once those adapters exist).
  - `create_app(registry: EngineRegistry | None = None) -> FastAPI` with routes:
    - `GET /health` → `{"status": "ok"}`
    - `GET /engines` → `{"engines": [<available engine names>]}`
    - `POST /ocr` (multipart form: `file`, repeated form field `engines`) → `{"results": [<OcrResult as dict>, ...]}`; 400 if `engines` is empty.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api.py
import io

from fastapi.testclient import TestClient

from ocrhub.api import create_app
from ocrhub.models import OcrResult
from ocrhub.registry import EngineRegistry


class StubAdapter:
    name = "stub"

    def available(self) -> bool:
        return True

    def extract(self, file_bytes: bytes, filename: str) -> OcrResult:
        return OcrResult(engine=self.name, text="stub text", elapsed_ms=1)


def _client() -> TestClient:
    registry = EngineRegistry()
    registry.register(StubAdapter())
    return TestClient(create_app(registry))


def test_health():
    resp = _client().get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_engines_lists_available_only():
    resp = _client().get("/engines")
    assert resp.status_code == 200
    assert resp.json() == {"engines": ["stub"]}


def test_ocr_runs_requested_engine():
    client = _client()
    files = {"file": ("f.png", io.BytesIO(b"fake-bytes"), "image/png")}
    resp = client.post("/ocr", files=files, data={"engines": ["stub"]})

    assert resp.status_code == 200
    body = resp.json()
    assert body["results"][0]["engine"] == "stub"
    assert body["results"][0]["text"] == "stub text"


def test_ocr_requires_at_least_one_engine():
    client = _client()
    files = {"file": ("f.png", io.BytesIO(b"fake-bytes"), "image/png")}
    resp = client.post("/ocr", files=files, data={})

    assert resp.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ocrhub.api'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ocrhub/api.py
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from ocrhub.adapters.pdfplumber_adapter import PdfplumberAdapter
from ocrhub.adapters.tesseract_adapter import TesseractAdapter
from ocrhub.registry import EngineRegistry
from ocrhub.service import process_document


def build_registry() -> EngineRegistry:
    registry = EngineRegistry()
    registry.register(PdfplumberAdapter())
    registry.register(TesseractAdapter())
    return registry


def create_app(registry: EngineRegistry | None = None) -> FastAPI:
    registry = registry or build_registry()
    app = FastAPI(title="ocrHub")
    app.state.registry = registry

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/engines")
    def engines() -> dict:
        return {"engines": registry.available_engines()}

    @app.post("/ocr")
    async def ocr(file: UploadFile = File(...), engines: list[str] = Form(default=[])) -> dict:
        if not engines:
            raise HTTPException(status_code=400, detail="at least one engine is required")

        file_bytes = await file.read()
        results = process_document(registry, file_bytes, file.filename or "upload", engines)
        return {"results": [vars(r) | {"pages": [vars(p) for p in r.pages]} for r in results]}

    return app
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ocrhub/api.py tests/test_api.py
git commit -m "feat: add REST API with /health, /engines, /ocr"
```

---

### Task 9: Surya adapter (opt-in)

**Files:**
- Create: `src/ocrhub/adapters/surya_adapter.py`
- Test: `tests/adapters/test_surya_adapter.py`

**Interfaces:**
- Consumes: `OcrAdapter` (Task 3), `OcrResult`/`PageResult` (Task 2), `is_pdf`/`rasterize_pdf` (Task 4).
- Produces: `SuryaAdapter` class, `name = "surya"`, `available()` returns `True` only if `surya` is importable (lazy import inside the method, caught via `ImportError`), `extract(file_bytes, filename)` handles images and PDFs like Task 6.

- [ ] **Step 1: Write the failing test**

```python
# tests/adapters/test_surya_adapter.py
from unittest.mock import MagicMock, patch

import pytest

from ocrhub.adapters.surya_adapter import SuryaAdapter


def test_available_false_when_surya_not_installed():
    with patch.dict("sys.modules", {"surya": None, "surya.recognition": None, "surya.detection": None}):
        assert SuryaAdapter().available() is False


def test_extract_uses_recognition_predictor(sample_image_bytes):
    adapter = SuryaAdapter()

    fake_line = MagicMock(text="OCRHUB TEST", confidence=0.95)
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/test_surya_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ocrhub.adapters.surya_adapter'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ocrhub/adapters/surya_adapter.py
import io
import time

from PIL import Image

from ocrhub.models import OcrResult, PageResult
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
            text = "\n".join(line.text for line in prediction.text_lines)
            confidences = [line.confidence for line in prediction.text_lines if line.confidence is not None]
            page_confidence = sum(confidences) / len(confidences) if confidences else None
            pages.append(PageResult(page_number=i, text=text, confidence=page_confidence))

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

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/adapters/test_surya_adapter.py -v`
Expected: PASS

Note: `RecognitionPredictor`/`DetectionPredictor` constructor names track the `surya-ocr` package's public API as of late 2025/early 2026 — if the installed version's API differs, adjust `_recognition_predictor_cls`/`_detection_predictor_cls` accordingly; the adapter's own interface (`available`/`extract`) does not change.

- [ ] **Step 5: Commit**

```bash
git add src/ocrhub/adapters/surya_adapter.py tests/adapters/test_surya_adapter.py
git commit -m "feat: add Surya adapter (opt-in engine)"
```

---

### Task 10: PaddleOCR adapter (opt-in)

**Files:**
- Create: `src/ocrhub/adapters/paddleocr_adapter.py`
- Test: `tests/adapters/test_paddleocr_adapter.py`

**Interfaces:**
- Consumes: `OcrAdapter` (Task 3), `OcrResult`/`PageResult` (Task 2), `is_pdf`/`rasterize_pdf` (Task 4).
- Produces: `PaddleOcrAdapter` class, `name = "paddleocr"`, `available()` returns `True` only if `paddleocr` is importable, `extract(file_bytes, filename)` handles images and PDFs.

- [ ] **Step 1: Write the failing test**

```python
# tests/adapters/test_paddleocr_adapter.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/test_paddleocr_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ocrhub.adapters.paddleocr_adapter'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ocrhub/adapters/paddleocr_adapter.py
import io
import time

from PIL import Image

from ocrhub.models import OcrResult, PageResult
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
            texts = [entry[1][0] for entry in lines]
            confidences = [entry[1][1] for entry in lines]
            text = "\n".join(texts)
            confidence = sum(confidences) / len(confidences) if confidences else None
            pages.append(PageResult(page_number=i, text=text, confidence=confidence))

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

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/adapters/test_paddleocr_adapter.py -v`
Expected: PASS

Note: this is the known-fragile engine (per spec Risks). If `pip install paddleocr paddlepaddle` fails or the `.ocr()` return shape differs from what's mocked here, pin the exact working versions once found and update this adapter's parsing to match — the adapter boundary (`available`/`extract`) stays the same either way.

- [ ] **Step 5: Commit**

```bash
git add src/ocrhub/adapters/paddleocr_adapter.py tests/adapters/test_paddleocr_adapter.py
git commit -m "feat: add PaddleOCR adapter (opt-in engine)"
```

---

### Task 11: Ollama/DeepSeek adapter

**Files:**
- Create: `src/ocrhub/adapters/ollama_adapter.py`
- Test: `tests/adapters/test_ollama_adapter.py`

**Interfaces:**
- Consumes: `OcrAdapter` (Task 3), `OcrResult`/`PageResult` (Task 2), `is_pdf`/`rasterize_pdf` (Task 4).
- Produces: `OllamaAdapter(host: str | None = None, model: str = "deepseek-vl")` class, `name = "ollama-deepseek"`, `available()` returns `True` only if a host is configured (constructor arg or `OLLAMA_HOST` env var) and `GET {host}/api/tags` succeeds within a short timeout, `extract(file_bytes, filename)` posts each page image (base64) to `{host}/api/generate` with a fixed OCR prompt.

- [ ] **Step 1: Write the failing test**

```python
# tests/adapters/test_ollama_adapter.py
import httpx
import pytest

from ocrhub.adapters.ollama_adapter import OllamaAdapter


def test_available_false_when_no_host_configured(monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert OllamaAdapter(host=None).available() is False


def test_available_false_when_host_unreachable():
    adapter = OllamaAdapter(host="http://localhost:1")  # nothing listens here
    assert adapter.available() is False


def test_available_true_when_host_responds(monkeypatch):
    adapter = OllamaAdapter(host="http://fake-ollama:11434")

    def fake_get(url, timeout):
        assert url == "http://fake-ollama:11434/api/tags"
        return httpx.Response(200, json={"models": []})

    monkeypatch.setattr(httpx, "get", fake_get)
    assert adapter.available() is True


def test_extract_posts_image_and_parses_response(monkeypatch, sample_image_bytes):
    adapter = OllamaAdapter(host="http://fake-ollama:11434", model="deepseek-vl")

    def fake_post(url, json, timeout):
        assert url == "http://fake-ollama:11434/api/generate"
        assert json["model"] == "deepseek-vl"
        assert json["images"]
        return httpx.Response(200, json={"response": "OCRHUB TEST"})

    monkeypatch.setattr(httpx, "post", fake_post)
    result = adapter.extract(sample_image_bytes, "sample.png")

    assert result.ok is True
    assert result.text == "OCRHUB TEST"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/test_ollama_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ocrhub.adapters.ollama_adapter'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ocrhub/adapters/ollama_adapter.py
import base64
import os
import time

import httpx

from ocrhub.models import OcrResult, PageResult
from ocrhub.pdf_utils import is_pdf, rasterize_pdf

OCR_PROMPT = "Transcribe all text visible in this image exactly as it appears. Output only the text."


class OllamaAdapter:
    name = "ollama-deepseek"

    def __init__(self, host: str | None = None, model: str = "deepseek-vl"):
        self.host = host if host is not None else os.environ.get("OLLAMA_HOST")
        self.model = model

    def available(self) -> bool:
        if not self.host:
            return False
        try:
            resp = httpx.get(f"{self.host}/api/tags", timeout=2.0)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    def extract(self, file_bytes: bytes, filename: str) -> OcrResult:
        start = time.monotonic()

        if is_pdf(filename):
            page_images = rasterize_pdf(file_bytes)
        else:
            page_images = [file_bytes]

        pages: list[PageResult] = []
        for i, page_bytes in enumerate(page_images, start=1):
            encoded = base64.b64encode(page_bytes).decode("ascii")
            resp = httpx.post(
                f"{self.host}/api/generate",
                json={"model": self.model, "prompt": OCR_PROMPT, "images": [encoded], "stream": False},
                timeout=120.0,
            )
            resp.raise_for_status()
            text = resp.json().get("response", "")
            pages.append(PageResult(page_number=i, text=text))

        elapsed_ms = int((time.monotonic() - start) * 1000)
        full_text = "\n".join(p.text for p in pages)
        return OcrResult(
            engine=self.name,
            text=full_text,
            pages=pages,
            confidence=None,
            elapsed_ms=elapsed_ms,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/adapters/test_ollama_adapter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ocrhub/adapters/ollama_adapter.py tests/adapters/test_ollama_adapter.py
git commit -m "feat: add Ollama/DeepSeek vision adapter"
```

---

### Task 12: Wire all adapters into the registry

**Files:**
- Modify: `src/ocrhub/api.py` (`build_registry`)
- Test: `tests/test_api.py` (extend)

**Interfaces:**
- Consumes: `SuryaAdapter` (Task 9), `PaddleOcrAdapter` (Task 10), `OllamaAdapter` (Task 11).
- Produces: `build_registry()` now registers all five adapters; unavailable ones simply won't appear in `available_engines()`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_api.py
from ocrhub.api import build_registry


def test_build_registry_registers_all_five_engines():
    registry = build_registry()
    names = {adapter.name for adapter in registry.all()}
    assert names == {"pdfplumber", "tesseract", "surya", "paddleocr", "ollama-deepseek"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api.py::test_build_registry_registers_all_five_engines -v`
Expected: FAIL — `names` only contains `{"pdfplumber", "tesseract"}`

- [ ] **Step 3: Update build_registry**

```python
# src/ocrhub/api.py — replace the build_registry function
from ocrhub.adapters.ollama_adapter import OllamaAdapter
from ocrhub.adapters.paddleocr_adapter import PaddleOcrAdapter
from ocrhub.adapters.pdfplumber_adapter import PdfplumberAdapter
from ocrhub.adapters.surya_adapter import SuryaAdapter
from ocrhub.adapters.tesseract_adapter import TesseractAdapter


def build_registry() -> EngineRegistry:
    registry = EngineRegistry()
    registry.register(PdfplumberAdapter())
    registry.register(TesseractAdapter())
    registry.register(SuryaAdapter())
    registry.register(PaddleOcrAdapter())
    registry.register(OllamaAdapter())
    return registry
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ocrhub/api.py tests/test_api.py
git commit -m "feat: register all five engine adapters in the default registry"
```

---

### Task 13: MCP server

**Files:**
- Create: `src/ocrhub/mcp_server.py`
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `EngineRegistry` (Task 3), `process_document` (Task 7), `build_registry` (Task 12).
- Produces:
  - `build_mcp_server(registry: EngineRegistry) -> FastMCP` registering one tool, `ocr_document(file_base64: str, filename: str, engines: list[str]) -> dict`, which base64-decodes the file, calls `process_document`, and returns `{"results": [...]}` shaped like the REST API's `/ocr` response.
  - `mcp_asgi_app(registry: EngineRegistry)` returns the mountable Starlette app (`FastMCP.streamable_http_app()`), for wiring into `main.py` at `/mcp`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mcp_server.py
import base64

import pytest

from ocrhub.mcp_server import build_mcp_server
from ocrhub.models import OcrResult
from ocrhub.registry import EngineRegistry


class StubAdapter:
    name = "stub"

    def available(self) -> bool:
        return True

    def extract(self, file_bytes: bytes, filename: str) -> OcrResult:
        assert file_bytes == b"hello"
        return OcrResult(engine=self.name, text="stub text", elapsed_ms=1)


@pytest.mark.asyncio
async def test_ocr_document_tool_decodes_and_runs_engine():
    registry = EngineRegistry()
    registry.register(StubAdapter())
    server = build_mcp_server(registry)

    tool = await server.get_tool("ocr_document")
    result = await tool.run(
        {
            "file_base64": base64.b64encode(b"hello").decode("ascii"),
            "filename": "f.png",
            "engines": ["stub"],
        }
    )

    assert result["results"][0]["engine"] == "stub"
    assert result["results"][0]["text"] == "stub text"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mcp_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ocrhub.mcp_server'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ocrhub/mcp_server.py
import base64

from mcp.server.fastmcp import FastMCP

from ocrhub.registry import EngineRegistry
from ocrhub.service import process_document


def build_mcp_server(registry: EngineRegistry) -> FastMCP:
    mcp = FastMCP("ocrhub")

    @mcp.tool()
    def ocr_document(file_base64: str, filename: str, engines: list[str]) -> dict:
        """Run one or more OCR engines over a base64-encoded document and return normalized results."""
        file_bytes = base64.b64decode(file_base64)
        results = process_document(registry, file_bytes, filename, engines)
        return {"results": [vars(r) | {"pages": [vars(p) for p in r.pages]} for r in results]}

    return mcp


def mcp_asgi_app(registry: EngineRegistry):
    return build_mcp_server(registry).streamable_http_app()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_mcp_server.py -v`
Expected: PASS

Note: `server.get_tool(...)` / `tool.run(...)` reflect the `mcp` Python SDK's `FastMCP` testing surface as of late 2025/early 2026 — if the installed SDK version exposes tools differently, adjust the test's tool-invocation call only; `ocr_document`'s own signature and return shape are unaffected.

- [ ] **Step 5: Commit**

```bash
git add src/ocrhub/mcp_server.py tests/test_mcp_server.py
git commit -m "feat: add MCP server exposing ocr_document tool"
```

---

### Task 14: Web UI

**Files:**
- Create: `src/ocrhub/web/templates/index.html`
- Create: `src/ocrhub/web/static/app.js`
- Modify: `src/ocrhub/api.py` (mount templates/static, add `GET /` route)
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `create_app` (Task 8), `/engines` and `/ocr` REST routes (Task 8).
- Produces: `GET /` renders `index.html`; static files served under `/static/`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_web.py
from fastapi.testclient import TestClient

from ocrhub.api import build_registry, create_app


def test_index_page_loads():
    client = TestClient(create_app(build_registry()))
    resp = client.get("/")

    assert resp.status_code == 200
    assert "ocrHub" in resp.text
    assert 'id="engine-list"' in resp.text


def test_static_app_js_is_served():
    client = TestClient(create_app(build_registry()))
    resp = client.get("/static/app.js")

    assert resp.status_code == 200
    assert "text/javascript" in resp.headers["content-type"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_web.py -v`
Expected: FAIL — `GET /` returns 404 (no such route yet)

- [ ] **Step 3: Write the template**

```html
<!-- src/ocrhub/web/templates/index.html -->
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>ocrHub</title>
</head>
<body>
  <h1>ocrHub</h1>
  <p>Upload a document, pick engines, compare results.</p>

  <form id="ocr-form">
    <input type="file" id="file-input" name="file" required />
    <fieldset id="engine-list">
      <legend>Engines</legend>
    </fieldset>
    <button type="submit">Run OCR</button>
  </form>

  <div id="results"></div>

  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 4: Write the client script**

```javascript
// src/ocrhub/web/static/app.js
async function loadEngines() {
  const resp = await fetch("/engines");
  const data = await resp.json();
  const container = document.getElementById("engine-list");
  data.engines.forEach((name) => {
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.name = "engines";
    checkbox.value = name;
    label.appendChild(checkbox);
    label.append(` ${name}`);
    container.appendChild(label);
  });
}

async function runOcr(event) {
  event.preventDefault();
  const form = document.getElementById("ocr-form");
  const formData = new FormData(form);
  const resp = await fetch("/ocr", { method: "POST", body: formData });
  const data = await resp.json();

  const resultsDiv = document.getElementById("results");
  resultsDiv.innerHTML = "";
  data.results.forEach((result) => {
    const block = document.createElement("pre");
    block.textContent = `[${result.engine}] (${result.elapsed_ms}ms)\n${result.error || result.text}`;
    resultsDiv.appendChild(block);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  loadEngines();
  document.getElementById("ocr-form").addEventListener("submit", runOcr);
});
```

- [ ] **Step 5: Wire routes into the app**

```python
# src/ocrhub/api.py — add near the top and inside create_app
from pathlib import Path

from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

WEB_DIR = Path(__file__).parent / "web"
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

# inside create_app(), after `app = FastAPI(title="ocrHub")`:
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

@app.get("/", response_class=HTMLResponse)
def index(request):
    return templates.TemplateResponse("index.html", {"request": request})
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_web.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/ocrhub/web src/ocrhub/api.py tests/test_web.py
git commit -m "feat: add web UI for drag-drop OCR comparison"
```

---

### Task 15: Application entrypoint

**Files:**
- Create: `src/ocrhub/main.py`

**Interfaces:**
- Consumes: `create_app`, `build_registry` (Task 8/12/14), `mcp_asgi_app` (Task 13).
- Produces: a single ASGI `app` object (FastAPI app with `/mcp` mounted) that `uvicorn ocrhub.main:app` can serve, plus a `if __name__ == "__main__"` block for `python -m ocrhub.main`.

- [ ] **Step 1: Write main.py**

```python
# src/ocrhub/main.py
import uvicorn

from ocrhub.api import build_registry, create_app
from ocrhub.mcp_server import mcp_asgi_app

registry = build_registry()
app = create_app(registry)
app.mount("/mcp", mcp_asgi_app(registry))


def run() -> None:
    uvicorn.run("ocrhub.main:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    run()
```

- [ ] **Step 2: Verify it starts locally**

Run: `python -m ocrhub.main &` then `curl -s localhost:8000/health` then stop the process.
Expected: `{"status":"ok"}`, then kill the background process.

- [ ] **Step 3: Commit**

```bash
git add src/ocrhub/main.py
git commit -m "feat: add application entrypoint mounting REST API, web UI, and MCP server"
```

---

### Task 16: Dockerfile with build-time engine selection

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`

**Interfaces:**
- Consumes: `pyproject.toml` optional-dependency extras (Task 1), `ocrhub.main:app` (Task 15).
- Produces: an image built via `docker build --build-arg ENGINES=surya,paddleocr -t ocrhub .` that serves the app on port 8000.

- [ ] **Step 1: Write .dockerignore**

```
__pycache__/
*.pyc
.venv/
.git/
.pytest_cache/
tests/
docs/
```

- [ ] **Step 2: Write Dockerfile**

```dockerfile
FROM python:3.11-slim

# tesseract-ocr binary is required by the Tesseract adapter (default-on engine)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

ARG ENGINES=""
RUN pip install --no-cache-dir --upgrade pip \
    && if [ -n "$ENGINES" ]; then \
         pip install --no-cache-dir ".[$ENGINES]"; \
       else \
         pip install --no-cache-dir .; \
       fi

EXPOSE 8000
CMD ["python", "-m", "ocrhub.main"]
```

- [ ] **Step 3: Build and smoke test**

Run:
```bash
docker build --build-arg ENGINES=surya,paddleocr -t ocrhub .
docker run --rm -p 8000:8000 ocrhub &
curl -s localhost:8000/health
curl -s localhost:8000/engines
```
Expected: `{"status":"ok"}`, and `/engines` includes at least `pdfplumber` and `tesseract` (surya/paddleocr appear too if their install succeeded — this is where the PaddleOCR risk from the spec would surface; if it fails, pin working versions in `pyproject.toml`'s `paddleocr` extra and rebuild).

- [ ] **Step 4: Commit**

```bash
git add Dockerfile .dockerignore
git commit -m "feat: add Dockerfile with build-time engine selection"
```

---

### Task 17: CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `pyproject.toml` `dev` extra (Task 1), full test suite (Tasks 2-14).
- Produces: a GitHub Actions workflow running on every push/PR that installs the base package + `dev` extra + `tesseract-ocr` system package, then runs `pytest`. Surya/PaddleOCR/Ollama tests are skipped automatically (their `available()`/`pytestmark` guards already handle absence in Tasks 9-11).

- [ ] **Step 1: Write the workflow**

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install system deps
        run: sudo apt-get update && sudo apt-get install -y tesseract-ocr
      - name: Install ocrhub
        run: pip install -e ".[dev]"
      - name: Run tests
        run: pytest -v
```

- [ ] **Step 2: Verify locally**

Run: `pip install -e ".[dev]" && pytest -v`
Expected: all tests PASS or SKIPPED (Surya/PaddleOCR skip if those extras aren't installed locally; Ollama tests don't need a real server since they're fully mocked).

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "chore: add CI workflow running pytest on push"
```

---

### Task 18: README

**Files:**
- Create: `README.md`

**Interfaces:**
- Consumes: nothing code-level — documents Tasks 1-17's end result.
- Produces: a README covering why the project exists, quickstart, engine comparison table, and attribution footer (per spec's "Repo & publishing" section).

- [ ] **Step 1: Write README.md**

```markdown
# ocrHub

One Docker image, several OCR engines, one API. Built after running
the same "which OCR engine works best for this document" comparison
by hand across two separate OCR pipeline projects — this bundles that
comparison into something you can run in one command.

## Quickstart

```bash
docker build --build-arg ENGINES=surya,paddleocr -t ocrhub .
docker run -p 8000:8000 -e OLLAMA_HOST=http://host.docker.internal:11434 ocrhub
```

Open `http://localhost:8000` to upload a document and compare engines
side by side, or call the REST API directly:

```bash
curl -s http://localhost:8000/engines

curl -s -F "file=@document.pdf" -F "engines=tesseract" -F "engines=pdfplumber" \
  http://localhost:8000/ocr
```

An MCP server is also mounted at `/mcp`, exposing an `ocr_document`
tool for agent frameworks that speak MCP.

## Engines

| Engine | Type | Install | Notes |
|---|---|---|---|
| Tesseract | local, CPU | default-on | classic baseline OCR |
| pdfplumber | local, CPU | default-on | text extraction for born-digital PDFs, not OCR |
| Surya | local, GPU-friendly | `ENGINES=surya` | modern layout-aware OCR |
| PaddleOCR | local, GPU-friendly | `ENGINES=paddleocr` | strong multilingual support |
| DeepSeek (via Ollama) | self-hosted vision model | set `OLLAMA_HOST` | point at your own Ollama instance |

## Build args

`ENGINES` is a comma-separated list of optional extras to install at
build time (currently: `surya`, `paddleocr`). Tesseract and pdfplumber
are always installed. Leave `ENGINES` unset for the smallest image.

## Why

Built and maintained by [your name/business] — automation and
document-processing pipelines. If you need this kind of thing built
into your own pipeline, [link to your site/contact].

## License

MIT — see `LICENSE`.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with quickstart and engine comparison table"
```

---

## Self-Review Notes

- **Spec coverage:** engines (Tesseract/pdfplumber/Surya/PaddleOCR/Ollama-DeepSeek) → Tasks 5,6,9,10,11; build-time selection → Tasks 1,16; three interfaces (UI/REST/MCP) sharing one service → Tasks 7,8,13,14,15; per-engine error isolation → Task 7; PaddleOCR risk called out → Task 10/16; Ollama availability degradation → Task 11; testing strategy (fixtures, CI skip GPU engines) → Tasks 4,17; repo/README/license → Tasks 1,18. All spec sections are covered.
- **Placeholder scan:** no TBD/TODO markers; every step has runnable code.
- **Type consistency:** `OcrResult`/`PageResult` field names (`engine`, `text`, `pages`, `confidence`, `elapsed_ms`, `error`, `ok`) are identical across Tasks 2, 5, 6, 7, 8, 9, 10, 11, 13, 14. `EngineRegistry.available_engines()`/`.get()`/`.register()`/`.all()` (Task 3) are used with the same signatures in Tasks 7, 8, 12. `process_document(registry, file_bytes, filename, engine_names)` (Task 7) is called identically in Tasks 8 and 13.
