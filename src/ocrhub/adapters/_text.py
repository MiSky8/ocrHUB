import html as _html
import re

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(raw: str) -> str:
    return _html.unescape(_HTML_TAG_RE.sub("", raw)).strip()
