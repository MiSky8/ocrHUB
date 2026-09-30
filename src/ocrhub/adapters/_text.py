import html as _html
import re

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_CELL_END_RE = re.compile(r"</t[dh]\s*>", re.IGNORECASE)
_LINE_END_RE = re.compile(r"</(?:tr|li|p|div|h[1-6])\s*>|<br\s*/?>", re.IGNORECASE)


def strip_html(raw: str) -> str:
    """Drop markup but keep structure: table cells become ' | ', rows and list
    items become separate lines (so cells/items don't run together)."""
    raw = _CELL_END_RE.sub(" | ", raw)
    raw = _LINE_END_RE.sub("\n", raw)
    text = _html.unescape(_HTML_TAG_RE.sub("", raw))
    lines = (line.strip().removesuffix("|").strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)
