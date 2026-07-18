# Security Policy

## Supported versions

Only the latest commit on `main` is supported. The pipeline redeploys daily,
so fixes land quickly.

## Reporting a vulnerability

Please **do not** open a public issue for security problems. Use GitHub's
private vulnerability reporting ("Report a vulnerability" under the Security
tab) so the report stays private until a fix is released.

## Scope notes

- Scraped content is untrusted input. The dashboard escapes every value it
  interpolates (`esc()` in `cronos/report.py`) and escapes `</` inside the
  embedded JSON block; regressions here are security bugs — report them.
- The GitHub Actions workflows intentionally run with the minimum
  permissions they need (`contents: write` only in the ETL pipeline).
