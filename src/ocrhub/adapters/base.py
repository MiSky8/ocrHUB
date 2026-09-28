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
