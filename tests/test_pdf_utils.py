from ocrhub.pdf_utils import is_pdf, pdf_has_text_layer, rasterize_pdf


def test_is_pdf_by_filename():
    assert is_pdf("doc.pdf") is True
    assert is_pdf("scan.PDF") is True
    assert is_pdf("photo.png") is False


def test_rasterize_pdf_returns_one_image_per_page(sample_scanned_pdf_bytes):
    pages = rasterize_pdf(sample_scanned_pdf_bytes)
    assert len(pages) == 1
    assert pages[0][:4] == b"\x89PNG"


def test_pdf_has_text_layer_true_for_born_digital(sample_born_digital_pdf_bytes):
    assert pdf_has_text_layer(sample_born_digital_pdf_bytes) is True


def test_pdf_has_text_layer_false_for_scanned(sample_scanned_pdf_bytes):
    assert pdf_has_text_layer(sample_scanned_pdf_bytes) is False
