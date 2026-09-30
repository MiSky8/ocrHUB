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

            # Tesseract reports words tagged with block/paragraph/line numbers, in
            # reading order. Group them into one box per line (comparable to the
            # other engines) and keep the words, with their confidences, nested.
            lines: dict[tuple[int, int, int], list[dict]] = {}
            for j, word in enumerate(data["text"]):
                if not word.strip():
                    continue
                key = (data["block_num"][j], data["par_num"][j], data["line_num"][j])
                left, top = data["left"][j], data["top"][j]
                conf = data["conf"][j]
                lines.setdefault(key, []).append(
                    {
                        "text": word,
                        "x0": float(left),
                        "y0": float(top),
                        "x1": float(left + data["width"][j]),
                        "y1": float(top + data["height"][j]),
                        "confidence": float(conf) if conf != -1 else None,
                    }
                )

            boxes: list[BoxResult] = []
            all_confs: list[float] = []
            for order, words in enumerate(lines.values()):
                confs = [w["confidence"] for w in words if w["confidence"] is not None]
                all_confs.extend(confs)
                boxes.append(
                    BoxResult(
                        text=" ".join(w["text"] for w in words),
                        x0=min(w["x0"] for w in words),
                        y0=min(w["y0"] for w in words),
                        x1=max(w["x1"] for w in words),
                        y1=max(w["y1"] for w in words),
                        confidence=sum(confs) / len(confs) if confs else None,
                        reading_order=order,
                        words=words,
                    )
                )
            text = "\n".join(box.text for box in boxes)
            page_confidence = sum(all_confs) / len(all_confs) if all_confs else None

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
        return OcrResult(
            engine=self.name,
            text=full_text,
            pages=pages,
            confidence=None,
            elapsed_ms=elapsed_ms,
        )
