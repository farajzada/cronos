"""Unit tests for src/validator.py."""

from __future__ import annotations

import csv

from src.scraper import FIELDNAMES, DatasetWriter, Quote
from src.validator import validate_dataset


def _write_valid_dataset(path):
    quotes = [
        Quote(text="Q1", author="A1", tags="t"),
        Quote(text="Q2", author="A2", tags=""),
    ]
    DatasetWriter(path).append_unique(iter(quotes))
    return quotes


def test_valid_dataset_passes(tmp_path):
    path = tmp_path / "dataset.csv"
    _write_valid_dataset(path)
    assert validate_dataset(path) == []


def test_missing_file_is_reported(tmp_path):
    errors = validate_dataset(tmp_path / "nope.csv")
    assert len(errors) == 1
    assert "not found" in errors[0]


def test_schema_mismatch_is_reported(tmp_path):
    path = tmp_path / "dataset.csv"
    path.write_text("wrong,header\n1,2\n", encoding="utf-8")
    errors = validate_dataset(path)
    assert len(errors) == 1
    assert "schema mismatch" in errors[0]


def test_tampered_row_fails_hash_check(tmp_path):
    path = tmp_path / "dataset.csv"
    quotes = _write_valid_dataset(path)
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    rows[0]["text"] = "Tampered content"  # id no longer matches
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    errors = validate_dataset(path)
    assert any("does not match content hash" in e for e in errors)
    assert quotes[0].quote_id  # sanity: original id existed


def test_duplicate_ids_are_reported(tmp_path):
    path = tmp_path / "dataset.csv"
    q = Quote(text="Q", author="A", tags="")
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerow(q.as_row())
        writer.writerow(q.as_row())
    errors = validate_dataset(path)
    assert any("duplicate quote_id" in e for e in errors)


def test_trailing_whitespace_in_text_is_valid(tmp_path):
    """Regression: hash must be checked against RAW values, not stripped ones.

    quotes.toscrape.com contains a real quote ending in a space; stripping
    before hashing produced a false 'hash mismatch' violation.
    """
    path = tmp_path / "dataset.csv"
    q = Quote(text="Trailing space here. ", author="W.C. Fields", tags="")
    DatasetWriter(path).append_unique(iter([q]))
    assert validate_dataset(path) == []


def test_empty_fields_are_reported(tmp_path):
    path = tmp_path / "dataset.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerow({"quote_id": "x", "text": "", "author": "", "tags": ""})
    errors = validate_dataset(path)
    assert any("empty text" in e for e in errors)
    assert any("empty author" in e for e in errors)
