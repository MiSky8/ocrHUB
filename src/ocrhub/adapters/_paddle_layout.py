"""Merge PaddleOCR text lines with PP-DocLayout regions into dashboard boxes.

Pure functions, no paddle import, so the merge is testable without models.
"""
from PIL import Image

from ocrhub.imaging import crop_jpeg_b64
from ocrhub.models import BoxResult

LAYOUT_MODEL = "PP-DocLayout-S"
PICTURE = "Picture"
TABLE = "Table"

# PP-DocLayout label -> the region_type names the dashboard already uses.
# Labels not listed (page numbers, formula numbers) are ignored and their lines
# stay as plain line boxes.
_REGION_TYPES = {
    "text": "Text",
    "abstract": "Text",
    "content": "Text",
    "reference": "Text",
    "reference_content": "Text",
    "aside_text": "Text",
    "footnote": "Text",
    "paragraph_title": "Title",
    "doc_title": "Title",
    "figure_title": "Caption",
    "header": "Header",
    "footer": "Footer",
    "table": "Table",
    "formula": "Formula",
    "image": PICTURE,
    "chart": PICTURE,
    "seal": PICTURE,
}


def _area(b) -> float:
    return max(b[2] - b[0], 0.0) * max(b[3] - b[1], 0.0)


def _overlap(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix * iy


def _dedupe_pictures(regions: list[dict]) -> list[dict]:
    """PP-DocLayout often reports one figure as both `image` and `chart`; keep the best."""
    kept: list[dict] = []
    for r in sorted(regions, key=lambda r: -r["score"]):
        # A small picture fully inside a larger one is deliberately dropped as a
        # duplicate (the 0.8 * smaller-area test).
        if r["type"] == PICTURE and any(
            k["type"] == PICTURE
            and _overlap(k["bbox"], r["bbox"]) > 0.8 * min(_area(k["bbox"]), _area(r["bbox"]))
            for k in kept
        ):
            continue
        kept.append(r)
    return kept


def _contains(bbox, x: float, y: float) -> bool:
    return bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]


def _line_key(ln: dict):
    return (ln["bbox"][1], ln["bbox"][0])


def _row_order(lines: list[dict]) -> list[dict]:
    """Top-to-bottom rows, left to right within a row.

    A plain (y0, x0) sort splits a table row apart: cells on one row differ by a
    few pixels in y0, so the sort orders them by that jitter instead of by column.
    A line joins the current row when its centre lies inside the row's first line.
    """
    rows: list[list[dict]] = []
    row_span = (0.0, 0.0)
    for ln in sorted(lines, key=_line_key):
        cy = (ln["bbox"][1] + ln["bbox"][3]) / 2
        if rows and row_span[0] <= cy <= row_span[1]:
            rows[-1].append(ln)
        else:
            rows.append([ln])
            row_span = (ln["bbox"][1], ln["bbox"][3])
    return [ln for row in rows for ln in sorted(row, key=lambda ln: ln["bbox"][0])]


def _line_box(ln: dict, order: int, region_type: str | None = None) -> BoxResult:
    x0, y0, x1, y1 = ln["bbox"]
    conf = ln["confidence"]
    return BoxResult(
        text=ln["text"], x0=x0, y0=y0, x1=x1, y1=y1,
        confidence=conf * 100 if conf is not None else None,
        reading_order=order,
        region_type=region_type,
    )


def merge_layout(lines: list[dict], layout_boxes: list[dict], image: Image.Image) -> list[BoxResult]:
    regions = []
    for lb in layout_boxes:
        rtype = _REGION_TYPES.get(lb["label"])
        if rtype is None:
            continue
        regions.append({
            "type": rtype,
            "score": float(lb["score"]),
            "bbox": tuple(float(v) for v in lb["coordinate"]),
        })
    regions = _dedupe_pictures(regions)

    owned: dict[int, list[dict]] = {i: [] for i in range(len(regions))}
    leftovers: list[dict] = []
    for ln in lines:
        cx = (ln["bbox"][0] + ln["bbox"][2]) / 2
        cy = (ln["bbox"][1] + ln["bbox"][3]) / 2
        candidates = [
            i for i, r in enumerate(regions)
            if r["type"] != PICTURE and _contains(r["bbox"], cx, cy)
        ]
        if candidates:
            owned[min(candidates, key=lambda i: _area(regions[i]["bbox"]))].append(ln)
        else:
            leftovers.append(ln)

    boxes: list[BoxResult] = []
    for i in sorted(range(len(regions)), key=lambda i: (regions[i]["bbox"][1], regions[i]["bbox"][0])):
        r = regions[i]
        if r["type"] == TABLE:
            # PaddleOCR finds no cells, so one joined box would hide the rows.
            # Keep each line as its own box, tagged Table, in row order.
            for ln in _row_order(owned[i]):
                boxes.append(_line_box(ln, len(boxes), TABLE))
            continue
        inside = sorted(owned[i], key=_line_key)
        if r["type"] != PICTURE and not inside:
            continue
        confs = [ln["confidence"] for ln in inside if ln["confidence"] is not None]
        x0, y0, x1, y1 = r["bbox"]
        box = BoxResult(
            text="\n".join(ln["text"] for ln in inside),
            x0=x0, y0=y0, x1=x1, y1=y1,
            confidence=sum(confs) / len(confs) * 100 if confs else None,
            reading_order=len(boxes),
            region_type=r["type"],
        )
        if r["type"] == PICTURE:
            box.image = crop_jpeg_b64(image, r["bbox"])
        boxes.append(box)

    for ln in sorted(leftovers, key=_line_key):
        boxes.append(_line_box(ln, len(boxes)))
    return boxes
