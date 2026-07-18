# Cronos — Serverless ETL Pipeline

[![Cronos ETL Pipeline](https://github.com/farajzada/cronos/actions/workflows/cronos_pipeline.yml/badge.svg)](https://github.com/farajzada/cronos/actions/workflows/cronos_pipeline.yml)
[![CI](https://github.com/farajzada/cronos/actions/workflows/ci.yml/badge.svg)](https://github.com/farajzada/cronos/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11-blue)
![License](https://img.shields.io/badge/license-MIT-green)

> Fully automated, serverless, zero-cost ETL pipeline. GitHub Actions runs the
> scraper daily at **00:00 UTC**, validates and deduplicates the results,
> regenerates statistics and a dashboard, and commits everything back to the
> repository (GitOps).

**Live dashboard:** https://farajzada.github.io/cronos/

## Architecture

```
┌────────────────┐   cron: 0 0 * * *   ┌──────────────────────────────┐
│ GitHub Actions │────────────────────▶│ ubuntu-latest + Python 3.11  │
│   (scheduler)  │                     │  pip cache (actions/cache)   │
└────────────────┘                     └──────────────┬───────────────┘
                                                      │
                  ┌───────────────────────────────────▼───────────────┐
                  │ python -m src.scraper    Extract → Transform → Load│
                  │ python -m src.validator  integrity gate (schema,   │
                  │                          hashes, dedup)            │
                  │ python -m src.metrics    data/stats.json + summary │
                  │ python -m src.report     docs/index.html dashboard │
                  └───────────────────────────────────┬───────────────┘
                                                      │ git status --porcelain
                                      ┌───────────────▼───────────────┐
                                      │ changed? → bot commit + push  │
                                      │ unchanged? → graceful exit 0  │
                                      └───────────────────────────────┘
```

## Data flow

1. **Extract** — `QuotesScraper` walks every page of the configured source
   with a rotating User-Agent pool, connect/read timeouts, and retries with
   linear backoff. 4xx responses fail fast; 5xx and network errors are
   retried.
2. **Transform** — each record is normalized into a `Quote` dataclass and
   assigned a `quote_id`: a SHA-256 hash of `text::author`.
3. **Load** — `DatasetWriter` loads all existing `quote_id` values into a
   `set()` (O(1) lookups) and appends **only unseen rows** to
   [`data/dataset.csv`](data/dataset.csv). The file is opened in append mode
   exclusively — history is never rewritten, so the script is idempotent:
   running it N times yields the same dataset as running it once.
4. **Validate** — `src/validator.py` gates the commit: schema, non-empty
   fields, hash consistency and uniqueness. A corrupt dataset fails the run
   before anything is pushed.
5. **Derive** — `src/metrics.py` writes [`data/stats.json`](data/stats.json)
   and a GitHub Actions job summary; `src/report.py` renders the dashboard.
   Both outputs are derived purely from dataset content (no timestamps), so
   an unchanged dataset regenerates byte-identical files.
6. **GitOps** — the workflow checks `git status --porcelain -- data/ docs/`.
   If anything changed, `github-actions[bot]` commits and pushes it;
   otherwise the run ends silently with exit code 0.

## Dashboard

[`docs/index.html`](docs/index.html) is a fully self-contained page (inline
CSS/JS, embedded data, zero external requests) with stat cards, top-tag
filter chips and a live-search table. View it locally:

```bash
python -m http.server -d docs 8000   # → http://localhost:8000
```

or publish it with GitHub Pages: **Settings → Pages → Deploy from a branch →
`main` / `docs`**. The pipeline regenerates it on every data change.

## Configuration

Every tunable is an environment variable (see [`src/config.py`](src/config.py)):

| Variable                  | Default                        | Purpose                    |
|---------------------------|--------------------------------|----------------------------|
| `CRONOS_BASE_URL`         | `https://quotes.toscrape.com/` | Scrape target              |
| `CRONOS_DATA_PATH`        | `data/dataset.csv`             | Dataset location           |
| `CRONOS_MAX_PAGES`        | `50`                           | Pagination ceiling         |
| `CRONOS_CONNECT_TIMEOUT`  | `5.0`                          | Connect timeout (s)        |
| `CRONOS_READ_TIMEOUT`     | `20.0`                         | Read timeout (s)           |
| `CRONOS_MAX_RETRIES`      | `3`                            | Attempts per request       |
| `CRONOS_RETRY_BACKOFF`    | `2.0`                          | Backoff base (s, linear)   |
| `CRONOS_POLITENESS_DELAY` | `0.5`                          | Delay between pages (s)    |

## Dataset schema (`data/dataset.csv`)

| Column     | Type   | Description                              |
|------------|--------|------------------------------------------|
| `quote_id` | string | SHA-256 content hash (deduplication key) |
| `text`     | string | Quote body, normalized                   |
| `author`   | string | Author name                              |
| `tags`     | string | Pipe-delimited tags (`life\|truth`)      |

## Project layout

```
cronos/
├── .github/workflows/
│   ├── cronos_pipeline.yml   # daily ETL: cron + cache + GitOps commit
│   └── ci.yml                # pytest on every push / PR
├── data/
│   ├── dataset.csv           # append-only dataset
│   └── stats.json            # derived statistics
├── docs/
│   └── index.html            # self-contained dashboard (Pages-ready)
├── src/
│   ├── config.py             # env-overridable runtime configuration
│   ├── scraper.py            # Extract / Transform / Load
│   ├── validator.py          # integrity gate
│   ├── metrics.py            # stats + Actions job summary
│   └── report.py             # dashboard generator
├── tests/                    # 25 unit tests (network fully mocked)
├── requirements.txt
└── requirements-dev.txt
```

## Running locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

python -m src.scraper     # scrape + idempotent load
python -m src.validator   # integrity check
python -m src.metrics     # data/stats.json
python -m src.report      # docs/index.html
pytest -q                 # test suite
```

The second consecutive scraper run appends `0` rows — that is the
idempotency guarantee working, not a bug.

## Adapting Cronos to your own source (fork guide)

1. **Fork** the repository and enable Actions (Settings → Actions → Allow).
2. Point `CRONOS_BASE_URL` at your target (workflow `env:` or
   `src/config.py` defaults).
3. Rewrite `_parse()` (CSS selectors) and `_next_page()` (pagination) in
   `src/scraper.py` for your site's markup; adjust the `Quote` dataclass and
   `FIELDNAMES` to your schema — keep the content-hash `quote_id` pattern for
   free deduplication.
4. Optionally change the cron expression in
   `.github/workflows/cronos_pipeline.yml`.
5. Trigger a manual run (Actions → *Cronos ETL Pipeline* → *Run workflow*)
   to verify before waiting for the nightly schedule.

Respect the target site's `robots.txt` and terms of service. The built-in
politeness delay and retry backoff are deliberate — keep them.

## Operational guarantees

- **Idempotent**: content-hash dedup; re-runs never duplicate rows.
- **Append-only**: existing history is never overwritten.
- **Validated**: corrupt data fails the pipeline before it can be pushed.
- **Deterministic derivations**: stats and dashboard regenerate
  byte-identically on unchanged data — no commit churn.
- **Graceful no-op**: no data change → no commit, exit 0, green run.
- **Race-safe**: `concurrency.group` prevents overlapping pipeline runs.
- **Bounded**: `CRONOS_MAX_PAGES` and `timeout-minutes` cap runaway jobs.
- **Tested**: 25 unit tests run on every push via the CI workflow.
