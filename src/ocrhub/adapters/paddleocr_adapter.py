import base64
import gc
import io
import logging
import os
import time

from PIL import Image

from ocrhub.adapters._paddle_layout import LAYOUT_MODEL, PICTURE, merge_layout
from ocrhub.models import BoxResult, OcrResult, PageResult
from ocrhub.pdf_utils import is_pdf, rasterize_pdf

logger = logging.getLogger(__name__)

_LAYOUT_REGION_TYPES = ["Text", "Title", "Caption", "Header", "Footer", "Table", "Formula", PICTURE]


def _layout_enabled() -> bool:
    return os.environ.get("PADDLE_LAYOUT", "0").strip().lower() in ("1", "true", "yes", "on")


def _free_memory() -> None:
    gc.collect()


def _plain_line_boxes(lines: list[dict]) -> list[BoxResult]:
    return [
        BoxResult(
            text=ln["text"],
            x0=ln["bbox"][0], y0=ln["bbox"][1], x1=ln["bbox"][2], y1=ln["bbox"][3],
            confidence=ln["confidence"] * 100,
            reading_order=order,
        )
        for order, ln in enumerate(lines)
    ]


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

        # The document orientation/unwarping models are off: they add two model
        # downloads and rewrite the page geometry, so boxes would no longer line
        # up with the page image the dashboard draws.
        return PaddleOCR(
            lang="en",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=True,
        )

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

            boxes = None
            if layouts is not None:
                try:
                    boxes = merge_layout(lines, layouts[i - 1], img)
                except Exception:  # noqa: BLE001 - a bad layout box must not lose the OCR lines
                    logger.warning(
                        "PaddleOCR layout merge failed on page %d; returning plain lines",
                        i, exc_info=True,
                    )
            if boxes is None:
                boxes = _plain_line_boxes(lines)
            text = "\n".join(b.text for b in boxes if b.text)
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
