"""Static dashboard generator for the Cronos pipeline.

Renders docs/index.html — a fully self-contained page (inline CSS/JS, data
embedded as JSON, zero external requests) with one tab per enabled source:
stat cards, facet filter chips, and a live-search table, all driven by each
Source's declared display_columns / facet_field.

XSS note: dataset content is untrusted (scraped). Every value interpolated
into markup client-side goes through esc() first; the embedded JSON blob
additionally escapes "</" so the script block cannot be broken out of.

Output is derived purely from dataset content (no timestamps), so
regenerating on an unchanged dataset is byte-identical and the GitOps
commit step stays a graceful no-op. Serve locally with:

    python -m http.server -d docs 8000

Run as a module from the repository root:  python -m src.report
"""

from __future__ import annotations

import json
import logging
import sys

from src.config import CONFIG, PROJECT_ROOT
from src.metrics import compute_source_stats
from src.sources import get_sources
from src.storage import read_rows

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
  .tabs { display: flex; gap: 8px; margin-top: 20px; border-bottom: 1px solid var(--border); }
  .tab { background: none; border: none; color: var(--muted); font-size: 15px; padding: 10px 14px; cursor: pointer; border-bottom: 2px solid transparent; }
  .tab:hover { color: var(--text); }
  .tab.active { color: var(--accent); border-bottom-color: var(--accent); }
  .tab .n { color: var(--muted); font-size: 12px; margin-left: 6px; }
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
  td a { color: var(--accent); text-decoration: none; }
  td .tag { color: var(--accent); font-size: 12px; margin-right: 6px; }
  #count { color: var(--muted); font-size: 13px; margin-bottom: 8px; }
  footer { color: var(--muted); font-size: 13px; margin-top: 24px; text-align: center; }
  footer a { color: var(--accent); text-decoration: none; }
</style>
</head>
<body>
<header>
  <h1>⏱ Cronos — Dataset Dashboard</h1>
  <p>Auto-generated daily by the serverless GitOps ETL pipeline.</p>
</header>

<nav class="tabs" id="tabs"></nav>
<section class="cards" id="cards"></section>
<section>
  <div class="chips" id="chips"></div>
  <input id="search" type="search" placeholder="Search…" autocomplete="off">
  <div id="count"></div>
  <table>
    <thead id="thead"></thead>
    <tbody id="rows"></tbody>
  </table>
</section>

<footer>Built by <a href="https://github.com/farajzada/cronos">Cronos</a> — serverless GitOps ETL.</footer>

<script id="data" type="application/json">__PAYLOAD__</script>
<script>
  const payload = JSON.parse(document.getElementById("data").textContent);
  const sources = payload.sources;
  let active = sources[0];
  let activeFacet = null;

  const tabsEl = document.getElementById("tabs");
  const cardsEl = document.getElementById("cards");
  const chipsEl = document.getElementById("chips");
  const theadEl = document.getElementById("thead");
  const rowsEl = document.getElementById("rows");
  const countEl = document.getElementById("count");
  const searchEl = document.getElementById("search");

  // Dataset content is untrusted (scraped): everything interpolated into
  // markup below MUST pass through esc() first.
  function esc(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
  }

  function renderTabs() {
    tabsEl.innerHTML = sources.map(s =>
      '<button class="tab' + (s === active ? " active" : "") + '" data-name="' + esc(s.name) + '">' +
      esc(s.title) + '<span class="n">' + s.stats.total_records + "</span></button>"
    ).join("");
  }

  function renderCards() {
    const cards = [{num: active.stats.total_records, label: "Records"}];
    for (const [field, agg] of Object.entries(active.stats.fields)) {
      cards.push({num: agg.unique, label: "Unique " + field});
    }
    cardsEl.innerHTML = cards.map(c =>
      '<div class="card"><div class="num">' + esc(c.num) + '</div><div class="label">' +
      esc(c.label) + "</div></div>"
    ).join("");
  }

  function renderChips() {
    if (!active.facet_field) { chipsEl.innerHTML = ""; return; }
    const top = active.stats.fields[active.facet_field].top;
    chipsEl.innerHTML = top.map(t =>
      '<span class="chip' + (t.value === activeFacet ? " active" : "") + '" data-value="' + esc(t.value) + '">' +
      esc(t.value) + '<span class="n">' + t.count + "</span></span>"
    ).join("");
  }

  function cellHtml(row, field) {
    const value = row[field] || "";
    if (field === "tags") {
      return value ? value.split("|").map(t => '<span class="tag">#' + esc(t) + "</span>").join("") : "";
    }
    if (field === "title" && row.url) {
      return '<a href="' + esc(row.url) + '" rel="noopener noreferrer">' + esc(value) + "</a>";
    }
    if (field === "text") {
      return "“" + esc(value) + "”";
    }
    return esc(value);
  }

  function facetMatches(row) {
    if (!activeFacet) return true;
    const raw = row[active.facet_field] || "";
    return active.facet_split
      ? raw.split(active.facet_split).includes(activeFacet)
      : raw === activeFacet;
  }

  function renderTable() {
    theadEl.innerHTML = "<tr>" + active.columns.map(c => "<th>" + esc(c[1]) + "</th>").join("") + "</tr>";
    const q = searchEl.value.trim().toLowerCase();
    const visible = active.records.filter(r => {
      if (!facetMatches(r)) return false;
      if (!q) return true;
      return active.columns.some(c => (r[c[0]] || "").toLowerCase().includes(q));
    });
    rowsEl.innerHTML = visible.map(r =>
      "<tr>" + active.columns.map(c => "<td>" + cellHtml(r, c[0]) + "</td>").join("") + "</tr>"
    ).join("");
    countEl.textContent = visible.length + " / " + active.records.length + " records";
  }

  function renderAll() { renderTabs(); renderCards(); renderChips(); renderTable(); }

  tabsEl.addEventListener("click", e => {
    const tab = e.target.closest(".tab");
    if (!tab) return;
    active = sources.find(s => s.name === tab.dataset.name);
    activeFacet = null;
    searchEl.value = "";
    renderAll();
  });

  chipsEl.addEventListener("click", e => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    activeFacet = activeFacet === chip.dataset.value ? null : chip.dataset.value;
    renderChips();
    renderTable();
  });

  searchEl.addEventListener("input", renderTable);
  renderAll();
</script>
</body>
</html>
"""


def build_payload() -> dict:
    sources_payload = []
    for source in get_sources(CONFIG.sources):
        path = source.dataset_path(CONFIG.data_dir)
        if not path.exists():
            continue
        rows = read_rows(path)
        facet_split = (
            dict(source.stat_fields).get(source.facet_field) if source.facet_field else None
        )
        sources_payload.append(
            {
                "name": source.name,
                "title": source.title,
                "columns": [list(pair) for pair in source.display_columns],
                "facet_field": source.facet_field,
                "facet_split": facet_split,
                "records": rows,
                "stats": compute_source_stats(source, rows),
            }
        )
    return {"sources": sources_payload}


def build_report() -> str:
    payload = build_payload()
    # "</" must be escaped inside an inline <script> block
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
    return TEMPLATE.replace("__PAYLOAD__", blob)


def main() -> int:
    payload_check = build_payload()
    if not payload_check["sources"]:
        logger.error("no datasets found under %s", CONFIG.data_dir)
        return 1

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    html = build_report()
    REPORT_PATH.write_text(html, encoding="utf-8")
    logger.info("Dashboard written to %s (%d bytes)", REPORT_PATH, len(html.encode("utf-8")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
