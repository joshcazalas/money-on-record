# Manual organization-candidate review

`mor-l0 candidates --limit 50` creates a deterministic, stratified candidate
CSV. Tier A differs only by typography; Tier B additionally removes a trailing
legal suffix. Both tiers contain hypotheses, never verified links.

Candidate-level files contain names and evidence links, so Git ignores both the
generated candidates and the human worksheet under `data/derived/`. Only the
completed aggregate summary under `reports/reviews/` is intended for version
control.

## Initialize the worksheet

```bash
uv run mor-l0 candidates --limit 50
uv run mor-l0 review-init
uv run mor-l0 review-validate
```

`review-init` creates
`data/derived/l0-organization-candidate-review.csv` and refuses to overwrite it.
This prevents a later candidate-generation run from erasing human work. Do not
edit `candidate_fingerprint` or any column to its left; validation recomputes the
fingerprint and compares the complete candidate set to the current generator
output.

## Review every row

For each candidate:

1. Open the official campaign filing and purchasing/payment record using the
   two `*_source_rows_url` columns. The artifact SHA columns pin the local
   snapshot behind each aggregate.
2. Determine whether both records refer to the same legal organization using
   independent evidence such as official websites, Texas entity records,
   contract documents, or clearly shared business identifiers. Name similarity
   alone is not evidence.
3. Set `review_status` to `COMPLETE` and `same_organization` to `YES`, `NO`, or
   `UNCERTAIN`.
4. Choose one compatible `review_reason` from the controlled list below.
5. Add at least one durable HTTPS `external_evidence_url`. Separate multiple
   URLs with ` | `.
6. Add concise `review_notes`, the `reviewer`, and an ISO 8601 `reviewed_at`
   timestamp with timezone, such as `2026-08-18T14:30:00-05:00`.

Allowed reasons:

| Decision | `review_reason` |
| --- | --- |
| `YES` | `INDEPENDENT_OFFICIAL_IDENTITY`, `SHARED_OFFICIAL_IDENTIFIER` |
| `NO` | `AMBIGUOUS_ABBREVIATION`, `CONFLICTING_IDENTIFIERS`, `DISTINCT_LEGAL_ENTITIES`, `FRANCHISE_OR_CHAPTER`, `PARENT_SUBSIDIARY`, `PERSON_ORGANIZATION_COLLISION`, `PLACEHOLDER_IDENTIFIER` |
| `UNCERTAIN` | `CONFLICTING_EVIDENCE`, `INSUFFICIENT_EVIDENCE`, `SOURCE_DATA_AMBIGUITY` |

Leave every review field blank while a row is `UNREVIEWED`; partially completed
rows fail validation. Reject ambiguous abbreviations, franchises/chapters,
parent/subsidiary pairs, distinct professional entities,
individual/organization collisions, and records whose only shared identifier is
an `MIS...` code. Preserve rejections because they are useful resolver
regression cases.

Validate progress at any time:

```bash
uv run mor-l0 review-validate
```

## Finish and publish the aggregate

```bash
uv run mor-l0 review-validate --require-complete
uv run mor-l0 review-summary
```

`review-summary` refuses incomplete or drifted reviews. It writes only totals,
decision/reason counts, tier/source breakdowns, timestamps, and a candidate-set
hash. It excludes organization names, codes, candidate IDs, evidence URLs,
notes, and reviewer names. Inspect the JSON before committing it.
