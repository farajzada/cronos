"""Unit tests for cronos/report.py (multi-source dashboard)."""

from __future__ import annotations

import json
import re

import pytest

from cronos.report import build_report
from cronos.sources.quotes import Quote, QuotesSource
from cronos.storage import DatasetWriter


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Point the report at an isolated data dir with a seeded quotes set."""
    from cronos import config, metrics, report

    test_config = config.Config.from_env()
    object.__setattr__(test_config, "data_dir", tmp_path)  # frozen dataclass
    object.__setattr__(test_config, "sources", ("quotes",))
    monkeypatch.setattr(report, "CONFIG", test_config)
    monkeypatch.setattr(metrics, "CONFIG", test_config)

    quotes = [
        Quote(text="Q1", author="Einstein", tags="life|science"),
        Quote(text="Q2", author="Rowling", tags=""),
    ]
    DatasetWriter(
        tmp_path / "quotes.csv", QuotesSource.fieldnames, QuotesSource.key_field
    ).append_unique(q.as_row() for q in quotes)
    return tmp_path


def _extract_payload(html):
    match = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S)
    assert match, "embedded JSON payload not found"
    return json.loads(match.group(1).replace("<\\/", "</"))


def test_report_embeds_sources_records_and_stats(data_dir):
    payload = _extract_payload(build_report())
    assert len(payload["sources"]) == 1
    quotes = payload["sources"][0]
    assert quotes["name"] == "quotes"
    assert quotes["facet_field"] == "tags"
    assert quotes["facet_split"] == "|"
    assert len(quotes["records"]) == 2
    assert quotes["stats"]["total_records"] == 2
    assert quotes["columns"][0] == ["text", "Quote"]


def test_report_is_deterministic(data_dir):
    """Unchanged dataset must render byte-identical HTML (GitOps no-op)."""
    assert build_report() == build_report()


def test_script_breakout_is_escaped(data_dir):
    """A record containing </script> must not terminate the data block."""
    DatasetWriter(
        data_dir / "quotes.csv", QuotesSource.fieldnames, QuotesSource.key_field
    ).append_unique(
        iter([Quote(text="evil </script><script>alert(1)</script>", author="X", tags="").as_row()])
    )
    html = build_report()
    payload_zone = html.split('<script id="data"', 1)[1]
    blob = payload_zone.split("</script>", 1)[0]  # first real terminator
    assert "<\\/script>" in blob  # malicious text stayed inside, escaped
    records = json.loads(blob.split(">", 1)[1].replace("<\\/", "</"))["sources"][0]["records"]
    assert any(r["text"].startswith("evil ") for r in records)


def test_report_is_self_contained(data_dir):
    """No external requests: no http(s) src/href except embedded record links."""
    html = build_report()
    static_zone = html.split('<script id="data"', 1)[0]
    external = re.findall(r'(?:src|href)="(https?://[^"]+)"', static_zone)
    assert external == ["https://github.com/farajzada/cronos"]


def test_report_ships_theme_toggle_and_downloads(data_dir):
    html = build_report()
    assert 'id="theme-toggle"' in html
    assert 'id="dl-csv"' in html
    assert 'id="dl-json"' in html
    assert '[data-theme="light"]' in html  # light palette defined
    payload = _extract_payload(html)
    assert payload["raw_base"].startswith("https://raw.githubusercontent.com/")
