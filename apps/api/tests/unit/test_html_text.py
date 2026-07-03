"""html_to_text: normalization rules the snapshot hash depends on."""

from __future__ import annotations

from src.domain.html_text import html_to_text


def test_paragraphs_and_headings_become_lines() -> None:
    html = "<html><body><h1>Villa Samui</h1><p>Beachfront pool villa</p></body></html>"
    assert html_to_text(html) == "Villa Samui\nBeachfront pool villa"


def test_script_style_noscript_are_stripped() -> None:
    html = (
        "<head><style>body{color:red}</style></head>"
        "<body><script>alert('x')</script><p>ราคา 5,000 บาท</p>"
        "<noscript>enable js</noscript></body>"
    )
    text = html_to_text(html)
    assert "alert" not in text
    assert "color" not in text
    assert "enable js" not in text
    assert "ราคา 5,000 บาท" in text


def test_nav_content_is_stripped() -> None:
    html = "<nav><a href='/'>Home</a><a href='/about'>About</a></nav><p>Pool villa</p>"
    text = html_to_text(html)
    assert "Home" not in text
    assert text == "Pool villa"


def test_list_items_each_get_a_line() -> None:
    html = "<ul><li>ห้องพัก 3 ห้อง</li><li>สระว่ายน้ำส่วนตัว</li></ul>"
    assert html_to_text(html) == "ห้องพัก 3 ห้อง\nสระว่ายน้ำส่วนตัว"


def test_entities_and_nbsp_are_decoded_and_collapsed() -> None:
    html = "<p>Bed &amp; Breakfast&nbsp;&nbsp;&#3652;&#3607;&#3618;</p>"
    assert html_to_text(html) == "Bed & Breakfast ไทย"


def test_whitespace_runs_collapse_inside_lines() -> None:
    html = "<p>  Pool\t\tVilla   with   view </p>"
    assert html_to_text(html) == "Pool Villa with view"


def test_malformed_html_never_raises() -> None:
    html = "<div><p>Open tags <b>bold<i>nested</div> stray </span> <p attr=>done"
    text = html_to_text(html)
    assert "Open tags" in text
    assert "done" in text


def test_deterministic_for_identical_input() -> None:
    html = "<p>ราคาพิเศษ</p><br/><div>Low season</div>"
    assert html_to_text(html) == html_to_text(html)


def test_inline_tags_do_not_split_lines() -> None:
    html = "<p>Deluxe <b>Pool</b> <i>Villa</i></p>"
    assert html_to_text(html) == "Deluxe Pool Villa"
