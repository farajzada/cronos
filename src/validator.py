"""Dataset integrity validator for the Cronos pipeline.

Runs after the scraper and before the GitOps commit, guaranteeing a corrupt
dataset is never pushed. Checks:
  1. schema  — header must match FIELDNAMES exactly;
  2. content — text and author must be non-empty on every row;
  3. hashes  — quote_id must equal sha256("{text}::{author}") (detects
               manual edits and encoding drift);
  4. dedup   — quote_id must be unique across the whole file.

Exit code 0 = dataset valid, 1 = at least one violation.

Run as a module from the repository root:  python -m src.validator
"""

from __future__ import annotations

import csv
import hashlib
import logging
import sys
from pathlib import Path
from typing import List, Set

from src.config import CONFIG
from src.scraper import FIELDNAMES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("cronos.validator")

MAX_REPORTED_ERRORS = 20


def _expected_id(text: str, author: str) -> str:
    return hashlib.sha256(f"{text}::{author}".encode("utf-8")).hexdigest()


def validate_dataset(path: Path) -> List[str]:
    """Return a list of human-readable violations (empty list = valid)."""
    if not path.exists():
        return [f"dataset not found: {path}"]

    errors: List[str] = []
    seen: Set[str] = set()

    with path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != FIELDNAMES:
            return [f"schema mismatch: expected {FIELDNAMES}, got {reader.fieldnames}"]

        for lineno, row in enumerate(reader, start=2):
            # Hash checks must use the RAW stored values: source text may
            # legitimately contain leading/trailing whitespace that is part
            # of the hashed identity. strip() is for emptiness checks only.
            text = row.get("text") or ""
            author = row.get("author") or ""
            quote_id = row.get("quote_id") or ""

            if not text.strip():
                errors.append(f"line {lineno}: empty text")
            if not author.strip():
                errors.append(f"line {lineno}: empty author")
            if text.strip() and author.strip() and quote_id != _expected_id(text, author):
                errors.append(f"line {lineno}: quote_id does not match content hash")
            if quote_id in seen:
                errors.append(f"line {lineno}: duplicate quote_id {quote_id[:12]}…")
            seen.add(quote_id)

    return errors


def main() -> int:
    errors = validate_dataset(CONFIG.data_path)
    if errors:
        for err in errors[:MAX_REPORTED_ERRORS]:
            logger.error(err)
        if len(errors) > MAX_REPORTED_ERRORS:
            logger.error("… and %d more", len(errors) - MAX_REPORTED_ERRORS)
        logger.error("Validation FAILED: %d violation(s) in %s", len(errors), CONFIG.data_path)
        return 1
    logger.info("Validation OK: %s is consistent", CONFIG.data_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
