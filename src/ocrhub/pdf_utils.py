import io

import pymupdf as fitz
from PIL import Image, ImageOps


def is_pdf(filename: str) -> bool:
    return filename.lower().endswith(".pdf")


def rasterize_pdf(file_bytes: bytes, dpi: int = 200) -> list[bytes]:
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages: list[bytes] = []
    try:
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            pages.append(pix.tobytes("png"))
    finally:
        doc.close()
    return pages


def pdf_has_text_layer(file_bytes: bytes, min_chars: int = 10) -> bool:
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    try:
        total_chars = sum(len(page.get_text().strip()) for page in doc)
        return total_chars >= min_chars
    finally:
        doc.close()


MAX_IMAGE_SIDE = 3000


def normalize_image(file_bytes: bytes, filename: str) -> tuple[bytes, str]:
    """Make an uploaded image safe for every engine: apply the EXIF rotation
    (phone photos are stored sideways with a flag), flatten to RGB, cap the long
    side, and re-encode as PNG. iPhone JPEGs are MPO files, which pytesseract
    rejects, and OCR of an unrotated photo would read the page sideways.

    Returns (bytes, filename). PDFs and anything Pillow can't open pass through
    untouched so the engines report their own errors for them."""
    if is_pdf(filename):
        return file_bytes, filename
    try:
        img = Image.open(io.BytesIO(file_bytes))
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
    except Exception:  # noqa: BLE001 - not an image Pillow understands (e.g. HEIC)
        return file_bytes, filename
    if max(img.size) > MAX_IMAGE_SIDE:
        img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return buf.getvalue(), f"{stem}.png"
