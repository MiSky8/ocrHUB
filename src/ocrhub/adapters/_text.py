import html as _html
import re
from html.parser import HTMLParser

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


_MARKER_RE = re.compile(r"\s*(?:\d+[.)]|[a-zA-Z][.)]|[\u2022\u25e6\u25aa\u25cf\u25cb\-\u2013*])\s")


class _TextBuilder(HTMLParser):
    """Markup -> plain text that keeps what strip_html loses: a bullet or number
    for every list item (unless the item text already starts with one, as
    Datalab sometimes does), and one line per table row."""

    _BLOCK = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "br"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._lists: list[dict] = []
        self._pending_marker: str | None = None

    def handle_starttag(self, tag, attrs):
        if tag in ("ul", "ol"):
            self._lists.append({"tag": tag, "n": 0})
            self.out.append("\n")
        elif tag == "li":
            self.out.append("\n" + "  " * max(len(self._lists) - 1, 0))
            if self._lists:
                lst = self._lists[-1]
                lst["n"] += 1
                self._pending_marker = f"{lst['n']}. " if lst["tag"] == "ol" else "\u2022 "
        elif tag in self._BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self.out.append(" | ")
        elif tag in ("ul", "ol"):
            if self._lists:
                self._lists.pop()
            self.out.append("\n")
        elif tag in self._BLOCK or tag == "li":
            self.out.append("\n")

    def handle_data(self, data):
        if self._pending_marker and data.strip():
            if not _MARKER_RE.match(data):
                self.out.append(self._pending_marker)
            self._pending_marker = None
        self.out.append(data)


def html_to_text(raw: str) -> str:
    builder = _TextBuilder()
    builder.feed(raw)
    builder.close()
    lines = (line.rstrip().removesuffix("|").rstrip() for line in "".join(builder.out).split("\n"))
    return "\n".join(line for line in lines if line.strip())
