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
