import io
import time
from collections import Counter

import pdfplumber

from ocrhub.models import BoxResult, OcrResult, PageResult
from ocrhub.pdf_utils import is_pdf


_BLANK = "\u2800"  # braille blank, used as invisible padding by some renderers


def _style_of(chars: list[dict]) -> dict:
    """Dominant font of a line: the most frequent (font, size) among its visible characters."""
    visible = [c for c in chars if c["text"].strip() and c["text"] != _BLANK]
    counts = Counter((c.get("fontname") or "", round(float(c.get("size") or 0), 1)) for c in visible)
    (font, size), _ = counts.most_common(1)[0]
    if "+" in font:  # strip the subset prefix, e.g. ABCDEF+Arial-BoldMT
        font = font.split("+", 1)[1]
    lower = font.lower()
    return {
        "font": font,
        "size": size,
        "bold": "bold" in lower or "black" in lower,
        "italic": "italic" in lower or "oblique" in lower,
    }


def _line_boxes(page) -> list[BoxResult]:
    # Near-zero-size characters (< 1pt) are invisible text-layer padding, not content.
    visible_page = page.filter(lambda o: o.get("object_type") != "char" or o.get("size", 1) >= 1)
    boxes: list[BoxResult] = []
    for line in visible_page.extract_text_lines(return_chars=True):
        text = line["text"].replace(_BLANK, "").strip()
        if not text:
            continue
        boxes.append(
            BoxResult(
                text=text,
                x0=float(line["x0"]),
                y0=float(line["top"]),
                x1=float(line["x1"]),
                y1=float(line["bottom"]),
                reading_order=len(boxes),
                region_type="Text",
                style=_style_of(line["chars"]),
            )
        )
    return boxes


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
                pages.append(
                    PageResult(
                        page_number=i,
                        text=text,
                        boxes=_line_boxes(page),
                        width=float(page.width),
                        height=float(page.height),
                    )
                )

        elapsed_ms = int((time.monotonic() - start) * 1000)
        full_text = "\n".join(p.text for p in pages)
        return OcrResult(
            engine=self.name,
            text=full_text,
            pages=pages,
            confidence=None,
            elapsed_ms=elapsed_ms,
        )
