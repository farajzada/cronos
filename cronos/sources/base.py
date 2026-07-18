"""Source contract: everything Cronos needs to ingest a new data source.

A Source declares its schema (fieldnames + unique key), how to scrape
itself into normalized rows, per-row integrity rules, and which fields the
metrics/dashboard layers should aggregate and display. The pipeline
(scraper, validator, metrics, report) is fully generic over this contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from cronos.http_client import HttpClient


class Source(ABC):
    #: unique registry name, also the dataset filename stem (data/<name>.csv)
    name: str
    #: human title shown in the dashboard
    title: str
    #: CSV schema, in column order
    fieldnames: List[str]
    #: column holding the deduplication key
    key_field: str
    #: (field, label) pairs rendered as dashboard table columns
    display_columns: List[Tuple[str, str]]
    #: fields aggregated by metrics: (field, split_char_or_None)
    stat_fields: List[Tuple[str, Optional[str]]]
    #: field powering the dashboard filter chips (must be in stat_fields)
    facet_field: Optional[str] = None

    def dataset_path(self, data_dir: Path) -> Path:
        return data_dir / f"{self.name}.csv"

    @abstractmethod
    def scrape(self, client: HttpClient) -> Iterator[Dict[str, str]]:
        """Yield normalized rows matching `fieldnames` exactly."""

    def validate_row(self, row: Dict[str, str]) -> List[str]:
        """Source-specific integrity checks; return violation messages."""
        return []
