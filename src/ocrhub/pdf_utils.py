import pymupdf as fitz


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
