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
