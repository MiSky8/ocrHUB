import io

import fitz  # PyMuPDF
import pytest
from fpdf import FPDF
from PIL import Image, ImageDraw


@pytest.fixture
def sample_image_bytes() -> bytes:
    img = Image.new("RGB", (400, 100), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((10, 40), "OCRHUB TEST", fill="black")
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
