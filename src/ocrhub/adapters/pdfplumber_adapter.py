import html
import io
import re
import time
from collections import Counter

import pdfplumber

from ocrhub.models import BoxResult, OcrResult, PageResult
from ocrhub.pdf_utils import is_pdf


_BLANK = "\u2800"  # braille blank, used as invisible padding by some renderers
_MIN_SIZE = 1  # characters under 1pt are invisible text-layer padding, not content


def _hex_color(color) -> str:
    """PDF colour (gray, RGB or CMYK tuple) -> '#rrggbb'; black when unknown."""
    if isinstance(color, (int, float)):
        color = (color,)
    try:
        vals = [max(0.0, min(1.0, float(v))) for v in color]
    except (TypeError, ValueError):
        return "#000000"
    if len(vals) == 1:
        r = g = b = vals[0]
    elif len(vals) == 3:
        r, g, b = vals
    elif len(vals) == 4:
        c, m, y, k = vals
        r, g, b = (1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)
    else:
        return "#000000"
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


def _char_style(c: dict) -> dict:
    font = c.get("fontname") or ""
    if "+" in font:  # strip the subset prefix, e.g. ABCDEF+Arial-BoldMT
        font = font.split("+", 1)[1]
    lower = font.lower()
    return {
        "font": font,
        "size": round(float(c.get("size") or 0), 1),
        "bold": "bold" in lower or "black" in lower,
        "italic": "italic" in lower or "oblique" in lower,
        "color": _hex_color(c.get("non_stroking_color")),
    }


def _visible(chars: list[dict]) -> list[dict]:
    return [c for c in chars if c["text"].strip() and c["text"] != _BLANK]


def _dominant_style(chars: list[dict]) -> dict:
    """Most frequent style among a line's visible characters."""
    styles = [_char_style(c) for c in _visible(chars)]
    keys = Counter(tuple(sorted(st.items())) for st in styles)
    return dict(keys.most_common(1)[0][0])


def _runs(chars: list[dict]) -> list[dict]:
    """Split a line into runs of one style (e.g. bold 'Date:' then regular text)
    with each run's own x-extent, so mixed styling survives."""
    runs: list[dict] = []
    space_before = False
    prev_x1: float | None = None
    for c in chars:
        if c["text"] == _BLANK:
            continue
        if not c["text"].strip():
            space_before = True
            continue
        st = _char_style(c)
        # extract_text_lines drops the text layer's space characters, so a gap
        # of more than ~0.12em between glyphs stands in for one.
        if prev_x1 is not None and float(c["x0"]) - prev_x1 > 0.12 * (st["size"] or 10):
            space_before = True
        prev_x1 = float(c["x1"])
        last = runs[-1] if runs else None
        if last and all(last[k] == st[k] for k in st):
            last["text"] += (" " if space_before else "") + c["text"]
            last["x1"] = float(c["x1"])
        else:
            runs.append({**st, "text": c["text"], "x0": float(c["x0"]), "x1": float(c["x1"])})
        space_before = False
    return runs


def _inside(box: tuple, table_bbox: tuple) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return table_bbox[0] <= cx <= table_bbox[2] and table_bbox[1] <= cy <= table_bbox[3]


def _center_in(c: dict, bbox: tuple) -> bool:
    cx, cy = (c["x0"] + c["x1"]) / 2, (c["top"] + c["bottom"]) / 2
    return bbox[0] <= cx < bbox[2] and bbox[1] <= cy < bbox[3]


def _cell_html(chars: list[dict], bbox: tuple) -> str:
    # Assign characters by centre point: the table's row edges don't always
    # enclose their text, and a plain crop would also grab overlapping neighbours.
    in_cell = [c for c in chars if c["text"] != _BLANK and _center_in(c, bbox)]
    inside = _visible(in_cell)
    text = (pdfplumber.utils.extract_text(in_cell) if inside else "").strip()
    if not text:
        return "<td></td>"
    left_gap = min(c["x0"] for c in inside) - bbox[0]
    right_gap = bbox[2] - max(c["x1"] for c in inside)
    align = "center" if abs(left_gap - right_gap) < 3 else "right" if right_gap < left_gap else "left"
    body = "<br>".join(html.escape(line) for line in text.split("\n"))
    if sum(_char_style(c)["bold"] for c in inside) > len(inside) / 2:
        body = f"<b>{body}</b>"
    return f'<td align="{align}">{body}</td>'


def _table_boxes(page) -> list[BoxResult]:
    boxes: list[BoxResult] = []
    try:
        tables = page.find_tables()
    except Exception:  # noqa: BLE001 - table detection is best-effort
        return boxes
    for table in tables:
        rows_html = []
        rows_text = []
        for row in table.rows:
            cells = [_cell_html(page.chars, c) if c else "<td></td>" for c in row.cells]
            if all(c == "<td></td>" for c in cells):
                continue
            rows_html.append("<tr>" + "".join(cells) + "</tr>")
            rows_text.append(" | ".join(re.sub(r"<[^>]+>", "", c).strip() for c in cells))
        chars = [c for c in _visible(page.chars) if _center_in(c, table.bbox)]
        if not chars:
            continue
        x0, top, x1, bottom = table.bbox
        boxes.append(
            BoxResult(
                text="\n".join(rows_text),
                x0=float(x0),
                y0=float(top),
                x1=float(x1),
                y1=float(bottom),
                region_type="Table",
                html="<table>" + "".join(rows_html) + "</table>",
                style=_dominant_style(chars),
            )
        )
    return boxes


def _page_boxes(page) -> list[BoxResult]:
    visible_page = page.filter(lambda o: o.get("object_type") != "char" or o.get("size", 1) >= _MIN_SIZE)
    tables = _table_boxes(visible_page)
    table_bboxes = [(t.x0, t.y0, t.x1, t.y1) for t in tables]

    boxes: list[BoxResult] = list(tables)
    for line in visible_page.extract_text_lines(return_chars=True):
        text = line["text"].replace(_BLANK, "").strip()
        if not text:
            continue
        bbox = (float(line["x0"]), float(line["top"]), float(line["x1"]), float(line["bottom"]))
        if bbox[1] < 0 or bbox[3] > page.height:  # glyphs positioned off the page
            continue
        if any(_inside(bbox, tb) for tb in table_bboxes):
            continue
        style = _dominant_style(line["chars"])
        style["runs"] = _runs(line["chars"])
        boxes.append(
            BoxResult(
                text=text, x0=bbox[0], y0=bbox[1], x1=bbox[2], y1=bbox[3],
                region_type="Text", style=style,
            )
        )
    boxes.sort(key=lambda b: (b.y0, b.x0))
    for order, box in enumerate(boxes):
        box.reading_order = order
    return boxes


class PdfplumberAdapter:
    name = "pdfplumber"

    def available(self) -> bool:
        return True

    def extract(self, file_bytes: bytes, filename: str) -> OcrResult:
        if not is_pdf(filename):
            raise ValueError("pdfplumber adapter only accepts PDF files")

        start = time.monotonic()
        pages: list[PageResult] = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                pages.append(
                    PageResult(
                        page_number=i,
                        text=text,
                        boxes=_page_boxes(page),
                        width=float(page.width),
                        height=float(page.height),
                    )
                )

        elapsed_ms = int((time.monotonic() - start) * 1000)
        full_text = "\n".join(p.text for p in pages)
        return OcrResult(
            engine=self.name,
            text=full_text,
            pages=pages,
            confidence=None,
            elapsed_ms=elapsed_ms,
        )
