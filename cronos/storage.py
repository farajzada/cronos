"""Generic append-only, deduplicated CSV storage.

Works for any source: the writer is parameterized with the column list and
the unique-key column. Existing keys are loaded into a set() for O(1)
membership checks, making every load idempotent — history is never
rewritten, only new unique rows are appended.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Dict, Iterator, List, Set

logger = logging.getLogger("cronos.storage")


class DatasetWriter:
    """Appends only unseen rows to the CSV; never overwrites history."""

    def __init__(self, path: Path, fieldnames: List[str], key_field: str) -> None:
        if key_field not in fieldnames:
            raise ValueError(f"key_field {key_field!r} must be one of {fieldnames}")
        self.path = path
        self.fieldnames = fieldnames
        self.key_field = key_field
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load_existing_keys(self) -> Set[str]:
        """Load current dedup keys into a set for O(1) lookups."""
        if not self.path.exists():
            return set()
        with self.path.open("r", newline="", encoding="utf-8") as fh:
            return {row[self.key_field] for row in csv.DictReader(fh) if row.get(self.key_field)}

    def append_unique(self, rows: Iterator[Dict[str, str]]) -> int:
        seen = self.load_existing_keys()
        logger.info("%s: existing dataset contains %d unique records", self.path.name, len(seen))

        is_new_file = not self.path.exists() or self.path.stat().st_size == 0
        appended = 0
        with self.path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=self.fieldnames)
            if is_new_file:
                writer.writeheader()
            for row in rows:
                key = row[self.key_field]
                if key in seen:
                    continue
                writer.writerow(row)
                seen.add(key)  # guards against in-batch duplicates too
                appended += 1
        return appended


def read_rows(path: Path) -> List[Dict[str, str]]:
    """Read a dataset CSV into a list of dicts (empty list if missing)."""
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))
