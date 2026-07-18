"""Resilient HTTP client shared by all Cronos sources.

Per-request User-Agent rotation, connect/read timeouts, linear-backoff
retries. 4xx responses fail fast (not retryable); 5xx and network errors
are retried up to CONFIG.max_retries.
"""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Optional

import requests

from src.config import CONFIG

logger = logging.getLogger("cronos.http")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
]


class HttpClient:
    def __init__(self) -> None:
        self.session = requests.Session()

    def get_text(self, url: str) -> Optional[str]:
        """GET a page; return body text or None after exhausting retries."""
        for attempt in range(1, CONFIG.max_retries + 1):
            headers = {"User-Agent": random.choice(USER_AGENTS)}
            try:
                response = self.session.get(url, headers=headers, timeout=CONFIG.timeout)
                response.raise_for_status()
                return response.text
            except requests.exceptions.Timeout:
                logger.warning("Timeout on %s (attempt %d/%d)", url, attempt, CONFIG.max_retries)
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

    def get_json(self, url: str) -> Optional[dict]:
        """GET a JSON document; return the parsed object or None."""
        body = self.get_text(url)
        if body is None:
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            logger.error("Invalid JSON from %s: %s", url, exc)
            return None
