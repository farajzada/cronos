# Cronos — Serverless ETL Pipeline

[![Cronos ETL Pipeline](https://github.com/farajzada/cronos/actions/workflows/cronos_pipeline.yml/badge.svg)](https://github.com/farajzada/cronos/actions/workflows/cronos_pipeline.yml)
![Python](https://img.shields.io/badge/python-3.11-blue)
![License](https://img.shields.io/badge/license-MIT-green)

> Fully automated, serverless, zero-cost ETL pipeline. GitHub Actions runs the
> scraper daily at **00:00 UTC**, deduplicates the results, and commits the
> updated dataset back to the repository (GitOps).

## Architecture

```
┌────────────────┐   cron: 0 0 * * *   ┌──────────────────────────────┐
│ GitHub Actions │────────────────────▶│ ubuntu-latest + Python 3.11  │
│   (scheduler)  │                     │  pip cache (actions/cache)   │
└────────────────┘                     └──────────────┬───────────────┘
                                                      │
                                      ┌───────────────▼───────────────┐
                                      │ src/scraper.py                │
                                      │  Extract  → paginated HTTP    │
                                      │  Transform→ normalize + hash  │
                                      │  Load     → append-only CSV   │
                                      └───────────────┬───────────────┘
                                                      │ git status --porcelain
                                      ┌───────────────▼───────────────┐
                                      │ changed? → bot commit + push  │
                                      │ unchanged? → graceful exit 0  │
                                      └───────────────────────────────┘
```

## Data flow

1. **Extract** — `QuotesScraper` walks every page of `quotes.toscrape.com`
   with a rotating User-Agent pool, connect/read timeouts `(5s, 20s)`, and
   3 retries with linear backoff. 4xx responses fail fast; 5xx and network
   errors are retried.
2. **Transform** — each record is normalized into a `Quote` dataclass and
   assigned a `quote_id`: a SHA-256 hash of `text::author`.
3. **Load** — `DatasetWriter` loads all existing `quote_id` values into a
   `set()` (O(1) lookups) and appends **only unseen rows** to
   [`data/dataset.csv`](data/dataset.csv). The file is opened in append mode
   exclusively — history is never rewritten, so the script is idempotent:
   running it N times yields the same dataset as running it once.
4. **GitOps** — the workflow checks `git status --porcelain -- data/dataset.csv`.
   If the dataset changed, `github-actions[bot]` commits and pushes it;
   otherwise the run ends silently with exit code 0.

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
├── .github/
│   └── workflows/
│       └── cronos_pipeline.yml   # cron + cache + GitOps commit logic
├── data/
│   └── dataset.csv               # created on first run, then appended
├── src/
│   └── scraper.py                # Extract / Transform / Load
├── requirements.txt
└── README.md
```

Dependencies are intentionally minimal (`requests`, `beautifulsoup4`).
`pandas` is not required: set-based hashing already gives O(1) deduplication
without loading the dataset into a DataFrame on every run.

## Running locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python src/scraper.py
```

The second consecutive run appends `0` rows — that is the idempotency
guarantee working, not a bug.

## Adapting Cronos to your own source (fork guide)

1. **Fork** the repository and enable Actions (Settings → Actions → Allow).
2. Ensure workflow write access: Settings → Actions → General →
   *Workflow permissions* → **Read and write permissions**.
3. Edit `src/scraper.py`:
   - point `BASE_URL` at your target;
   - rewrite `_parse()` (CSS selectors) and `_next_page()` (pagination) for
     your site's markup;
   - adjust the `Quote` dataclass and `FIELDNAMES` to your schema — keep the
     content-hash `quote_id` pattern for free deduplication.
4. Optionally change the cron expression in
   `.github/workflows/cronos_pipeline.yml`.
5. Trigger a manual run (Actions → *Cronos ETL Pipeline* → *Run workflow*)
   to verify before waiting for the nightly schedule.

Respect the target site's `robots.txt` and terms of service. The built-in
politeness delay (0.5s/page) and retry backoff are deliberate — keep them.

## Operational guarantees

- **Idempotent**: content-hash dedup; re-runs never duplicate rows.
- **Append-only**: existing history is never overwritten.
- **Graceful no-op**: no data change → no commit, exit 0, green run.
- **Race-safe**: `concurrency.group` prevents overlapping pipeline runs.
- **Bounded**: `MAX_PAGES=50` and `timeout-minutes: 15` cap runaway jobs.
