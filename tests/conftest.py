import io

import fitz  # PyMuPDF
import pytest
from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFont

_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial.ttf",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


@pytest.fixture
def sample_image_bytes() -> bytes:
    img = Image.new("RGB", (500, 120), color="white")
    draw = ImageDraw.Draw(img)
    font = _load_font(32)
    draw.text((10, 40), "OCRHUB TEST", fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def sample_born_digital_pdf_bytes() -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=14)
    pdf.cell(0, 10, "OCRHUB TEXT LAYER")
    return bytes(pdf.output())


@pytest.fixture
def sample_scanned_pdf_bytes(sample_image_bytes: bytes) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    rect = fitz.Rect(0, 0, page.rect.width, page.rect.height)
    page.insert_image(rect, stream=sample_image_bytes)
    buf = doc.tobytes()
    doc.close()
    return buf
