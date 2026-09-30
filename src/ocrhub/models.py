from dataclasses import dataclass, field


@dataclass
class BoxResult:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    confidence: float | None = None
    reading_order: int | None = None
    region_type: str | None = None
    # Original markup for engines that return it (Datalab): keeps lists, tables
    # and bullets that the plain `text` flattens away.
    html: str | None = None
    # Font info for engines that read a PDF's text layer (pdfplumber):
    # {"font": str, "size": float, "bold": bool, "italic": bool}.
    style: dict | None = None
    # Per-word boxes nested in a line box (Tesseract): text, x0..y1, confidence.
    words: list[dict] | None = None
    # Cropped picture as base64 JPEG, for region_type "Picture" boxes; `text` is its alt text/caption.
    image: str | None = None


@dataclass
class PageResult:
    page_number: int
    text: str
    confidence: float | None = None
    boxes: list["BoxResult"] = field(default_factory=list)
    image_base64: str | None = None
    width: float | None = None
    height: float | None = None


@dataclass
class OcrResult:
    engine: str
    text: str
    pages: list[PageResult] = field(default_factory=list)
    confidence: float | None = None
    elapsed_ms: int = 0
    error: str | None = None
    # Engine's untouched response (Datalab's block tree), saved to disk for
    # anyone using the output directly; not sent to the dashboard.
    raw: dict | None = None

    @property
    def ok(self) -> bool:
        return self.error is None
