"""Unit tests for the generic validator in cronos/validator.py."""

from __future__ import annotations

import csv

from cronos.sources.hackernews import HackerNewsSource
from cronos.sources.quotes import Quote, QuotesSource
from cronos.storage import DatasetWriter
from cronos.validator import validate_source


def _write(path, source, rows):
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=source.fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _valid_quotes_file(path):
    quotes = [Quote(text="Q1", author="A1", tags="t"), Quote(text="Q2", author="A2", tags="")]
    DatasetWriter(path, QuotesSource.fieldnames, QuotesSource.key_field).append_unique(
        q.as_row() for q in quotes
    )


def test_valid_quotes_dataset_passes(tmp_path):
    path = tmp_path / "quotes.csv"
    _valid_quotes_file(path)
    assert validate_source(QuotesSource(), path) == []


def test_schema_mismatch_is_reported(tmp_path):
    path = tmp_path / "quotes.csv"
    path.write_text("wrong,header\n1,2\n", encoding="utf-8")
    errors = validate_source(QuotesSource(), path)
    assert len(errors) == 1
    assert "schema mismatch" in errors[0]


def test_duplicate_keys_are_reported(tmp_path):
    path = tmp_path / "quotes.csv"
    q = Quote(text="Q", author="A", tags="")
    _write(path, QuotesSource(), [q.as_row(), q.as_row()])
    errors = validate_source(QuotesSource(), path)
    assert any("duplicate quote_id" in e for e in errors)


def test_empty_key_is_reported(tmp_path):
    source = HackerNewsSource()
    path = tmp_path / "hackernews.csv"
    _write(
        path,
        source,
        [
            {
                "item_id": "",
                "title": "T",
                "url": "https://x.io",
                "domain": "x.io",
                "author": "a",
                "points": "1",
            }
        ],
    )
    errors = validate_source(source, path)
    assert any("empty item_id" in e for e in errors)


def test_source_specific_rules_are_applied(tmp_path):
    """Tampered quote text must fail the content-hash rule via the source."""
    path = tmp_path / "quotes.csv"
    q = Quote(text="Original", author="A", tags="")
    row = q.as_row()
    row["text"] = "Tampered"
    _write(path, QuotesSource(), [row])
    errors = validate_source(QuotesSource(), path)
    assert any("does not match content hash" in e for e in errors)


def test_hackernews_rules_are_applied(tmp_path):
    source = HackerNewsSource()
    path = tmp_path / "hackernews.csv"
    _write(
        path,
        source,
        [
            {
                "item_id": "1",
                "title": "T",
                "url": "https://x.io",
                "domain": "x.io",
                "author": "a",
                "points": "not-a-number",
            }
        ],
    )
    errors = validate_source(source, path)
    assert any("points" in e for e in errors)
