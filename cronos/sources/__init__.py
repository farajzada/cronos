"""Source registry: maps source names to Source implementations.

Adding a new source to Cronos:
  1. subclass `Source` in a new module under cronos/sources/;
  2. register it in REGISTRY below;
  3. enable it via CRONOS_SOURCES (comma-separated names).
"""

from __future__ import annotations

from typing import Dict, List, Type

from cronos.sources.base import Source
from cronos.sources.hackernews import HackerNewsSource
from cronos.sources.quotes import QuotesSource

REGISTRY: Dict[str, Type[Source]] = {
    QuotesSource.name: QuotesSource,
    HackerNewsSource.name: HackerNewsSource,
}


def get_sources(names) -> List[Source]:
    """Instantiate the requested sources, failing loudly on unknown names."""
    unknown = [n for n in names if n not in REGISTRY]
    if unknown:
        raise KeyError(f"unknown source(s) {unknown}; available: {sorted(REGISTRY)}")
    return [REGISTRY[name]() for name in names]
