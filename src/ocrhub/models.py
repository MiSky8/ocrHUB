from dataclasses import dataclass, field


@dataclass
class BoxResult:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    confidence: float | None = None


@dataclass
class PageResult:
    page_number: int
    text: str
    confidence: float | None = None
    boxes: list["BoxResult"] = field(default_factory=list)
    image_base64: str | None = None


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
