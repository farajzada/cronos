"""Cronos ETL pipeline — Extract & Transform & Load module.

Target source : https://quotes.toscrape.com (pagination-aware, configurable)
Output        : data/dataset.csv (append-only, deduplicated, idempotent)

Design notes:
  - All tunables live in src/config.py and are CRONOS_* env-overridable.
  - Dedup key is a SHA-256 content hash (text + author), stored as `quote_id`.
    Existing IDs are loaded into a set() for O(1) membership checks, so the
    script may run any number of times without producing duplicate rows.
  - The CSV is opened in append mode only; existing history is never rewritten.

Run as a module from the repository root:  python -m src.scraper
"""

from __future__ import annotations

import csv
import hashlib
import logging
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Set
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.config import CONFIG

FIELDNAMES = ["quote_id", "text", "author", "tags"]

# Mock User-Agent rotation pool: a random identity is picked per request.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("cronos")


# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Quote:
    """A single normalized record scraped from the source."""

    text: str
    author: str
    tags: str  # pipe-delimited, e.g. "life|truth"

    @property
    def quote_id(self) -> str:
        """Stable content hash used as the deduplication key."""
        payload = f"{self.text}::{self.author}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def as_row(self) -> dict:
        return {
            "quote_id": self.quote_id,
            "text": self.text,
            "author": self.author,
            "tags": self.tags,
        }


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------


class QuotesScraper:
    """Extracts quotes from the configured source with retry + UA rotation."""

    def __init__(self, base_url: str = CONFIG.base_url) -> None:
        self.base_url = base_url
        self.session = requests.Session()

    def _fetch(self, url: str) -> Optional[str]:
        """GET a page with per-request UA rotation, timeout and retries."""
        for attempt in range(1, CONFIG.max_retries + 1):
            headers = {"User-Agent": random.choice(USER_AGENTS)}
            try:
                response = self.session.get(url, headers=headers, timeout=CONFIG.timeout)
                response.raise_for_status()
                return response.text
            except requests.exceptions.Timeout:
                logger.warning(
                    "Timeout on %s (attempt %d/%d)", url, attempt, CONFIG.max_retries
                )
            except requests.exceptions.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else "?"
                logger.warning(
                    "HTTP %s on %s (attempt %d/%d)", status, url, attempt, CONFIG.max_retries
                )
                # 4xx is not retryable; fail fast.
                if exc.response is not None and 400 <= exc.response.status_code < 500:
                    return None
            except requests.exceptions.RequestException as exc:
                logger.warning(
                    "Network error on %s (attempt %d/%d): %s",
                    url,
                    attempt,
                    CONFIG.max_retries,
                    exc,
                )
            if attempt < CONFIG.max_retries:
                time.sleep(CONFIG.retry_backoff_seconds * attempt)
        logger.error("Giving up on %s after %d attempts", url, CONFIG.max_retries)
        return None

    @staticmethod
    def _parse(html: str) -> List[Quote]:
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
    def _next_page(html: str, current_url: str) -> Optional[str]:
        soup = BeautifulSoup(html, "html.parser")
        link = soup.select_one("li.next > a")
        if link and link.has_attr("href"):
            return urljoin(current_url, link["href"])
        return None

    def scrape(self) -> Iterator[Quote]:
        """Walk all pages and yield normalized Quote records."""
        url: Optional[str] = self.base_url
        pages = 0
        while url and pages < CONFIG.max_pages:
            html = self._fetch(url)
            if html is None:
                break
            page_quotes = self._parse(html)
            logger.info("Extracted %d records from %s", len(page_quotes), url)
            yield from page_quotes
            url = self._next_page(html, url)
            pages += 1
            if url:
                time.sleep(CONFIG.politeness_delay_seconds)


# ---------------------------------------------------------------------------
# Load (idempotent, append-only)
# ---------------------------------------------------------------------------


class DatasetWriter:
    """Appends only unseen rows to the CSV; never overwrites history."""

    def __init__(self, path: Path = CONFIG.data_path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load_existing_ids(self) -> Set[str]:
        """Load current dedup keys into a set for O(1) lookups."""
        if not self.path.exists():
            return set()
        with self.path.open("r", newline="", encoding="utf-8") as fh:
            return {row["quote_id"] for row in csv.DictReader(fh) if row.get("quote_id")}

    def append_unique(self, quotes: Iterator[Quote]) -> int:
        seen = self.load_existing_ids()
        logger.info("Existing dataset contains %d unique records", len(seen))

        is_new_file = not self.path.exists() or self.path.stat().st_size == 0
        appended = 0
        with self.path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
            if is_new_file:
                writer.writeheader()
            for quote in quotes:
                if quote.quote_id in seen:
                    continue
                writer.writerow(quote.as_row())
                seen.add(quote.quote_id)  # guards against in-batch duplicates too
                appended += 1
        return appended


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> int:
    logger.info("Cronos pipeline started (target: %s)", CONFIG.base_url)
    scraper = QuotesScraper()
    writer = DatasetWriter()

    appended = writer.append_unique(scraper.scrape())

    if appended:
        logger.info("Loaded %d new unique records into %s", appended, writer.path)
    else:
        logger.info("No new records; dataset is already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
