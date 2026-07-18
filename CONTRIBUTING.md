# Contributing to Cronos

Thanks for your interest! Cronos is deliberately small — please keep it that
way: minimal dependencies, deterministic outputs, append-only data.

## Development setup

```bash
git clone https://github.com/farajzada/cronos.git && cd cronos
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Workflow

1. Fork and create a feature branch from `main` (`feature/<short-name>`).
2. Make your change. Every PR must pass the CI gate:
   ```bash
   ruff check cronos tests
   ruff format --check cronos tests
   pytest
   ```
3. Open a pull request with a clear description. One logical change per PR.

## Adding a data source

This is the most welcome kind of contribution. The whole pipeline is generic
over the `Source` contract ([cronos/sources/base.py](cronos/sources/base.py)):

1. Create `cronos/sources/<name>.py` subclassing `Source`. Declare:
   - `name`, `title`, `fieldnames`, `key_field` — schema + dedup key;
   - `display_columns`, `stat_fields`, `facet_field` — dashboard/metrics metadata;
   - `scrape(client)` — yield normalized `dict` rows;
   - optional `validate_row(row)` — source-specific integrity rules.
2. Register the class in `REGISTRY` ([cronos/sources/__init__.py](cronos/sources/__init__.py)).
3. Add unit tests under `tests/test_sources_<name>.py` — network **must** be
   mocked; look at the Hacker News tests for the pattern.
4. Enable it via `CRONOS_SOURCES` and run `cronos all` locally.

Ground rules for sources:

- **Idempotency is non-negotiable**: pick a stable `key_field` (natural id
  or content hash). Rows are append-only snapshots — never rewritten.
- **Be polite**: respect robots.txt and terms of service; keep the built-in
  timeouts, retries and politeness delay. Prefer official APIs over HTML.
- **Determinism**: no timestamps or randomness in stored rows, stats, or
  dashboard output — unchanged data must produce byte-identical files.

## Reporting bugs / requesting features

Use the issue templates. For security concerns see [SECURITY.md](SECURITY.md).
