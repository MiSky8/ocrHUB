import base64
import io
import logging
import shutil
import time
from pathlib import Path

from PIL import Image

from ocrhub.adapters._text import strip_html
from ocrhub.models import BoxResult, OcrResult, PageResult
from ocrhub.pdf_utils import is_pdf, rasterize_pdf


logger = logging.getLogger(__name__)


def remove_incomplete_models(cache_dir, is_complete) -> list[Path]:
    """Delete model dirs (<cache>/<name>/<version>) that failed to finish downloading.

    Surya downloads into a temp dir and then moves the files into place. If that
    is interrupted (e.g. the disk fills up), a half-populated dir is left behind
    and every later download fails with "Destination path ... already exists".
    Removing such dirs lets Surya download them again.
    """
    removed: list[Path] = []
    root = Path(cache_dir)
    if not root.is_dir():
        return removed
    for model_dir in sorted(root.glob("*/*")):
        if model_dir.is_dir() and not is_complete(model_dir):
            logger.warning("Removing incomplete Surya model download: %s", model_dir)
            shutil.rmtree(model_dir, ignore_errors=True)
            removed.append(model_dir)
    return removed


def _heal_model_cache() -> None:
    try:
        from surya.common.s3 import check_manifest
        from surya.settings import settings
    except ImportError:
        return

    remove_incomplete_models(settings.MODEL_CACHE_DIR, check_manifest)


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

        _heal_model_cache()
        recognition_predictor = self._recognition_predictor_cls()
        detection_predictor = self._detection_predictor_cls()

        pages: list[PageResult] = []
        for i, page_bytes in enumerate(page_images, start=1):
            img = Image.open(io.BytesIO(page_bytes))
            [prediction] = recognition_predictor([img], det_predictor=detection_predictor)

            boxes: list[BoxResult] = []
            line_texts = [strip_html(line.text) for line in prediction.text_lines]
            for line, line_text in zip(prediction.text_lines, line_texts):
                x0, y0, x1, y1 = line.bbox
                boxes.append(
                    BoxResult(
                        text=line_text,
                        x0=float(x0),
                        y0=float(y0),
                        x1=float(x1),
                        y1=float(y1),
                        confidence=line.confidence * 100 if line.confidence is not None else None,
                    )
                )

            text = "\n".join(line_texts)
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
