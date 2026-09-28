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
