import base64
import io

from PIL import Image

from ocrhub.imaging import crop_jpeg_b64


def test_crop_returns_jpeg_of_the_region():
    img = Image.new("RGB", (400, 300), "white")
    out = crop_jpeg_b64(img, (10, 20, 110, 70))
    crop = Image.open(io.BytesIO(base64.b64decode(out)))
    assert crop.format == "JPEG"
    assert crop.size == (100, 50)


def test_crop_is_downscaled_to_800px():
    img = Image.new("RGB", (3000, 2000), "white")
    out = crop_jpeg_b64(img, (0, 0, 3000, 2000))
    assert max(Image.open(io.BytesIO(base64.b64decode(out))).size) == 800


def test_crop_clamps_to_image_and_rejects_tiny_regions():
    img = Image.new("RGB", (100, 100), "white")
    assert crop_jpeg_b64(img, (-50, -50, 40, 40)) is not None
    assert crop_jpeg_b64(img, (10, 10, 11, 11)) is None
    assert crop_jpeg_b64(img, ("a", 0, 1, 1)) is None
