"""Dataset statistics generator for the Cronos pipeline.

Derives data/stats.json purely from the dataset content — no timestamps,
no randomness — so regenerating it on an unchanged dataset produces a
byte-identical file and the GitOps step stays a graceful no-op.

Also appends a markdown run report to $GITHUB_STEP_SUMMARY when running
inside GitHub Actions.

Run as a module from the repository root:  python -m src.metrics
"""

from __future__ import annotations

import csv
import json
import logging
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List

from src.config import CONFIG

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("cronos.metrics")

TOP_N = 10


def stats_path() -> Path:
    return CONFIG.data_path.parent / "stats.json"


def compute_stats(path: Path) -> Dict:
    """Aggregate deterministic statistics from the dataset CSV."""
    with path.open("r", newline="", encoding="utf-8") as fh:
        rows: List[dict] = list(csv.DictReader(fh))

    authors = Counter(row["author"] for row in rows)
    tags: Counter = Counter()
    for row in rows:
        for tag in filter(None, (row.get("tags") or "").split("|")):
            tags[tag] += 1

    return {
        "total_records": len(rows),
        "unique_authors": len(authors),
        "unique_tags": len(tags),
        "top_authors": [
            {"author": name, "count": count} for name, count in authors.most_common(TOP_N)
        ],
        "top_tags": [
            {"tag": name, "count": count} for name, count in tags.most_common(TOP_N)
        ],
    }


def write_stats(stats: Dict, path: Path) -> None:
    path.write_text(
        json.dumps(stats, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_step_summary(stats: Dict) -> None:
    """Publish a run report to the GitHub Actions job summary, if available."""
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_file:
        return
    top_tags = ", ".join(f"`{t['tag']}` ({t['count']})" for t in stats["top_tags"][:5])
    lines = [
        "## Cronos dataset report",
        "",
        f"- **Records:** {stats['total_records']}",
        f"- **Authors:** {stats['unique_authors']}",
        f"- **Tags:** {stats['unique_tags']}",
        f"- **Top tags:** {top_tags}",
    ]
    with open(summary_file, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main() -> int:
    if not CONFIG.data_path.exists():
        logger.error("dataset not found: %s", CONFIG.data_path)
        return 1

    stats = compute_stats(CONFIG.data_path)
    write_stats(stats, stats_path())
    write_step_summary(stats)
    logger.info(
        "Stats written to %s (%d records, %d authors, %d tags)",
        stats_path(),
        stats["total_records"],
        stats["unique_authors"],
        stats["unique_tags"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
