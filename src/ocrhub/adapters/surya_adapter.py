import base64
import gc
import html
import io
import logging
import os
import shutil
import time
from pathlib import Path

from PIL import Image

from ocrhub.adapters._text import strip_html
from ocrhub.models import BoxResult, OcrResult, PageResult
from ocrhub.pdf_utils import is_pdf, rasterize_pdf


logger = logging.getLogger(__name__)


def remove_incomplete_models(cache_dir, is_complete) -> list[Path]:
    """Delete model dirs (<cache>/<name>/<version>) that failed to finish downloading.

    Surya downloads into a temp dir and then moves the files into place. If that
    is interrupted (e.g. the disk fills up), a half-populated dir is left behind
    and every later download fails with "Destination path ... already exists".
    Removing such dirs lets Surya download them again.
    """
    removed: list[Path] = []
    root = Path(cache_dir)
    if not root.is_dir():
        return removed
    for model_dir in sorted(root.glob("*/*")):
        if model_dir.is_dir() and not is_complete(model_dir):
            logger.warning("Removing incomplete Surya model download: %s", model_dir)
            shutil.rmtree(model_dir, ignore_errors=True)
            removed.append(model_dir)
    return removed


def _heal_model_cache() -> None:
    try:
        from surya.common.s3 import check_manifest
        from surya.settings import settings
    except ImportError:
        return

    remove_incomplete_models(settings.MODEL_CACHE_DIR, check_manifest)


# Surya layout label -> the region names the dashboard already knows from Datalab.
# Labels without an entry keep Surya's own name (Equation, Code, Form, ...).
_REGION_TYPES = {
    "SectionHeader": "Title",
    "Text": "Text",
    "TextInlineMath": "Text",
    "ListItem": "Text",
    "Footnote": "Text",
    "PageHeader": "Header",
    "PageFooter": "Footer",
    "Picture": "Picture",
    "Figure": "Picture",
}
_TABLE_LABELS = frozenset({"Table"})
_PICTURE_LABELS = frozenset({"Picture", "Figure"})
_MAX_PICTURE_SIDE = 800


def _centre(bbox) -> tuple[float, float]:
    return (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2


def _contains(bbox, point) -> bool:
    return bbox[0] <= point[0] <= bbox[2] and bbox[1] <= point[1] <= bbox[3]


def _area(bbox) -> float:
    return max(bbox[2] - bbox[0], 0) * max(bbox[3] - bbox[1], 0)


def _rows(lines: list[dict]) -> list[list[dict]]:
    """Group lines into visual rows, top to bottom, each left to right.

    A line joins a row when its vertical centre falls inside that row's extent.
    Sorting by top edge alone puts a list marker, which sits a little lower
    than its text, on a row of its own after the text.
    """
    rows: list[list] = []  # [top, bottom, lines]
    for ln in sorted(lines, key=lambda ln: _centre(ln["bbox"])[1]):
        cy = _centre(ln["bbox"])[1]
        for row in rows:
            if row[0] <= cy <= row[1]:
                row[0], row[1] = min(row[0], ln["bbox"][1]), max(row[1], ln["bbox"][3])
                row[2].append(ln)
                break
        else:
            rows.append([ln["bbox"][1], ln["bbox"][3], [ln]])
    rows.sort(key=lambda row: row[0])
    return [sorted(row[2], key=lambda ln: ln["bbox"][0]) for row in rows]


def _row_texts(lines: list[dict]) -> list[str]:
    """One string per visual row, its lines joined with spaces."""
    return [" ".join(ln["text"] for ln in row) for row in _rows(lines)]


def _lines_in(lines: list[dict], bbox) -> list[dict]:
    """Lines whose centre is inside bbox, in reading order."""
    inside = [ln for ln in lines if _contains(bbox, _centre(ln["bbox"]))]
    return [ln for row in _rows(inside) for ln in row]


def _table_text(cells: list[dict], lines: list[dict]) -> str:
    """One line per table row, cells separated by ' | ', in column order."""
    rows: dict[int, list[dict]] = {}
    for cell in cells:
        rows.setdefault(cell["row"], []).append(cell)
    return "\n".join(
        " | ".join(
            " ".join(_row_texts(_lines_in(lines, c["bbox"])))
            for c in sorted(rows[r], key=lambda c: c["col"])
        )
        for r in sorted(rows)
    )


def _table_html(cells: list[dict], lines: list[dict]) -> str:
    """<table> from Surya's table cells, each filled with the OCR lines inside it."""
    rows: dict[int, list[dict]] = {}
    for cell in cells:
        rows.setdefault(cell["row"], []).append(cell)
    out = []
    for row_id in sorted(rows):
        tds = []
        for cell in sorted(rows[row_id], key=lambda c: c["col"]):
            text = "<br>".join(html.escape(t) for t in _row_texts(_lines_in(lines, cell["bbox"])))
            tag = "th" if cell["header"] else "td"
            attrs = "".join(
                f' {name}="{value}"'
                for name, value in (("colspan", cell["colspan"]), ("rowspan", cell["rowspan"]))
                if value and value > 1
            )
            tds.append(f"<{tag}{attrs}>{text}</{tag}>")
        out.append("<tr>" + "".join(tds) + "</tr>")
    return "<table>" + "".join(out) + "</table>"


def build_region_boxes(
    lines: list[dict],
    regions: list[dict],
    tables: dict[int, list[dict]] | None = None,
    pictures: dict[int, str] | None = None,
) -> list[BoxResult]:
    """One box per layout region, in the layout model's reading order.

    lines:    OCR lines, {"text", "bbox", "confidence" (0-1 or None)}
    regions:  layout regions, {"label", "position", "bbox"}
    tables:   region index -> table cells {"bbox", "row", "col", "rowspan", "colspan", "header"}
    pictures: region index -> cropped picture as base64 JPEG

    A line goes to the smallest region around its centre. Lines outside every
    region are kept as boxes without a region type or reading order, so no
    recognised text is lost.
    """
    tables = tables or {}
    pictures = pictures or {}
    usable = [i for i, r in enumerate(regions) if r["label"] != "Blank"]
    owned: dict[int, list[dict]] = {i: [] for i in usable}
    orphans: list[dict] = []
    for line in lines:
        point = _centre(line["bbox"])
        homes = [i for i in usable if _contains(regions[i]["bbox"], point)]
        if homes:
            owned[min(homes, key=lambda i: _area(regions[i]["bbox"]))].append(line)
        else:
            orphans.append(line)

    boxes: list[tuple[int, BoxResult]] = []
    for i in usable:
        region = regions[i]
        label = region["label"]
        inside = owned[i]
        if not inside and label not in _PICTURE_LABELS and i not in tables:
            continue
        confs = [ln["confidence"] for ln in inside if ln["confidence"] is not None]
        x0, y0, x1, y1 = (float(v) for v in region["bbox"])
        box = BoxResult(
            text="\n".join(_row_texts(inside)),
            x0=x0, y0=y0, x1=x1, y1=y1,
            confidence=sum(confs) / len(confs) * 100 if confs else None,
            reading_order=int(region["position"]),
            region_type=_REGION_TYPES.get(label, label),
        )
        if label in _PICTURE_LABELS:
            box.image = pictures.get(i)
        elif i in tables:
            box.html = _table_html(tables[i], inside)
            box.text = _table_text(tables[i], inside) or box.text
        boxes.append((box.reading_order, box))
    boxes.sort(key=lambda pair: pair[0])
    result = [box for _, box in boxes]

    for line in sorted(orphans, key=lambda ln: (ln["bbox"][1], ln["bbox"][0])):
        x0, y0, x1, y1 = (float(v) for v in line["bbox"])
        conf = line["confidence"]
        result.append(
            BoxResult(text=line["text"], x0=x0, y0=y0, x1=x1, y1=y1,
                      confidence=conf * 100 if conf is not None else None)
        )
    return result


def _crop_jpeg_b64(img: Image.Image, bbox) -> str | None:
    """Region crop as a downscaled base64 JPEG, for the dashboard's picture boxes."""
    try:
        x0, y0, x1, y1 = (int(v) for v in bbox)
        crop = img.convert("RGB").crop((max(x0, 0), max(y0, 0), min(x1, img.width), min(y1, img.height)))
        if crop.width < 2 or crop.height < 2:
            return None
        crop.thumbnail((_MAX_PICTURE_SIDE, _MAX_PICTURE_SIDE))
        buf = io.BytesIO()
        crop.save(buf, format="JPEG", quality=70)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:  # noqa: BLE001 - the crop is a nicety; the region is still reported
        return None


def _layout_enabled() -> bool:
    return os.environ.get("SURYA_LAYOUT", "1").strip().lower() not in ("0", "false", "no", "off")


def _free_memory() -> None:
    gc.collect()




class SuryaAdapter:
    name = "surya"

    def available(self) -> bool:
        try:
            import surya.detection  # noqa: F401
            import surya.recognition  # noqa: F401
        except ImportError:
            return False
        return True

    @property
    def _recognition_predictor_cls(self):
        from surya.recognition import RecognitionPredictor

        return RecognitionPredictor

    @property
    def _detection_predictor_cls(self):
        from surya.detection import DetectionPredictor

        return DetectionPredictor

    @property
    def _layout_predictor_cls(self):
        from surya.layout import LayoutPredictor

        return LayoutPredictor

    @property
    def _table_predictor_cls(self):
        from surya.table_rec import TableRecPredictor

        return TableRecPredictor

    def _analyse_layout(self, images: list[Image.Image]):
        """Layout regions per page, and table cells for each Table region.

        Models run one after another and each is released before the next loads:
        Surya on CPU already peaks near 5-6 GB, so they must not sit in memory together.
        """
        layout_predictor = self._layout_predictor_cls()
        regions: list[list[dict]] = []
        for img in images:
            [prediction] = layout_predictor([img])
            regions.append(
                [
                    {"label": b.label, "position": b.position, "bbox": [float(v) for v in b.bbox]}
                    for b in prediction.bboxes
                ]
            )
        del layout_predictor
        _free_memory()

        crops: list[tuple[int, int, tuple[float, float]]] = []  # (page, region index, crop origin)
        crop_images: list[Image.Image] = []
        for page_idx, page_regions in enumerate(regions):
            for region_idx, region in enumerate(page_regions):
                if region["label"] in _TABLE_LABELS:
                    x0, y0, x1, y1 = (int(v) for v in region["bbox"])
                    x0, y0 = max(x0, 0), max(y0, 0)
                    x1, y1 = min(x1, images[page_idx].width), min(y1, images[page_idx].height)
                    if x1 - x0 < 2 or y1 - y0 < 2:
                        continue
                    crop_images.append(images[page_idx].convert("RGB").crop((x0, y0, x1, y1)))
                    crops.append((page_idx, region_idx, (float(x0), float(y0))))

        tables: list[dict[int, list[dict]]] = [{} for _ in images]
        if crop_images:
            table_predictor = self._table_predictor_cls()
            predictions = table_predictor(crop_images)
            del table_predictor
            _free_memory()
            for (page_idx, region_idx, (ox, oy)), prediction in zip(crops, predictions):
                tables[page_idx][region_idx] = [
                    {
                        "bbox": [c.bbox[0] + ox, c.bbox[1] + oy, c.bbox[2] + ox, c.bbox[3] + oy],
                        "row": c.row_id,
                        "col": c.col_id if c.col_id is not None else 0,
                        "rowspan": c.rowspan or 1,
                        "colspan": c.colspan or 1,
                        "header": bool(c.is_header),
                    }
                    for c in prediction.cells
                ]
        return regions, tables

    def extract(self, file_bytes: bytes, filename: str) -> OcrResult:
        start = time.monotonic()

        if is_pdf(filename):
            page_images = rasterize_pdf(file_bytes)
        else:
            page_images = [file_bytes]

        _heal_model_cache()
        recognition_predictor = self._recognition_predictor_cls()
        detection_predictor = self._detection_predictor_cls()

        images: list[Image.Image] = []
        page_lines: list[list[dict]] = []
        for page_bytes in page_images:
            img = Image.open(io.BytesIO(page_bytes))
            img.load()
            [prediction] = recognition_predictor([img], det_predictor=detection_predictor)
            images.append(img)
            page_lines.append(
                [
                    {
                        "text": strip_html(line.text),
                        "bbox": [float(v) for v in line.bbox],
                        "confidence": line.confidence,
                    }
                    for line in prediction.text_lines
                ]
            )
        del recognition_predictor, detection_predictor
        _free_memory()

        regions: list[list[dict]] | None = None
        tables: list[dict[int, list[dict]]] = [{} for _ in images]
        if _layout_enabled():
            try:
                regions, tables = self._analyse_layout(images)
            except Exception:  # noqa: BLE001 - keep the OCR text if layout can't run
                logger.warning("Surya layout/table analysis failed; returning plain lines", exc_info=True)
                regions = None

        pages: list[PageResult] = []
        for i, (img, lines) in enumerate(zip(images, page_lines), start=1):
            if regions is None:
                boxes = [
                    BoxResult(
                        text=ln["text"],
                        x0=ln["bbox"][0], y0=ln["bbox"][1], x1=ln["bbox"][2], y1=ln["bbox"][3],
                        confidence=ln["confidence"] * 100 if ln["confidence"] is not None else None,
                    )
                    for ln in lines
                ]
                text = "\n".join(ln["text"] for ln in lines)
            else:
                page_regions = regions[i - 1]
                pictures = {
                    idx: _crop_jpeg_b64(img, r["bbox"])
                    for idx, r in enumerate(page_regions)
                    if r["label"] in _PICTURE_LABELS
                }
                boxes = build_region_boxes(lines, page_regions, tables[i - 1], pictures)
                text = "\n\n".join(b.text for b in boxes if b.text)

            confidences = [ln["confidence"] for ln in lines if ln["confidence"] is not None]
            page_confidence = sum(confidences) / len(confidences) if confidences else None

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
        page_confidences = [p.confidence for p in pages if p.confidence is not None]
        overall_confidence = sum(page_confidences) / len(page_confidences) if page_confidences else None
        return OcrResult(
            engine=self.name,
            text=full_text,
            pages=pages,
            confidence=overall_confidence,
            elapsed_ms=elapsed_ms,
        )
