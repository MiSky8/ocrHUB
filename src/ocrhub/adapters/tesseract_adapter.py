import base64
import io
import shutil
import time

import pytesseract
from PIL import Image
from pytesseract import Output

from ocrhub.models import BoxResult, OcrResult, PageResult
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
            data = pytesseract.image_to_data(img, output_type=Output.DICT)

            boxes: list[BoxResult] = []
            lines: dict[tuple[int, int, int], list[str]] = {}
            for j, word in enumerate(data["text"]):
                if not word.strip():
                    continue
                line_key = (data["block_num"][j], data["par_num"][j], data["line_num"][j])
                lines.setdefault(line_key, []).append(word)

                left, top = data["left"][j], data["top"][j]
                width, height = data["width"][j], data["height"][j]
                conf = data["conf"][j]
                boxes.append(
                    BoxResult(
                        text=word,
                        x0=float(left),
                        y0=float(top),
                        x1=float(left + width),
                        y1=float(top + height),
                        confidence=float(conf) if conf != -1 else None,
                    )
                )
            text = "\n".join(" ".join(words) for words in lines.values())

            png_buf = io.BytesIO()
            img.convert("RGB").save(png_buf, format="PNG")
            image_base64 = base64.b64encode(png_buf.getvalue()).decode("ascii")

            pages.append(
                PageResult(page_number=i, text=text, boxes=boxes, image_base64=image_base64)
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
