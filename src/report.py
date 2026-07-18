"""Static dashboard generator for the Cronos pipeline.

Renders docs/index.html — a fully self-contained page (inline CSS/JS, data
embedded as JSON, zero external requests) visualizing the current dataset:
stat cards, top-tag chips, and a live-search table.

XSS note: dataset content is untrusted (scraped). Every value interpolated
into markup client-side goes through esc() first; the embedded JSON blob
additionally escapes "</" so the script block cannot be broken out of.

Output is derived purely from dataset content (no timestamps), so
regenerating on an unchanged dataset is byte-identical and the GitOps
commit step stays a graceful no-op. Serve locally with:

    python -m http.server -d docs 8000

or publish via GitHub Pages (Settings → Pages → main /docs).

Run as a module from the repository root:  python -m src.report
"""

from __future__ import annotations

import csv
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List

from src.config import CONFIG, PROJECT_ROOT
from src.metrics import compute_stats

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("cronos.report")

DOCS_DIR = PROJECT_ROOT / "docs"
REPORT_PATH = DOCS_DIR / "index.html"

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cronos — Dataset Dashboard</title>
<style>
  :root {
    --bg: #0f1420; --panel: #171e2e; --border: #26304a;
    --text: #e6ecff; --muted: #8b97b8; --accent: #5b8cff; --chip: #22304f;
  }
  * { box-sizing: border-box; margin: 0; }
  body {
    background: var(--bg); color: var(--text);
    font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    padding: 32px 16px; max-width: 1000px; margin: 0 auto;
  }
  header h1 { font-size: 26px; letter-spacing: .5px; }
  header p { color: var(--muted); margin-top: 4px; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin: 24px 0; }
  .card { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
  .card .num { font-size: 30px; font-weight: 700; color: var(--accent); }
  .card .label { color: var(--muted); font-size: 13px; text-transform: uppercase; letter-spacing: .8px; }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 24px; }
  .chip { background: var(--chip); border: 1px solid var(--border); border-radius: 999px; padding: 4px 12px; font-size: 13px; cursor: pointer; user-select: none; }
  .chip:hover, .chip.active { border-color: var(--accent); color: var(--accent); }
  .chip .n { color: var(--muted); margin-left: 4px; }
  #search { width: 100%; padding: 12px 14px; border-radius: 10px; border: 1px solid var(--border); background: var(--panel); color: var(--text); font-size: 15px; margin-bottom: 16px; outline: none; }
  #search:focus { border-color: var(--accent); }
  table { width: 100%; border-collapse: collapse; background: var(--panel); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
  th, td { text-align: left; padding: 10px 14px; border-bottom: 1px solid var(--border); vertical-align: top; }
  th { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .8px; }
  tr:last-child td { border-bottom: none; }
  td.quote { width: 60%; }
  td .tag { color: var(--accent); font-size: 12px; margin-right: 6px; }
  #count { color: var(--muted); font-size: 13px; margin-bottom: 8px; }
  footer { color: var(--muted); font-size: 13px; margin-top: 24px; text-align: center; }
  footer a { color: var(--accent); text-decoration: none; }
</style>
</head>
<body>
<header>
  <h1>⏱ Cronos — Dataset Dashboard</h1>
  <p>Auto-generated from <code>data/dataset.csv</code> by the daily ETL pipeline.</p>
</header>

<section class="cards">
  <div class="card"><div class="num" id="stat-records"></div><div class="label">Records</div></div>
  <div class="card"><div class="num" id="stat-authors"></div><div class="label">Authors</div></div>
  <div class="card"><div class="num" id="stat-tags"></div><div class="label">Unique tags</div></div>
</section>

<section>
  <div class="chips" id="chips"></div>
  <input id="search" type="search" placeholder="Search quotes, authors or tags…" autocomplete="off">
  <div id="count"></div>
  <table>
    <thead><tr><th>Quote</th><th>Author</th><th>Tags</th></tr></thead>
    <tbody id="rows"></tbody>
  </table>
</section>

<footer>Built by <a href="https://github.com/farajzada/cronos">Cronos</a> — serverless GitOps ETL.</footer>

<script id="data" type="application/json">__PAYLOAD__</script>
<script>
  const payload = JSON.parse(document.getElementById("data").textContent);
  const { records, stats } = payload;

  document.getElementById("stat-records").textContent = stats.total_records;
  document.getElementById("stat-authors").textContent = stats.unique_authors;
  document.getElementById("stat-tags").textContent = stats.unique_tags;

  const rowsEl = document.getElementById("rows");
  const countEl = document.getElementById("count");
  const searchEl = document.getElementById("search");
  const chipsEl = document.getElementById("chips");
  let activeTag = null;

  // Dataset content is untrusted (scraped): everything interpolated into
  // markup below MUST pass through esc() first.
  function esc(s) {
    return s.replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
  }

  function render() {
    const q = searchEl.value.trim().toLowerCase();
    const visible = records.filter(r => {
      if (activeTag && !r.tags.split("|").includes(activeTag)) return false;
      if (!q) return true;
      return (r.text + " " + r.author + " " + r.tags).toLowerCase().includes(q);
    });
    rowsEl.innerHTML = visible.map(r => {
      const tags = r.tags
        ? r.tags.split("|").map(t => '<span class="tag">#' + esc(t) + "</span>").join("")
        : "";
      return "<tr><td class='quote'>“" + esc(r.text) + "”</td><td>" +
             esc(r.author) + "</td><td>" + tags + "</td></tr>";
    }).join("");
    countEl.textContent = visible.length + " / " + records.length + " records";
  }

  chipsEl.innerHTML = stats.top_tags.map(t =>
    '<span class="chip" data-tag="' + esc(t.tag) + '">#' + esc(t.tag) +
    '<span class="n">' + t.count + "</span></span>"
  ).join("");

  chipsEl.addEventListener("click", e => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    activeTag = activeTag === chip.dataset.tag ? null : chip.dataset.tag;
    document.querySelectorAll(".chip").forEach(c =>
      c.classList.toggle("active", c.dataset.tag === activeTag));
    render();
  });

  searchEl.addEventListener("input", render);
  render();
</script>
</body>
</html>
"""


def load_records(path: Path) -> List[Dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as fh:
        return [
            {"text": row["text"], "author": row["author"], "tags": row["tags"]}
            for row in csv.DictReader(fh)
        ]


def build_report(dataset_path: Path) -> str:
    payload = {
        "records": load_records(dataset_path),
        "stats": compute_stats(dataset_path),
    }
    # "</" must be escaped inside an inline <script> block
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
    return TEMPLATE.replace("__PAYLOAD__", blob)


def main() -> int:
    if not CONFIG.data_path.exists():
        logger.error("dataset not found: %s", CONFIG.data_path)
        return 1

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    html = build_report(CONFIG.data_path)
    REPORT_PATH.write_text(html, encoding="utf-8")
    logger.info("Dashboard written to %s (%d bytes)", REPORT_PATH, len(html.encode("utf-8")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
