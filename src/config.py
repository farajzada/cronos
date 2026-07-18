"""Central runtime configuration for Cronos.

Every value can be overridden with a CRONOS_* environment variable, so forks
can retarget the pipeline (sources, URLs, limits, timing) without touching
code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc


@dataclass(frozen=True)
class Config:
    sources: Tuple[str, ...]
    data_dir: Path
    quotes_url: str
    hackernews_url: str
    max_pages: int
    connect_timeout: float
    read_timeout: float
    max_retries: int
    retry_backoff_seconds: float
    politeness_delay_seconds: float

    @property
    def timeout(self) -> Tuple[float, float]:
        """(connect, read) tuple in the shape `requests` expects."""
        return (self.connect_timeout, self.read_timeout)

    @classmethod
    def from_env(cls) -> "Config":
        sources = tuple(
            name.strip()
            for name in _env_str("CRONOS_SOURCES", "quotes,hackernews").split(",")
            if name.strip()
        )
        return cls(
            sources=sources,
            data_dir=Path(_env_str("CRONOS_DATA_DIR", str(PROJECT_ROOT / "data"))),
            # CRONOS_BASE_URL kept as a legacy alias for CRONOS_QUOTES_URL
            quotes_url=_env_str(
                "CRONOS_QUOTES_URL",
                _env_str("CRONOS_BASE_URL", "https://quotes.toscrape.com/"),
            ),
            hackernews_url=_env_str(
                "CRONOS_HN_URL",
                "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=30",
            ),
            max_pages=_env_int("CRONOS_MAX_PAGES", 50),
            connect_timeout=_env_float("CRONOS_CONNECT_TIMEOUT", 5.0),
            read_timeout=_env_float("CRONOS_READ_TIMEOUT", 20.0),
            max_retries=_env_int("CRONOS_MAX_RETRIES", 3),
            retry_backoff_seconds=_env_float("CRONOS_RETRY_BACKOFF", 2.0),
            politeness_delay_seconds=_env_float("CRONOS_POLITENESS_DELAY", 0.5),
        )


CONFIG = Config.from_env()
