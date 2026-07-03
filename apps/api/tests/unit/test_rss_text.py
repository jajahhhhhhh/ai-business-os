"""rss_to_text: RSS 2.0 + Atom extraction and malformed-feed behaviour."""

from __future__ import annotations

import pytest

from src.domain.rss_text import rss_to_text

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Villa News</title>
<item><title>โปรโมชั่นหน้าฝน</title><description>ลด 20% &lt;b&gt;ทุกห้อง&lt;/b&gt;</description>
<link>https://example.com/promo</link></item>
<item><title>New pool bar</title><description>Open daily</description>
<link>https://example.com/bar</link></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Feed</title>
<entry><title>Season rates</title><summary>From 4,900 THB</summary>
<link href="https://example.com/rates"/></entry>
</feed>"""


def test_rss_items_become_lines_with_links() -> None:
    text = rss_to_text(RSS)
    lines = text.splitlines()
    assert len(lines) == 2
    assert lines[0] == "โปรโมชั่นหน้าฝน — ลด 20% ทุกห้อง (https://example.com/promo)"
    assert "New pool bar — Open daily (https://example.com/bar)" == lines[1]


def test_atom_entries_are_supported() -> None:
    text = rss_to_text(ATOM)
    assert text == "Season rates — From 4,900 THB (https://example.com/rates)"


def test_embedded_html_in_descriptions_is_flattened() -> None:
    assert "<b>" not in rss_to_text(RSS)


def test_unparseable_xml_raises_value_error() -> None:
    with pytest.raises(ValueError, match="unparseable"):
        rss_to_text("<html><body>not a feed")


def test_feed_without_items_raises_value_error() -> None:
    with pytest.raises(ValueError, match="no <item> or <entry>"):
        rss_to_text("<?xml version='1.0'?><rss><channel><title>empty</title></channel></rss>")


def test_deterministic_output() -> None:
    assert rss_to_text(RSS) == rss_to_text(RSS)
