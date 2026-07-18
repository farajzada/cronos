"""Hacker News front-page source — JSON API example.

Demonstrates the API flavour of a Cronos source, using the official
hn.algolia.com search API (no HTML scraping, robots-friendly). Rows are a
first-seen snapshot: the HN item id is the natural dedup key, so points
are captured once and never rewritten (append-only history).
"""

from __future__ import annotations

import logging
from typing import Dict, Iterator, List, Optional
from urllib.parse import urlparse

from src.config import CONFIG
from src.http_client import HttpClient
from src.sources.base import Source

logger = logging.getLogger("cronos.sources.hackernews")

HN_ITEM_URL = "https://news.ycombinator.com/item?id="


def extract_domain(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


class HackerNewsSource(Source):
    name = "hackernews"
    title = "Hacker News"
    fieldnames = ["item_id", "title", "url", "domain", "author", "points"]
    key_field = "item_id"
    display_columns = [
        ("title", "Title"),
        ("domain", "Domain"),
        ("author", "Author"),
        ("points", "Points"),
    ]
    stat_fields = [("author", None), ("domain", None)]
    facet_field = "domain"

    def __init__(self, api_url: Optional[str] = None) -> None:
        self.api_url = api_url or CONFIG.hackernews_url

    @staticmethod
    def normalize_hit(hit: dict) -> Optional[Dict[str, str]]:
        item_id = str(hit.get("objectID") or "").strip()
        title = (hit.get("title") or "").strip()
        if not item_id or not title:
            return None  # skip malformed hits instead of crashing
        # Ask HN / Show HN posts have no external URL: link to the HN item.
        url = (hit.get("url") or "").strip() or (HN_ITEM_URL + item_id)
        return {
            "item_id": item_id,
            "title": title,
            "url": url,
            "domain": extract_domain(url),
            "author": (hit.get("author") or "").strip(),
            "points": str(hit.get("points") or 0),
        }

    def parse(self, payload: dict) -> List[Dict[str, str]]:
        rows = []
        for hit in payload.get("hits", []):
            row = self.normalize_hit(hit)
            if row is not None:
                rows.append(row)
        return rows

    def scrape(self, client: HttpClient) -> Iterator[Dict[str, str]]:
        payload = client.get_json(self.api_url)
        if payload is None:
            logger.error("Hacker News API unavailable: %s", self.api_url)
            return
        rows = self.parse(payload)
        logger.info("Extracted %d records from %s", len(rows), self.api_url)
        yield from rows

    def validate_row(self, row: Dict[str, str]) -> List[str]:
        errors: List[str] = []
        if not (row.get("title") or "").strip():
            errors.append("empty title")
        if not (row.get("url") or "").strip():
            errors.append("empty url")
        points = row.get("points") or ""
        if not points.isdigit():
            errors.append(f"points is not a non-negative integer: {points!r}")
        return errors
