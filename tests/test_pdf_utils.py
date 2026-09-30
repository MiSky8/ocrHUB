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


def test_normalize_image_applies_exif_rotation_and_reencodes_as_png():
    import io

    from PIL import Image

    from ocrhub.pdf_utils import normalize_image

    img = Image.new("RGB", (400, 200), "white")
    exif = Image.Exif()
    exif[0x0112] = 6  # stored sideways: displayed rotated 90 degrees
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)

    data, name = normalize_image(buf.getvalue(), "IMG_1.jpeg")

    out = Image.open(io.BytesIO(data))
    assert out.format == "PNG"
    assert out.size == (200, 400)
    assert name == "IMG_1.png"


def test_normalize_image_leaves_pdfs_and_non_images_alone():
    from ocrhub.pdf_utils import normalize_image

    assert normalize_image(b"%PDF-1.4", "a.pdf") == (b"%PDF-1.4", "a.pdf")
    assert normalize_image(b"not an image", "a.jpg") == (b"not an image", "a.jpg")
