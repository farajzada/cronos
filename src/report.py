"""Static dashboard generator for the Cronos pipeline.

Renders docs/index.html — a fully self-contained page (inline CSS/JS, data
embedded as JSON, zero external requests at render time) with one tab per
enabled source: stat cards, an SVG bar chart of the top facet values,
facet filter chips, a live-search table, light/dark theme toggle and
CSV/JSON download links, all driven by each Source's declared metadata.

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
REPO_URL = "https://github.com/farajzada/cronos"
RAW_BASE = "https://raw.githubusercontent.com/farajzada/cronos/main"

TEMPLATE = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cronos — Dataset Dashboard</title>
<style>
  :root, [data-theme="dark"] {
    --bg: #0f1420; --panel: #171e2e; --border: #26304a;
    --text: #e6ecff; --muted: #8b97b8; --accent: #5b8cff; --chip: #22304f;
    --bar: #3a5fd9;
  }
  [data-theme="light"] {
    --bg: #f4f6fb; --panel: #ffffff; --border: #d9e0ef;
    --text: #1a2233; --muted: #5d6b8a; --accent: #2f5fe0; --chip: #e8edf9;
    --bar: #7aa0ff;
  }
  * { box-sizing: border-box; margin: 0; }
  body {
    background: var(--bg); color: var(--text);
    font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    padding: 32px 16px; max-width: 1000px; margin: 0 auto;
    transition: background .2s, color .2s;
  }
  header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
  header h1 { font-size: 26px; letter-spacing: .5px; }
  header p { color: var(--muted); margin-top: 4px; }
  .actions { display: flex; gap: 8px; flex-shrink: 0; }
  .btn {
    background: var(--panel); border: 1px solid var(--border); color: var(--text);
    border-radius: 8px; padding: 7px 12px; font-size: 13px; cursor: pointer;
    text-decoration: none; display: inline-flex; align-items: center; gap: 6px;
  }
  .btn:hover { border-color: var(--accent); color: var(--accent); }
  .tabs { display: flex; gap: 8px; margin-top: 20px; border-bottom: 1px solid var(--border); }
  .tab { background: none; border: none; color: var(--muted); font-size: 15px; padding: 10px 14px; cursor: pointer; border-bottom: 2px solid transparent; }
  .tab:hover { color: var(--text); }
  .tab.active { color: var(--accent); border-bottom-color: var(--accent); }
  .tab .n { color: var(--muted); font-size: 12px; margin-left: 6px; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin: 24px 0; }
  .card { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
  .card .num { font-size: 30px; font-weight: 700; color: var(--accent); }
  .card .label { color: var(--muted); font-size: 13px; text-transform: uppercase; letter-spacing: .8px; }
  .chart-panel { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 16px; margin-bottom: 24px; }
  .chart-panel h2 { font-size: 13px; color: var(--muted); text-transform: uppercase; letter-spacing: .8px; margin-bottom: 12px; }
  .chart-panel svg { width: 100%; height: auto; display: block; }
  .chart-panel text { fill: var(--text); font-size: 12px; }
  .chart-panel .count-label { fill: var(--muted); }
  .chart-panel rect { fill: var(--bar); }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 24px; }
  .chip { background: var(--chip); border: 1px solid var(--border); border-radius: 999px; padding: 4px 12px; font-size: 13px; cursor: pointer; user-select: none; }
  .chip:hover, .chip.active { border-color: var(--accent); color: var(--accent); }
  .chip .n { color: var(--muted); margin-left: 4px; }
  #search { width: 100%; padding: 12px 14px; border-radius: 10px; border: 1px solid var(--border); background: var(--panel); color: var(--text); font-size: 15px; margin-bottom: 16px; outline: none; }
  #search:focus { border-color: var(--accent); }
  .table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: 10px; }
  table { width: 100%; border-collapse: collapse; background: var(--panel); }
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
  <div>
    <h1>⏱ Cronos — Dataset Dashboard</h1>
    <p>Auto-generated daily by the serverless GitOps ETL pipeline.</p>
  </div>
  <div class="actions">
    <a class="btn" id="dl-csv" href="#" download>⬇ CSV</a>
    <button class="btn" id="dl-json" type="button">⬇ JSON</button>
    <button class="btn" id="theme-toggle" type="button" aria-label="Toggle theme">◐</button>
  </div>
</header>

<nav class="tabs" id="tabs"></nav>
<section class="cards" id="cards"></section>
<section class="chart-panel" id="chart-panel">
  <h2 id="chart-title"></h2>
  <div id="chart"></div>
</section>
<section>
  <div class="chips" id="chips"></div>
  <input id="search" type="search" placeholder="Search…" autocomplete="off">
  <div id="count"></div>
  <div class="table-wrap">
    <table>
      <thead id="thead"></thead>
      <tbody id="rows"></tbody>
    </table>
  </div>
</section>

<footer>Built by <a href="__REPO_URL__">Cronos</a> — serverless GitOps ETL.</footer>

<script id="data" type="application/json">__PAYLOAD__</script>
<script>
  const payload = JSON.parse(document.getElementById("data").textContent);
  const sources = payload.sources;
  const RAW_BASE = payload.raw_base;
  let active = sources[0];
  let activeFacet = null;

  const tabsEl = document.getElementById("tabs");
  const cardsEl = document.getElementById("cards");
  const chipsEl = document.getElementById("chips");
  const chartEl = document.getElementById("chart");
  const chartTitleEl = document.getElementById("chart-title");
  const theadEl = document.getElementById("thead");
  const rowsEl = document.getElementById("rows");
  const countEl = document.getElementById("count");
  const searchEl = document.getElementById("search");

  // --- theme ------------------------------------------------------------
  const root = document.documentElement;
  function applyTheme(theme) {
    root.setAttribute("data-theme", theme);
    try { localStorage.setItem("cronos-theme", theme); } catch (e) { /* private mode */ }
  }
  (function initTheme() {
    let saved = null;
    try { saved = localStorage.getItem("cronos-theme"); } catch (e) { /* private mode */ }
    if (saved) { applyTheme(saved); return; }
    if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) {
      applyTheme("light");
    }
  })();
  document.getElementById("theme-toggle").addEventListener("click", () => {
    applyTheme(root.getAttribute("data-theme") === "dark" ? "light" : "dark");
  });

  // --- helpers ----------------------------------------------------------
  // Dataset content is untrusted (scraped): everything interpolated into
  // markup below MUST pass through esc() first.
  function esc(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
  }

  // --- downloads ----------------------------------------------------------
  const dlCsv = document.getElementById("dl-csv");
  function refreshDownloadLinks() {
    dlCsv.href = RAW_BASE + "/data/" + active.name + ".csv";
    dlCsv.setAttribute("download", active.name + ".csv");
  }
  document.getElementById("dl-json").addEventListener("click", () => {
    const blob = new Blob(
      [JSON.stringify({ source: active.name, records: active.records }, null, 2)],
      { type: "application/json" }
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = active.name + ".json";
    a.click();
    URL.revokeObjectURL(url);
  });

  // --- renderers ----------------------------------------------------------
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

  function renderChart() {
    if (!active.facet_field) { chartEl.innerHTML = ""; chartTitleEl.textContent = ""; return; }
    const top = active.stats.fields[active.facet_field].top.slice(0, 8);
    chartTitleEl.textContent = "Top " + active.facet_field;
    if (!top.length) { chartEl.innerHTML = ""; return; }
    const max = top[0].count;
    const rowH = 28, labelW = 180, countW = 44, barMax = 420;
    const width = labelW + barMax + countW, height = top.length * rowH;
    const bars = top.map((t, i) => {
      const w = Math.max(2, Math.round(barMax * t.count / max));
      const y = i * rowH;
      const label = t.value.length > 24 ? t.value.slice(0, 23) + "…" : t.value;
      return '<text x="' + (labelW - 8) + '" y="' + (y + 18) + '" text-anchor="end">' + esc(label) + "</text>" +
             '<rect x="' + labelW + '" y="' + (y + 5) + '" width="' + w + '" height="16" rx="4"><title>' +
             esc(t.value) + ": " + t.count + "</title></rect>" +
             '<text class="count-label" x="' + (labelW + w + 8) + '" y="' + (y + 18) + '">' + t.count + "</text>";
    }).join("");
    chartEl.innerHTML =
      '<svg viewBox="0 0 ' + width + " " + height + '" role="img" aria-label="Top ' +
      esc(active.facet_field) + ' bar chart">' + bars + "</svg>";
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

  function renderAll() {
    renderTabs(); renderCards(); renderChart(); renderChips(); renderTable();
    refreshDownloadLinks();
  }

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
    return {"sources": sources_payload, "raw_base": RAW_BASE}


def build_report() -> str:
    payload = build_payload()
    # "</" must be escaped inside an inline <script> block
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
    return TEMPLATE.replace("__PAYLOAD__", blob).replace("__REPO_URL__", REPO_URL)


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
