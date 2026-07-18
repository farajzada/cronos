# Cronos — Serverless Multi-Source ETL Pipeline

[![Cronos ETL Pipeline](https://github.com/farajzada/cronos/actions/workflows/cronos_pipeline.yml/badge.svg)](https://github.com/farajzada/cronos/actions/workflows/cronos_pipeline.yml)
[![CI](https://github.com/farajzada/cronos/actions/workflows/ci.yml/badge.svg)](https://github.com/farajzada/cronos/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Lint: ruff](https://img.shields.io/badge/lint-ruff-261230)](https://github.com/astral-sh/ruff)

> Fully automated, serverless, **zero-cost** ETL. GitHub Actions runs daily at
> 00:00 UTC, scrapes every enabled source, validates and deduplicates the
> results, regenerates statistics and a dashboard, and commits everything back
> to the repository (GitOps). No servers, no database, no bills.

**Live dashboard:** https://farajzada.github.io/cronos/

## Why Cronos?

- **Pluggable sources** — add a new site or API by writing one small class
  ([guide below](#adding-your-own-source)). Ships with two reference
  implementations: HTML scraping (`quotes`) and an official JSON API
  (`hackernews`).
- **Idempotent by construction** — every source declares a stable dedup key
  (natural id or content hash); loads are append-only with O(1) `set()`
  membership checks. Run it 1× or 100×, the dataset is the same.
- **Corruption cannot ship** — an integrity validator (schema, key
  uniqueness, per-source rules like content-hash verification) gates the
  GitOps commit.
- **Deterministic outputs** — stats and dashboard are derived purely from
  data (no timestamps), so unchanged data means byte-identical files and a
  silent no-op run.
- **A real frontend for free** — self-contained dashboard (tabs per source,
  SVG charts, facet filters, live search, light/dark theme, CSV/JSON export)
  served by GitHub Pages, regenerated on every data change.

## Architecture

```
┌────────────────┐   cron: 0 0 * * *   ┌──────────────────────────────┐
│ GitHub Actions │────────────────────▶│ ubuntu-latest + Python 3.11  │
│   (scheduler)  │                     │  pip cache (actions/cache)   │
└────────────────┘                     └──────────────┬───────────────┘
                                                      │
        ┌─────────────────────────────────────────────▼─────────────┐
        │ cronos run       Source registry → scrape each source     │
        │                  → append-only dedup load (data/<src>.csv)│
        │ cronos validate  schema + key uniqueness + source rules   │
        │ cronos stats     data/stats.json + Actions job summary    │
        │ cronos report    docs/index.html (self-contained SPA)     │
        └─────────────────────────────────────────────┬─────────────┘
                                                      │ git status --porcelain
                                      ┌───────────────▼───────────────┐
                                      │ changed? → bot commit + push  │
                                      │          → Pages redeploys    │
                                      │ unchanged? → graceful exit 0  │
                                      └───────────────────────────────┘
```

Bundled sources:

| Source       | Type       | Dataset               | Dedup key                       |
|--------------|------------|-----------------------|---------------------------------|
| `quotes`     | HTML pages | `data/quotes.csv`     | SHA-256 of `text::author`       |
| `hackernews` | JSON API   | `data/hackernews.csv` | HN item id (first-seen snapshot)|

## Quick start

```bash
git clone https://github.com/farajzada/cronos.git && cd cronos
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cronos all        # run → validate → stats → report
cronos sources    # list available/enabled sources
python -m http.server -d docs 8000   # view the dashboard locally
```

Every stage is also runnable as a module (`python -m src.scraper`, etc.) —
that is exactly what the GitHub Actions workflow does.

The second consecutive `cronos run` appends `0` rows — that is the
idempotency guarantee working, not a bug.

## Configuration

Everything is environment-variable driven (see [src/config.py](src/config.py)):

| Variable                  | Default                          | Purpose                     |
|---------------------------|----------------------------------|-----------------------------|
| `CRONOS_SOURCES`          | `quotes,hackernews`              | Enabled sources (comma-sep) |
| `CRONOS_DATA_DIR`         | `data/`                          | Dataset directory           |
| `CRONOS_QUOTES_URL`       | `https://quotes.toscrape.com/`   | Quotes target               |
| `CRONOS_HN_URL`           | Algolia front-page endpoint      | Hacker News API             |
| `CRONOS_MAX_PAGES`        | `50`                             | Pagination ceiling          |
| `CRONOS_CONNECT_TIMEOUT`  | `5.0`                            | Connect timeout (s)         |
| `CRONOS_READ_TIMEOUT`     | `20.0`                           | Read timeout (s)            |
| `CRONOS_MAX_RETRIES`      | `3`                              | Attempts per request        |
| `CRONOS_RETRY_BACKOFF`    | `2.0`                            | Backoff base (s, linear)    |
| `CRONOS_POLITENESS_DELAY` | `0.5`                            | Delay between pages (s)     |

## Adding your own source

The pipeline is generic over the `Source` contract — scraper, validator,
metrics and dashboard all adapt automatically:

```python
# src/sources/mysite.py
from src.sources.base import Source

class MySiteSource(Source):
    name = "mysite"                      # → data/mysite.csv
    title = "My Site"                    # dashboard tab label
    fieldnames = ["post_id", "title", "url", "category"]
    key_field = "post_id"                # stable dedup key
    display_columns = [("title", "Title"), ("category", "Category")]
    stat_fields = [("category", None)]   # aggregated in stats.json
    facet_field = "category"             # filter chips + bar chart

    def scrape(self, client):
        payload = client.get_json("https://mysite.example/api/posts")
        for post in payload["posts"]:
            yield {
                "post_id": str(post["id"]),
                "title": post["title"],
                "url": post["url"],
                "category": post["category"],
            }
```

Then register it in [src/sources/\_\_init\_\_.py](src/sources/__init__.py) and
enable it: `CRONOS_SOURCES=quotes,hackernews,mysite`. Full checklist in
[CONTRIBUTING.md](CONTRIBUTING.md).

Respect the target's `robots.txt` and terms of service — prefer official
APIs, keep the politeness delay and retry backoff.

## Project layout

```
cronos/
├── .github/workflows/
│   ├── cronos_pipeline.yml     # daily ETL: cron + cache + GitOps commit
│   └── ci.yml                  # ruff lint/format + pytest on every push
├── data/                       # append-only datasets + stats.json
├── docs/index.html             # self-contained dashboard (GitHub Pages)
├── src/
│   ├── cli.py                  # `cronos` command
│   ├── config.py               # env-overridable configuration
│   ├── http_client.py          # retries, timeouts, UA rotation
│   ├── storage.py              # generic idempotent CSV writer
│   ├── scraper.py / validator.py / metrics.py / report.py
│   └── sources/                # Source contract + implementations
└── tests/                      # 37 unit tests, network fully mocked
```

## Operational guarantees

- **Idempotent**: stable dedup keys; re-runs never duplicate rows.
- **Append-only**: history is never rewritten.
- **Validated**: corrupt data fails the run before it can be pushed.
- **Fault-isolated**: one failing source never blocks the others.
- **Deterministic**: unchanged data → byte-identical outputs → no commit churn.
- **Race-safe & bounded**: concurrency group, page ceilings, job timeouts.
- **Zero-cost**: public repo Actions minutes + GitHub Pages hosting.

## Contributing & security

PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). New data sources are
the most valued contribution. Security reports: [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
