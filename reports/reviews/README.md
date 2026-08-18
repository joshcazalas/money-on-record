# Candidate-review reports

This directory accepts only aggregate candidate-review summaries produced by:

```bash
uv run mor-l0 review-validate --require-complete
uv run mor-l0 review-summary
```

The generator excludes organization names, public-record codes, candidate IDs,
evidence URLs, notes, and reviewer names. Review generated JSON before adding it
to version control. Candidate-level worksheets remain under ignored
`data/derived/` storage.
