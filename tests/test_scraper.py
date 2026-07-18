"""Unit tests for the Extract/Transform/Load core in src/scraper.py."""

from __future__ import annotations

import csv

import pytest
import requests

from src import scraper as scraper_module
from src.scraper import FIELDNAMES, DatasetWriter, Quote, QuotesScraper

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


class FakeResponse:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(response=self)


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------


def test_parse_extracts_normalized_quotes():
    quotes = QuotesScraper._parse(PAGE_HTML)
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
    url = QuotesScraper._next_page(PAGE_HTML, "https://example.com/page/1/")
    assert url == "https://example.com/page/2/"
    assert QuotesScraper._next_page(LAST_PAGE_HTML, "https://example.com/") is None


# ---------------------------------------------------------------------------
# Extract (network behaviour, fully mocked)
# ---------------------------------------------------------------------------


def test_fetch_retries_on_timeout_then_succeeds(monkeypatch):
    monkeypatch.setattr(scraper_module.time, "sleep", lambda _: None)
    s = QuotesScraper(base_url="https://example.com/")
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        assert "User-Agent" in headers
        assert timeout is not None
        if calls["n"] < 3:
            raise requests.exceptions.Timeout()
        return FakeResponse(text="payload")

    monkeypatch.setattr(s.session, "get", fake_get)
    assert s._fetch("https://example.com/") == "payload"
    assert calls["n"] == 3


def test_fetch_fails_fast_on_4xx(monkeypatch):
    monkeypatch.setattr(scraper_module.time, "sleep", lambda _: None)
    s = QuotesScraper(base_url="https://example.com/")
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        return FakeResponse(status_code=404)

    monkeypatch.setattr(s.session, "get", fake_get)
    assert s._fetch("https://example.com/missing") is None
    assert calls["n"] == 1  # 4xx must not be retried


def test_fetch_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(scraper_module.time, "sleep", lambda _: None)
    s = QuotesScraper(base_url="https://example.com/")
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(s.session, "get", fake_get)
    assert s._fetch("https://example.com/") is None
    assert calls["n"] == scraper_module.CONFIG.max_retries


# ---------------------------------------------------------------------------
# Load (idempotency)
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_quotes():
    return [
        Quote(text="Q1", author="A1", tags="t1"),
        Quote(text="Q2", author="A2", tags=""),
    ]


def test_writer_creates_file_with_header(tmp_path, sample_quotes):
    path = tmp_path / "dataset.csv"
    appended = DatasetWriter(path).append_unique(iter(sample_quotes))
    assert appended == 2
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert [r["text"] for r in rows] == ["Q1", "Q2"]
    assert list(rows[0].keys()) == FIELDNAMES


def test_writer_is_idempotent_across_runs(tmp_path, sample_quotes):
    path = tmp_path / "dataset.csv"
    writer = DatasetWriter(path)
    assert writer.append_unique(iter(sample_quotes)) == 2
    assert writer.append_unique(iter(sample_quotes)) == 0  # second run: no dupes
    with path.open(newline="", encoding="utf-8") as fh:
        assert len(list(csv.DictReader(fh))) == 2


def test_writer_deduplicates_within_a_single_batch(tmp_path):
    path = tmp_path / "dataset.csv"
    batch = [Quote(text="Q", author="A", tags="")] * 3
    assert DatasetWriter(path).append_unique(iter(batch)) == 1


def test_writer_appends_only_new_rows(tmp_path, sample_quotes):
    path = tmp_path / "dataset.csv"
    writer = DatasetWriter(path)
    writer.append_unique(iter(sample_quotes))
    newer = sample_quotes + [Quote(text="Q3", author="A3", tags="fresh")]
    assert writer.append_unique(iter(newer)) == 1
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert [r["text"] for r in rows] == ["Q1", "Q2", "Q3"]  # history preserved
