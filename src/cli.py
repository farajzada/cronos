"""Cronos command-line interface.

    cronos run        scrape all enabled sources (idempotent load)
    cronos validate   check dataset integrity
    cronos stats      regenerate data/stats.json
    cronos report     regenerate docs/index.html
    cronos all        run the full pipeline: run → validate → stats → report
    cronos sources    list available and enabled sources

Installed as the `cronos` console script via pyproject.toml, or run as a
module from the repository root:  python -m src.cli <command>
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable, Dict, List

from src import metrics, report, scraper, validator
from src.config import CONFIG
from src.sources import REGISTRY

COMMANDS: Dict[str, Callable[[], int]] = {
    "run": scraper.main,
    "validate": validator.main,
    "stats": metrics.main,
    "report": report.main,
}

PIPELINE_ORDER = ["run", "validate", "stats", "report"]


def cmd_all() -> int:
    for name in PIPELINE_ORDER:
        code = COMMANDS[name]()
        if code != 0:
            print(f"cronos: step {name!r} failed with exit code {code}", file=sys.stderr)
            return code
    return 0


def cmd_sources() -> int:
    for name in sorted(REGISTRY):
        marker = "enabled " if name in CONFIG.sources else "disabled"
        print(f"{marker}  {name:12s}  data/{name}.csv")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cronos",
        description="Serverless GitOps ETL pipeline (scrape → validate → stats → report).",
    )
    parser.add_argument(
        "command",
        choices=[*PIPELINE_ORDER, "all", "sources"],
        help="pipeline stage to execute ('all' runs the full chain)",
    )
    return parser


def main(argv: List[str] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "all":
        return cmd_all()
    if args.command == "sources":
        return cmd_sources()
    return COMMANDS[args.command]()


if __name__ == "__main__":
    sys.exit(main())
