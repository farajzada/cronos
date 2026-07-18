"""Unit tests for the generic append-only storage in cronos/storage.py."""

from __future__ import annotations

import csv

import pytest

from cronos.storage import DatasetWriter, read_rows

FIELDS = ["id", "value"]


def _rows(*pairs):
    return [{"id": i, "value": v} for i, v in pairs]


def test_writer_rejects_unknown_key_field(tmp_path):
    with pytest.raises(ValueError):
        DatasetWriter(tmp_path / "x.csv", FIELDS, key_field="nope")


def test_writer_creates_file_with_header(tmp_path):
    path = tmp_path / "data.csv"
    appended = DatasetWriter(path, FIELDS, "id").append_unique(iter(_rows(("1", "a"), ("2", "b"))))
    assert appended == 2
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert [r["value"] for r in rows] == ["a", "b"]
    assert list(rows[0].keys()) == FIELDS


def test_writer_is_idempotent_across_runs(tmp_path):
    path = tmp_path / "data.csv"
    writer = DatasetWriter(path, FIELDS, "id")
    batch = _rows(("1", "a"), ("2", "b"))
    assert writer.append_unique(iter(batch)) == 2
    assert writer.append_unique(iter(batch)) == 0  # second run: no dupes
    assert len(read_rows(path)) == 2


def test_writer_deduplicates_within_a_single_batch(tmp_path):
    path = tmp_path / "data.csv"
    batch = _rows(("1", "a"), ("1", "a"), ("1", "a"))
    assert DatasetWriter(path, FIELDS, "id").append_unique(iter(batch)) == 1


def test_writer_appends_only_new_rows(tmp_path):
    path = tmp_path / "data.csv"
    writer = DatasetWriter(path, FIELDS, "id")
    writer.append_unique(iter(_rows(("1", "a"), ("2", "b"))))
    assert writer.append_unique(iter(_rows(("1", "a"), ("2", "b"), ("3", "c")))) == 1
    assert [r["id"] for r in read_rows(path)] == ["1", "2", "3"]  # history preserved


def test_read_rows_missing_file_is_empty_list(tmp_path):
    assert read_rows(tmp_path / "absent.csv") == []
