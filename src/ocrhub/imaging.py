import base64
import io

from PIL import Image

MAX_PICTURE_SIDE = 800


def crop_jpeg_b64(img: Image.Image, bbox) -> str | None:
    """Region crop as a downscaled base64 JPEG, for the dashboard's picture boxes."""
    try:
        x0, y0, x1, y1 = (int(v) for v in bbox)
        crop = img.convert("RGB").crop((max(x0, 0), max(y0, 0), min(x1, img.width), min(y1, img.height)))
        if crop.width < 2 or crop.height < 2:
            return None
        crop.thumbnail((MAX_PICTURE_SIDE, MAX_PICTURE_SIDE))
        buf = io.BytesIO()
        crop.save(buf, format="JPEG", quality=70)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:  # noqa: BLE001 - the crop is a nicety; the region is still reported
        return None
