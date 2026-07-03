"""HTML -> normalized plain text for competitor page snapshots (M3).

Pure stdlib (html.parser). Deterministic: identical HTML always yields
identical text, so the snapshot content hash is stable. Script/style/
noscript/head content is dropped, block-level elements become line breaks,
whitespace runs collapse, and entities are decoded by the parser.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

_SKIP_TAGS = frozenset({"script", "style", "noscript", "head", "template"})

_BLOCK_TAGS = frozenset(
    {
        "address", "article", "aside", "blockquote", "br", "caption", "dd",
        "div", "dl", "dt", "fieldset", "figcaption", "figure", "footer",
        "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li",
        "main", "nav", "ol", "option", "p", "pre", "section", "select",
        "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
    }
)

# Horizontal whitespace runs, including the \xa0 that &nbsp; decodes to.
_WS_RUN = re.compile(r"[ \t\r\f\v\xa0]+")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        # convert_charrefs=True (default) decodes entities into handle_data.
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Self-closing form (<br/>): void tags never nest, so a skip tag
        # written this way contributes nothing and needs no depth tracking.
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """Extract readable text: one line per block, whitespace collapsed."""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    raw = "".join(parser.parts)
    lines = [_WS_RUN.sub(" ", line).strip() for line in raw.split("\n")]
    return "\n".join(line for line in lines if line)
