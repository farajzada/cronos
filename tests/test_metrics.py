"""Unit tests for src/metrics.py."""

from __future__ import annotations

import json

from src.metrics import compute_stats, write_stats
from src.scraper import DatasetWriter, Quote


def _seed(path):
    quotes = [
        Quote(text="Q1", author="Einstein", tags="life|science"),
        Quote(text="Q2", author="Einstein", tags="science"),
        Quote(text="Q3", author="Rowling", tags=""),
    ]
    DatasetWriter(path).append_unique(iter(quotes))


def test_compute_stats_aggregates_correctly(tmp_path):
    path = tmp_path / "dataset.csv"
    _seed(path)
    stats = compute_stats(path)
    assert stats["total_records"] == 3
    assert stats["unique_authors"] == 2
    assert stats["unique_tags"] == 2
    assert stats["top_authors"][0] == {"author": "Einstein", "count": 2}
    assert {"tag": "science", "count": 2} in stats["top_tags"]


def test_empty_tags_are_not_counted(tmp_path):
    path = tmp_path / "dataset.csv"
    _seed(path)
    stats = compute_stats(path)
    assert all(t["tag"] for t in stats["top_tags"])  # no "" tag entries


def test_stats_output_is_deterministic(tmp_path):
    """Same dataset must yield byte-identical stats.json (GitOps no-op)."""
    path = tmp_path / "dataset.csv"
    _seed(path)
    out1 = tmp_path / "stats1.json"
    out2 = tmp_path / "stats2.json"
    write_stats(compute_stats(path), out1)
    write_stats(compute_stats(path), out2)
    assert out1.read_bytes() == out2.read_bytes()
    assert json.loads(out1.read_text(encoding="utf-8"))["total_records"] == 3


def test_step_summary_written_when_env_set(tmp_path, monkeypatch):
    from src.metrics import write_step_summary

    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    path = tmp_path / "dataset.csv"
    _seed(path)
    write_step_summary(compute_stats(path))
    content = summary.read_text(encoding="utf-8")
    assert "Cronos dataset report" in content
    assert "**Records:** 3" in content
