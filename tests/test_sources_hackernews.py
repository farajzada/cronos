"""Unit tests for the Hacker News (Algolia API) source."""

from __future__ import annotations

from src.sources.hackernews import HackerNewsSource, extract_domain

SAMPLE_PAYLOAD = {
    "hits": [
        {
            "objectID": "1001",
            "title": "Show HN: Cronos",
            "url": "https://www.example.com/post",
            "author": "alice",
            "points": 123,
        },
        {
            "objectID": "1002",
            "title": "Ask HN: Anything?",
            "url": None,  # Ask HN posts have no external URL
            "author": "bob",
            "points": 0,
        },
        {"objectID": "", "title": "malformed, no id"},
        {"objectID": "1003", "title": ""},
    ]
}


def test_extract_domain_strips_www_and_lowercases():
    assert extract_domain("https://www.Example.COM/a/b") == "example.com"
    assert extract_domain("https://news.ycombinator.com/item?id=1") == "news.ycombinator.com"


def test_parse_normalizes_and_skips_malformed():
    rows = HackerNewsSource().parse(SAMPLE_PAYLOAD)
    assert len(rows) == 2  # two malformed hits skipped
    assert rows[0] == {
        "item_id": "1001",
        "title": "Show HN: Cronos",
        "url": "https://www.example.com/post",
        "domain": "example.com",
        "author": "alice",
        "points": "123",
    }


def test_ask_hn_posts_link_to_hn_item():
    rows = HackerNewsSource().parse(SAMPLE_PAYLOAD)
    assert rows[1]["url"] == "https://news.ycombinator.com/item?id=1002"
    assert rows[1]["domain"] == "news.ycombinator.com"
    assert rows[1]["points"] == "0"


def test_scrape_yields_rows_matching_schema(monkeypatch):
    source = HackerNewsSource(api_url="https://api.example.com/hn")

    class FakeClient:
        def get_json(self, url):
            assert url == "https://api.example.com/hn"
            return SAMPLE_PAYLOAD

    rows = list(source.scrape(FakeClient()))
    assert len(rows) == 2
    assert all(set(row) == set(HackerNewsSource.fieldnames) for row in rows)


def test_scrape_handles_api_outage(monkeypatch):
    source = HackerNewsSource()

    class DeadClient:
        def get_json(self, url):
            return None

    assert list(source.scrape(DeadClient())) == []


def test_validate_row_flags_violations():
    source = HackerNewsSource()
    ok = {"item_id": "1", "title": "T", "url": "https://x.io", "domain": "x.io",
          "author": "a", "points": "10"}
    assert source.validate_row(ok) == []
    assert "empty title" in source.validate_row({**ok, "title": " "})
    assert "empty url" in source.validate_row({**ok, "url": ""})
    assert any("points" in e for e in source.validate_row({**ok, "points": "-5"}))
