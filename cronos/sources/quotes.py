"""quotes.toscrape.com source — paginated HTML scraping example.

Demonstrates the HTML-scraping flavour of a Cronos source: CSS selectors,
pagination walking, politeness delay, and a content-hash dedup key.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from cronos.config import CONFIG
from cronos.http_client import HttpClient
from cronos.sources.base import Source

logger = logging.getLogger("cronos.sources.quotes")


def content_hash(text: str, author: str) -> str:
    """Stable identity of a quote: tags may change, text+author may not."""
    return hashlib.sha256(f"{text}::{author}".encode()).hexdigest()


@dataclass(frozen=True)
class Quote:
    """A single normalized record scraped from the source."""

    text: str
    author: str
    tags: str  # pipe-delimited, e.g. "life|truth"

    @property
    def quote_id(self) -> str:
        return content_hash(self.text, self.author)

    def as_row(self) -> Dict[str, str]:
        return {
            "quote_id": self.quote_id,
            "text": self.text,
            "author": self.author,
            "tags": self.tags,
        }


class QuotesSource(Source):
    name = "quotes"
    title = "Quotes"
    fieldnames = ["quote_id", "text", "author", "tags"]
    key_field = "quote_id"
    display_columns = [("text", "Quote"), ("author", "Author"), ("tags", "Tags")]
    stat_fields = [("author", None), ("tags", "|")]
    facet_field = "tags"

    def __init__(self, base_url: Optional[str] = None) -> None:
        self.base_url = base_url or CONFIG.quotes_url

    @staticmethod
    def parse(html: str) -> List[Quote]:
        soup = BeautifulSoup(html, "html.parser")
        quotes: List[Quote] = []
        for node in soup.select("div.quote"):
            text_node = node.select_one("span.text")
            author_node = node.select_one("small.author")
            if text_node is None or author_node is None:
                continue  # skip malformed blocks instead of crashing
            tags = [t.get_text(strip=True) for t in node.select("a.tag")]
            quotes.append(
                Quote(
                    text=text_node.get_text(strip=True).strip("“”"),
                    author=author_node.get_text(strip=True),
                    tags="|".join(tags),
                )
            )
        return quotes

    @staticmethod
    def next_page(html: str, current_url: str) -> Optional[str]:
        soup = BeautifulSoup(html, "html.parser")
        link = soup.select_one("li.next > a")
        if link and link.has_attr("href"):
            return urljoin(current_url, link["href"])
        return None

    def scrape(self, client: HttpClient) -> Iterator[Dict[str, str]]:
        url: Optional[str] = self.base_url
        pages = 0
        while url and pages < CONFIG.max_pages:
            html = client.get_text(url)
            if html is None:
                break
            page_quotes = self.parse(html)
            logger.info("Extracted %d records from %s", len(page_quotes), url)
            for quote in page_quotes:
                yield quote.as_row()
            url = self.next_page(html, url)
            pages += 1
            if url:
                time.sleep(CONFIG.politeness_delay_seconds)

    def validate_row(self, row: Dict[str, str]) -> List[str]:
        # Hash checks must use the RAW stored values: source text may
        # legitimately contain leading/trailing whitespace that is part
        # of the hashed identity. strip() is for emptiness checks only.
        errors: List[str] = []
        text = row.get("text") or ""
        author = row.get("author") or ""
        if not text.strip():
            errors.append("empty text")
        if not author.strip():
            errors.append("empty author")
        if text.strip() and author.strip() and row.get("quote_id") != content_hash(text, author):
            errors.append("quote_id does not match content hash")
        return errors
