"""Unit tests for the quotes.toscrape.com source."""

from __future__ import annotations

from src.sources.quotes import Quote, QuotesSource, content_hash

PAGE_HTML = """
<html><body>
  <div class="quote">
    <span class="text">“Test quote one.”</span>
    <span><small class="author">Author One</small></span>
    <div class="tags"><a class="tag">alpha</a><a class="tag">beta</a></div>
  </div>
  <div class="quote">
    <span class="text">“Test quote two.”</span>
    <span><small class="author">Author Two</small></span>
    <div class="tags"></div>
  </div>
  <div class="quote"><span class="text">“Malformed: no author.”</span></div>
  <ul class="pager"><li class="next"><a href="/page/2/">Next</a></li></ul>
</body></html>
"""

LAST_PAGE_HTML = "<html><body><ul class='pager'></ul></body></html>"


def test_parse_extracts_normalized_quotes():
    quotes = QuotesSource.parse(PAGE_HTML)
    assert len(quotes) == 2  # malformed block skipped, not crashed on
    assert quotes[0] == Quote(text="Test quote one.", author="Author One", tags="alpha|beta")
    assert quotes[1].tags == ""


def test_quote_id_is_deterministic_content_hash():
    a = Quote(text="Same", author="Person", tags="x")
    b = Quote(text="Same", author="Person", tags="different-tags")
    c = Quote(text="Other", author="Person", tags="x")
    assert a.quote_id == b.quote_id  # tags don't affect identity
    assert a.quote_id != c.quote_id
    assert len(a.quote_id) == 64  # sha256 hex


def test_next_page_resolves_relative_url():
    url = QuotesSource.next_page(PAGE_HTML, "https://example.com/page/1/")
    assert url == "https://example.com/page/2/"
    assert QuotesSource.next_page(LAST_PAGE_HTML, "https://example.com/") is None


def test_scrape_walks_pagination(monkeypatch):
    from src.sources import quotes as quotes_module

    monkeypatch.setattr(quotes_module.time, "sleep", lambda _: None)
    source = QuotesSource(base_url="https://example.com/")

    class FakeClient:
        def __init__(self):
            self.pages = {"https://example.com/": PAGE_HTML,
                          "https://example.com/page/2/": LAST_PAGE_HTML}

        def get_text(self, url):
            return self.pages[url]

    rows = list(source.scrape(FakeClient()))
    assert len(rows) == 2
    assert rows[0]["author"] == "Author One"
    assert set(rows[0]) == set(QuotesSource.fieldnames)


def test_validate_row_accepts_valid_and_raw_whitespace():
    """Regression: hash must be checked against RAW values, not stripped ones.

    quotes.toscrape.com contains a real quote ending in a space; stripping
    before hashing produced a false 'hash mismatch' violation.
    """
    source = QuotesSource()
    q = Quote(text="Trailing space here. ", author="W.C. Fields", tags="")
    assert source.validate_row(q.as_row()) == []


def test_validate_row_flags_violations():
    source = QuotesSource()
    assert "empty text" in source.validate_row(
        {"quote_id": "x", "text": " ", "author": "A", "tags": ""}
    )
    assert "empty author" in source.validate_row(
        {"quote_id": "x", "text": "T", "author": "", "tags": ""}
    )
    tampered = {"quote_id": content_hash("orig", "A"), "text": "changed", "author": "A", "tags": ""}
    assert "quote_id does not match content hash" in source.validate_row(tampered)
