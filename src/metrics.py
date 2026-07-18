"""Dataset statistics generator for the Cronos pipeline.

Derives data/stats.json purely from dataset content — no timestamps, no
randomness — so regenerating on unchanged data produces a byte-identical
file and the GitOps step stays a graceful no-op.

Shape (fully generic over sources and their declared stat_fields):

    {
      "total_records": 130,
      "sources": {
        "quotes": {
          "total_records": 100,
          "fields": {
            "author": {"unique": 50, "top": [{"value": "...", "count": 10}, …]},
            "tags":   {"unique": 137, "top": […]}
          }
        },
        …
      }
    }

Also appends a markdown run report to $GITHUB_STEP_SUMMARY when running
inside GitHub Actions.

Run as a module from the repository root:  python -m src.metrics
"""

from __future__ import annotations

import json
import logging
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List

from src.config import CONFIG
from src.sources import get_sources
from src.sources.base import Source
from src.storage import read_rows

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("cronos.metrics")

TOP_N = 10


def stats_path() -> Path:
    return CONFIG.data_dir / "stats.json"


def compute_source_stats(source: Source, rows: List[dict]) -> Dict:
    fields: Dict[str, Dict] = {}
    for field, split in source.stat_fields:
        counter: Counter = Counter()
        for row in rows:
            raw = row.get(field) or ""
            values = filter(None, raw.split(split)) if split else ([raw] if raw else [])
            counter.update(values)
        fields[field] = {
            "unique": len(counter),
            "top": [{"value": v, "count": c} for v, c in counter.most_common(TOP_N)],
        }
    return {"total_records": len(rows), "fields": fields}


def compute_stats() -> Dict:
    sources_stats: Dict[str, Dict] = {}
    total = 0
    for source in get_sources(CONFIG.sources):
        rows = read_rows(source.dataset_path(CONFIG.data_dir))
        if not rows and not source.dataset_path(CONFIG.data_dir).exists():
            continue  # source never scraped yet
        sources_stats[source.name] = compute_source_stats(source, rows)
        total += len(rows)
    return {"total_records": total, "sources": sources_stats}


def write_stats(stats: Dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(stats, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_step_summary(stats: Dict) -> None:
    """Publish a run report to the GitHub Actions job summary, if available."""
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_file:
        return
    lines = ["## Cronos dataset report", ""]
    lines.append(f"- **Total records:** {stats['total_records']}")
    for name, src_stats in sorted(stats["sources"].items()):
        parts = [f"{src_stats['total_records']} records"]
        for field, agg in sorted(src_stats["fields"].items()):
            parts.append(f"{agg['unique']} unique {field}")
        lines.append(f"- **{name}:** " + ", ".join(parts))
    with open(summary_file, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main() -> int:
    stats = compute_stats()
    if not stats["sources"]:
        logger.error("no datasets found under %s", CONFIG.data_dir)
        return 1

    write_stats(stats, stats_path())
    write_step_summary(stats)
    logger.info(
        "Stats written to %s (%d records across %d sources)",
        stats_path(),
        stats["total_records"],
        len(stats["sources"]),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
