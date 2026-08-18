# Versionable reports

This directory contains aggregate-only outputs that are safe to review and
version. Each profile records the content-addressed raw artifact used, exact row
and null counts, selected distinct counts, chronological date bounds, candidate
key duplicates, categorical frequencies, and suspicious-date checks.

Regenerate from the frozen local artifacts:

```bash
uv run mor-l0 profile --all
uv run mor-l0 candidates --limit 50
uv run mor-l0 review-init
uv run mor-l0 review-validate
uv run mor-l0 identity-audit
```

Raw CSVs, candidate names, human evidence, reviewer details, and the full
identity-audit JSON remain under ignored `data/` storage. Completed candidate
reviews can produce a versionable aggregate with `mor-l0 review-summary`.
