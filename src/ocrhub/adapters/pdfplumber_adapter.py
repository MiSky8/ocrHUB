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
