## What

<!-- One-paragraph summary of the change. -->

## Why

<!-- Motivation / linked issue. -->

## Checklist

- [ ] `ruff check cronos tests` and `ruff format --check cronos tests` pass
- [ ] `pytest` passes; new behaviour is covered by tests (network mocked)
- [ ] Outputs stay deterministic (no timestamps/randomness in data, stats, dashboard)
- [ ] New source only: registered in `REGISTRY`, polite scraping, stable dedup key
