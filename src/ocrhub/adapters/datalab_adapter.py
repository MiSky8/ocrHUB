import itertools
import os
import tempfile
import time

from ocrhub.adapters._text import html_to_text
from ocrhub.models import BoxResult, OcrResult, PageResult

# "Page" wraps every top-level block and carries no text of its own, so it is skipped
# (its children are still walked). Pictures are kept as image boxes, see _picture_box.
_SKIP_TYPES = frozenset({"Page"})
_PICTURE_TYPES = frozenset({"Picture", "Figure"})

_BLOCK_TYPE_MAP: dict[str, str] = {
    "SectionHeader": "Title",
    "Text": "Text",
    "ListGroup": "Text",
    "ListItem": "Text",
    "Footnote": "Text",
    "Table": "Table",
    "Figure": "Figure",
    "Caption": "Caption",
    "PageHeader": "Header",
    "PageFooter": "Footer",
}


def _map_block_type(block_type: str) -> str:
    return _BLOCK_TYPE_MAP.get(block_type, "Text")


def _picture_box(block: dict, order: int) -> BoxResult | None:
    """A Picture/Figure block: its region, its alt text/caption (`text`) and the
    cropped image Datalab extracted (first entry of the block's `images`)."""
    bbox = block.get("bbox")
    if not bbox or len(bbox) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in bbox)
    except (TypeError, ValueError):
        return None
    images = block.get("images") or {}
    return BoxResult(
        text=html_to_text(block.get("html") or ""),
        x0=x0, y0=y0, x1=x1, y1=y1,
        reading_order=order,
        region_type="Picture",
        image=next(iter(images.values()), None),
    )


def _walk(block: dict, counter: "itertools.count[int]") -> list[BoxResult]:
    boxes: list[BoxResult] = []
    block_type = block.get("block_type", "")

    if block_type in _PICTURE_TYPES:
        picture = _picture_box(block, next(counter))
        if picture:
            boxes.append(picture)
        return boxes

    if block_type in _SKIP_TYPES:
        for child in block.get("children") or []:
            boxes.extend(_walk(child, counter))
        return boxes

    html = block.get("html") or ""
    text = html_to_text(html)
    bbox = block.get("bbox")
    if text and bbox and len(bbox) == 4:
        try:
            x0, y0, x1, y1 = (float(v) for v in bbox)
        except (TypeError, ValueError):
            x0 = y0 = x1 = y1 = None
        if x0 is not None:
            boxes.append(
                BoxResult(
                    text=text,
                    x0=x0,
                    y0=y0,
                    x1=x1,
                    y1=y1,
                    reading_order=next(counter),
                    region_type=_map_block_type(block_type),
                    html=html,
                )
            )

    for child in block.get("children") or []:
        boxes.extend(_walk(child, counter))
    return boxes


def parse_datalab_json(data: dict) -> list[PageResult]:
    """Flatten Datalab's nested block tree into one PageResult per page, each
    carrying its blocks as boxes in reading order."""
    pages: list[PageResult] = []
    for i, page_block in enumerate(data.get("children", []), start=1):
        counter: "itertools.count[int]" = itertools.count()
        boxes = _walk(page_block, counter)
        text = "\n\n".join(b.text for b in boxes if b.region_type != "Picture")
        pages.append(PageResult(page_number=i, text=text, boxes=boxes))
    return pages


class DatalabAdapter:
    name = "datalab"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key if api_key is not None else os.environ.get("DATALAB_API_KEY")
        self.base_url = os.environ.get("DATALAB_BASE_URL", "https://www.datalab.to")
        self.timeout = int(os.environ.get("DATALAB_TIMEOUT", "600"))
        self.mode = os.environ.get("DATALAB_MODE", "accurate")

    def available(self) -> bool:
        return bool(self.api_key)

    def extract(self, file_bytes: bytes, filename: str) -> OcrResult:
        start = time.monotonic()
        try:
            pages, raw = self._convert(file_bytes, filename)
        except Exception as e:  # noqa: BLE001 - per-engine failure isolation
            return OcrResult(engine=self.name, text="", error=str(e))

        elapsed_ms = int((time.monotonic() - start) * 1000)
        full_text = "\n\n".join(p.text for p in pages)
        return OcrResult(
            engine=self.name, text=full_text, pages=pages, elapsed_ms=elapsed_ms, raw=raw
        )

    def _convert(self, file_bytes: bytes, filename: str) -> tuple[list[PageResult], dict]:
        import asyncio

        from datalab_sdk import AsyncDatalabClient, ConvertOptions

        suffix = "_" + (filename or "upload")

        async def run() -> tuple[list[PageResult], dict]:
            with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
                tmp.write(file_bytes)
                tmp.flush()
                options = ConvertOptions(output_format="json", mode=self.mode)
                async with AsyncDatalabClient(
                    api_key=self.api_key, base_url=self.base_url, timeout=self.timeout
                ) as client:
                    result = await client.convert(tmp.name, options=options)

            if not result.success or not isinstance(result.json, dict):
                raise RuntimeError(getattr(result, "error", None) or "Datalab conversion failed")
            return parse_datalab_json(result.json), result.json

        return asyncio.run(run())
