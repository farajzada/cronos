"""Unit tests for src/metrics.py."""

from __future__ import annotations

import json

from src.metrics import compute_source_stats, write_stats, write_step_summary
from src.sources.quotes import Quote, QuotesSource
from src.storage import DatasetWriter, read_rows


def _seed(path):
    quotes = [
        Quote(text="Q1", author="Einstein", tags="life|science"),
        Quote(text="Q2", author="Einstein", tags="science"),
        Quote(text="Q3", author="Rowling", tags=""),
    ]
    DatasetWriter(path, QuotesSource.fieldnames, QuotesSource.key_field).append_unique(
        q.as_row() for q in quotes
    )


def test_compute_source_stats_aggregates_declared_fields(tmp_path):
    path = tmp_path / "quotes.csv"
    _seed(path)
    stats = compute_source_stats(QuotesSource(), read_rows(path))
    assert stats["total_records"] == 3
    assert stats["fields"]["author"]["unique"] == 2
    assert stats["fields"]["author"]["top"][0] == {"value": "Einstein", "count": 2}
    assert stats["fields"]["tags"]["unique"] == 2
    assert {"value": "science", "count": 2} in stats["fields"]["tags"]["top"]


def test_split_fields_ignore_empty_values(tmp_path):
    path = tmp_path / "quotes.csv"
    _seed(path)
    stats = compute_source_stats(QuotesSource(), read_rows(path))
    assert all(t["value"] for t in stats["fields"]["tags"]["top"])  # no "" entries


def test_stats_output_is_deterministic(tmp_path):
    """Same dataset must yield byte-identical stats.json (GitOps no-op)."""
    path = tmp_path / "quotes.csv"
    _seed(path)
    stats = {
        "total_records": 3,
        "sources": {"quotes": compute_source_stats(QuotesSource(), read_rows(path))},
    }
    out1 = tmp_path / "stats1.json"
    out2 = tmp_path / "stats2.json"
    write_stats(stats, out1)
    write_stats(stats, out2)
    assert out1.read_bytes() == out2.read_bytes()
    assert json.loads(out1.read_text(encoding="utf-8"))["total_records"] == 3


def test_step_summary_written_when_env_set(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    path = tmp_path / "quotes.csv"
    _seed(path)
    stats = {
        "total_records": 3,
        "sources": {"quotes": compute_source_stats(QuotesSource(), read_rows(path))},
    }
    write_step_summary(stats)
    content = summary.read_text(encoding="utf-8")
    assert "Cronos dataset report" in content
    assert "**Total records:** 3" in content
    assert "**quotes:** 3 records" in content
