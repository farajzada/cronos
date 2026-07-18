"""Dataset integrity validator for the Cronos pipeline.

Runs after the scraper and before the GitOps commit, guaranteeing a corrupt
dataset is never pushed. Generic checks for every source:
  1. schema — header must match the source's fieldnames exactly;
  2. key    — dedup key must be non-empty and unique across the file;
plus each source's own validate_row() rules (e.g. quotes verifies the
SHA-256 content hash, hackernews verifies numeric points).

A missing dataset file is skipped with a warning (the source may be newly
enabled or its upstream may have been down); corrupt content is fatal.

Exit code 0 = all present datasets valid, 1 = at least one violation.

Run as a module from the repository root:  python -m src.validator
"""

from __future__ import annotations

import csv
import logging
import sys
from pathlib import Path
from typing import List, Set

from src.config import CONFIG
from src.sources import get_sources
from src.sources.base import Source

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("cronos.validator")

MAX_REPORTED_ERRORS = 20


def validate_source(source: Source, path: Path) -> List[str]:
    """Return a list of human-readable violations (empty list = valid)."""
    errors: List[str] = []
    seen: Set[str] = set()

    with path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != source.fieldnames:
            return [
                f"schema mismatch: expected {source.fieldnames}, got {reader.fieldnames}"
            ]

        for lineno, row in enumerate(reader, start=2):
            key = row.get(source.key_field) or ""
            if not key:
                errors.append(f"line {lineno}: empty {source.key_field}")
            if key in seen:
                errors.append(f"line {lineno}: duplicate {source.key_field} {key[:12]}…")
            seen.add(key)
            for violation in source.validate_row(row):
                errors.append(f"line {lineno}: {violation}")

    return errors


def main() -> int:
    total_errors = 0
    for source in get_sources(CONFIG.sources):
        path = source.dataset_path(CONFIG.data_dir)
        if not path.exists():
            logger.warning("[%s] dataset not found, skipping: %s", source.name, path)
            continue
        errors = validate_source(source, path)
        if errors:
            for err in errors[:MAX_REPORTED_ERRORS]:
                logger.error("[%s] %s", source.name, err)
            if len(errors) > MAX_REPORTED_ERRORS:
                logger.error("[%s] … and %d more", source.name, len(errors) - MAX_REPORTED_ERRORS)
            total_errors += len(errors)
        else:
            logger.info("[%s] validation OK: %s is consistent", source.name, path)

    if total_errors:
        logger.error("Validation FAILED: %d violation(s)", total_errors)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
