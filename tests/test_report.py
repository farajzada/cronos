"""Unit tests for src/report.py."""

from __future__ import annotations

import json
import re

from src.report import build_report
from src.scraper import DatasetWriter, Quote


def _seed(path, quotes=None):
    quotes = quotes or [
        Quote(text="Q1", author="Einstein", tags="life|science"),
        Quote(text="Q2", author="Rowling", tags=""),
    ]
    DatasetWriter(path).append_unique(iter(quotes))


def _extract_payload(html):
    match = re.search(
        r'<script id="data" type="application/json">(.*?)</script>', html, re.S
    )
    assert match, "embedded JSON payload not found"
    return json.loads(match.group(1).replace("<\\/", "</"))


def test_report_embeds_all_records_and_stats(tmp_path):
    path = tmp_path / "dataset.csv"
    _seed(path)
    payload = _extract_payload(build_report(path))
    assert len(payload["records"]) == 2
    assert payload["stats"]["total_records"] == 2
    assert payload["records"][0] == {"text": "Q1", "author": "Einstein", "tags": "life|science"}


def test_report_is_deterministic(tmp_path):
    """Unchanged dataset must render byte-identical HTML (GitOps no-op)."""
    path = tmp_path / "dataset.csv"
    _seed(path)
    assert build_report(path) == build_report(path)


def test_script_breakout_is_escaped(tmp_path):
    """A record containing </script> must not terminate the data block."""
    path = tmp_path / "dataset.csv"
    _seed(path, [Quote(text="evil </script><script>alert(1)</script>", author="X", tags="")])
    html = build_report(path)
    payload_zone = html.split('<script id="data"', 1)[1]
    blob = payload_zone.split("</script>", 1)[0]  # first real terminator
    # the malicious text must still be fully inside the JSON blob, escaped
    assert "<\\/script>" in blob
    assert json.loads(blob.split(">", 1)[1].replace("<\\/", "</"))["records"][0][
        "text"
    ].startswith("evil ")


def test_report_is_self_contained(tmp_path):
    """No external requests: no http(s) src/href except the repo link."""
    path = tmp_path / "dataset.csv"
    _seed(path)
    html = build_report(path)
    external = re.findall(r'(?:src|href)="(https?://[^"]+)"', html)
    assert external == ["https://github.com/farajzada/cronos"]
