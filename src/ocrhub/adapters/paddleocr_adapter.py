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
