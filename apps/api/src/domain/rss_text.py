"""RSS/Atom feed -> normalized plain text for competitor snapshots (M3).

Approach (documented decision): a LOCAL stdlib parse (xml.etree) rather than
reusing services/collectors' RssCollector. The collectors package is an
optional runtime dependency of the API (installed in the container, absent in
API-only test environments), and snapshot hashing must be deterministic and
importable everywhere — so feed parsing lives here, mirroring the same
minimal-stdlib philosophy as collectors/rss.py. Item descriptions may contain
embedded HTML, which is flattened through html_to_text for stable hashes.

Malformed XML raises ValueError; the sweep records it as a per-source
'error: ...' status and continues (NFR-1).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from src.domain.html_text import html_to_text

_ATOM_NS = "{http://www.w3.org/2005/Atom}"


def _clean(fragment: str | None) -> str:
    """Flatten a possibly-HTML text fragment to collapsed plain text."""
    if not fragment:
        return ""
    return " ".join(html_to_text(fragment).split())


def rss_to_text(body: str) -> str:
    """Extract feed items as 'title — summary (link)' lines, one per item.

    Supports RSS 2.0 (<item>) and Atom (<entry>). Raises ValueError when the
    body is not parseable XML or contains no recognizable feed items.
    """
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise ValueError(f"unparseable feed XML: {exc}") from exc

    lines: list[str] = []
    for item in root.iter("item"):  # RSS 2.0
        title = _clean(item.findtext("title"))
        desc = _clean(item.findtext("description"))
        link = (item.findtext("link") or "").strip()
        lines.append(_format_line(title, desc, link))
    for entry in root.iter(f"{_ATOM_NS}entry"):  # Atom
        title = _clean(entry.findtext(f"{_ATOM_NS}title"))
        summary = _clean(
            entry.findtext(f"{_ATOM_NS}summary") or entry.findtext(f"{_ATOM_NS}content")
        )
        link_el = entry.find(f"{_ATOM_NS}link")
        link = link_el.get("href", "").strip() if link_el is not None else ""
        lines.append(_format_line(title, summary, link))

    if not lines:
        raise ValueError("feed XML contains no <item> or <entry> elements")
    return "\n".join(lines)


def _format_line(title: str, summary: str, link: str) -> str:
    parts = [part for part in (title, summary) if part]
    line = " — ".join(parts) if parts else "(no text)"
    return f"{line} ({link})" if link else line
