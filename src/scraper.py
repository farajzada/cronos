"""Cronos ETL pipeline — Extract & Load orchestrator.

Iterates every source enabled in CRONOS_SOURCES, scrapes it into
normalized rows, and appends only new unique rows to data/<source>.csv
via the generic idempotent DatasetWriter.

A single failing source is logged and skipped so one flaky upstream never
blocks the others; the run only fails if EVERY enabled source errors.

Run as a module from the repository root:  python -m src.scraper
"""

from __future__ import annotations

import logging
import sys

from src.config import CONFIG
from src.http_client import HttpClient
from src.sources import get_sources
from src.storage import DatasetWriter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("cronos")


def main() -> int:
    logger.info("Cronos pipeline started (sources: %s)", ", ".join(CONFIG.sources))
    client = HttpClient()
    failures = 0

    for source in get_sources(CONFIG.sources):
        logger.info("[%s] scraping…", source.name)
        writer = DatasetWriter(
            path=source.dataset_path(CONFIG.data_dir),
            fieldnames=source.fieldnames,
            key_field=source.key_field,
        )
        try:
            appended = writer.append_unique(source.scrape(client))
        except Exception:
            logger.exception("[%s] scrape failed; skipping source", source.name)
            failures += 1
            continue
        if appended:
            logger.info("[%s] loaded %d new unique records into %s",
                        source.name, appended, writer.path)
        else:
            logger.info("[%s] no new records; dataset is already up to date", source.name)

    if failures == len(CONFIG.sources):
        logger.error("All %d sources failed", failures)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
